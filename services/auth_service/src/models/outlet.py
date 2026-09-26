"""
Outlet entity model.
Represents a physical branch, store, kiosk, or warehouse.
"""
from datetime import datetime, timezone
import uuid
from sqlalchemy import Boolean, DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from services.auth_service.src.db.base import Base


class Outlet(Base):
    __tablename__ = "outlets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=True)
    phone: Mapped[str] = mapped_column(String(30), nullable=True)
    tax_number: Mapped[str] = mapped_column(String(50), nullable=True)  # GSTIN, VAT, etc.
    receipt_footer: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

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
    users: Mapped[list["User"]] = relationship("User", back_populates="outlet")
