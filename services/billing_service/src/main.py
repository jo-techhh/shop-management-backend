"""
Billing & POS Microservice entry point.
Manages cashier shifts, cart calculations, orders, payment processing, and checkout saga.
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
logger = logging.getLogger("billing_service")

INVENTORY_STREAM = os.getenv("INVENTORY_STREAM", "stream:inventory")
BILLING_CONSUMER_GROUP = os.getenv("BILLING_CONSUMER_GROUP", "billing-group")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting Billing & POS Microservice...")
    try:
        redis = await get_redis_client()
        await ensure_consumer_group(redis, INVENTORY_STREAM, BILLING_CONSUMER_GROUP)
        logger.info(f"Verified consumer group '{BILLING_CONSUMER_GROUP}' on '{INVENTORY_STREAM}'.")
    except Exception as e:
        logger.warning(f"Could not connect to Redis on startup: {e}")
    yield
    logger.info("Stopping Billing & POS Microservice...")
    await close_redis_client()


app = FastAPI(
    title="Billing & POS Microservice",
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
        service="billing-service",
        version="1.0.0",
        dependencies={"database": "configured", "redis_streams": "configured"},
    )
