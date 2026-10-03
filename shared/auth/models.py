"""
Authentication domain models shared across microservices.
"""
from typing import List, Optional, Set
from uuid import UUID
from pydantic import BaseModel, Field


class CurrentUser(BaseModel):
    id: UUID
    email: str
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    outlet_id: Optional[UUID] = None
    is_superuser: bool = False

    @property
    def permissions_set(self) -> Set[str]:
        return set(self.permissions)

    def has_permission(self, permission: str) -> bool:
        if self.is_superuser:
            return True
        return permission in self.permissions_set

    def has_role(self, role: str) -> bool:
        if self.is_superuser:
            return True
        return role in self.roles
