"""
Pydantic schemas for order and payment event payloads.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class OrderItemPayload(BaseModel):
    variant_id: str
    sku: str
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0.0)


class OrderCreatedPayload(BaseModel):
    order_id: str
    outlet_id: str
    cashier_id: str
    items: List[OrderItemPayload]
    total_amount: float = Field(ge=0.0)


class PaymentProcessedPayload(BaseModel):
    order_id: str
    payment_id: str
    outlet_id: str
    amount: float
    payment_mode: str  # CASH, CARD, UPI


class PaymentFailedPayload(BaseModel):
    order_id: str
    outlet_id: str
    items: List[OrderItemPayload]
    reason: str


class OrderCancelledPayload(BaseModel):
    order_id: str
    outlet_id: str
    items: List[OrderItemPayload]
    reason: str
