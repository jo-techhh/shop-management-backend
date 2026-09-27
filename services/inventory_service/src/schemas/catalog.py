"""
Catalog Pydantic schemas: Categories, Products, and Variants.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CategoryBase(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(min_length=2, max_length=100)
    description: Optional[str] = None
    is_active: bool = True


class CategoryCreate(CategoryBase):
    pass


class CategoryResponse(CategoryBase):
    id: UUID
    model_config = ConfigDict(from_attributes=True)


class ProductVariantBase(BaseModel):
    sku: str = Field(min_length=2, max_length=100)
    barcode: Optional[str] = Field(default=None, max_length=100)
    title: str = Field(min_length=1, max_length=150)
    cost_price: float = Field(ge=0.0, default=0.0)
    retail_price: float = Field(ge=0.0)
    is_active: bool = True


class ProductVariantCreate(ProductVariantBase):
    pass


class ProductVariantResponse(ProductVariantBase):
    id: UUID
    product_id: UUID
    model_config = ConfigDict(from_attributes=True)


class ProductBase(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: Optional[str] = None
    brand: Optional[str] = None
    category_id: Optional[UUID] = None
    is_active: bool = True


class ProductCreate(ProductBase):
    variants: List[ProductVariantCreate] = Field(default_factory=list)


class ProductResponse(ProductBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    category: Optional[CategoryResponse] = None
    variants: List[ProductVariantResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
