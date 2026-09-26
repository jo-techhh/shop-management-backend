"""
System permission definitions and default role mappings.
"""
from typing import Dict, List


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


ALL_PERMISSIONS: List[Dict[str, str]] = [
    {"code": Permissions.OUTLET_READ, "description": "View outlet details and settings"},
    {"code": Permissions.OUTLET_WRITE, "description": "Create and update outlets"},
    {"code": Permissions.OUTLET_DELETE, "description": "Deactivate or delete outlets"},

    {"code": Permissions.USER_READ, "description": "View user profiles and staff lists"},
    {"code": Permissions.USER_WRITE, "description": "Create and modify staff accounts"},
    {"code": Permissions.USER_DELETE, "description": "Deactivate staff accounts"},

    {"code": Permissions.ROLE_MANAGE, "description": "Create and assign custom roles and permissions"},

    {"code": Permissions.CATALOG_READ, "description": "Browse catalog, products, and prices"},
    {"code": Permissions.CATALOG_WRITE, "description": "Create, edit, and categorize products"},

    {"code": Permissions.STOCK_READ, "description": "View stock levels and inventory alerts"},
    {"code": Permissions.STOCK_ADJUST, "description": "Manually adjust stock counts and write-offs"},
    {"code": Permissions.STOCK_TRANSFER, "description": "Initiate and approve inter-outlet transfers"},

    {"code": Permissions.POS_CHECKOUT, "description": "Process billing, barcode scans, and payments"},
    {"code": Permissions.POS_SHIFT_MANAGE, "description": "Open and close cashier register shifts"},
    {"code": Permissions.POS_DISCOUNT_APPLY, "description": "Apply custom discounts on items or carts"},
    {"code": Permissions.POS_ORDER_VOID, "description": "Void or cancel active/held POS orders"},

    {"code": Permissions.REPORT_SALES_READ, "description": "View daily sales and cashier performance reports"},
    {"code": Permissions.REPORT_FINANCIAL_READ, "description": "View consolidated financial and tax reports"},
]

DEFAULT_ROLE_PERMISSIONS = {
    "SUPERADMIN": [p["code"] for p in ALL_PERMISSIONS],
    "ADMIN": [
        Permissions.OUTLET_READ,
        Permissions.OUTLET_WRITE,
        Permissions.USER_READ,
        Permissions.USER_WRITE,
        Permissions.CATALOG_READ,
        Permissions.CATALOG_WRITE,
        Permissions.STOCK_READ,
        Permissions.STOCK_ADJUST,
        Permissions.STOCK_TRANSFER,
        Permissions.POS_CHECKOUT,
        Permissions.POS_SHIFT_MANAGE,
        Permissions.POS_DISCOUNT_APPLY,
        Permissions.POS_ORDER_VOID,
        Permissions.REPORT_SALES_READ,
    ],
    "CASHIER": [
        Permissions.CATALOG_READ,
        Permissions.STOCK_READ,
        Permissions.POS_CHECKOUT,
        Permissions.POS_SHIFT_MANAGE,
    ],
}
