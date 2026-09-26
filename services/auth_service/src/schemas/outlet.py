"""
Outlet request and response schemas.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class OutletBase(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    code: str = Field(min_length=2, max_length=20)
    address: Optional[str] = None
    phone: Optional[str] = None
    tax_number: Optional[str] = None
    receipt_footer: Optional[str] = None
    is_active: bool = True


class OutletCreate(OutletBase):
    pass


class OutletUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    tax_number: Optional[str] = None
    receipt_footer: Optional[str] = None
    is_active: Optional[bool] = None


class OutletResponse(OutletBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
