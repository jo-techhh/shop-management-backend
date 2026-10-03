"""
Shared Authentication and Authorization package for Shop Management Platform.
"""
from shared.auth.dependencies import (
    get_current_user,
    require_permission,
    require_role,
    require_superuser,
)
from shared.auth.models import CurrentUser
from shared.auth.permissions import Permissions
from shared.auth.security import create_access_token, decode_access_token

__all__ = [
    "CurrentUser",
    "Permissions",
    "get_current_user",
    "require_permission",
    "require_role",
    "require_superuser",
    "decode_access_token",
    "create_access_token",
]
