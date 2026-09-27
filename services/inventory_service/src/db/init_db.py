"""
Database initialization and sample catalog seeding for Inventory Service.
"""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.inventory_service.src.db.base import Base
from services.inventory_service.src.db.session import engine
from services.inventory_service.src.models.catalog import Category, Product, ProductVariant

logger = logging.getLogger("inventory_init_db")


async def init_db() -> None:
    """Create tables and seed sample catalog categories and products."""
    async with engine.begin() as conn:
        logger.info("Ensuring inventory database tables exist...")
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        try:
            # Check if categories exist
            res = await session.execute(select(Category))
            if not res.scalars().first():
                logger.info("Seeding initial catalog categories and products...")
                apparel = Category(name="Apparel & Clothing", slug="apparel", description="Men and Women Clothing")
                accessories = Category(name="Accessories", slug="accessories", description="Hats, belts, and bags")
                session.add_all([apparel, accessories])
                await session.flush()

                # Add sample product: T-Shirt
                tshirt = Product(
                    name="Classic Crewneck T-Shirt",
                    description="100% Ring-spun cotton premium everyday t-shirt",
                    brand="Everyday Basics",
                    category_id=apparel.id,
                )
                session.add(tshirt)
                await session.flush()

                # Add variants
                v1 = ProductVariant(
                    product_id=tshirt.id,
                    sku="TSHIRT-BLK-M",
                    barcode="890123456701",
                    title="Black / Medium",
                    cost_price=8.50,
                    retail_price=24.99,
                )
                v2 = ProductVariant(
                    product_id=tshirt.id,
                    sku="TSHIRT-BLK-L",
                    barcode="890123456702",
                    title="Black / Large",
                    cost_price=8.50,
                    retail_price=24.99,
                )
                v3 = ProductVariant(
                    product_id=tshirt.id,
                    sku="TSHIRT-WHT-M",
                    barcode="890123456703",
                    title="White / Medium",
                    cost_price=8.00,
                    retail_price=24.99,
                )
                session.add_all([v1, v2, v3])
                await session.commit()
                logger.info("Sample catalog seeded with product and 3 variants.")
        except Exception as e:
            await session.rollback()
            logger.error(f"Error during inventory database initialization: {e}")
            raise
