"""
Central system permissions definitions shared across microservices.
"""


class Permissions:
    # Outlets
    OUTLET_READ = "outlet:read"
    OUTLET_WRITE = "outlet:write"
    OUTLET_DELETE = "outlet:delete"

    # User & Staff Management
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_DELETE = "user:delete"

    # Role & Permissions
    ROLE_MANAGE = "role:manage"

    # Catalog & Products
    CATALOG_READ = "catalog:read"
    CATALOG_WRITE = "catalog:write"

    # Inventory & Stock
    STOCK_READ = "stock:read"
    STOCK_ADJUST = "stock:adjust"
    STOCK_TRANSFER = "stock:transfer"

    # POS & Billing
    POS_CHECKOUT = "pos:checkout"
    POS_SHIFT_MANAGE = "pos:shift:manage"
    POS_DISCOUNT_APPLY = "pos:discount:apply"
    POS_ORDER_VOID = "pos:order:void"

    # Reports & Analytics
    REPORT_SALES_READ = "report:sales:read"
    REPORT_FINANCIAL_READ = "report:financial:read"
