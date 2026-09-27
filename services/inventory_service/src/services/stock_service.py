"""
Core stock management service handling row-level locks, reservations, deductions, releases, and outbox event creation.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.inventory_service.src.models.catalog import ProductVariant
from services.inventory_service.src.models.outbox import OutboxEvent
from services.inventory_service.src.models.stock import OutletInventory, StockAuditLog
from shared.events.base import EventType

logger = logging.getLogger("stock_service")


async def get_or_create_inventory(
    session: AsyncSession,
    outlet_id: UUID,
    variant_id: UUID,
    for_update: bool = False,
) -> OutletInventory:
    """Fetch or initialize an OutletInventory row with optional row-level locking."""
    stmt = select(OutletInventory).where(
        OutletInventory.outlet_id == outlet_id,
        OutletInventory.variant_id == variant_id,
    )
    if for_update:
        stmt = stmt.with_for_update()

    result = await session.execute(stmt)
    inv = result.scalar_one_or_none()
    if not inv:
        inv = OutletInventory(
            outlet_id=outlet_id,
            variant_id=variant_id,
            quantity_on_hand=0,
            reserved_quantity=0,
            reorder_threshold=5,
        )
        session.add(inv)
        await session.flush()
    return inv


async def adjust_stock(
    session: AsyncSession,
    outlet_id: UUID,
    variant_id: UUID,
    quantity_change: int,
    change_type: str = "ADJUSTMENT",
    notes: Optional[str] = None,
    reference_id: Optional[str] = None,
) -> OutletInventory:
    """Manually add or subtract stock with audit log and row-level locking."""
    inv = await get_or_create_inventory(session, outlet_id, variant_id, for_update=True)

    prev_hand = inv.quantity_on_hand
    prev_res = inv.reserved_quantity

    new_hand = prev_hand + quantity_change
    if new_hand < 0:
        raise ValueError(f"Cannot adjust stock: resulting on-hand ({new_hand}) would be negative.")

    inv.quantity_on_hand = new_hand

    # Audit log
    audit = StockAuditLog(
        outlet_id=outlet_id,
        variant_id=variant_id,
        change_type=change_type,
        quantity_change=quantity_change,
        previous_on_hand=prev_hand,
        new_on_hand=new_hand,
        previous_reserved=prev_res,
        new_reserved=prev_res,
        reference_id=reference_id,
        notes=notes,
    )
    session.add(audit)
    await session.flush()
    return inv


async def reserve_stock_for_order(
    session: AsyncSession,
    order_id: str,
    outlet_id: UUID,
    items: List[Dict[str, Any]],
    correlation_id: str,
    causation_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Saga Step: Atomically reserve stock for an ORDER_CREATED event.
    Locks each variant row. If any item is insufficient, writes STOCK_RESERVATION_FAILED to outbox.
    If all available, increments reserved_quantity and writes STOCK_RESERVED to outbox.
    """
    locked_inventories: List[Tuple[OutletInventory, int, Dict[str, Any]]] = []

    # 1. Acquire row-level locks and verify availability for all items
    for item in items:
        variant_id = UUID(item["variant_id"])
        req_qty = int(item["quantity"])

        inv = await get_or_create_inventory(session, outlet_id, variant_id, for_update=True)
        available = inv.quantity_on_hand - inv.reserved_quantity

        if available < req_qty:
            fail_msg = (
                f"Insufficient stock for SKU '{item.get('sku', str(variant_id))}': "
                f"requested {req_qty}, available {available} (on hand: {inv.quantity_on_hand}, reserved: {inv.reserved_quantity})"
            )
            logger.warning(f"Order {order_id} reservation failed: {fail_msg}")

            # Write STOCK_RESERVATION_FAILED to transactional outbox
            failed_outbox = OutboxEvent(
                event_id=str(uuid4()),
                aggregate_type="INVENTORY",
                aggregate_id=order_id,
                event_type=EventType.STOCK_RESERVATION_FAILED.value,
                payload_json=json.dumps({
                    "order_id": order_id,
                    "outlet_id": str(outlet_id),
                    "failed_variant_id": str(variant_id),
                    "reason": fail_msg,
                }),
                correlation_id=correlation_id,
                causation_id=causation_id,
                status="PENDING",
            )
            session.add(failed_outbox)
            return False, fail_msg

        locked_inventories.append((inv, req_qty, item))

    # 2. All items available: increment reserved_quantity and record audit
    for inv, req_qty, item in locked_inventories:
        prev_hand = inv.quantity_on_hand
        prev_res = inv.reserved_quantity
        inv.reserved_quantity += req_qty

        audit = StockAuditLog(
            outlet_id=outlet_id,
            variant_id=inv.variant_id,
            change_type="RESERVATION",
            quantity_change=req_qty,
            previous_on_hand=prev_hand,
            new_on_hand=prev_hand,
            previous_reserved=prev_res,
            new_reserved=inv.reserved_quantity,
            reference_id=order_id,
            notes=f"Reserved for order {order_id}",
        )
        session.add(audit)

    # 3. Write STOCK_RESERVED event to transactional outbox
    success_outbox = OutboxEvent(
        event_id=str(uuid4()),
        aggregate_type="INVENTORY",
        aggregate_id=order_id,
        event_type=EventType.STOCK_RESERVED.value,
        payload_json=json.dumps({
            "order_id": order_id,
            "outlet_id": str(outlet_id),
            "items": items,
        }),
        correlation_id=correlation_id,
        causation_id=causation_id,
        status="PENDING",
    )
    session.add(success_outbox)
    logger.info(f"Order {order_id} stock reserved successfully across {len(items)} items.")
    return True, "Stock reserved successfully"


