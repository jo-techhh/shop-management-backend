"""
Authentication, RBAC and database session dependencies.
"""
from typing import Callable
from uuid import UUID
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import jwt

from services.auth_service.src.core.security import decode_token
from services.auth_service.src.db.session import get_db
from services.auth_service.src.models.outlet import Outlet
from services.auth_service.src.models.role import Role
from services.auth_service.src.models.user import User

security_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate Bearer JWT token and fetch active user with roles & outlet context."""
    token = credentials.credentials
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type: access token required",
            )
        user_id_str: str = payload.get("sub")
        if not user_id_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed token: missing subject",
            )
        user_id = UUID(user_id_str)
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch user with roles and outlet eager-loaded
    query = (
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.roles).selectinload(Role.permissions),
            selectinload(User.outlet),
        )
    )
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    return user


async def get_current_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """Ensure current user is a platform superadmin."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin privileges required",
        )
    return current_user


def require_permission(permission_code: str) -> Callable:
    """Dependency factory checking if current user possesses a specific permission code."""
    async def permission_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.is_superuser:
            return current_user

        user_perms = current_user.permissions_set
        if permission_code not in user_perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action forbidden: '{permission_code}' permission required",
            )
        return current_user

    return permission_checker


def require_role(role_name: str) -> Callable:
    """Dependency factory checking if current user belongs to a specific role."""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.is_superuser:
            return current_user

        user_roles = {r.name for r in current_user.roles}
        if role_name not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action forbidden: '{role_name}' role required",
            )
        return current_user

    return role_checker
