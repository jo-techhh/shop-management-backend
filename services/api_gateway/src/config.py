"""
Configuration settings for the API Gateway.
"""
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    PROJECT_NAME: str = "API Gateway - Shop Management Platform"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    PORT: int = 8000

    # Downstream Microservices URLs
    AUTH_SERVICE_URL: str = "http://auth_service:8001"
    INVENTORY_SERVICE_URL: str = "http://inventory_service:8002"
    BILLING_SERVICE_URL: str = "http://billing_service:8003"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = GatewaySettings()
