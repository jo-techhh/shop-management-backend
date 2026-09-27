"""
Billing and POS business service: invoice generation, order creation with outbox,
payment processing with compensation triggers, and thermal receipt generation.
"""
from datetime import datetime, timezone
import json
import logging
from typing import Tuple
from uuid import UUID, uuid4
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.billing_service.src.models.order import Order, OrderItem
from services.billing_service.src.models.outbox import OutboxEvent
from services.billing_service.src.models.payment import Payment
from services.billing_service.src.models.shift import PosShift
from services.billing_service.src.schemas.order import CheckoutRequest
from services.billing_service.src.schemas.payment import PaymentRequest
from shared.events.base import EventType

logger = logging.getLogger("billing_service")


async def generate_invoice_number(session: AsyncSession, outlet_id: UUID) -> str:
    """Generate sequential, unique invoice numbers: INV-{YYYYMMDD}-{COUNT:04d}."""
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    count_stmt = select(func.count(Order.id)).where(
        Order.outlet_id == outlet_id,
        func.to_char(Order.created_at, "YYYYMMDD") == today_str if session.bind.dialect.name == "postgresql" else True,
    )
    count_res = await session.execute(count_stmt)
    seq = (count_res.scalar() or 0) + 1
    return f"INV-{today_str}-{seq:04d}"


async def create_checkout_order(
    session: AsyncSession,
    checkout_in: CheckoutRequest,
    correlation_id: str,
) -> Order:
    """
    Saga Entrypoint:
    1. Validates shift if provided.
    2. Persists Order in 'PENDING' state with line items.
    3. Writes ORDER_CREATED event to outbox in the same local ACID transaction.
    """
    # Verify active shift if provided
    if checkout_in.shift_id:
        shift_res = await session.execute(
            select(PosShift).where(PosShift.id == checkout_in.shift_id, PosShift.status == "OPEN")
        )
        if not shift_res.scalar_one_or_none():
            raise ValueError(f"POS Shift '{checkout_in.shift_id}' is closed or does not exist.")

    # Calculate totals
    subtotal = sum(item.unit_price * item.quantity for item in checkout_in.items)
    total_amount = round(subtotal - checkout_in.discount_amount + checkout_in.tax_amount, 2)
    invoice_num = await generate_invoice_number(session, checkout_in.outlet_id)

    order = Order(
        invoice_number=invoice_num,
        outlet_id=checkout_in.outlet_id,
        cashier_id=checkout_in.cashier_id,
        shift_id=checkout_in.shift_id,
        customer_name=checkout_in.customer_name,
        customer_phone=checkout_in.customer_phone,
        subtotal=subtotal,
        discount_amount=checkout_in.discount_amount,
        tax_amount=checkout_in.tax_amount,
        total_amount=total_amount,
        status="PENDING",
    )
    session.add(order)
    await session.flush()

    items_payload = []
    for item_in in checkout_in.items:
        line_total = round(item_in.unit_price * item_in.quantity, 2)
        order_item = OrderItem(
            order_id=order.id,
            variant_id=item_in.variant_id,
            sku=item_in.sku,
            title=item_in.title,
            unit_price=item_in.unit_price,
            quantity=item_in.quantity,
            line_total=line_total,
        )
        session.add(order_item)
        items_payload.append({
            "variant_id": str(item_in.variant_id),
            "sku": item_in.sku,
            "quantity": item_in.quantity,
            "unit_price": item_in.unit_price,
        })

    # Write ORDER_CREATED to Transactional Outbox
    outbox = OutboxEvent(
        event_id=str(uuid4()),
        aggregate_type="ORDER",
        aggregate_id=str(order.id),
        event_type=EventType.ORDER_CREATED.value,
        payload_json=json.dumps({
            "order_id": str(order.id),
            "invoice_number": order.invoice_number,
            "outlet_id": str(order.outlet_id),
            "cashier_id": str(order.cashier_id),
            "items": items_payload,
            "total_amount": order.total_amount,
        }),
        correlation_id=correlation_id,
        status="PENDING",
    )
    session.add(outbox)
    logger.info(f"Created order {order.id} ({order.invoice_number}) in PENDING state with outbox event.")
    return order


