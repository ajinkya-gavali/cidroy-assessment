"""
app/core/secrets.py

Dual-mode secrets loader.

- APP_ENV=local: returns credentials from environment variables / config.
- APP_ENV=production: fetches from AWS Secrets Manager.

The application should always call get_api_keys() rather than reading
config.PRODUCT_API_KEY directly, so the same code path is exercised in
both modes.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiKeys:
    """Holds the API keys needed to authenticate with PIM and WMS."""
    product_api_key: str
    warehouse_api_key: str


@lru_cache(maxsize=1)
def get_api_keys() -> ApiKeys:
    """Return API keys, loading from Secrets Manager in production.

    In production mode, this function fetches secrets from AWS Secrets Manager.
    In local mode, it reads from environment variables.

    The result is cached after the first call to avoid repeated network requests.

    Returns:
        ApiKeys dataclass.

    Raises:
        RuntimeError: If required credentials are missing in production mode.
    """
    env = os.getenv("APP_ENV", "local").lower()

    if env == "production":
        return _load_from_secrets_manager()

    # Local mode: read from environment
    product_key = os.getenv("PRODUCT_API_KEY", "challenge-product-key")
    warehouse_key = os.getenv("WAREHOUSE_API_KEY", "challenge-warehouse-key")
    return ApiKeys(
        product_api_key=product_key,
        warehouse_api_key=warehouse_key,
    )


def _load_from_secrets_manager() -> ApiKeys:
    """Fetch API keys from AWS Secrets Manager."""
    try:
        import boto3  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("boto3 is required in production mode") from exc

    region = os.getenv("AWS_REGION", "ap-south-1")
    client = boto3.client("secretsmanager", region_name=region)

    product_secret_name = os.getenv(
        "SECRETS_PRODUCT_API_KEY_NAME", "catalogue/product_api_key"
    )
    warehouse_secret_name = os.getenv(
        "SECRETS_WAREHOUSE_API_KEY_NAME", "catalogue/warehouse_api_key"
    )

    product_key = _get_secret_value(client, product_secret_name)
    warehouse_key = _get_secret_value(client, warehouse_secret_name)

    if not product_key:
        raise RuntimeError(
            f"Missing secret '{product_secret_name}' in Secrets Manager"
        )
    if not warehouse_key:
        raise RuntimeError(
            f"Missing secret '{warehouse_secret_name}' in Secrets Manager"
        )

    return ApiKeys(
        product_api_key=product_key,
        warehouse_api_key=warehouse_key,
    )


def _get_secret_value(client: object, secret_name: str) -> str:
    """Retrieve a plaintext secret value from Secrets Manager."""
    resp = client.get_secret_value(SecretId=secret_name)  # type: ignore[attr-defined]
    secret = resp.get("SecretString", "")
    # Some secrets are stored as JSON objects: {"value": "..."}
    try:
        parsed = json.loads(secret)
        if isinstance(parsed, dict):
            return parsed.get("value", secret)
    except (json.JSONDecodeError, TypeError):
        pass
    return secret


def clear_cache() -> None:
    """Clear the cached API keys. Useful in tests."""
    get_api_keys.cache_clear()
