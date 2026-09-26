"""
Dynamic RBAC Role and Permission management endpoints.
"""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.auth_service.src.api.deps import require_permission
from services.auth_service.src.core.permissions import Permissions
from services.auth_service.src.db.session import get_db
from services.auth_service.src.models.role import Permission, Role, RolePermission
from services.auth_service.src.schemas.role import (
    PermissionResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
)

router = APIRouter(prefix="/roles", tags=["Roles & Permissions"])


@router.get("/permissions", response_model=List[PermissionResponse])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.ROLE_MANAGE)),
) -> List[PermissionResponse]:
    """List all available system permissions."""
    result = await db.execute(select(Permission).order_by(Permission.code))
    return list(result.scalars().all())


@router.get("", response_model=List[RoleResponse])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.ROLE_MANAGE)),
) -> List[RoleResponse]:
    """List all roles and their assigned permissions."""
    result = await db.execute(
        select(Role).options(selectinload(Role.permissions)).order_by(Role.name)
    )
    return list(result.scalars().all())


@router.post("", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_role(
    role_in: RoleCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.ROLE_MANAGE)),
) -> RoleResponse:
    """Create a new custom role and assign permissions."""
    existing_res = await db.execute(select(Role).where(Role.name == role_in.name))
    if existing_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role '{role_in.name}' already exists.",
        )

    # Fetch permissions to assign
    perms_res = await db.execute(
        select(Permission).where(Permission.code.in_(role_in.permission_codes))
    )
    assigned_perms = list(perms_res.scalars().all())

    role = Role(
        name=role_in.name,
        description=role_in.description,
        is_system=False,
    )
    db.add(role)
    await db.flush()

    for perm in assigned_perms:
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    await db.commit()

    # Reload with permissions
    reloaded = await db.execute(
        select(Role).where(Role.id == role.id).options(selectinload(Role.permissions))
    )
    return reloaded.scalar_one()


@router.get("/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.ROLE_MANAGE)),
) -> RoleResponse:
    """Get role details by ID."""
    res = await db.execute(
        select(Role).where(Role.id == role_id).options(selectinload(Role.permissions))
    )
    role = res.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_role(
    role_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.ROLE_MANAGE)),
) -> None:
    """Delete a custom role. System roles cannot be deleted."""
    res = await db.execute(select(Role).where(Role.id == role_id))
    role = res.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System roles (SUPERADMIN, ADMIN, CASHIER) cannot be deleted.",
        )

    await db.delete(role)
    await db.commit()
