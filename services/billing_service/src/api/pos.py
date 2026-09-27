"""
POS & Billing API endpoints: Checkout Saga Initiation, Payments, and Receipts.
"""
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.billing_service.src.db.session import get_db
from services.billing_service.src.models.order import Order
from services.billing_service.src.schemas.order import CheckoutRequest, OrderResponse
from services.billing_service.src.schemas.payment import PaymentRequest, PaymentResponse
from services.billing_service.src.schemas.receipt import ReceiptResponse
from services.billing_service.src.services import billing_service
from shared.middleware.correlation import get_correlation_id

router = APIRouter(prefix="/pos", tags=["Point of Sale & Billing"])


@router.post("/checkout", response_model=OrderResponse, status_code=status.HTTP_202_ACCEPTED)
async def checkout(
    checkout_in: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    """
    Saga Entrypoint: Initiates checkout by creating an order in PENDING state
    and atomically writing ORDER_CREATED to the outbox table.
    """
    try:
        correlation_id = get_correlation_id()
        order = await billing_service.create_checkout_order(
            session=db,
            checkout_in=checkout_in,
            correlation_id=correlation_id,
        )
        await db.commit()
        await db.refresh(order, attribute_names=["items"])
        return order
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    """Check order status and items (e.g. while POS waits for STOCK_RESERVED)."""
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
    )
    res = await db.execute(stmt)
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.post("/orders/{order_id}/pay", response_model=OrderResponse)
async def pay_order(
    order_id: UUID,
    payment_in: PaymentRequest,
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    """
    Process payment for an order with reserved stock.
    - If payment succeeds: order transitions to COMPLETED and emits ORDER_PAID.
    - If payment fails: order transitions to COMPENSATING_STOCK and emits ORDER_CANCELLED to release reserved stock.
    """
    try:
        correlation_id = get_correlation_id()
        order, payment = await billing_service.process_order_payment(
            session=db,
            order_id=order_id,
            payment_in=payment_in,
            correlation_id=correlation_id,
        )
        await db.commit()
        await db.refresh(order, attribute_names=["items"])
        return order
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.get("/orders/{order_id}/receipt", response_model=ReceiptResponse)
async def get_receipt(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ReceiptResponse:
    """Generate printable receipt and 80mm ESC/POS thermal text."""
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.items),
            selectinload(Order.payments),
        )
    )
    res = await db.execute(stmt)
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    thermal_text = billing_service.format_escpos_thermal_receipt(order, order.payments)

    return ReceiptResponse(
        invoice_number=order.invoice_number,
        outlet_id=order.outlet_id,
        cashier_id=order.cashier_id,
        order_id=order.id,
        date=order.created_at,
        customer_name=order.customer_name,
        items=order.items,
        subtotal=order.subtotal,
        discount_amount=order.discount_amount,
        tax_amount=order.tax_amount,
        total_amount=order.total_amount,
        status=order.status,
        payments=order.payments,
        escpos_thermal_text=thermal_text,
    )
