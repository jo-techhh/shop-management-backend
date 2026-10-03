"""
JWT Security utilities for microservices.
"""
import os
from typing import Any, Dict, Optional
import jwt

DEFAULT_SECRET_KEY = "dev-insecure-secret-key-replace-in-production-abcdef1234567890"
DEFAULT_ALGORITHM = "HS256"


def get_jwt_secret_key() -> str:
    return os.environ.get("JWT_SECRET_KEY", DEFAULT_SECRET_KEY)


def get_jwt_algorithm() -> str:
    return os.environ.get("JWT_ALGORITHM", DEFAULT_ALGORITHM)


def decode_access_token(
    token: str,
    secret_key: Optional[str] = None,
    algorithm: Optional[str] = None,
) -> Dict[str, Any]:
    """Decode and validate a JWT access token."""
    key = secret_key or get_jwt_secret_key()
    algo = algorithm or get_jwt_algorithm()
    return jwt.decode(token, key, algorithms=[algo])


def create_access_token(
    data: Dict[str, Any],
    secret_key: Optional[str] = None,
    expires_delta: Optional[Any] = None,
) -> str:
    """Generate a JWT access token containing user claims."""
    from datetime import datetime, timedelta, timezone

    key = secret_key or get_jwt_secret_key()
    algo = get_jwt_algorithm()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=1))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, key, algorithm=algo)
