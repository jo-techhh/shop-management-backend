"""
End-to-End Cross-Service Integration Test for the Shop Management Microservices Platform:
Orchestrates the entire retail lifecycle across all services:
1. Auth Service: Superadmin creates branch outlet and provisions cashier.
2. Inventory Service: Catalog manager creates product with barcode and stocks the branch.
3. Billing Service: Cashier opens POS register shift with starting float.
4. Billing Service: Cashier scans barcode and initiates checkout -> Order in PENDING.
5. Saga Choreography (Redis Streams):
   - Billing Outbox -> ORDER_CREATED
   - Inventory Saga Consumer -> Reserves stock (available drops) -> Emits STOCK_RESERVED
   - Billing Saga Consumer -> Transitions order to STOCK_RESERVED
6. Billing Service: Cashier captures payment -> Order marked COMPLETED, emits ORDER_PAID.
7. Inventory Service: Consumes ORDER_PAID -> Permanently deducts stock on-hand.
8. Billing Service: Generates 80mm ESC/POS thermal receipt.
9. Billing Service: Cashier counts drawer and closes shift with zero cash variance.
"""
from datetime import datetime, timezone
import json
from uuid import UUID, uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Models & Services from Auth
from services.auth_service.src.core.security import hash_password
from services.auth_service.src.db.base import Base as AuthBase
from services.auth_service.src.models.outlet import Outlet
from services.auth_service.src.models.role import Role, Permission, RolePermission
from services.auth_service.src.models.user import User, UserRole

# Models & Services from Inventory
from services.inventory_service.src.db.base import Base as InvBase
from services.inventory_service.src.events.consumer import process_order_event as inv_process_order_event
from services.inventory_service.src.models.catalog import Category, Product, ProductVariant
from services.inventory_service.src.models.stock import OutletInventory
from services.inventory_service.src.services import stock_service

# Models & Services from Billing
from services.billing_service.src.db.base import Base as BillBase
from services.billing_service.src.events.consumer import process_inventory_event as bill_process_inv_event
from services.billing_service.src.models.order import Order
from services.billing_service.src.models.outbox import OutboxEvent as BillOutboxEvent
from services.billing_service.src.models.shift import PosShift
from services.billing_service.src.schemas.order import CheckoutRequest, OrderItemRequest
from services.billing_service.src.schemas.payment import PaymentRequest
from services.billing_service.src.services import billing_service
from shared.events.base import EventEnvelope, EventType

# Independent In-Memory Database Engines
auth_engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
inv_engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
bill_engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

