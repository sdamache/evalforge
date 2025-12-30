"""API key authentication middleware for approval workflow.

Implements API key validation using X-API-Key header with
constant-time comparison to prevent timing attacks.

Usage:
    from src.api.auth import verify_api_key

    @app.post("/suggestions/{id}/approve")
    async def approve(id: str, api_key: str = Depends(verify_api_key)):
        ...
"""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from src.common.config import load_approval_config
from src.common.logging import get_logger

logger = get_logger(__name__)

# API key header configuration
# auto_error=False so we can return 401 (not 403) for missing header
api_key_header = APIKeyHeader(
    name="X-API-Key",
    description="API key for authentication",
    auto_error=False,
)


def verify_api_key(
    api_key: Optional[str] = Depends(api_key_header),
) -> str:
    """Validate API key with constant-time comparison.

    Args:
        api_key: The API key from the X-API-Key header.

    Returns:
        The validated API key (for logging/audit purposes).

    Raises:
        HTTPException: 401 Unauthorized if API key is invalid or missing.
    """
    # Handle missing header (auto_error=False means api_key can be None)
    if api_key is None:
        logger.warning("Missing X-API-Key header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "APIKey"},
        )

    config = load_approval_config()
    expected_key = config.api_key

    # If no API key is configured, reject all requests
    if not expected_key:
        logger.warning("APPROVAL_API_KEY not configured - rejecting request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key not configured on server",
            headers={"WWW-Authenticate": "APIKey"},
        )

    # Use constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, expected_key):
        logger.warning("Invalid API key provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "APIKey"},
        )

    return api_key


def get_optional_api_key(
    api_key: Optional[str] = Depends(
        APIKeyHeader(name="X-API-Key", auto_error=False)
    )
) -> Optional[str]:
    """Get API key if provided, without requiring it.

    Useful for endpoints that work with or without authentication
    (e.g., health checks that show more info when authenticated).

    Args:
        api_key: The API key from the X-API-Key header, or None.

    Returns:
        The API key if provided and valid, None otherwise.
    """
    if api_key is None:
        return None

    config = load_approval_config()
    expected_key = config.api_key

    if not expected_key:
        return None

    if secrets.compare_digest(api_key, expected_key):
        return api_key

    return None
