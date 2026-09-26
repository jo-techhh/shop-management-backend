"""
Role and Permission request and response schemas.
"""
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class PermissionResponse(BaseModel):
    id: UUID
    code: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    description: Optional[str] = None


class RoleCreate(RoleBase):
    permission_codes: List[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    description: Optional[str] = None
    permission_codes: Optional[List[str]] = None


class RoleResponse(RoleBase):
    id: UUID
    is_system: bool
    permissions: List[PermissionResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
