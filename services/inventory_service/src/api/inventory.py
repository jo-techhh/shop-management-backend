"""
Inventory & Stock management API endpoints.
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.inventory_service.src.db.session import get_db
from services.inventory_service.src.models.stock import OutletInventory, StockAuditLog
from services.inventory_service.src.schemas.stock import (
    OutletInventoryResponse,
    StockAdjustRequest,
    StockAuditResponse,
)
from services.inventory_service.src.services import stock_service

router = APIRouter(prefix="/inventory", tags=["Inventory & Stock"])


@router.get("/outlets/{outlet_id}", response_model=List[OutletInventoryResponse])
async def list_outlet_inventory(
    outlet_id: UUID,
    low_stock_only: bool = False,
    limit: int = Query(default=100, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> List[OutletInventoryResponse]:
    """List current stock levels for a specific outlet, with optional low-stock filter."""
    stmt = (
        select(OutletInventory)
        .where(OutletInventory.outlet_id == outlet_id)
        .options(selectinload(OutletInventory.variant))
    )
    if low_stock_only:
        stmt = stmt.where(
            (OutletInventory.quantity_on_hand - OutletInventory.reserved_quantity) <= OutletInventory.reorder_threshold
        )
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    records = result.scalars().all()

    responses = []
    for r in records:
        resp = OutletInventoryResponse.model_validate(r)
        resp.available_quantity = r.available_quantity
        responses.append(resp)
    return responses


@router.get("/outlets/{outlet_id}/variants/{variant_id}", response_model=OutletInventoryResponse)
async def get_variant_inventory(
    outlet_id: UUID,
    variant_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> OutletInventoryResponse:
    """Retrieve stock level for a specific product variant at an outlet."""
    stmt = (
        select(OutletInventory)
        .where(OutletInventory.outlet_id == outlet_id, OutletInventory.variant_id == variant_id)
        .options(selectinload(OutletInventory.variant))
    )
    res = await db.execute(stmt)
    inv = res.scalar_one_or_none()
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No stock record found for variant '{variant_id}' at outlet '{outlet_id}'.",
        )
    resp = OutletInventoryResponse.model_validate(inv)
    resp.available_quantity = inv.available_quantity
    return resp


@router.post("/adjust", response_model=OutletInventoryResponse)
async def adjust_stock(
    adjust_in: StockAdjustRequest,
    db: AsyncSession = Depends(get_db),
) -> OutletInventoryResponse:
    """Manually add stock (intake) or subtract stock (write-off/damage) with audit logging."""
    try:
        inv = await stock_service.adjust_stock(
            session=db,
            outlet_id=adjust_in.outlet_id,
            variant_id=adjust_in.variant_id,
            quantity_change=adjust_in.quantity_change,
            change_type="ADJUSTMENT",
            notes=adjust_in.notes,
            reference_id=adjust_in.reference_id,
        )
        await db.commit()
        await db.refresh(inv, attribute_names=["variant"])
        resp = OutletInventoryResponse.model_validate(inv)
        resp.available_quantity = inv.available_quantity
        return resp
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.get("/outlets/{outlet_id}/audit-logs", response_model=List[StockAuditResponse])
async def list_stock_audit_logs(
    outlet_id: UUID,
    variant_id: Optional[UUID] = None,
    limit: int = Query(default=50, le=100),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> List[StockAuditResponse]:
    """View immutable stock audit log history for an outlet."""
    stmt = select(StockAuditLog).where(StockAuditLog.outlet_id == outlet_id)
    if variant_id:
        stmt = stmt.where(StockAuditLog.variant_id == variant_id)
    stmt = stmt.order_by(StockAuditLog.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())
