"""
Outlet Management endpoints.
"""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_service.src.api.deps import require_permission
from services.auth_service.src.core.permissions import Permissions
from services.auth_service.src.db.session import get_db
from services.auth_service.src.models.outlet import Outlet
from services.auth_service.src.schemas.outlet import OutletCreate, OutletResponse, OutletUpdate

router = APIRouter(prefix="/outlets", tags=["Outlets"])


@router.get("", response_model=List[OutletResponse])
async def list_outlets(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.OUTLET_READ)),
) -> List[OutletResponse]:
    """List all registered outlets."""
    stmt = select(Outlet)
    if active_only:
        stmt = stmt.where(Outlet.is_active == True)
    stmt = stmt.order_by(Outlet.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=OutletResponse, status_code=status.HTTP_201_CREATED)
async def create_outlet(
    outlet_in: OutletCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.OUTLET_WRITE)),
) -> OutletResponse:
    """Create a new retail outlet / branch."""
    existing_res = await db.execute(select(Outlet).where(Outlet.code == outlet_in.code))
    if existing_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Outlet code '{outlet_in.code}' already exists.",
        )

    outlet = Outlet(**outlet_in.model_dump())
    db.add(outlet)
    await db.commit()
    await db.refresh(outlet)
    return outlet


@router.get("/{outlet_id}", response_model=OutletResponse)
async def get_outlet(
    outlet_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.OUTLET_READ)),
) -> OutletResponse:
    """Retrieve outlet details by UUID."""
    res = await db.execute(select(Outlet).where(Outlet.id == outlet_id))
    outlet = res.scalar_one_or_none()
    if not outlet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outlet '{outlet_id}' not found.",
        )
    return outlet


@router.patch("/{outlet_id}", response_model=OutletResponse)
async def update_outlet(
    outlet_id: UUID,
    outlet_in: OutletUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.OUTLET_WRITE)),
) -> OutletResponse:
    """Update outlet details or settings."""
    res = await db.execute(select(Outlet).where(Outlet.id == outlet_id))
    outlet = res.scalar_one_or_none()
    if not outlet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outlet '{outlet_id}' not found.",
        )

    for field, value in outlet_in.model_dump(exclude_unset=True).items():
        setattr(outlet, field, value)

    await db.commit()
    await db.refresh(outlet)
    return outlet


@router.delete("/{outlet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_outlet(
    outlet_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.OUTLET_DELETE)),
) -> None:
    """Deactivate an outlet."""
    res = await db.execute(select(Outlet).where(Outlet.id == outlet_id))
    outlet = res.scalar_one_or_none()
    if not outlet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outlet '{outlet_id}' not found.",
        )

    outlet.is_active = False
    await db.commit()
