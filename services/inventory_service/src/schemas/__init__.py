from services.inventory_service.src.schemas.catalog import (
    CategoryCreate,
    CategoryResponse,
    ProductVariantCreate,
    ProductVariantResponse,
    ProductCreate,
    ProductResponse,
)
from services.inventory_service.src.schemas.stock import (
    StockAdjustRequest,
    OutletInventoryResponse,
    StockAuditResponse,
)

__all__ = [
    "CategoryCreate",
    "CategoryResponse",
    "ProductVariantCreate",
    "ProductVariantResponse",
    "ProductCreate",
    "ProductResponse",
    "StockAdjustRequest",
    "OutletInventoryResponse",
    "StockAuditResponse",
]
