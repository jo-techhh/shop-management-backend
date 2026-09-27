"""
Cashier POS Shift schemas.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class ShiftOpenRequest(BaseModel):
    outlet_id: UUID
    opening_float: float = Field(ge=0.0, default=0.0)
    notes: Optional[str] = None


class ShiftCloseRequest(BaseModel):
    closing_cash: float = Field(ge=0.0)
    notes: Optional[str] = None


class PosShiftResponse(BaseModel):
    id: UUID
    outlet_id: UUID
    cashier_id: UUID
    opening_float: float
    cash_collected: float
    cash_drops: float
    expected_cash: float
    closing_cash: Optional[float] = None
    cash_variance: Optional[float] = None
    status: str
    opened_at: datetime
    closed_at: Optional[datetime] = None
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
