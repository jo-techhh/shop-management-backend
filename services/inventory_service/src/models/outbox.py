"""
Transactional Outbox model for Inventory Service.
Ensures zero dual-write inconsistencies between database mutations and Redis Streams event publishing.
"""
from datetime import datetime, timezone
import json
from typing import Any, Dict
import uuid
from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from services.inventory_service.src.db.base import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., 'INVENTORY'
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)    # e.g., order_id, variant_id
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True, nullable=False)
    # Statuses: 'PENDING', 'PUBLISHED', 'FAILED'

    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def payload(self) -> Dict[str, Any]:
        return json.loads(self.payload_json)

    @payload.setter
    def payload(self, val: Dict[str, Any]) -> None:
        self.payload_json = json.dumps(val)
