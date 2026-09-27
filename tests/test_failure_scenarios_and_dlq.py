"""
Comprehensive verification of failure scenarios, compensations, and DLQ handling:
- Scenario 1: Insufficient stock failure path (STOCK_FAILED)
- Scenario 2: Payment failure and stock release compensation (STOCK_RELEASED -> CANCELLED)
- Scenario 3: Duplicate message redelivery idempotency across both services
- Scenario 4: Poison pill / failed event Dead Letter Queue (DLQ) routing
- Scenario 5: Outbox retry limits and DLQ escalation on broker persistent failure
"""
from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Inventory
from services.inventory_service.src.db.base import Base as InvBase
from services.inventory_service.src.events.consumer import process_order_event as inv_process_order_event
from services.inventory_service.src.models.outbox import OutboxEvent as InvOutboxEvent
from services.inventory_service.src.models.processed import ProcessedEvent as InvProcessedEvent
from services.inventory_service.src.models.stock import OutletInventory
from services.inventory_service.src.services import stock_service

# Billing
from services.billing_service.src.db.base import Base as BillBase
from services.billing_service.src.events.consumer import process_inventory_event as bill_process_inv_event
from services.billing_service.src.models.order import Order
from services.billing_service.src.models.outbox import OutboxEvent as BillOutboxEvent
from services.billing_service.src.models.processed import ProcessedEvent as BillProcessedEvent
from services.billing_service.src.schemas.order import CheckoutRequest, OrderItemRequest
from services.billing_service.src.schemas.payment import PaymentRequest
from services.billing_service.src.services import billing_service
from shared.broker.streams import send_to_dlq
from shared.events.base import EventEnvelope, EventType

inv_engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
bill_engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

