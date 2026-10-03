"""
End-to-End API Integration test for Auth & RBAC Microservice.
Tests:
1. Superadmin login
2. Reading /auth/me profile
3. Creating a new outlet
4. Creating a custom role with permissions
5. Creating a cashier staff account
6. Cashier login and permission isolation
7. RBAC enforcement (Cashier blocked with 403 from admin routes)
"""
from typing import AsyncGenerator
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from services.auth_service.src.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS, Permissions
from services.auth_service.src.core.security import hash_password
from services.auth_service.src.db.base import Base
from services.auth_service.src.db.session import get_db
from services.auth_service.src.main import app
from services.auth_service.src.models.outlet import Outlet
from services.auth_service.src.models.role import Permission, Role, RolePermission
from services.auth_service.src.models.user import User, UserRole

# In-memory async SQLite engine with static pool for isolated test lifecycle
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestAsyncSession = async_sessionmaker(bind=test_engine, expire_on_commit=False)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestAsyncSession() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    """Create tables and seed initial permissions, system roles, and superadmin."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestAsyncSession() as session:
        # Seed permissions
        perms_map = {}
        for p in ALL_PERMISSIONS:
            perm = Permission(code=p["code"], description=p["description"])
            session.add(perm)
            perms_map[p["code"]] = perm
        await session.flush()

        # Seed roles
        superadmin_role = Role(name="SUPERADMIN", description="Superadmin", is_system=True)
        session.add(superadmin_role)
        cashier_role = Role(name="CASHIER", description="Cashier", is_system=True)
        session.add(cashier_role)
        await session.flush()

        for code in DEFAULT_ROLE_PERMISSIONS["SUPERADMIN"]:
            session.add(RolePermission(role_id=superadmin_role.id, permission_id=perms_map[code].id))
        for code in DEFAULT_ROLE_PERMISSIONS["CASHIER"]:
            session.add(RolePermission(role_id=cashier_role.id, permission_id=perms_map[code].id))

        # Seed default outlet
        outlet = Outlet(name="Headquarters", code="HQ-01", is_active=True)
        session.add(outlet)
        await session.flush()

        # Seed superadmin user
        admin = User(
            email="admin@shop.example.com",
            hashed_password=hash_password("SuperSecret@123"),
            full_name="Platform Admin",
            is_active=True,
            is_superuser=True,
            outlet_id=outlet.id,
        )
        session.add(admin)
        await session.flush()
        session.add(UserRole(user_id=admin.id, role_id=superadmin_role.id))

        await session.commit()

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_full_auth_and_rbac_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login as Superadmin
        login_resp = await client.post(
            "/auth/login",
            json={"email": "admin@shop.example.com", "password": "SuperSecret@123"},
        )
        assert login_resp.status_code == 200
        tokens = login_resp.json()
        assert "access_token" in tokens
        admin_token = tokens["access_token"]
        auth_headers = {"Authorization": f"Bearer {admin_token}"}

        # 2. Check /auth/me
        me_resp = await client.get("/auth/me", headers=auth_headers)
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["email"] == "admin@shop.example.com"
        assert me_data["is_superuser"] is True
        assert Permissions.OUTLET_WRITE in me_data["permissions"]

        # 3. Create a secondary branch outlet as Admin
        outlet_resp = await client.post(
            "/outlets",
            json={"name": "Airport Kiosk", "code": "AIRPORT-01", "phone": "+1-555-8888"},
            headers=auth_headers,
        )
        assert outlet_resp.status_code == 201
        outlet_data = outlet_resp.json()
        airport_outlet_id = outlet_data["id"]
        assert outlet_data["code"] == "AIRPORT-01"

        # 4. Create custom role: SENIOR_CASHIER (with pos:checkout and pos:discount:apply)
        role_resp = await client.post(
            "/roles",
            json={
                "name": "SENIOR_CASHIER",
                "description": "Senior cashier with discount authority",
                "permission_codes": [Permissions.POS_CHECKOUT, Permissions.POS_DISCOUNT_APPLY],
            },
            headers=auth_headers,
        )
        assert role_resp.status_code == 201
        role_data = role_resp.json()
        assert role_data["name"] == "SENIOR_CASHIER"

        # 5. Create a Cashier User assigned to Airport Kiosk
        user_resp = await client.post(
            "/users",
            json={
                "email": "cashier_sam@shop.example.com",
                "password": "SamPassword@123",
                "full_name": "Sam Cashier",
                "outlet_id": airport_outlet_id,
                "role_names": ["SENIOR_CASHIER"],
            },
            headers=auth_headers,
        )
        assert user_resp.status_code == 201
        cashier_user_data = user_resp.json()
        assert cashier_user_data["email"] == "cashier_sam@shop.example.com"
        assert cashier_user_data["outlet"]["code"] == "AIRPORT-01"

        # 6. Login as Cashier Sam
        cashier_login = await client.post(
            "/auth/login",
            json={"email": "cashier_sam@shop.example.com", "password": "SamPassword@123"},
        )
        assert cashier_login.status_code == 200
        cashier_token = cashier_login.json()["access_token"]
        cashier_headers = {"Authorization": f"Bearer {cashier_token}"}

        # Verify Cashier Sam profile and isolated permissions
        cashier_me = await client.get("/auth/me", headers=cashier_headers)
        assert cashier_me.status_code == 200
        c_data = cashier_me.json()
        assert c_data["is_superuser"] is False
        assert Permissions.POS_CHECKOUT in c_data["permissions"]
        assert Permissions.POS_DISCOUNT_APPLY in c_data["permissions"]
        assert Permissions.OUTLET_WRITE not in c_data["permissions"]

        # 7. Verify RBAC enforcement: Cashier attempts admin-only operation (creating an outlet)
        forbidden_resp = await client.post(
            "/outlets",
            json={"name": "Hacked Store", "code": "HACK-01"},
            headers=cashier_headers,
        )
        assert forbidden_resp.status_code == 403
        assert "outlet:write" in forbidden_resp.json()["detail"]

        # 8. Test Refresh Token via POST
        admin_refresh_token = tokens["refresh_token"]
        post_refresh_resp = await client.post(
            "/auth/refresh",
            json={"refresh_token": admin_refresh_token},
        )
        assert post_refresh_resp.status_code == 200
        refreshed_tokens = post_refresh_resp.json()
        assert "access_token" in refreshed_tokens
        assert "refresh_token" in refreshed_tokens

        # 9. Test Refresh Token via GET (using Bearer header)
        get_refresh_resp = await client.get(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {admin_refresh_token}"},
        )
        assert get_refresh_resp.status_code == 200
        get_refreshed_tokens = get_refresh_resp.json()
        assert "access_token" in get_refreshed_tokens

        # 10. Test Refresh Token via GET (using query parameter)
        query_refresh_resp = await client.get(
            f"/auth/refresh?refresh_token={admin_refresh_token}",
        )
        assert query_refresh_resp.status_code == 200
        assert "access_token" in query_refresh_resp.json()
