"""
Shared base events module defining standardized event envelopes and event types.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class EventType(str, Enum):
    # Order / Billing lifecycle events
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_PAID = "ORDER_PAID"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_COMPLETED = "ORDER_COMPLETED"

    # Inventory / Stock lifecycle events
    STOCK_RESERVED = "STOCK_RESERVED"
    STOCK_RESERVATION_FAILED = "STOCK_RESERVATION_FAILED"
    STOCK_RELEASED = "STOCK_RELEASED"


class EventEnvelope(BaseModel):
    """
    Standard envelope format for all domain events across the Redis Streams broker.
    Provides strict lineage tracing via correlation_id and causation_id.
    """
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    aggregate_type: str  # e.g., 'ORDER', 'INVENTORY'
    aggregate_id: str   # e.g., order_id, variant_id
    correlation_id: str
    causation_id: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    producer: str       # e.g., 'billing-service', 'inventory-service'
    version: str = "1.0"
    payload: Dict[str, Any]

    def to_stream_dict(self) -> Dict[str, str]:
        """Convert envelope to Redis Stream key-value string format."""
        import json
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id or "",
            "timestamp": self.timestamp,
            "producer": self.producer,
            "version": self.version,
            "payload": json.dumps(self.payload),
        }

    @classmethod
    def from_stream_dict(cls, data: Dict[str, str]) -> "EventEnvelope":
        """Reconstruct event envelope from Redis Stream message data."""
        import json
        return cls(
            event_id=data["event_id"],
            event_type=EventType(data["event_type"]),
            aggregate_type=data["aggregate_type"],
            aggregate_id=data["aggregate_id"],
            correlation_id=data["correlation_id"],
            causation_id=data.get("causation_id") or None,
            timestamp=data["timestamp"],
            producer=data["producer"],
            version=data.get("version", "1.0"),
            payload=json.loads(data["payload"]),
        )
