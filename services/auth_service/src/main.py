"""
Auth & RBAC Microservice entry point.
Manages users, roles, permissions, outlets, and JWT issuance.
"""
from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.auth_service.src.api.auth import router as auth_router
from services.auth_service.src.api.outlets import router as outlets_router
from services.auth_service.src.api.roles import router as roles_router
from services.auth_service.src.api.users import router as users_router
from services.auth_service.src.config import settings
from services.auth_service.src.db.init_db import init_db
from shared.middleware.correlation import CorrelationIdMiddleware
from shared.schemas.common import HealthStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("auth_service")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting Auth & RBAC Microservice...")
    try:
        await init_db()
        logger.info("Database schemas and seed data verified successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
    yield
    logger.info("Stopping Auth & RBAC Microservice...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(CorrelationIdMiddleware)

# Include Routers
app.include_router(auth_router)
app.include_router(outlets_router)
app.include_router(roles_router)
app.include_router(users_router)


@app.get("/health", response_model=HealthStatus, tags=["System"])
async def health_check() -> HealthStatus:
    return HealthStatus(
        status="ok",
        service="auth-service",
        version="1.0.0",
        dependencies={"database": "connected"},
    )
