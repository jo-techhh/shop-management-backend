"""
Database initialization and default seeding (Permissions, System Roles, Superadmin, Main Outlet).
"""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.auth_service.src.config import settings
from services.auth_service.src.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS
from services.auth_service.src.core.security import hash_password
from services.auth_service.src.db.base import Base
from services.auth_service.src.db.session import AsyncSessionLocal, engine
from services.auth_service.src.models.outlet import Outlet
from services.auth_service.src.models.role import Permission, Role, RolePermission
from services.auth_service.src.models.user import User, UserRole

logger = logging.getLogger("auth_init_db")


async def init_db() -> None:
    """Create all tables and seed default permissions, roles, and initial superadmin."""
    async with engine.begin() as conn:
        logger.info("Ensuring database tables exist...")
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        try:
            # 1. Seed Permissions
            logger.info("Checking and seeding permissions...")
            existing_perms_res = await session.execute(select(Permission))
            existing_perms = {p.code: p for p in existing_perms_res.scalars().all()}

            for perm_data in ALL_PERMISSIONS:
                if perm_data["code"] not in existing_perms:
                    new_perm = Permission(code=perm_data["code"], description=perm_data["description"])
                    session.add(new_perm)
                    existing_perms[perm_data["code"]] = new_perm
            await session.commit()

            # Refresh permissions dictionary
            perms_res = await session.execute(select(Permission))
            all_perms_map = {p.code: p for p in perms_res.scalars().all()}

            # 2. Seed Default Roles
            logger.info("Checking and seeding system roles...")
            for role_name, perm_codes in DEFAULT_ROLE_PERMISSIONS.items():
                role_res = await session.execute(select(Role).where(Role.name == role_name))
                role = role_res.scalar_one_or_none()
                if not role:
                    role = Role(
                        name=role_name,
                        description=f"System default role for {role_name}",
                        is_system=True,
                    )
                    session.add(role)
                    await session.flush()

                    # Assign permissions
                    for code in perm_codes:
                        if code in all_perms_map:
                            rp = RolePermission(role_id=role.id, permission_id=all_perms_map[code].id)
                            session.add(rp)
            await session.commit()

            # 3. Seed Default Main Outlet
            logger.info("Checking and seeding default main outlet...")
            outlet_res = await session.execute(select(Outlet).where(Outlet.code == "MAIN-01"))
            main_outlet = outlet_res.scalar_one_or_none()
            if not main_outlet:
                main_outlet = Outlet(
                    name="Main Store & Headquarters",
                    code="MAIN-01",
                    address="123 Retail Boulevard, Downtown",
                    phone="+1-555-0100",
                    tax_number="TAX-MAIN-001",
                    receipt_footer="Thank you for shopping at our Main Branch!",
                    is_active=True,
                )
                session.add(main_outlet)
                await session.flush()
            main_outlet_id = main_outlet.id
            await session.commit()

            # 4. Seed First Superadmin User
            logger.info("Checking and seeding first superadmin user...")
            user_res = await session.execute(
                select(User).where(User.email == settings.FIRST_SUPERADMIN_EMAIL)
            )
            admin_user = user_res.scalar_one_or_none()
            if not admin_user:
                superadmin_role_res = await session.execute(
                    select(Role).where(Role.name == "SUPERADMIN")
                )
                superadmin_role = superadmin_role_res.scalar_one()

                admin_user = User(
                    email=settings.FIRST_SUPERADMIN_EMAIL,
                    hashed_password=hash_password(settings.FIRST_SUPERADMIN_PASSWORD),
                    full_name=settings.FIRST_SUPERADMIN_NAME,
                    is_active=True,
                    is_superuser=True,
                    outlet_id=main_outlet_id,
                )
                session.add(admin_user)
                await session.flush()

                ur = UserRole(user_id=admin_user.id, role_id=superadmin_role.id)
                session.add(ur)
                await session.commit()
                logger.info(f"Created default Superadmin: {settings.FIRST_SUPERADMIN_EMAIL}")

        except Exception as e:
            await session.rollback()
            logger.error(f"Error during database initialization: {e}")
            raise