async def release_stock_for_order(
    session: AsyncSession,
    order_id: str,
    outlet_id: UUID,
    items: List[Dict[str, Any]],
    correlation_id: str,
    causation_id: Optional[str] = None,
    reason: str = "Payment failed or cancelled",
) -> None:
    """
    Saga Compensation Step: Release previously reserved stock back to available pool.
    Emits STOCK_RELEASED event via transactional outbox.
    """
    for item in items:
        variant_id = UUID(item["variant_id"])
        req_qty = int(item["quantity"])

        inv = await get_or_create_inventory(session, outlet_id, variant_id, for_update=True)
        prev_hand = inv.quantity_on_hand
        prev_res = inv.reserved_quantity

        # Decrement reserved quantity safely
        inv.reserved_quantity = max(0, inv.reserved_quantity - req_qty)

        audit = StockAuditLog(
            outlet_id=outlet_id,
            variant_id=variant_id,
            change_type="RELEASE",
            quantity_change=-req_qty,
            previous_on_hand=prev_hand,
            new_on_hand=prev_hand,
            previous_reserved=prev_res,
            new_reserved=inv.reserved_quantity,
            reference_id=order_id,
            notes=f"Released reservation for order {order_id}: {reason}",
        )
        session.add(audit)

    # Write STOCK_RELEASED event to transactional outbox
    released_outbox = OutboxEvent(
        event_id=str(uuid4()),
        aggregate_type="INVENTORY",
        aggregate_id=order_id,
        event_type=EventType.STOCK_RELEASED.value,
        payload_json=json.dumps({
            "order_id": order_id,
            "outlet_id": str(outlet_id),
            "items": items,
            "reason": reason,
        }),
        correlation_id=correlation_id,
        causation_id=causation_id,
        status="PENDING",
    )
    session.add(released_outbox)
    logger.info(f"Order {order_id} stock released successfully.")


async def deduct_stock_for_order(
    session: AsyncSession,
    order_id: str,
    outlet_id: UUID,
    items: List[Dict[str, Any]],
    reference_id: Optional[str] = None,
) -> None:
    """
    Saga Finalization Step: Called upon ORDER_PAID event.
    Permanently subtracts from both quantity_on_hand and reserved_quantity.
    """
    for item in items:
        variant_id = UUID(item["variant_id"])
        req_qty = int(item["quantity"])

        inv = await get_or_create_inventory(session, outlet_id, variant_id, for_update=True)
        prev_hand = inv.quantity_on_hand
        prev_res = inv.reserved_quantity

        inv.quantity_on_hand = max(0, inv.quantity_on_hand - req_qty)
        inv.reserved_quantity = max(0, inv.reserved_quantity - req_qty)

        audit = StockAuditLog(
            outlet_id=outlet_id,
            variant_id=variant_id,
            change_type="DEDUCTION",
            quantity_change=-req_qty,
            previous_on_hand=prev_hand,
            new_on_hand=inv.quantity_on_hand,
            previous_reserved=prev_res,
            new_reserved=inv.reserved_quantity,
            reference_id=order_id,
            notes=f"Deducted for paid order {order_id}",
        )
        session.add(audit)
    logger.info(f"Order {order_id} stock permanently deducted.")
