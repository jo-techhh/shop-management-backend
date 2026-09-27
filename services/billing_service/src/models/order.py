"""
Order and OrderItem models with explicit Saga lifecycle states.
"""
from datetime import datetime, timezone
import uuid
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from services.billing_service.src.db.base import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    outlet_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    cashier_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pos_shifts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    customer_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    subtotal: Mapped[float] = mapped_column(Float, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)

    # Saga States:
    # PENDING -> STOCK_RESERVED -> PAYMENT_PENDING -> PAID -> COMPLETED
    # Failure & compensation: STOCK_FAILED, PAYMENT_FAILED, COMPENSATING_STOCK, CANCELLED
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True, nullable=False)

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
    shift: Mapped["PosShift"] = relationship("PosShift", back_populates="orders", lazy="selectin")
    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[float] = mapped_column(Float, nullable=False)

    order: Mapped[Order] = relationship("Order", back_populates="items")
