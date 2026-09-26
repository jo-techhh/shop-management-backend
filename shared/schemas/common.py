"""
Standardized API request and response schemas shared across microservices.
"""
from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class ApiResponse(BaseModel, Generic[DataT]):
    success: bool = True
    message: Optional[str] = None
    data: Optional[DataT] = None
    correlation_id: Optional[str] = None


class ApiErrorDetail(BaseModel):
    code: str
    message: str
    field: Optional[str] = None


class ApiErrorResponse(BaseModel):
    success: bool = False
    error: str
    details: Optional[List[ApiErrorDetail]] = None
    correlation_id: Optional[str] = None


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseModel, Generic[DataT]):
    items: List[DataT]
    total_count: int
    page: int
    page_size: int
    total_pages: int


class HealthStatus(BaseModel):
    status: str = "ok"
    service: str
    version: str = "1.0.0"
    dependencies: Dict[str, str] = Field(default_factory=dict)
