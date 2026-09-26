"""
Unit tests for correlation ID tracing middleware and context propagation.
"""
from starlette.requests import Request
from starlette.responses import Response
import pytest
from shared.middleware.correlation import (
    CorrelationIdMiddleware,
    CORRELATION_ID_HEADER,
    get_correlation_id,
    set_correlation_id,
)


@pytest.mark.asyncio
async def test_correlation_id_generated_when_missing():
    middleware = CorrelationIdMiddleware(app=None)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": [],
    }
    request = Request(scope)

    async def call_next(req: Request) -> Response:
        cid = get_correlation_id()
        assert cid.startswith("req_")
        return Response(content="ok")

    response = await middleware.dispatch(request, call_next)
    assert CORRELATION_ID_HEADER in response.headers
    assert response.headers[CORRELATION_ID_HEADER].startswith("req_")


@pytest.mark.asyncio
async def test_correlation_id_propagated_when_provided():
    middleware = CorrelationIdMiddleware(app=None)

    custom_cid = "custom-trace-uuid-12345"
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": [(CORRELATION_ID_HEADER.lower().encode(), custom_cid.encode())],
    }
    request = Request(scope)

    async def call_next(req: Request) -> Response:
        cid = get_correlation_id()
        assert cid == custom_cid
        return Response(content="ok")

    response = await middleware.dispatch(request, call_next)
    assert response.headers[CORRELATION_ID_HEADER] == custom_cid