AuthSession = async_sessionmaker(bind=auth_engine, expire_on_commit=False)
InvSession = async_sessionmaker(bind=inv_engine, expire_on_commit=False)
BillSession = async_sessionmaker(bind=bill_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_all_databases():
    async with auth_engine.begin() as conn:
        await conn.run_sync(AuthBase.metadata.create_all)
    async with inv_engine.begin() as conn:
        await conn.run_sync(InvBase.metadata.create_all)
    async with bill_engine.begin() as conn:
        await conn.run_sync(BillBase.metadata.create_all)

    yield

    async with auth_engine.begin() as conn:
        await conn.run_sync(AuthBase.metadata.drop_all)
    async with inv_engine.begin() as conn:
        await conn.run_sync(InvBase.metadata.drop_all)
    async with bill_engine.begin() as conn:
        await conn.run_sync(BillBase.metadata.drop_all)


@pytest.mark.asyncio
async def test_full_retail_lifecycle_e2e():
    correlation_id = "trace_e2e_full_lifecycle_001"

    # =========================================================================
    # STEP 1: AUTH SERVICE - Setup Branch Outlet and Cashier
    # =========================================================================
    async with AuthSession() as auth_session:
        outlet = Outlet(
            name="Airport Terminal Branch",
            code="AIRPORT-02",
            address="Terminal 2 Departures, Gate 14",
            phone="+1-555-777-0100",
            tax_number="GST-AIRPORT-02",
            receipt_footer="Have a pleasant flight! Thank you for your visit.",
        )
        auth_session.add(outlet)

        cashier_role = Role(name="CASHIER", description="Counter Cashier", is_system=True)
        auth_session.add(cashier_role)
        await auth_session.flush()

        cashier_user = User(
            email="elena_cashier@shop.example.com",
            hashed_password=hash_password("ElenaSecret@123"),
            full_name="Elena Rostova",
            is_active=True,
            outlet_id=outlet.id,
        )
        auth_session.add(cashier_user)
        await auth_session.flush()
        auth_session.add(UserRole(user_id=cashier_user.id, role_id=cashier_role.id))
        await auth_session.commit()

        outlet_id = outlet.id
        cashier_id = cashier_user.id

    # =========================================================================
    # STEP 2: INVENTORY SERVICE - Create Catalog Product and Stock Branch
    # =========================================================================
    async with InvSession() as inv_session:
        cat = Category(name="Outerwear", slug="outerwear", description="Jackets & Coats")
        inv_session.add(cat)
        await inv_session.flush()

        product = Product(
            name="Denim Trucker Jacket",
            brand="Leviathan Denim",
            category_id=cat.id,
        )
        inv_session.add(product)
        await inv_session.flush()

        variant = ProductVariant(
            product_id=product.id,
            sku="JACKET-DNM-M",
            barcode="890111222333",
            title="Medium / Vintage Wash",
            cost_price=35.00,
            retail_price=79.99,
        )
        inv_session.add(variant)
        await inv_session.commit()
        variant_id = variant.id

        # Stock 10 units at Airport Terminal Branch
        inv = await stock_service.adjust_stock(
            session=inv_session,
            outlet_id=outlet_id,
            variant_id=variant_id,
            quantity_change=10,
            notes="Opening branch shipment",
            reference_id="GRN-AIRPORT-001",
        )
        await inv_session.commit()

        assert inv.quantity_on_hand == 10
        assert inv.available_quantity == 10

    # =========================================================================
    # STEP 3: BILLING SERVICE - Cashier Elena Opens POS Shift
    # =========================================================================
    async with BillSession() as bill_session:
        shift = PosShift(
            outlet_id=outlet_id,
            cashier_id=cashier_id,
            opening_float=100.00,
            status="OPEN",
            notes="Morning terminal shift",
        )
        bill_session.add(shift)
        await bill_session.commit()
        shift_id = shift.id
        assert shift.expected_cash == 100.00

    # =========================================================================
    # STEP 4: BILLING SERVICE - Cashier Scans Barcode & Initiates Checkout
    # =========================================================================
    async with BillSession() as bill_session:
        # Customer buys 2 jackets ($79.99 x 2 = $159.98)
        checkout_req = CheckoutRequest(
            outlet_id=outlet_id,
            cashier_id=cashier_id,
            shift_id=shift_id,
            customer_name="Michael Brown",
            customer_phone="+1-555-444-3322",
            items=[
                OrderItemRequest(
                    variant_id=variant_id,
                    sku="JACKET-DNM-M",
                    title="Medium / Vintage Wash",
                    unit_price=79.99,
                    quantity=2,
                )
            ],
            discount_amount=0.0,
            tax_amount=0.0,
        )
        order = await billing_service.create_checkout_order(bill_session, checkout_req, correlation_id)
        await bill_session.commit()

        order_id = order.id
        assert order.status == "PENDING"
        assert order.total_amount == 159.98

        # Verify ORDER_CREATED outbox event was generated
        bill_outbox_res = await bill_session.execute(
            select(BillOutboxEvent).where(BillOutboxEvent.aggregate_id == str(order_id))
        )
        order_created_outbox = bill_outbox_res.scalar_one()
        assert order_created_outbox.event_type == EventType.ORDER_CREATED.value

        order_created_envelope = EventEnvelope(
            event_id=order_created_outbox.event_id,
            event_type=EventType.ORDER_CREATED,
            aggregate_type="ORDER",
            aggregate_id=str(order_id),
            correlation_id=correlation_id,
            producer="billing-service",
            payload=order_created_outbox.payload,
        )

    # =========================================================================
    # STEP 5: SAGA STEP 1 - Inventory Service Consumes ORDER_CREATED
    # =========================================================================
    async with InvSession() as inv_session:
        # Process order created event
        await inv_process_order_event(inv_session, order_created_envelope)
        await inv_session.commit()

        # Check stock state: 10 on hand, 2 reserved, 8 available
        inv_check = await stock_service.get_or_create_inventory(inv_session, outlet_id, variant_id)
        assert inv_check.quantity_on_hand == 10
        assert inv_check.reserved_quantity == 2
        assert inv_check.available_quantity == 8

        # Check Inventory Outbox produced STOCK_RESERVED
        from services.inventory_service.src.models.outbox import OutboxEvent as InvOutboxEvent
        inv_outbox_res = await inv_session.execute(
            select(InvOutboxEvent).where(
                InvOutboxEvent.aggregate_id == str(order_id),
                InvOutboxEvent.event_type == EventType.STOCK_RESERVED.value,
            )
        )
        stock_reserved_outbox = inv_outbox_res.scalar_one()

        stock_reserved_envelope = EventEnvelope(
            event_id=stock_reserved_outbox.event_id,
            event_type=EventType.STOCK_RESERVED,
            aggregate_type="INVENTORY",
            aggregate_id=str(order_id),
            correlation_id=correlation_id,
            causation_id=order_created_envelope.event_id,
            producer="inventory-service",
            payload=stock_reserved_outbox.payload,
        )

    # =========================================================================
    # STEP 6: SAGA STEP 2 - Billing Service Consumes STOCK_RESERVED
    # =========================================================================
    async with BillSession() as bill_session:
        await bill_process_inv_event(bill_session, stock_reserved_envelope)
        await bill_session.commit()

        # Verify order state advanced from PENDING -> STOCK_RESERVED
        order_reloaded = await bill_session.get(Order, order_id)
        assert order_reloaded.status == "STOCK_RESERVED"

    # =========================================================================
    # STEP 7: BILLING SERVICE - Cashier Collects Cash Payment
    # =========================================================================
    async with BillSession() as bill_session:
        payment_req = PaymentRequest(payment_mode="CASH", amount=159.98)
        order, payment = await billing_service.process_order_payment(
            session=bill_session,
            order_id=order_id,
            payment_in=payment_req,
            correlation_id=correlation_id,
        )
        await bill_session.commit()

        assert payment.status == "SUCCESS"
        assert order.status == "COMPLETED"

        # Check shift cash collected incremented: 0 + 159.98 = $159.98
        shift_reloaded = await bill_session.get(PosShift, shift_id)
        assert shift_reloaded.cash_collected == 159.98
        assert shift_reloaded.expected_cash == 259.98  # $100 float + $159.98 sales

        # Verify ORDER_PAID outbox event was generated
        order_paid_outbox_res = await bill_session.execute(
            select(BillOutboxEvent).where(
                BillOutboxEvent.aggregate_id == str(order_id),
                BillOutboxEvent.event_type == EventType.ORDER_PAID.value,
            )
        )
        order_paid_outbox = order_paid_outbox_res.scalar_one()

        order_paid_envelope = EventEnvelope(
            event_id=order_paid_outbox.event_id,
            event_type=EventType.ORDER_PAID,
            aggregate_type="ORDER",
            aggregate_id=str(order_id),
            correlation_id=correlation_id,
            producer="billing-service",
            payload=order_paid_outbox.payload,
        )

    # =========================================================================
    # STEP 8: SAGA FINALIZATION - Inventory Service Consumes ORDER_PAID
    # =========================================================================
    async with InvSession() as inv_session:
        # Inventory permanently deducts stock
        await inv_process_order_event(inv_session, order_paid_envelope)
        await inv_session.commit()

        # Check final stock: 8 on hand, 0 reserved, 8 available
        final_inv = await stock_service.get_or_create_inventory(inv_session, outlet_id, variant_id)
        assert final_inv.quantity_on_hand == 8
        assert final_inv.reserved_quantity == 0
        assert final_inv.available_quantity == 8

    # =========================================================================
    # STEP 9: BILLING SERVICE - Generate Receipt & Close POS Shift
    # =========================================================================
    async with BillSession() as bill_session:
        order_final = await bill_session.get(Order, order_id)
        thermal_receipt = billing_service.format_escpos_thermal_receipt(order_final, [payment])

        assert "RETAIL STORE RECEIPT" in thermal_receipt
        assert order_final.invoice_number in thermal_receipt
        assert "Denim Trucker Jacket" in thermal_receipt or "Medium / Vintage" in thermal_receipt
        assert "$159.98" in thermal_receipt
        assert "PAID VIA CASH" in thermal_receipt

        # Cashier counts $259.98 in the cash drawer at end of shift
        shift_final = await bill_session.get(PosShift, shift_id)
        shift_final.closing_cash = 259.98
        shift_final.cash_variance = round(shift_final.closing_cash - shift_final.expected_cash, 2)
        shift_final.status = "CLOSED"
        shift_final.closed_at = datetime.now(timezone.utc)
        await bill_session.commit()

        # Drawer is completely balanced!
        assert shift_final.status == "CLOSED"
        assert shift_final.cash_variance == 0.00
