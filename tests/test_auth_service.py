"""
Unit tests for Auth & RBAC service security, schemas, and model permission calculations.
"""
from uuid import uuid4
import pytest
from services.auth_service.src.core.permissions import (
    ALL_PERMISSIONS,
    DEFAULT_ROLE_PERMISSIONS,
    Permissions,
)
from services.auth_service.src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from services.auth_service.src.models.outlet import Outlet
from services.auth_service.src.models.role import Permission, Role
from services.auth_service.src.models.user import User
from services.auth_service.src.schemas.auth import LoginRequest, TokenResponse
from services.auth_service.src.schemas.outlet import OutletCreate
from services.auth_service.src.schemas.role import RoleCreate
from services.auth_service.src.schemas.user import UserCreate


def test_password_hashing_and_verification():
    raw_password = "SecurePassword@123"
    hashed = hash_password(raw_password)

    assert hashed != raw_password
    assert verify_password(raw_password, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_jwt_token_creation_and_decoding():
    user_id = str(uuid4())
    claims = {
        "sub": user_id,
        "email": "test@shop.local",
        "roles": ["CASHIER"],
        "permissions": [Permissions.POS_CHECKOUT],
    }

    access_token = create_access_token(claims)
    decoded = decode_token(access_token)

    assert decoded["sub"] == user_id
    assert decoded["email"] == "test@shop.local"
    assert "CASHIER" in decoded["roles"]
    assert Permissions.POS_CHECKOUT in decoded["permissions"]
    assert decoded["type"] == "access"

    refresh_token = create_refresh_token({"sub": user_id})
    decoded_refresh = decode_token(refresh_token)
    assert decoded_refresh["sub"] == user_id
    assert decoded_refresh["type"] == "refresh"


def test_user_permissions_set_aggregation():
    perm1 = Permission(code="pos:checkout", description="Checkout")
    perm2 = Permission(code="catalog:read", description="Read catalog")
    perm3 = Permission(code="stock:adjust", description="Adjust stock")

    cashier_role = Role(name="CASHIER", description="Cashier")
    cashier_role.permissions = [perm1, perm2]

    manager_role = Role(name="MANAGER", description="Manager")
    manager_role.permissions = [perm2, perm3]

    user = User(
        email="cashier@shop.local",
        hashed_password="hash",
        full_name="Jane Doe",
    )
    user.roles = [cashier_role, manager_role]

    perms = user.permissions_set
    assert len(perms) == 3
    assert "pos:checkout" in perms
    assert "catalog:read" in perms
    assert "stock:adjust" in perms


def test_schema_validations():
    login = LoginRequest(email="admin@shop.example.com", password="SecretPassword")
    assert login.email == "admin@shop.example.com"

    outlet = OutletCreate(name="Downtown Branch", code="DT-01")
    assert outlet.code == "DT-01"

    role = RoleCreate(
        name="AUDITOR",
        description="Auditing only",
        permission_codes=[Permissions.REPORT_SALES_READ],
    )
    assert role.name == "AUDITOR"
    assert len(role.permission_codes) == 1

    user = UserCreate(
        email="cashier1@shop.example.com",
        password="CashierPassword1",
        full_name="Cashier One",
        role_names=["CASHIER"],
    )
    assert user.role_names == ["CASHIER"]
