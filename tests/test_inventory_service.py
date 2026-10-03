"""
Comprehensive tests for Catalog & Multi-Outlet Inventory Service:
- Catalog models & barcode lookup
- Stock adjustment and audit ledger
- Saga stock reservation with row locks
- Insufficient stock failure handling & outbox generation
- Saga compensation (stock release)
- Idempotent consumer behavior (zero duplicate reservations on redelivery)
- REST API integration endpoints
"""
from typing import AsyncGenerator
from uuid import uuid4
from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from services.inventory_service.src.db.base import Base
from services.inventory_service.src.db.session import get_db
from services.inventory_service.src.events.consumer import process_order_event
from services.inventory_service.src.main import app
from services.inventory_service.src.models.catalog import Category, Product, ProductVariant
from services.inventory_service.src.models.outbox import OutboxEvent
from services.inventory_service.src.models.processed import ProcessedEvent
from services.inventory_service.src.models.stock import OutletInventory, StockAuditLog
from services.inventory_service.src.services import stock_service
from shared.events.base import EventEnvelope, EventType

# In-memory async SQLite engine with static pool for isolated test lifecycle
test_inv_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestAsyncSession = async_sessionmaker(bind=test_inv_engine, expire_on_commit=False)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestAsyncSession() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    async with test_inv_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_inv_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_stock_adjustment_and_audit():
    async with TestAsyncSession() as session:
        outlet_id = uuid4()
        variant_id = uuid4()

        # 1. Intake 100 units of stock
        inv = await stock_service.adjust_stock(
            session=session,
            outlet_id=outlet_id,
            variant_id=variant_id,
            quantity_change=100,
            notes="Initial shipment received",
            reference_id="PO-001",
        )
        await session.commit()

        assert inv.quantity_on_hand == 100
        assert inv.reserved_quantity == 0
        assert inv.available_quantity == 100

        # Verify audit log
        audit_res = await session.execute(
            select(StockAuditLog).where(StockAuditLog.outlet_id == outlet_id)
        )
        logs = audit_res.scalars().all()
        assert len(logs) == 1
        assert logs[0].quantity_change == 100
        assert logs[0].new_on_hand == 100
        assert logs[0].reference_id == "PO-001"


@pytest.mark.asyncio
async def test_saga_stock_reservation_success():
    async with TestAsyncSession() as session:
        outlet_id = uuid4()
        variant_id = uuid4()

        # Seed initial stock of 10 units
        await stock_service.adjust_stock(session, outlet_id, variant_id, 10)
        await session.commit()

        # Reserve 4 units for Order 101
        items = [{"variant_id": str(variant_id), "sku": "SKU-A", "quantity": 4, "unit_price": 20.0}]
        success, msg = await stock_service.reserve_stock_for_order(
            session=session,
            order_id="ord_101",
            outlet_id=outlet_id,
            items=items,
            correlation_id="corr_101",
        )
        await session.commit()

        assert success is True

        # Check inventory: on_hand=10, reserved=4, available=6
        inv = await stock_service.get_or_create_inventory(session, outlet_id, variant_id)
        assert inv.quantity_on_hand == 10
        assert inv.reserved_quantity == 4
        assert inv.available_quantity == 6

        # Check outbox has STOCK_RESERVED
        outbox_res = await session.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == "ord_101")
        )
        outbox = outbox_res.scalar_one()
        assert outbox.event_type == EventType.STOCK_RESERVED.value
        assert outbox.status == "PENDING"


@pytest.mark.asyncio
async def test_saga_stock_reservation_insufficient_stock():
    async with TestAsyncSession() as session:
        outlet_id = uuid4()
        variant_id = uuid4()

        # Seed initial stock of only 2 units
        await stock_service.adjust_stock(session, outlet_id, variant_id, 2)
        await session.commit()

        # Attempt to reserve 5 units
        items = [{"variant_id": str(variant_id), "sku": "SKU-LIMITED", "quantity": 5, "unit_price": 20.0}]
        success, msg = await stock_service.reserve_stock_for_order(
            session=session,
            order_id="ord_102",
            outlet_id=outlet_id,
            items=items,
            correlation_id="corr_102",
        )
        await session.commit()

        assert success is False
        assert "Insufficient stock" in msg

        # Verify stock was untouched
        inv = await stock_service.get_or_create_inventory(session, outlet_id, variant_id)
        assert inv.quantity_on_hand == 2
        assert inv.reserved_quantity == 0

        # Check outbox has STOCK_RESERVATION_FAILED
        outbox_res = await session.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == "ord_102")
        )
        outbox = outbox_res.scalar_one()
        assert outbox.event_type == EventType.STOCK_RESERVATION_FAILED.value


@pytest.mark.asyncio
async def test_saga_stock_compensation_release():
    async with TestAsyncSession() as session:
        outlet_id = uuid4()
        variant_id = uuid4()

        # Seed 10, reserve 4
        await stock_service.adjust_stock(session, outlet_id, variant_id, 10)
        items = [{"variant_id": str(variant_id), "sku": "SKU-A", "quantity": 4, "unit_price": 20.0}]
        await stock_service.reserve_stock_for_order(session, "ord_103", outlet_id, items, "corr_103")
        await session.commit()

        # Customer cancelled payment -> trigger compensation release
        await stock_service.release_stock_for_order(
            session=session,
            order_id="ord_103",
            outlet_id=outlet_id,
            items=items,
            correlation_id="corr_103",
            reason="Card declined",
        )
        await session.commit()

        # Verify reserved quantity returned to 0
        inv = await stock_service.get_or_create_inventory(session, outlet_id, variant_id)
        assert inv.quantity_on_hand == 10
        assert inv.reserved_quantity == 0
        assert inv.available_quantity == 10

        # Check outbox contains STOCK_RELEASED
        outbox_res = await session.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == "ord_103",
                OutboxEvent.event_type == EventType.STOCK_RELEASED.value,
            )
        )
        outbox = outbox_res.scalar_one()
        assert outbox.payload["reason"] == "Card declined"


