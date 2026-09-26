"""
User and UserRole models.
"""
from datetime import datetime, timezone
import uuid
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from services.auth_service.src.db.base import Base
from services.auth_service.src.models.outlet import Outlet
from services.auth_service.src.models.role import Role


class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    outlet_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("outlets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    outlet: Mapped[Outlet | None] = relationship("Outlet", back_populates="users", lazy="selectin")
    roles: Mapped[list[Role]] = relationship(
        "Role",
        secondary="user_roles",
        back_populates="users",
        lazy="selectin",
    )

    @property
    def permissions_set(self) -> set[str]:
        """Aggregate all permission codes from user's assigned roles."""
        perms = set()
        for role in self.roles:
            for perm in role.permissions:
                perms.add(perm.code)
        return perms
