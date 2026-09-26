"""
User and Staff request and response schemas.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from services.auth_service.src.schemas.outlet import OutletResponse
from services.auth_service.src.schemas.role import RoleResponse


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=100)
    is_active: bool = True
    outlet_id: Optional[UUID] = None


class UserCreate(UserBase):
    password: str = Field(min_length=6)
    role_names: List[str] = Field(default_factory=lambda: ["CASHIER"])


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    outlet_id: Optional[UUID] = None
    is_active: Optional[bool] = None
    role_names: Optional[List[str]] = None


class UserResponse(UserBase):
    id: UUID
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    outlet: Optional[OutletResponse] = None
    roles: List[RoleResponse] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
