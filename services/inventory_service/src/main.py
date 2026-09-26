"""
Catalog & Multi-Outlet Inventory Microservice entry point.
Manages products, variants, barcodes, outlet stock, and stock reservation sagas.
"""
from contextlib import asynccontextmanager
import logging
import os
from typing import AsyncGenerator
from fastapi import FastAPI
from shared.broker.redis_client import get_redis_client, close_redis_client
from shared.broker.streams import ensure_consumer_group
from shared.middleware.correlation import CorrelationIdMiddleware
from shared.schemas.common import HealthStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inventory_service")

ORDERS_STREAM = os.getenv("ORDERS_STREAM", "stream:orders")
INVENTORY_CONSUMER_GROUP = os.getenv("INVENTORY_CONSUMER_GROUP", "inventory-group")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting Catalog & Inventory Microservice...")
    try:
        redis = await get_redis_client()
        await ensure_consumer_group(redis, ORDERS_STREAM, INVENTORY_CONSUMER_GROUP)
        logger.info(f"Verified consumer group '{INVENTORY_CONSUMER_GROUP}' on '{ORDERS_STREAM}'.")
    except Exception as e:
        logger.warning(f"Could not connect to Redis on startup: {e}")
    yield
    logger.info("Stopping Catalog & Inventory Microservice...")
    await close_redis_client()


app = FastAPI(
    title="Catalog & Multi-Outlet Inventory Microservice",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(CorrelationIdMiddleware)


@app.get("/health", response_model=HealthStatus, tags=["System"])
async def health_check() -> HealthStatus:
    return HealthStatus(
        status="ok",
        service="inventory-service",
        version="1.0.0",
        dependencies={"database": "configured", "redis_streams": "configured"},
    )
