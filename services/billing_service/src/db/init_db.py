"""
Database initialization for Billing & POS Service.
"""
import logging
from services.billing_service.src.db.base import Base
from services.billing_service.src.db.session import engine

logger = logging.getLogger("billing_init_db")


async def init_db() -> None:
    """Ensure all billing tables exist in billing_db."""
    async with engine.begin() as conn:
        logger.info("Ensuring billing database tables exist...")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Billing database tables verified.")
