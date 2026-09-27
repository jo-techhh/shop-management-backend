"""
Catalog & Inventory Service configuration settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class InventorySettings(BaseSettings):
    PROJECT_NAME: str = "Catalog & Inventory Microservice"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    PORT: int = 8002

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/inventory_db"

    # Redis Broker & Streams
    REDIS_URL: str = "redis://localhost:6379/0"
    ORDERS_STREAM: str = "stream:orders"
    INVENTORY_STREAM: str = "stream:inventory"
    DLQ_STREAM: str = "dlq:failed-events"
    INVENTORY_CONSUMER_GROUP: str = "inventory-group"
    CONSUMER_NAME: str = "inventory-worker-1"

    # Outbox polling interval (seconds)
    OUTBOX_POLL_INTERVAL: float = 0.5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = InventorySettings()
