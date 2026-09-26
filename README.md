# 🛒 Shop & Multi-Outlet Management Platform (Backend)

A production-grade, event-driven microservices retail Point of Sale (POS) and inventory ERP built with **FastAPI**, **PostgreSQL**, **Redis Streams**, and **Docker Compose**.

---

## 🏛️ Architecture Overview

The system is decomposed into 4 decoupled microservices following a **database-per-service** model and an **event-driven Saga choreography**:

- **🚪 API Gateway (`:8000`)**: Reverse proxy entrypoint, CORS handling, client request routing, and `X-Correlation-ID` distributed tracing injection.
- **🔐 Auth & RBAC Service (`:8001`)**: Superadmin, Store Admin, Cashier roles, granular permissions, outlets configuration, and JWT authentication (`auth_db`).
- **📦 Catalog & Inventory Service (`:8002`)**: Base products, variants (SKU, barcode), multi-outlet stock ledger (`quantity_on_hand`, `reserved_quantity`), transactional outbox, and stock reservation/release sagas (`inventory_db`).
- **💳 Billing & POS Service (`:8003`)**: Cashier shifts/registers (opening float, cash count), checkout saga orchestrator, payments, thermal receipt formatting (`billing_db`).
- **⚡ Redis Infrastructure (`:6379`)**:
  - **Redis Streams**: Event broker (`stream:orders`, `stream:inventory`) with consumer groups (`XREADGROUP`, `XACK`).
  - **Dead Letter Queue (DLQ)**: `dlq:failed-events` for unprocessable poison pills and replay.
  - **Distributed Locks**: Redlock / `SET NX EX` for cash register drawer and concurrency safety.
  - **Cache**: Fast catalog SKU/barcode and RBAC permission lookups.

---

## 📂 Project Structure

```
backend/
├── docker-compose.yml              # All 4 services + 3 DBs + Redis
├── .env.example                    # Template environment variables
├── .env                            # Active environment configuration
├── shared/                         # Shared libraries (Used across all microservices)
│   ├── events/                     # Standard EventEnvelope, EventTypes, Payloads
│   ├── broker/                     # Redis Streams client, XADD, XREADGROUP, DLQ helpers
│   ├── middleware/                 # X-Correlation-ID context propagation
│   └── schemas/                    # Common ApiResponse, ErrorDetail, HealthStatus
├── infra/
│   └── postgres/
│       └── init-databases.sh       # Auto-creates auth_db, inventory_db, billing_db
├── services/
│   ├── api_gateway/                # Reverse proxy & routing
│   ├── auth_service/               # Auth, Outlets, RBAC
│   ├── inventory_service/          # Catalog & Multi-Outlet Stock
│   └── billing_service/            # Shifts, POS Checkout & Receipts
└── tests/                          # Automated unit and integration tests
```

---

## 🚀 Running the System

### Prerequisites
- Docker & Docker Compose (v2+)
- Python 3.11+ (for local development)

### Start with Docker Compose
```bash
docker compose up -d --build
```

### Healthcheck
Check the Gateway and service mesh status:
```bash
curl http://localhost:8000/health
```

### Run Tests
```bash
python -m pytest tests/
```
