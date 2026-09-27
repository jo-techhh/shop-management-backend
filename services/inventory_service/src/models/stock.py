"""
Stock and Inventory models: OutletInventory and StockAuditLog.
"""
from datetime import datetime, timezone
import uuid
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from services.inventory_service.src.db.base import Base


class OutletInventory(Base):
    __tablename__ = "outlet_inventory"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reorder_threshold: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("outlet_id", "variant_id", name="uq_outlet_variant"),
    )

    variant: Mapped["ProductVariant"] = relationship("ProductVariant", back_populates="stock_records", lazy="selectin")

    @property
    def available_quantity(self) -> int:
        return max(0, self.quantity_on_hand - self.reserved_quantity)


class StockAuditLog(Base):
    __tablename__ = "stock_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    variant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # e.g., 'INITIAL', 'ADJUSTMENT', 'RESERVATION', 'DEDUCTION', 'RELEASE'

    quantity_change: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    new_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_reserved: Mapped[int] = mapped_column(Integer, nullable=False)
    new_reserved: Mapped[int] = mapped_column(Integer, nullable=False)

    reference_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