async def process_order_payment(
    session: AsyncSession,
    order_id: UUID,
    payment_in: PaymentRequest,
    correlation_id: str,
) -> Tuple[Order, Payment]:
    """
    Process payment for an order with reserved stock.
    - If payment succeeds: mark PAID -> COMPLETED and emit ORDER_PAID.
    - If payment fails: mark PAYMENT_FAILED -> COMPENSATING_STOCK and emit ORDER_CANCELLED.
    """
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.items),
            selectinload(Order.payments),
            selectinload(Order.shift),
        )
        .with_for_update()
    )
    res = await session.execute(stmt)
    order = res.scalar_one_or_none()

    if not order:
        raise ValueError(f"Order '{order_id}' not found.")

    if order.status != "STOCK_RESERVED":
        raise ValueError(
            f"Cannot process payment for order in '{order.status}' state. Must be 'STOCK_RESERVED'."
        )

    items_payload = [
        {
            "variant_id": str(it.variant_id),
            "sku": it.sku,
            "quantity": it.quantity,
            "unit_price": it.unit_price,
        }
        for it in order.items
    ]

    # Handle payment failure or simulated decline
    if payment_in.simulate_failure or round(payment_in.amount, 2) != round(order.total_amount, 2):
        payment = Payment(
            order_id=order.id,
            payment_mode=payment_in.payment_mode,
            amount=payment_in.amount,
            status="FAILED",
            transaction_ref=payment_in.transaction_ref,
        )
        session.add(payment)

        order.status = "COMPENSATING_STOCK"

        # Emit compensation ORDER_CANCELLED event to trigger stock release in Inventory
        cancel_outbox = OutboxEvent(
            event_id=str(uuid4()),
            aggregate_type="ORDER",
            aggregate_id=str(order.id),
            event_type=EventType.ORDER_CANCELLED.value,
            payload_json=json.dumps({
                "order_id": str(order.id),
                "outlet_id": str(order.outlet_id),
                "items": items_payload,
                "reason": "Payment failed or amount mismatch",
            }),
            correlation_id=correlation_id,
            status="PENDING",
        )
        session.add(cancel_outbox)
        logger.warning(f"Payment failed for order {order.id}. Triggered stock release compensation.")
        return order, payment

    # Payment Success
    payment = Payment(
        order_id=order.id,
        payment_mode=payment_in.payment_mode,
        amount=payment_in.amount,
        status="SUCCESS",
        transaction_ref=payment_in.transaction_ref,
    )
    session.add(payment)

    order.status = "COMPLETED"

    # If cash payment and shift linked, increment shift cash collected
    if payment_in.payment_mode.upper() == "CASH" and order.shift:
        order.shift.cash_collected = round(order.shift.cash_collected + payment_in.amount, 2)

    # Emit ORDER_PAID event so inventory permanently deducts stock
    paid_outbox = OutboxEvent(
        event_id=str(uuid4()),
        aggregate_type="ORDER",
        aggregate_id=str(order.id),
        event_type=EventType.ORDER_PAID.value,
        payload_json=json.dumps({
            "order_id": str(order.id),
            "outlet_id": str(order.outlet_id),
            "items": items_payload,
            "total_amount": order.total_amount,
        }),
        correlation_id=correlation_id,
        status="PENDING",
    )
    session.add(paid_outbox)
    logger.info(f"Payment completed successfully for order {order.id} ({order.invoice_number}).")
    return order, payment


def format_escpos_thermal_receipt(order: Order, payments: list[Payment]) -> str:
    """Format an 80mm ESC/POS representation for counter receipt printers."""
    created_dt = order.created_at if order.created_at else datetime.now(timezone.utc)
    lines = [
        "========================================",
        "          RETAIL STORE RECEIPT          ",
        "========================================",
        f"Invoice: {order.invoice_number}",
        f"Date:    {created_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Cashier: {str(order.cashier_id)[:8]}",
        f"Outlet:  {str(order.outlet_id)[:8]}",
        "----------------------------------------",
        f"{'Item':<20} {'Qty':<4} {'Price':<6} {'Total':>7}",
        "----------------------------------------",
    ]

    for item in order.items:
        title = item.title[:19]
        lines.append(f"{title:<20} {item.quantity:<4} ${item.unit_price:<5.2f} ${item.line_total:>6.2f}")

    sub_str = f"${order.subtotal:.2f}"
    disc_str = f"-${order.discount_amount:.2f}"
    tax_str = f"${order.tax_amount:.2f}"
    tot_str = f"${order.total_amount:.2f}"

    lines.extend([
        "----------------------------------------",
        f"Subtotal:{sub_str:>31}",
        f"Discount:{disc_str:>31}",
        f"Tax:{tax_str:>36}",
        "========================================",
        f"TOTAL DUE:{tot_str:>30}",
        "========================================",
    ])

    for p in payments:
        if p.status == "SUCCESS":
            pay_amt_str = f"${p.amount:.2f}"
            lines.append(f"PAID VIA {p.payment_mode:<15}{pay_amt_str:>16}")

    lines.extend([
        "----------------------------------------",
        "       Thank you for your visit!        ",
        "       Please retain your receipt       ",
        "========================================",
    ])
    return "\n".join(lines)
