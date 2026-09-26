"""
Pydantic schemas for inventory stock event payloads.
"""
from typing import List, Optional
from pydantic import BaseModel
from shared.events.order_payloads import OrderItemPayload


class StockReservedPayload(BaseModel):
    order_id: str
    outlet_id: str
    items: List[OrderItemPayload]


class StockReservationFailedPayload(BaseModel):
    order_id: str
    outlet_id: str
    failed_variant_id: Optional[str] = None
    reason: str


class StockReleasedPayload(BaseModel):
    order_id: str
    outlet_id: str
    items: List[OrderItemPayload]
    reason: str
