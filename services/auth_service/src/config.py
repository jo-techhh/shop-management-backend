"""
Auth Service configuration settings.
"""
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    PROJECT_NAME: str = "Auth & RBAC Service"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    PORT: int = 8001

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/auth_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security & JWT
    JWT_SECRET_KEY: str = "dev-insecure-secret-key-replace-in-production-abcdef1234567890"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Default Superadmin Seed
    FIRST_SUPERADMIN_EMAIL: str = "superadmin@shop.example.com"
    FIRST_SUPERADMIN_PASSWORD: str = "Admin@123456"
    FIRST_SUPERADMIN_NAME: str = "System Superadmin"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = AuthSettings()
