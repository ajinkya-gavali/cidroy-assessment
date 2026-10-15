"""
app/config.py

Application configuration loaded from environment variables.

For local development, values can be set in a .env file or directly in the
shell environment. In production (APP_ENV=production), sensitive credentials
are fetched from AWS Secrets Manager via app.core.secrets.

All settings have sensible defaults for local development against the
provided Docker mock services.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Runtime environment
# ---------------------------------------------------------------------------
APP_ENV: str = os.getenv("APP_ENV", "local").lower()
IS_LOCAL: bool = APP_ENV != "production"

# ---------------------------------------------------------------------------
# External API endpoints
# ---------------------------------------------------------------------------
PRODUCT_API_URL: str = os.getenv("PRODUCT_API_URL", "http://localhost:8001")
WAREHOUSE_API_URL: str = os.getenv("WAREHOUSE_API_URL", "http://localhost:8002")

# ---------------------------------------------------------------------------
# API credentials (plain env fallback for local; Secrets Manager in prod)
# ---------------------------------------------------------------------------
PRODUCT_API_KEY: str = os.getenv("PRODUCT_API_KEY", "challenge-product-key" if IS_LOCAL else "")
WAREHOUSE_API_KEY: str = os.getenv("WAREHOUSE_API_KEY", "challenge-warehouse-key" if IS_LOCAL else "")

# ---------------------------------------------------------------------------
# Pagination and batching
# ---------------------------------------------------------------------------
PAGE_SIZE: int = int(os.getenv("PAGE_SIZE", "500"))
BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "100"))

# ---------------------------------------------------------------------------
# Rate limiting (requests per second, with safety margin below API limits)
# ---------------------------------------------------------------------------
PIM_RATE_LIMIT: float = float(os.getenv("PIM_RATE_LIMIT", "9.0"))    # limit: 10 req/s
WMS_RATE_LIMIT: float = float(os.getenv("WMS_RATE_LIMIT", "17.5"))   # limit: 20 req/s

# ---------------------------------------------------------------------------
# Retry settings
# ---------------------------------------------------------------------------
MAX_RETRY_ATTEMPTS: int = int(os.getenv("MAX_RETRY_ATTEMPTS", "5"))
RETRY_BASE_WAIT: float = float(os.getenv("RETRY_BASE_WAIT", "0.5"))  # seconds
RETRY_MAX_WAIT: float = float(os.getenv("RETRY_MAX_WAIT", "8.0"))    # seconds

# ---------------------------------------------------------------------------
# Worker concurrency
# ---------------------------------------------------------------------------
WMS_WORKER_COUNT: int = int(os.getenv("WMS_WORKER_COUNT", "6"))

# ---------------------------------------------------------------------------
# Storage paths (local mode)
# ---------------------------------------------------------------------------
LOCAL_STORAGE_ROOT: str = os.getenv("LOCAL_STORAGE_ROOT", "./runtime/s3")
EXPORT_DIR: str = os.getenv("EXPORT_DIR", "./runtime/exports")
STATE_DB_PATH: str = os.getenv("STATE_DB_PATH", "./runtime/state.db")
LOG_FILE_PATH: str = os.getenv("LOG_FILE_PATH", "./runtime/logs/sync.log")

# ---------------------------------------------------------------------------
# AWS settings (production mode)
# ---------------------------------------------------------------------------
AWS_REGION: str = os.getenv("AWS_REGION", "ap-south-1")
S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "catalogue-sync-exports")
DYNAMODB_RUNS_TABLE: str = os.getenv("DYNAMODB_RUNS_TABLE", "CatalogueSyncRuns")
DYNAMODB_BATCHES_TABLE: str = os.getenv("DYNAMODB_BATCHES_TABLE", "CatalogueSyncBatches")
DYNAMODB_DLQ_TABLE: str = os.getenv("DYNAMODB_DLQ_TABLE", "CatalogueSyncDLQ")

# ---------------------------------------------------------------------------
# Secrets Manager keys (production mode)
# ---------------------------------------------------------------------------
SECRETS_PRODUCT_API_KEY_NAME: str = os.getenv(
    "SECRETS_PRODUCT_API_KEY_NAME", "catalogue/product_api_key"
)
SECRETS_WAREHOUSE_API_KEY_NAME: str = os.getenv(
    "SECRETS_WAREHOUSE_API_KEY_NAME", "catalogue/warehouse_api_key"
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
