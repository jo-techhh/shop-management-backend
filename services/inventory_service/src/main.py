"""
Catalog & Multi-Outlet Inventory Microservice entry point.
Manages products, variants, barcodes, outlet stock, transactional outbox publishing,
and Saga order event consumption with strict row-level locking.
"""
import asyncio
from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from fastapi import FastAPI

from services.inventory_service.src.api.catalog import router as catalog_router
from services.inventory_service.src.api.inventory import router as inventory_router
from services.inventory_service.src.config import settings
from services.inventory_service.src.db.init_db import init_db
from services.inventory_service.src.events.consumer import run_order_consumer
from services.inventory_service.src.services.outbox_worker import run_outbox_worker
from shared.broker.redis_client import close_redis_client, get_redis_client
from shared.middleware.correlation import CorrelationIdMiddleware
from shared.schemas.common import HealthStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inventory_service")

# Background task handles
outbox_task: asyncio.Task | None = None
consumer_task: asyncio.Task | None = None
stop_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global outbox_task, consumer_task
    logger.info("Starting Catalog & Inventory Microservice...")

    # 1. Initialize DB tables & default catalog
    try:
        await init_db()
        logger.info("Inventory database tables verified.")
    except Exception as db_err:
        logger.error(f"Failed to initialize inventory DB: {db_err}")

    # 2. Connect to Redis & start background workers
    try:
        redis = await get_redis_client()
        stop_event.clear()

        # Start Transactional Outbox Worker
        outbox_task = asyncio.create_task(
            run_outbox_worker(redis_client=redis, stop_event=stop_event),
            name="inventory_outbox_worker",
        )

        # Start Saga Order Consumer
        consumer_task = asyncio.create_task(
            run_order_consumer(redis_client=redis, stop_event=stop_event),
            name="inventory_saga_consumer",
        )
        logger.info("Inventory background workers (Outbox + Consumer) launched.")
    except Exception as redis_err:
        logger.warning(f"Could not initialize Redis background workers: {redis_err}")

    yield

    # Shutdown: gracefully cancel workers
    logger.info("Stopping Catalog & Inventory Microservice...")
    stop_event.set()

    tasks_to_cancel = [t for t in (outbox_task, consumer_task) if t is not None]
    for t in tasks_to_cancel:
        t.cancel()

    if tasks_to_cancel:
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    await close_redis_client()
    logger.info("Inventory Microservice gracefully stopped.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(CorrelationIdMiddleware)

# Mount Routers
app.include_router(catalog_router)
app.include_router(inventory_router)


@app.get("/health", response_model=HealthStatus, tags=["System"])
async def health_check() -> HealthStatus:
    return HealthStatus(
        status="ok",
        service="inventory-service",
        version="1.0.0",
        dependencies={
            "database": "connected",
            "redis_streams": "configured",
            "outbox_worker": "running" if outbox_task and not outbox_task.done() else "stopped",
            "saga_consumer": "running" if consumer_task and not consumer_task.done() else "stopped",
        },
    )
