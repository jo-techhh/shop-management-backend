"""
User and Staff Management endpoints.
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.auth_service.src.api.deps import get_current_user, require_permission
from services.auth_service.src.core.permissions import Permissions
from services.auth_service.src.core.security import hash_password
from services.auth_service.src.db.session import get_db
from services.auth_service.src.models.outlet import Outlet
from services.auth_service.src.models.role import Role
from services.auth_service.src.models.user import User, UserRole
from services.auth_service.src.schemas.user import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Users & Staff"])


@router.get("", response_model=List[UserResponse])
async def list_users(
    outlet_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.USER_READ)),
) -> List[UserResponse]:
    """List staff accounts, optionally filtered by outlet."""
    stmt = (
        select(User)
        .options(
            selectinload(User.roles).selectinload(Role.permissions),
            selectinload(User.outlet),
        )
        .order_by(User.full_name)
    )
    if outlet_id:
        stmt = stmt.where(User.outlet_id == outlet_id)

    result = await db.execute(stmt)
    users = result.scalars().all()

    responses = []
    for u in users:
        resp = UserResponse.model_validate(u)
        resp.permissions = list(u.permissions_set)
        responses.append(resp)
    return responses


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_permission(Permissions.USER_WRITE)),
) -> UserResponse:
    """Create a new staff member (e.g. cashier or manager) with role assignment."""
    existing_res = await db.execute(select(User).where(User.email == user_in.email))
    if existing_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with email '{user_in.email}' already exists.",
        )

    # Validate outlet if provided
    if user_in.outlet_id:
        out_res = await db.execute(select(Outlet).where(Outlet.id == user_in.outlet_id))
        if not out_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Outlet '{user_in.outlet_id}' not found.",
            )

    # Validate roles
    roles_res = await db.execute(select(Role).where(Role.name.in_(user_in.role_names)))
    assigned_roles = list(roles_res.scalars().all())
    if not assigned_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No valid roles found for {user_in.role_names}.",
        )

    user = User(
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        full_name=user_in.full_name,
        is_active=user_in.is_active,
        is_superuser=False,
        outlet_id=user_in.outlet_id,
    )
    db.add(user)
    await db.flush()

    for role in assigned_roles:
        db.add(UserRole(user_id=user.id, role_id=role.id))

    await db.commit()

    # Reload user with associations
    reloaded_res = await db.execute(
        select(User)
        .where(User.id == user.id)
        .options(
            selectinload(User.roles).selectinload(Role.permissions),
            selectinload(User.outlet),
        )
    )
    reloaded = reloaded_res.scalar_one()
    resp = UserResponse.model_validate(reloaded)
    resp.permissions = list(reloaded.permissions_set)
    return resp


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_permission(Permissions.USER_READ)),
) -> UserResponse:
    """Get staff account details by ID."""
    res = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.roles).selectinload(Role.permissions),
            selectinload(User.outlet),
        )
    )
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    resp = UserResponse.model_validate(user)
    resp.permissions = list(user.permissions_set)
    return resp


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_in: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_permission(Permissions.USER_WRITE)),
) -> UserResponse:
    """Update staff details, status, outlet assignment, or roles."""
    res = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.roles).selectinload(Role.permissions),
            selectinload(User.outlet),
        )
    )
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    update_dict = user_in.model_dump(exclude_unset=True)

    if "role_names" in update_dict and update_dict["role_names"] is not None:
        new_roles_res = await db.execute(
            select(Role).where(Role.name.in_(update_dict["role_names"]))
        )
        new_roles = list(new_roles_res.scalars().all())
        # Delete old assignments
        await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
        for r in new_roles:
            db.add(UserRole(user_id=user.id, role_id=r.id))
        del update_dict["role_names"]

    for field, val in update_dict.items():
        setattr(user, field, val)

    await db.commit()

    # Reload
    reloaded_res = await db.execute(
        select(User)
        .where(User.id == user.id)
        .options(
            selectinload(User.roles).selectinload(Role.permissions),
            selectinload(User.outlet),
        )
    )
    reloaded = reloaded_res.scalar_one()
    resp = UserResponse.model_validate(reloaded)
    resp.permissions = list(reloaded.permissions_set)
    return resp


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.USER_DELETE)),
) -> None:
    """Deactivate a staff account."""
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own user account.",
        )

    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = False
    await db.commit()
