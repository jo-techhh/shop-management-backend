"""
Catalog API endpoints: Categories, Products, and Variants (including fast Barcode lookup for POS).
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.inventory_service.src.db.session import get_db
from services.inventory_service.src.models.catalog import Category, Product, ProductVariant
from services.inventory_service.src.schemas.catalog import (
    CategoryCreate,
    CategoryResponse,
    ProductCreate,
    ProductResponse,
    ProductVariantCreate,
    ProductVariantResponse,
)
from shared.auth import CurrentUser, Permissions, require_permission

router = APIRouter(prefix="/catalog", tags=["Catalog"])


# --- Categories ---
@router.get("/categories", response_model=List[CategoryResponse])
async def list_categories(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(require_permission(Permissions.CATALOG_READ)),
) -> List[CategoryResponse]:
    """List all product categories."""
    stmt = select(Category)
    if active_only:
        stmt = stmt.where(Category.is_active == True)
    stmt = stmt.order_by(Category.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    cat_in: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(require_permission(Permissions.CATALOG_WRITE)),
) -> CategoryResponse:
    """Create a new product category."""
    existing = await db.execute(select(Category).where(Category.slug == cat_in.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category with slug '{cat_in.slug}' already exists.",
        )
    category = Category(**cat_in.model_dump())
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


# --- Products & Variants ---
@router.get("/products", response_model=List[ProductResponse])
async def list_products(
    category_id: Optional[UUID] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, le=100),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(require_permission(Permissions.CATALOG_READ)),
) -> List[ProductResponse]:
    """List products with their variants and category."""
    stmt = (
        select(Product)
        .options(
            selectinload(Product.category),
            selectinload(Product.variants),
        )
        .where(Product.is_active == True)
    )
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if search:
        stmt = stmt.where(Product.name.ilike(f"%{search}%"))

    stmt = stmt.order_by(Product.name).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    prod_in: ProductCreate,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(require_permission(Permissions.CATALOG_WRITE)),
) -> ProductResponse:
    """Create a base product with optional initial variants."""
    product = Product(
        name=prod_in.name,
        description=prod_in.description,
        brand=prod_in.brand,
        category_id=prod_in.category_id,
        is_active=prod_in.is_active,
    )
    db.add(product)
    await db.flush()

    for v_in in prod_in.variants:
        # Check SKU uniqueness
        sku_check = await db.execute(select(ProductVariant).where(ProductVariant.sku == v_in.sku))
        if sku_check.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"SKU '{v_in.sku}' already exists.")

        variant = ProductVariant(
            product_id=product.id,
            sku=v_in.sku,
            barcode=v_in.barcode,
            title=v_in.title,
            cost_price=v_in.cost_price,
            retail_price=v_in.retail_price,
            is_active=v_in.is_active,
        )
        db.add(variant)

    await db.commit()

    # Reload product with relations
    reloaded_res = await db.execute(
        select(Product)
        .where(Product.id == product.id)
        .options(selectinload(Product.category), selectinload(Product.variants))
    )
    return reloaded_res.scalar_one()


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(require_permission(Permissions.CATALOG_READ)),
) -> ProductResponse:
    """Get product details by UUID."""
    res = await db.execute(
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.category), selectinload(Product.variants))
    )
    prod = res.scalar_one_or_none()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    return prod


@router.post("/products/{product_id}/variants", response_model=ProductVariantResponse, status_code=status.HTTP_201_CREATED)
async def add_variant(
    product_id: UUID,
    variant_in: ProductVariantCreate,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(require_permission(Permissions.CATALOG_WRITE)),
) -> ProductVariantResponse:
    """Add a variant (SKU/Size/Color) to an existing product."""
    prod_check = await db.execute(select(Product).where(Product.id == product_id))
    if not prod_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")

    sku_check = await db.execute(select(ProductVariant).where(ProductVariant.sku == variant_in.sku))
    if sku_check.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"SKU '{variant_in.sku}' already exists.")

    variant = ProductVariant(
        product_id=product_id,
        sku=variant_in.sku,
        barcode=variant_in.barcode,
        title=variant_in.title,
        cost_price=variant_in.cost_price,
        retail_price=variant_in.retail_price,
        is_active=variant_in.is_active,
    )
    db.add(variant)
    await db.commit()
    await db.refresh(variant)
    return variant


# --- Fast Barcode & SKU Lookup (for POS) ---
@router.get("/variants/barcode/{barcode}", response_model=ProductVariantResponse)
async def get_variant_by_barcode(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(require_permission(Permissions.CATALOG_READ)),
) -> ProductVariantResponse:
    """Fast barcode scanner lookup for POS counter cashiers."""
    res = await db.execute(
        select(ProductVariant)
        .where(ProductVariant.barcode == barcode, ProductVariant.is_active == True)
    )
    variant = res.scalar_one_or_none()
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active product variant found with barcode '{barcode}'.",
        )
    return variant


@router.get("/variants/sku/{sku}", response_model=ProductVariantResponse)
async def get_variant_by_sku(
    sku: str,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(require_permission(Permissions.CATALOG_READ)),
) -> ProductVariantResponse:
    """Lookup product variant by SKU code."""
    res = await db.execute(
        select(ProductVariant)
        .where(ProductVariant.sku == sku, ProductVariant.is_active == True)
    )
    variant = res.scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail=f"Variant with SKU '{sku}' not found.")
    return variant
