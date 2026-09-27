"""
Cashier Register Shift / Session model.
Tracks opening cash float, cash sales, cash drops, and drawer reconciliation variances.
"""
from datetime import datetime, timezone
import uuid
from sqlalchemy import DateTime, Float, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from services.billing_service.src.db.base import Base


class PosShift(Base):
    __tablename__ = "pos_shifts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    cashier_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)

    opening_float: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cash_collected: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cash_drops: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    closing_cash: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash_variance: Mapped[float | None] = mapped_column(Float, nullable=True)  # closing_cash - expected_cash

    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True, nullable=False)
    # Statuses: 'OPEN', 'CLOSED'

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="shift")

    @property
    def expected_cash(self) -> float:
        """Expected cash in drawer = opening float + cash collected - cash drops."""
        return round(self.opening_float + self.cash_collected - self.cash_drops, 2)
