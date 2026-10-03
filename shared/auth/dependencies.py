"""
Reusable FastAPI authentication & RBAC dependencies for microservices.
"""
from typing import Callable, Optional
from uuid import UUID
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from shared.auth.models import CurrentUser
from shared.auth.security import decode_access_token

security_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
) -> CurrentUser:
    """Validate Bearer JWT token and return authenticated CurrentUser."""
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type: access token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id_str: Optional[str] = payload.get("sub")
        if not user_id_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed token: missing subject",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id = UUID(user_id_str)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_outlet = payload.get("outlet_id")
    outlet_id = UUID(raw_outlet) if raw_outlet else None

    return CurrentUser(
        id=user_id,
        email=payload.get("email", ""),
        roles=payload.get("roles", []),
        permissions=payload.get("permissions", []),
        outlet_id=outlet_id,
        is_superuser=payload.get("is_superuser", False),
    )


def require_permission(permission_code: str) -> Callable:
    """Dependency factory verifying that the authenticated user possesses a specific permission."""
    async def permission_checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.is_superuser:
            return current_user

        if permission_code not in current_user.permissions_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action forbidden: '{permission_code}' permission required",
            )
        return current_user

    return permission_checker


def require_role(role_name: str) -> Callable:
    """Dependency factory verifying that the authenticated user has a specific role."""
    async def role_checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.is_superuser:
            return current_user

        if role_name not in current_user.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action forbidden: '{role_name}' role required",
            )
        return current_user

    return role_checker


async def require_superuser(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency verifying that the user is a platform superadmin."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin privileges required",
        )
    return current_user