@pytest.mark.asyncio
async def test_consumer_idempotency_duplicate_events():
    async with TestAsyncSession() as session:
        outlet_id = uuid4()
        variant_id = uuid4()

        # Seed stock of 20
        await stock_service.adjust_stock(session, outlet_id, variant_id, 20)
        await session.commit()

        event = EventEnvelope(
            event_id="evt_unique_12345",
            event_type=EventType.ORDER_CREATED,
            aggregate_type="ORDER",
            aggregate_id="ord_idempotent_test",
            correlation_id="corr_idempotent",
            producer="billing-service",
            payload={
                "order_id": "ord_idempotent_test",
                "outlet_id": str(outlet_id),
                "items": [{"variant_id": str(variant_id), "sku": "SKU-IDEM", "quantity": 5, "unit_price": 10.0}],
            },
        )

        # 1. First event processing
        await process_order_event(session, event)
        await session.commit()

        inv = await stock_service.get_or_create_inventory(session, outlet_id, variant_id)
        assert inv.reserved_quantity == 5

        # 2. Broker re-delivers duplicate of same event
        await process_order_event(session, event)
        await session.commit()

        # Reserved quantity MUST still be 5, NOT 10!
        inv_after = await stock_service.get_or_create_inventory(session, outlet_id, variant_id)
        assert inv_after.reserved_quantity == 5

        # Check ProcessedEvent table has exactly 1 entry
        proc_res = await session.execute(
            select(ProcessedEvent).where(ProcessedEvent.event_id == "evt_unique_12345")
        )
        assert proc_res.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_catalog_and_inventory_api():
    from shared.auth import Permissions, create_access_token

    admin_token = create_access_token({
        "sub": str(uuid4()),
        "email": "admin@shop.example.com",
        "roles": ["ADMIN"],
        "permissions": [
            Permissions.CATALOG_READ,
            Permissions.CATALOG_WRITE,
            Permissions.STOCK_READ,
            Permissions.STOCK_ADJUST,
        ],
        "is_superuser": True,
    })
    read_only_token = create_access_token({
        "sub": str(uuid4()),
        "email": "cashier@shop.example.com",
        "roles": ["CASHIER"],
        "permissions": [Permissions.CATALOG_READ, Permissions.STOCK_READ],
        "is_superuser": False,
    })

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    read_headers = {"Authorization": f"Bearer {read_only_token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthenticated request must return 401 Unauthorized
        unauth_resp = await client.post(
            "/catalog/categories",
            json={"name": "Electronics", "slug": "electronics", "description": "Gadgets"},
        )
        assert unauth_resp.status_code == 401

        # 2. Insufficient permission request must return 403 Forbidden
        forbidden_resp = await client.post(
            "/catalog/categories",
            json={"name": "Electronics", "slug": "electronics", "description": "Gadgets"},
            headers=read_headers,
        )
        assert forbidden_resp.status_code == 403

        # 3. Create Category with Admin token
        cat_resp = await client.post(
            "/catalog/categories",
            json={"name": "Electronics", "slug": "electronics", "description": "Gadgets"},
            headers=admin_headers,
        )
        assert cat_resp.status_code == 201
        cat_id = cat_resp.json()["id"]

        # 4. Create Product with 2 Variants
        prod_resp = await client.post(
            "/catalog/products",
            json={
                "name": "Wireless Headphones",
                "brand": "SoundWave",
                "category_id": cat_id,
                "variants": [
                    {
                        "sku": "HEADPHONE-BLK",
                        "barcode": "999888777001",
                        "title": "Black Edition",
                        "cost_price": 30.0,
                        "retail_price": 79.99,
                    },
                    {
                        "sku": "HEADPHONE-WHT",
                        "barcode": "999888777002",
                        "title": "White Edition",
                        "cost_price": 30.0,
                        "retail_price": 79.99,
                    },
                ],
            },
            headers=admin_headers,
        )
        assert prod_resp.status_code == 201
        prod_data = prod_resp.json()
        assert len(prod_data["variants"]) == 2
        var_id = prod_data["variants"][0]["id"]

        # 5. Test Fast Barcode Lookup
        barcode_resp = await client.get("/catalog/variants/barcode/999888777001", headers=read_headers)
        assert barcode_resp.status_code == 200
        assert barcode_resp.json()["sku"] == "HEADPHONE-BLK"

        # 6. Adjust Stock via API
        outlet_id = str(uuid4())
        adjust_resp = await client.post(
            "/inventory/adjust",
            json={
                "outlet_id": outlet_id,
                "variant_id": var_id,
                "quantity_change": 50,
                "notes": "Opening store stock",
            },
            headers=admin_headers,
        )
        assert adjust_resp.status_code == 200
        inv_data = adjust_resp.json()
        assert inv_data["quantity_on_hand"] == 50
        assert inv_data["available_quantity"] == 50

        # 7. Read Outlet Inventory via API
        list_inv = await client.get(f"/inventory/outlets/{outlet_id}", headers=read_headers)
        assert list_inv.status_code == 200
        assert len(list_inv.json()) == 1
        assert list_inv.json()[0]["quantity_on_hand"] == 50
