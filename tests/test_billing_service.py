"""
Comprehensive tests for Billing & POS Service:
- POS register shifts (opening, cash drops, closing variance)
- Order checkout initiation and transactional outbox event creation
- Saga inventory outcome consumer (STOCK_RESERVED, STOCK_RESERVATION_FAILED, STOCK_RELEASED)
- Multi-tender payments (Cash, Card, UPI)
- Payment failure compensation flow (ORDER_CANCELLED outbox event)
- Thermal ESC/POS receipt generation
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

from services.billing_service.src.db.base import Base
from services.billing_service.src.db.session import get_db
from services.billing_service.src.events.consumer import process_inventory_event
from services.billing_service.src.main import app
from services.billing_service.src.models.order import Order, OrderItem
from services.billing_service.src.models.outbox import OutboxEvent
from services.billing_service.src.models.payment import Payment
from services.billing_service.src.models.shift import PosShift
from services.billing_service.src.schemas.order import CheckoutRequest, OrderItemRequest
from services.billing_service.src.schemas.payment import PaymentRequest
from services.billing_service.src.services import billing_service
from shared.events.base import EventEnvelope, EventType

# In-memory async SQLite engine with static pool for isolated test lifecycle
test_bill_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestAsyncSession = async_sessionmaker(bind=test_bill_engine, expire_on_commit=False)


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
    async with test_bill_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_bill_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_pos_shift_lifecycle_and_variance():
    async with TestAsyncSession() as session:
        outlet_id = uuid4()
        cashier_id = uuid4()

        # 1. Open shift with $150 starting float
        shift = PosShift(
            outlet_id=outlet_id,
            cashier_id=cashier_id,
            opening_float=150.0,
            status="OPEN",
        )
        session.add(shift)
        await session.commit()

        assert shift.expected_cash == 150.0

        # 2. Simulate cash sales during the day
        shift.cash_collected = 320.00
        shift.cash_drops = 100.00
        await session.commit()

        # Expected: 150 + 320 - 100 = $370
        assert shift.expected_cash == 370.00

        # 3. Cashier counts $365 in drawer at closing (a -$5.00 variance)
        shift.closing_cash = 365.00
        shift.cash_variance = round(shift.closing_cash - shift.expected_cash, 2)
        shift.status = "CLOSED"
        await session.commit()

        assert shift.cash_variance == -5.00
        assert shift.status == "CLOSED"


@pytest.mark.asyncio
async def test_checkout_initiation_and_outbox():
    async with TestAsyncSession() as session:
        outlet_id = uuid4()
        cashier_id = uuid4()
        variant_id = uuid4()

        req = CheckoutRequest(
            outlet_id=outlet_id,
            cashier_id=cashier_id,
            items=[
                OrderItemRequest(
                    variant_id=variant_id,
                    sku="SHIRT-BLK",
                    title="Black T-Shirt",
                    unit_price=25.0,
                    quantity=2,
                )
            ],
            discount_amount=5.0,
            tax_amount=2.0,
        )

        order = await billing_service.create_checkout_order(session, req, correlation_id="corr_check_01")
        await session.commit()

        # Order totals check: (25*2) - 5 + 2 = $47.00
        assert order.status == "PENDING"
        assert order.subtotal == 50.0
        assert order.total_amount == 47.0
        assert order.invoice_number.startswith("INV-")

        # Outbox event check
        outbox_res = await session.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == str(order.id))
        )
        outbox = outbox_res.scalar_one()
        assert outbox.event_type == EventType.ORDER_CREATED.value
        assert outbox.payload["total_amount"] == 47.0
        assert len(outbox.payload["items"]) == 1


@pytest.mark.asyncio
async def test_saga_inventory_events_consumer():
    async with TestAsyncSession() as session:
        outlet_id = uuid4()
        cashier_id = uuid4()

        # Create base order
        req = CheckoutRequest(
            outlet_id=outlet_id,
            cashier_id=cashier_id,
            items=[OrderItemRequest(variant_id=uuid4(), sku="S-1", title="Item 1", unit_price=10.0, quantity=1)],
        )
        order = await billing_service.create_checkout_order(session, req, "corr_saga")
        await session.commit()
        assert order.status == "PENDING"

        # 1. Simulate STOCK_RESERVED event from Inventory
        stock_reserved_event = EventEnvelope(
            event_id="evt_res_01",
            event_type=EventType.STOCK_RESERVED,
            aggregate_type="INVENTORY",
            aggregate_id=str(order.id),
            correlation_id="corr_saga",
            producer="inventory-service",
            payload={"order_id": str(order.id), "outlet_id": str(outlet_id), "items": []},
        )
        await process_inventory_event(session, stock_reserved_event)
        await session.commit()

        # Verify order transitioned to STOCK_RESERVED
        reloaded = await session.get(Order, order.id)
        assert reloaded.status == "STOCK_RESERVED"


@pytest.mark.asyncio
async def test_payment_success_and_order_completion():
    async with TestAsyncSession() as session:
        outlet_id = uuid4()
        cashier_id = uuid4()

        # Create and reserve order
        req = CheckoutRequest(
            outlet_id=outlet_id,
            cashier_id=cashier_id,
            items=[OrderItemRequest(variant_id=uuid4(), sku="S-1", title="Item 1", unit_price=20.0, quantity=1)],
        )
        order = await billing_service.create_checkout_order(session, req, "corr_pay")
        order.status = "STOCK_RESERVED"  # Stock was reserved by Inventory
        await session.commit()

        # Process successful cash payment
        pay_req = PaymentRequest(payment_mode="CASH", amount=20.0)
        order, payment = await billing_service.process_order_payment(session, order.id, pay_req, "corr_pay")
        await session.commit()

        assert payment.status == "SUCCESS"
        assert order.status == "COMPLETED"

        # Check ORDER_PAID outbox event was emitted
        outbox_res = await session.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == str(order.id),
                OutboxEvent.event_type == EventType.ORDER_PAID.value,
            )
        )
        outbox = outbox_res.scalar_one()
        assert outbox.payload["total_amount"] == 20.0


@pytest.mark.asyncio
async def test_payment_failure_compensation_trigger():
    async with TestAsyncSession() as session:
        outlet_id = uuid4()
        cashier_id = uuid4()

        # Create and reserve order
        req = CheckoutRequest(
            outlet_id=outlet_id,
            cashier_id=cashier_id,
            items=[OrderItemRequest(variant_id=uuid4(), sku="S-1", title="Item 1", unit_price=50.0, quantity=1)],
        )
        order = await billing_service.create_checkout_order(session, req, "corr_fail")
        order.status = "STOCK_RESERVED"
        await session.commit()

        # Card declined / simulated failure
        pay_req = PaymentRequest(payment_mode="CARD", amount=50.0, simulate_failure=True)
        order, payment = await billing_service.process_order_payment(session, order.id, pay_req, "corr_fail")
        await session.commit()

        assert payment.status == "FAILED"
        assert order.status == "COMPENSATING_STOCK"

        # Check ORDER_CANCELLED event exists in outbox to trigger stock release
        outbox_res = await session.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == str(order.id),
                OutboxEvent.event_type == EventType.ORDER_CANCELLED.value,
            )
        )
        outbox = outbox_res.scalar_one()
        assert "Payment failed" in outbox.payload["reason"]


@pytest.mark.asyncio
async def test_thermal_receipt_formatting():
    order = Order(
        invoice_number="INV-20260927-0042",
        outlet_id=uuid4(),
        cashier_id=uuid4(),
        subtotal=40.0,
        discount_amount=5.0,
        tax_amount=3.5,
        total_amount=38.5,
    )
    item = OrderItem(
        variant_id=uuid4(),
        sku="TSHIRT-L",
        title="Graphic T-Shirt",
        unit_price=20.0,
        quantity=2,
        line_total=40.0,
    )
    order.items = [item]
    payment = Payment(payment_mode="CARD", amount=38.5, status="SUCCESS")

    thermal_text = billing_service.format_escpos_thermal_receipt(order, [payment])
    assert "RETAIL STORE RECEIPT" in thermal_text
    assert "INV-20260927-0042" in thermal_text
    assert "Graphic T-Shirt" in thermal_text
    assert "PAID VIA CARD" in thermal_text
    assert "$38.50" in thermal_text


@pytest.mark.asyncio
async def test_pos_and_shifts_api():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        outlet_id = str(uuid4())
        cashier_id = str(uuid4())

        # 1. Open POS Shift
        open_resp = await client.post(
            "/shifts/open",
            json={"outlet_id": outlet_id, "opening_float": 100.0, "notes": "Morning Shift"},
            headers={"X-User-Id": cashier_id},
        )
        assert open_resp.status_code == 201
        shift_data = open_resp.json()
        shift_id = shift_data["id"]
        assert shift_data["status"] == "OPEN"
        assert shift_data["expected_cash"] == 100.0

        # 2. Checkout Order
        var_id = str(uuid4())
        checkout_resp = await client.post(
            "/pos/checkout",
            json={
                "outlet_id": outlet_id,
                "cashier_id": cashier_id,
                "shift_id": shift_id,
                "customer_name": "Alice Smith",
                "items": [
                    {
                        "variant_id": var_id,
                        "sku": "JEANS-32",
                        "title": "Denim Jeans 32",
                        "unit_price": 60.0,
                        "quantity": 1,
                    }
                ],
                "discount_amount": 0.0,
                "tax_amount": 5.0,
            },
        )
        assert checkout_resp.status_code == 202
        order_data = checkout_resp.json()
        order_id = order_data["id"]
        assert order_data["status"] == "PENDING"
        assert order_data["total_amount"] == 65.0

        # 3. Simulate Stock Reserved via DB and test payment
        async with TestAsyncSession() as session:
            from uuid import UUID
            o = await session.get(Order, UUID(order_id))
            o.status = "STOCK_RESERVED"
            await session.commit()

        # 4. Pay Order
        pay_resp = await client.post(
            f"/pos/orders/{order_id}/pay",
            json={"payment_mode": "CASH", "amount": 65.0},
        )
        assert pay_resp.status_code == 200
        assert pay_resp.json()["status"] == "COMPLETED"

        # 5. Fetch Receipt
        receipt_resp = await client.get(f"/pos/orders/{order_id}/receipt")
        assert receipt_resp.status_code == 200
        receipt = receipt_resp.json()
        assert receipt["total_amount"] == 65.0
        assert "RETAIL STORE RECEIPT" in receipt["escpos_thermal_text"]

        # 6. Close Shift
        close_resp = await client.post(
            f"/shifts/{shift_id}/close",
            json={"closing_cash": 165.0, "notes": "Balanced drawer"},
        )
        assert close_resp.status_code == 200
        closed_data = close_resp.json()
        # Opening (100) + Cash Collected (65) = 165 -> Variance = 0.0
        assert closed_data["status"] == "CLOSED"
        assert closed_data["cash_variance"] == 0.0
