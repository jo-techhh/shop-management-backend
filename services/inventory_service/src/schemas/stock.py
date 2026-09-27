"""
Stock and Inventory schemas.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from services.inventory_service.src.schemas.catalog import ProductVariantResponse


class StockAdjustRequest(BaseModel):
    outlet_id: UUID
    variant_id: UUID
    quantity_change: int  # can be positive (stock intake) or negative (breakage/write-off)
    notes: Optional[str] = None
    reference_id: Optional[str] = None


class OutletInventoryResponse(BaseModel):
    id: UUID
    outlet_id: UUID
    variant_id: UUID
    quantity_on_hand: int
    reserved_quantity: int
    available_quantity: int
    reorder_threshold: int
    updated_at: datetime
    variant: Optional[ProductVariantResponse] = None

    model_config = ConfigDict(from_attributes=True)


class StockAuditResponse(BaseModel):
    id: UUID
    outlet_id: UUID
    variant_id: UUID
    change_type: str
    quantity_change: int
    previous_on_hand: int
    new_on_hand: int
    previous_reserved: int
    new_reserved: int
    reference_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
