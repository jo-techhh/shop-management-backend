"""
Receipt and thermal printer format schemas.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from services.billing_service.src.schemas.order import OrderItemResponse
from services.billing_service.src.schemas.payment import PaymentResponse


class ReceiptResponse(BaseModel):
    invoice_number: str
    outlet_id: UUID
    cashier_id: UUID
    order_id: UUID
    date: datetime
    customer_name: Optional[str] = None
    items: List[OrderItemResponse]
    subtotal: float
    discount_amount: float
    tax_amount: float
    total_amount: float
    status: str
    payments: List[PaymentResponse]
    escpos_thermal_text: str  # Formatted 80mm ESC/POS representation for counter receipt printers
