"""
Correlation ID middleware and context management for distributed tracing across services.
"""
from contextvars import ContextVar
from typing import Optional
from uuid import uuid4
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-ID"

# ContextVar storing the current request correlation ID across async task boundaries
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id_ctx", default="")


def get_correlation_id() -> str:
    """Retrieve the current correlation ID, generating a new fallback if unset."""
    cid = correlation_id_ctx.get()
    if not cid:
        cid = f"gen_{uuid4().hex[:16]}"
        correlation_id_ctx.set(cid)
    return cid


def set_correlation_id(correlation_id: str) -> None:
    """Explicitly set the correlation ID in the context."""
    correlation_id_ctx.set(correlation_id)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures every incoming HTTP request has an X-Correlation-ID.
    Attaches the ID to the contextvar and propagates it in the response header.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cid = request.headers.get(CORRELATION_ID_HEADER)
        if not cid:
            cid = f"req_{uuid4().hex[:16]}"

        correlation_id_ctx.set(cid)
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = cid
        return response
