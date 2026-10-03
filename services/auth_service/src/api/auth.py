"""
Authentication endpoints: Login, Refresh, Me.
"""
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import jwt

from services.auth_service.src.api.deps import get_current_user
from services.auth_service.src.config import settings
from services.auth_service.src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from services.auth_service.src.db.session import get_db
from services.auth_service.src.models.role import Role
from services.auth_service.src.models.user import User
from services.auth_service.src.schemas.auth import LoginRequest, RefreshTokenRequest, TokenResponse
from services.auth_service.src.schemas.user import UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate user with email and password, issuing access & refresh tokens."""
    query = (
        select(User)
        .where(User.email == login_data.email)
        .options(
            selectinload(User.roles).selectinload(Role.permissions),
            selectinload(User.outlet),
        )
    )
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # Payload claims
    roles_list = [r.name for r in user.roles]
    perms_list = list(user.permissions_set)
    token_claims = {
        "sub": str(user.id),
        "email": user.email,
        "roles": roles_list,
        "permissions": perms_list,
        "outlet_id": str(user.outlet_id) if user.outlet_id else None,
        "is_superuser": user.is_superuser,
    }

    access_token = create_access_token(token_claims)
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


async def _execute_token_refresh(raw_refresh_token: str, db: AsyncSession) -> TokenResponse:
    """Internal helper to validate refresh token and mint a new token pair."""
    try:
        payload = decode_token(raw_refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type: refresh token expected",
            )
        user_id_str = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    from uuid import UUID
    user_res = await db.execute(
        select(User)
        .where(User.id == UUID(user_id_str))
        .options(
            selectinload(User.roles).selectinload(Role.permissions),
            selectinload(User.outlet),
        )
    )
    user = user_res.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    token_claims = {
        "sub": str(user.id),
        "email": user.email,
        "roles": [r.name for r in user.roles],
        "permissions": list(user.permissions_set),
        "outlet_id": str(user.outlet_id) if user.outlet_id else None,
        "is_superuser": user.is_superuser,
    }

    new_access_token = create_access_token(token_claims)
    new_refresh_token = create_refresh_token({"sub": str(user.id)})

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    refresh_data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange valid refresh token for a new access token via POST body."""
    return await _execute_token_refresh(refresh_data.refresh_token, db)


@router.get("/refresh", response_model=TokenResponse)
async def refresh_token_get(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_refresh_token: Optional[str] = Header(None, alias="X-Refresh-Token"),
    refresh_token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Exchange valid refresh token for a new access token via GET.
    Accepts token via Authorization Bearer header, X-Refresh-Token header, or ?refresh_token query parameter.
    """
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_refresh_token:
        token = x_refresh_token.strip()
    elif refresh_token:
        token = refresh_token.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required (via Bearer header, X-Refresh-Token header, or ?refresh_token query parameter).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await _execute_token_refresh(token, db)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Retrieve currently logged in user profile with assigned roles and permissions."""
    resp = UserResponse.model_validate(current_user)
    resp.permissions = list(current_user.permissions_set)
    return resp
