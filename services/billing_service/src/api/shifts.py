"""
Cashier POS Shift endpoints.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.billing_service.src.db.session import get_db
from services.billing_service.src.models.shift import PosShift
from services.billing_service.src.schemas.shift import PosShiftResponse, ShiftCloseRequest, ShiftOpenRequest
from shared.auth import CurrentUser, Permissions, require_permission

router = APIRouter(prefix="/shifts", tags=["POS Shifts"])


@router.post("/open", response_model=PosShiftResponse, status_code=status.HTTP_201_CREATED)
async def open_shift(
    shift_in: ShiftOpenRequest,
    x_user_id: Optional[str] = Header(None, alias="x-user-id"),
    cashier_id_query: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Permissions.POS_SHIFT_MANAGE)),
) -> PosShiftResponse:
    """Open a cashier register shift with starting cash float."""
    cashier_uuid_str = x_user_id or (str(cashier_id_query) if cashier_id_query else None) or str(current_user.id)
    cashier_id = UUID(cashier_uuid_str)

    # Check if cashier already has an active OPEN shift
    existing_stmt = select(PosShift).where(
        PosShift.cashier_id == cashier_id,
        PosShift.outlet_id == shift_in.outlet_id,
        PosShift.status == "OPEN",
    )
    existing_res = await db.execute(existing_stmt)
    if existing_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cashier already has an active OPEN shift at this outlet. Close it first.",
        )

    shift = PosShift(
        outlet_id=shift_in.outlet_id,
        cashier_id=cashier_id,
        opening_float=shift_in.opening_float,
        notes=shift_in.notes,
        status="OPEN",
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    resp = PosShiftResponse.model_validate(shift)
    resp.expected_cash = shift.expected_cash
    return resp


@router.post("/{shift_id}/close", response_model=PosShiftResponse)
async def close_shift(
    shift_id: UUID,
    close_in: ShiftCloseRequest,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(require_permission(Permissions.POS_SHIFT_MANAGE)),
) -> PosShiftResponse:
    """Close an active shift, calculate drawer cash variance, and finalize reconciliation."""
    stmt = select(PosShift).where(PosShift.id == shift_id, PosShift.status == "OPEN")
    res = await db.execute(stmt)
    shift = res.scalar_one_or_none()

    if not shift:
        raise HTTPException(status_code=404, detail="Active OPEN shift not found.")

    shift.closing_cash = close_in.closing_cash
    shift.cash_variance = round(close_in.closing_cash - shift.expected_cash, 2)
    shift.status = "CLOSED"
    shift.closed_at = datetime.now(timezone.utc)
    if close_in.notes:
        shift.notes = f"{shift.notes or ''} | Closing notes: {close_in.notes}".strip()

    await db.commit()
    await db.refresh(shift)
    resp = PosShiftResponse.model_validate(shift)
    resp.expected_cash = shift.expected_cash
    return resp


@router.get("/active", response_model=PosShiftResponse)
async def get_active_shift(
    outlet_id: UUID,
    cashier_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_permission(Permissions.POS_SHIFT_MANAGE)),
) -> PosShiftResponse:
    """Get current cashier's active shift at an outlet."""
    effective_cashier_id = cashier_id or current_user.id
    stmt = select(PosShift).where(
        PosShift.cashier_id == effective_cashier_id,
        PosShift.outlet_id == outlet_id,
        PosShift.status == "OPEN",
    )
    res = await db.execute(stmt)
    shift = res.scalar_one_or_none()
    if not shift:
        raise HTTPException(status_code=404, detail="No active shift found for this cashier.")
    resp = PosShiftResponse.model_validate(shift)
    resp.expected_cash = shift.expected_cash
    return resp


@router.get("/{shift_id}", response_model=PosShiftResponse)
async def get_shift(
    shift_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(require_permission(Permissions.POS_SHIFT_MANAGE)),
) -> PosShiftResponse:
    """Get shift details by ID."""
    stmt = select(PosShift).where(PosShift.id == shift_id)
    res = await db.execute(stmt)
    shift = res.scalar_one_or_none()
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found.")
    resp = PosShiftResponse.model_validate(shift)
    resp.expected_cash = shift.expected_cash
    return resp