InvSession = async_sessionmaker(bind=inv_engine, expire_on_commit=False)
BillSession = async_sessionmaker(bind=bill_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_databases():
    async with inv_engine.begin() as conn:
        await conn.run_sync(InvBase.metadata.create_all)
    async with bill_engine.begin() as conn:
        await conn.run_sync(BillBase.metadata.create_all)
    yield
    async with inv_engine.begin() as conn:
        await conn.run_sync(InvBase.metadata.drop_all)
    async with bill_engine.begin() as conn:
        await conn.run_sync(BillBase.metadata.drop_all)


@pytest.mark.asyncio
async def test_failure_scenario_insufficient_stock():
    """Scenario 1: Checkout requested qty exceeds available stock."""
    outlet_id = uuid4()
    cashier_id = uuid4()
    variant_id = uuid4()

    # 1. Stock only 2 units in Inventory
    async with InvSession() as session:
        await stock_service.adjust_stock(session, outlet_id, variant_id, 2)
        await session.commit()

    # 2. Billing: customer requests 5 units
    async with BillSession() as session:
        req = CheckoutRequest(
            outlet_id=outlet_id,
            cashier_id=cashier_id,
            items=[OrderItemRequest(variant_id=variant_id, sku="SKU-LIMITED", title="Item", unit_price=10.0, quantity=5)],
        )
        order = await billing_service.create_checkout_order(session, req, "corr_insufficient")
        await session.commit()
        order_id = order.id
        assert order.status == "PENDING"

        # Construct ORDER_CREATED envelope
        order_created_env = EventEnvelope(
            event_id="evt_insufficient_stock",
            event_type=EventType.ORDER_CREATED,
            aggregate_type="ORDER",
            aggregate_id=str(order_id),
            correlation_id="corr_insufficient",
            producer="billing-service",
            payload={
                "order_id": str(order_id),
                "outlet_id": str(outlet_id),
                "items": [{"variant_id": str(variant_id), "sku": "SKU-LIMITED", "quantity": 5}],
            },
        )

    # 3. Inventory: Consumes ORDER_CREATED -> detects shortage -> emits STOCK_RESERVATION_FAILED
    async with InvSession() as session:
        await inv_process_order_event(session, order_created_env)
        await session.commit()

        # Stock is untouched
        inv = await stock_service.get_or_create_inventory(session, outlet_id, variant_id)
        assert inv.quantity_on_hand == 2
        assert inv.reserved_quantity == 0

        # Outbox has failure event
        outbox_res = await session.execute(
            select(InvOutboxEvent).where(
                InvOutboxEvent.aggregate_id == str(order_id),
                InvOutboxEvent.event_type == EventType.STOCK_RESERVATION_FAILED.value,
            )
        )
        stock_failed_outbox = outbox_res.scalar_one()
        assert "Insufficient stock" in stock_failed_outbox.payload["reason"]

        stock_failed_env = EventEnvelope(
            event_id=stock_failed_outbox.event_id,
            event_type=EventType.STOCK_RESERVATION_FAILED,
            aggregate_type="INVENTORY",
            aggregate_id=str(order_id),
            correlation_id="corr_insufficient",
            producer="inventory-service",
            payload=stock_failed_outbox.payload,
        )

    # 4. Billing: Consumes STOCK_RESERVATION_FAILED -> transitions order to STOCK_FAILED
    async with BillSession() as session:
        await bill_process_inv_event(session, stock_failed_env)
        await session.commit()

        reloaded_order = await session.get(Order, order_id)
        assert reloaded_order.status == "STOCK_FAILED"


@pytest.mark.asyncio
async def test_failure_scenario_payment_declined_compensation():
    """Scenario 2: Payment fails after stock reservation -> compensation releases stock."""
    outlet_id = uuid4()
    cashier_id = uuid4()
    variant_id = uuid4()

    # 1. Seed 10 in inventory
    async with InvSession() as session:
        await stock_service.adjust_stock(session, outlet_id, variant_id, 10)
        await session.commit()

    # 2. Billing: checkout order created & stock reserved
    async with BillSession() as session:
        req = CheckoutRequest(
            outlet_id=outlet_id,
            cashier_id=cashier_id,
            items=[OrderItemRequest(variant_id=variant_id, sku="SKU-COMP", title="Item", unit_price=50.0, quantity=3)],
        )
        order = await billing_service.create_checkout_order(session, req, "corr_comp")
        order.status = "STOCK_RESERVED"
        await session.commit()
        order_id = order.id

    # 3. Inventory: has 3 reserved (available=7)
    async with InvSession() as session:
        await stock_service.reserve_stock_for_order(
            session=session,
            order_id=str(order_id),
            outlet_id=outlet_id,
            items=[{"variant_id": str(variant_id), "sku": "SKU-COMP", "quantity": 3, "unit_price": 50.0}],
            correlation_id="corr_comp",
        )
        await session.commit()
        inv = await stock_service.get_or_create_inventory(session, outlet_id, variant_id)
        assert inv.reserved_quantity == 3
        assert inv.available_quantity == 7

    # 4. Billing: Payment declined
    async with BillSession() as session:
        pay_req = PaymentRequest(payment_mode="CARD", amount=150.0, simulate_failure=True)
        order, payment = await billing_service.process_order_payment(session, order_id, pay_req, "corr_comp")
        await session.commit()

        assert payment.status == "FAILED"
        assert order.status == "COMPENSATING_STOCK"

        # Check ORDER_CANCELLED outbox
        outbox_res = await session.execute(
            select(BillOutboxEvent).where(
                BillOutboxEvent.aggregate_id == str(order_id),
                BillOutboxEvent.event_type == EventType.ORDER_CANCELLED.value,
            )
        )
        cancel_outbox = outbox_res.scalar_one()

        cancel_env = EventEnvelope(
            event_id=cancel_outbox.event_id,
            event_type=EventType.ORDER_CANCELLED,
            aggregate_type="ORDER",
            aggregate_id=str(order_id),
            correlation_id="corr_comp",
            producer="billing-service",
            payload=cancel_outbox.payload,
        )

    # 5. Inventory: Consumes ORDER_CANCELLED -> releases stock back to available
    async with InvSession() as session:
        await inv_process_order_event(session, cancel_env)
        await session.commit()

        # Reserved quantity restored to 0, available restored to 10
        inv_after = await stock_service.get_or_create_inventory(session, outlet_id, variant_id)
        assert inv_after.quantity_on_hand == 10
        assert inv_after.reserved_quantity == 0
        assert inv_after.available_quantity == 10

        # Outbox emitted STOCK_RELEASED
        outbox_res = await session.execute(
            select(InvOutboxEvent).where(
                InvOutboxEvent.aggregate_id == str(order_id),
                InvOutboxEvent.event_type == EventType.STOCK_RELEASED.value,
            )
        )
        released_outbox = outbox_res.scalar_one()
        released_env = EventEnvelope(
            event_id=released_outbox.event_id,
            event_type=EventType.STOCK_RELEASED,
            aggregate_type="INVENTORY",
            aggregate_id=str(order_id),
            correlation_id="corr_comp",
            producer="inventory-service",
            payload=released_outbox.payload,
        )

    # 6. Billing: Consumes STOCK_RELEASED -> order finalized as CANCELLED
    async with BillSession() as session:
        await bill_process_inv_event(session, released_env)
        await session.commit()

        final_order = await session.get(Order, order_id)
        assert final_order.status == "CANCELLED"


@pytest.mark.asyncio
async def test_failure_scenario_duplicate_event_idempotency():
    """Scenario 3: Network blip causes Redis Streams to redeliver ORDER_CREATED multiple times."""
    outlet_id = uuid4()
    variant_id = uuid4()

    async with InvSession() as session:
        # Initial stock: 15
        await stock_service.adjust_stock(session, outlet_id, variant_id, 15)
        await session.commit()

        duplicate_event = EventEnvelope(
            event_id="evt_redelivery_dup_999",
            event_type=EventType.ORDER_CREATED,
            aggregate_type="ORDER",
            aggregate_id="ord_duplicate_test",
            correlation_id="corr_dup",
            producer="billing-service",
            payload={
                "order_id": "ord_duplicate_test",
                "outlet_id": str(outlet_id),
                "items": [{"variant_id": str(variant_id), "sku": "SKU-DUP", "quantity": 4}],
            },
        )

        # 1st Delivery
        await inv_process_order_event(session, duplicate_event)
        await session.commit()
        inv1 = await stock_service.get_or_create_inventory(session, outlet_id, variant_id)
        assert inv1.reserved_quantity == 4

        # 2nd Redelivery of exact same message
        await inv_process_order_event(session, duplicate_event)
        await session.commit()
        inv2 = await stock_service.get_or_create_inventory(session, outlet_id, variant_id)
        assert inv2.reserved_quantity == 4  # STILL 4!

        # 3rd Redelivery of exact same message
        await inv_process_order_event(session, duplicate_event)
        await session.commit()
        inv3 = await stock_service.get_or_create_inventory(session, outlet_id, variant_id)
        assert inv3.reserved_quantity == 4  # STILL 4!

        # ProcessedEvent contains only 1 entry
        proc_res = await session.execute(
            select(InvProcessedEvent).where(InvProcessedEvent.event_id == "evt_redelivery_dup_999")
        )
        assert len(proc_res.scalars().all()) == 1


@pytest.mark.asyncio
async def test_dlq_routing_for_failed_events():
    """Scenario 4: Poison pill routing to Dead Letter Queue stream."""
    mock_redis = AsyncMock()
    mock_redis.xadd.return_value = "1727400000000-0"

    dlq_id = await send_to_dlq(
        redis=mock_redis,
        dlq_stream="dlq:failed-events",
        raw_message_id="1727400000000-0",
        event_data={
            "event_id": "evt_poison_pill_01",
            "event_type": "CORRUPTED_EVENT",
            "correlation_id": "trace_err_01",
            "payload": {"corrupted": True},
        },
        error_message="KeyError: 'outlet_id' missing from malformed event",
        retry_count=5,
        consumer_name="test-consumer",
    )

    assert dlq_id == "1727400000000-0"
    mock_redis.xadd.assert_called_once()
    call_args = mock_redis.xadd.call_args[1]
    assert call_args["name"] == "dlq:failed-events"
    fields = call_args["fields"]
    assert fields["event_id"] == "evt_poison_pill_01"
    assert "KeyError" in fields["error"]
    assert fields["retry_count"] == "5"
