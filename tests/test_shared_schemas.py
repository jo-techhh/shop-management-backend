"""
Unit tests for shared API response envelopes and schemas.
"""
from shared.schemas.common import (
    ApiResponse,
    ApiErrorResponse,
    ApiErrorDetail,
    PaginatedResponse,
    HealthStatus,
)


def test_api_response_envelope():
    res = ApiResponse(
        success=True,
        message="Created successfully",
        data={"id": "usr_101", "role": "ADMIN"},
        correlation_id="corr_test_01",
    )
    assert res.success is True
    assert res.data["role"] == "ADMIN"
    assert res.correlation_id == "corr_test_01"


def test_api_error_response():
    err = ApiErrorResponse(
        success=False,
        error="Validation failed",
        details=[ApiErrorDetail(code="INVALID_QUANTITY", message="Quantity must be > 0", field="quantity")],
        correlation_id="corr_test_02",
    )
    assert err.success is False
    assert len(err.details) == 1
    assert err.details[0].field == "quantity"


def test_paginated_response():
    paginated = PaginatedResponse(
        items=[{"name": "Item 1"}, {"name": "Item 2"}],
        total_count=10,
        page=1,
        page_size=2,
        total_pages=5,
    )
    assert len(paginated.items) == 2
    assert paginated.total_pages == 5


def test_health_status_schema():
    health = HealthStatus(
        status="ok",
        service="test-service",
        dependencies={"redis": "healthy", "database": "healthy"},
    )
    assert health.status == "ok"
    assert health.dependencies["redis"] == "healthy"
