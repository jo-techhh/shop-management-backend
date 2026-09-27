"""
Payment request and response schemas.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class PaymentRequest(BaseModel):
    payment_mode: str = Field(description="CASH, CARD, or UPI")
    amount: float = Field(gt=0.0)
    transaction_ref: Optional[str] = None
    simulate_failure: bool = False  # Allows testing payment decline / compensation


class PaymentResponse(BaseModel):
    id: UUID
    order_id: UUID
    payment_mode: str
    amount: float
    status: str
    transaction_ref: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
