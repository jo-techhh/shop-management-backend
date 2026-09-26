"""
API Gateway entry point.
Dispatches incoming REST calls to Auth, Inventory, and Billing microservices,
propagating X-Correlation-ID and security headers.
"""
from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
import httpx
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.api_gateway.src.config import settings
from shared.middleware.correlation import CorrelationIdMiddleware, get_correlation_id
from shared.schemas.common import HealthStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_gateway")

# Shared HTTP client for reverse proxying to downstream microservices
http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global http_client
    logger.info("Initializing API Gateway shared HTTP client pool...")
    http_client = httpx.AsyncClient(timeout=15.0)
    yield
    if http_client:
        logger.info("Closing API Gateway shared HTTP client pool...")
        await http_client.aclose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Correlation ID tracing middleware
app.add_middleware(CorrelationIdMiddleware)

# Cross-Origin Resource Sharing
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID"],
)


@app.get("/health", response_model=HealthStatus, tags=["System"])
async def gateway_health() -> HealthStatus:
    """Check Gateway and downstream microservice availability."""
    dependencies = {}

    # Probe Auth Service
    try:
        r = await http_client.get(f"{settings.AUTH_SERVICE_URL}/health", timeout=2.0)
        dependencies["auth_service"] = "healthy" if r.status_code == 200 else f"status_{r.status_code}"
    except Exception:
        dependencies["auth_service"] = "unreachable"

    # Probe Inventory Service
    try:
        r = await http_client.get(f"{settings.INVENTORY_SERVICE_URL}/health", timeout=2.0)
        dependencies["inventory_service"] = "healthy" if r.status_code == 200 else f"status_{r.status_code}"
    except Exception:
        dependencies["inventory_service"] = "unreachable"

    # Probe Billing Service
    try:
        r = await http_client.get(f"{settings.BILLING_SERVICE_URL}/health", timeout=2.0)
        dependencies["billing_service"] = "healthy" if r.status_code == 200 else f"status_{r.status_code}"
    except Exception:
        dependencies["billing_service"] = "unreachable"

    return HealthStatus(
        status="ok",
        service="api-gateway",
        version="1.0.0",
        dependencies=dependencies,
    )


async def proxy_request(request: Request, target_base_url: str, path: str) -> Response:
    """
    Forward HTTP request to downstream microservice, preserving method, headers,
    request body, query parameters, and injecting X-Correlation-ID.
    """
    assert http_client is not None, "HTTP Client is uninitialized"
    target_url = f"{target_base_url}{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    # Copy headers and ensure X-Correlation-ID is attached
    headers = dict(request.headers)
    headers["x-correlation-id"] = get_correlation_id()
    # Remove host header to avoid downstream conflicts
    headers.pop("host", None)

    body = await request.body()

    try:
        downstream_response = await http_client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
        )

        excluded_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
        response_headers = {
            k: v for k, v in downstream_response.headers.items()
            if k.lower() not in excluded_headers
        }
        response_headers["X-Correlation-ID"] = get_correlation_id()

        return Response(
            content=downstream_response.content,
            status_code=downstream_response.status_code,
            headers=response_headers,
            media_type=downstream_response.headers.get("content-type"),
        )
    except httpx.ConnectError:
        logger.error(f"Downstream connection error contacting {target_url}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False,
                "error": "Service Unavailable",
                "message": f"Target service for '{path}' is temporarily unreachable.",
                "correlation_id": get_correlation_id(),
            },
        )
    except httpx.TimeoutException:
        logger.error(f"Downstream timeout contacting {target_url}")
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={
                "success": False,
                "error": "Gateway Timeout",
                "message": f"Target service timed out processing '{path}'.",
                "correlation_id": get_correlation_id(),
            },
        )


# --- Route Dispatchers ---

# Auth & Outlets Microservice Routing
@app.api_route("/api/v1/auth/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def route_auth(request: Request, path: str) -> Response:
    return await proxy_request(request, settings.AUTH_SERVICE_URL, f"/auth/{path}")


@app.api_route("/api/v1/outlets/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/api/v1/outlets", methods=["GET", "POST"])
async def route_outlets(request: Request, path: str = "") -> Response:
    subpath = f"/{path}" if path else ""
    return await proxy_request(request, settings.AUTH_SERVICE_URL, f"/outlets{subpath}")


@app.api_route("/api/v1/roles/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/api/v1/roles", methods=["GET", "POST"])
async def route_roles(request: Request, path: str = "") -> Response:
    subpath = f"/{path}" if path else ""
    return await proxy_request(request, settings.AUTH_SERVICE_URL, f"/roles{subpath}")


# Catalog & Inventory Microservice Routing
@app.api_route("/api/v1/catalog/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/api/v1/catalog", methods=["GET", "POST"])
async def route_catalog(request: Request, path: str = "") -> Response:
    subpath = f"/{path}" if path else ""
    return await proxy_request(request, settings.INVENTORY_SERVICE_URL, f"/catalog{subpath}")


@app.api_route("/api/v1/inventory/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/api/v1/inventory", methods=["GET", "POST"])
async def route_inventory(request: Request, path: str = "") -> Response:
    subpath = f"/{path}" if path else ""
    return await proxy_request(request, settings.INVENTORY_SERVICE_URL, f"/inventory{subpath}")


# Billing & POS Microservice Routing
@app.api_route("/api/v1/pos/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/api/v1/pos", methods=["GET", "POST"])
async def route_pos(request: Request, path: str = "") -> Response:
    subpath = f"/{path}" if path else ""
    return await proxy_request(request, settings.BILLING_SERVICE_URL, f"/pos{subpath}")


@app.api_route("/api/v1/shifts/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/api/v1/shifts", methods=["GET", "POST"])
async def route_shifts(request: Request, path: str = "") -> Response:
    subpath = f"/{path}" if path else ""
    return await proxy_request(request, settings.BILLING_SERVICE_URL, f"/shifts{subpath}")
