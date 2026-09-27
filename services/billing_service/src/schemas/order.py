"""
Order and Checkout schemas.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class OrderItemRequest(BaseModel):
    variant_id: UUID
    sku: str
    title: str
    unit_price: float = Field(ge=0.0)
    quantity: int = Field(gt=0)


class CheckoutRequest(BaseModel):
    outlet_id: UUID
    cashier_id: UUID
    shift_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    items: List[OrderItemRequest] = Field(min_length=1)
    discount_amount: float = Field(default=0.0, ge=0.0)
    tax_amount: float = Field(default=0.0, ge=0.0)


class OrderItemResponse(BaseModel):
    id: UUID
    variant_id: UUID
    sku: str
    title: str
    unit_price: float
    quantity: int
    line_total: float

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    id: UUID
    invoice_number: str
    outlet_id: UUID
    cashier_id: UUID
    shift_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    subtotal: float
    discount_amount: float
    tax_amount: float
    total_amount: float
    status: str
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
