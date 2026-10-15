"""
tests/test_api_clients.py

Tests for API client configurations, token bucket defaults, and headers.
Preserves existing tests.
"""
from app import config
from app.clients import product_api, warehouse_api


def test_page_size_is_configured():
    """Preserved original test: page size must be positive."""
    assert config.PAGE_SIZE > 0
    assert config.PAGE_SIZE <= 500


def test_batch_size_is_configured():
    """WMS batch size must not exceed the warehouse API limit of 100."""
    assert config.BATCH_SIZE > 0
    assert config.BATCH_SIZE <= 100


def test_rate_limits_within_bounds():
    """Rate limit configurations must stay strictly below upstream limits."""
    assert config.PIM_RATE_LIMIT <= 10.0
    assert config.WMS_RATE_LIMIT <= 20.0
    # Safety margins
    assert config.PIM_RATE_LIMIT < 10.0
    assert config.WMS_RATE_LIMIT < 20.0


def test_product_client_initialization():
    """ProductApiClient initializes with correct headers and limiters."""
    client = product_api.ProductApiClient(
        base_url="http://localhost:8001",
        api_key="test-key",
        page_size=200,
        rate=8.0,
    )
    assert client._headers == {"X-API-Key": "test-key"}
    assert client._page_size == 200
    assert client._limiter.rate == 8.0


def test_warehouse_client_initialization():
    """WarehouseApiClient initializes with correct headers and limiters."""
    client = warehouse_api.WarehouseApiClient(
        base_url="http://localhost:8002",
        api_key="test-warehouse-key",
        rate=15.0,
    )
    assert client._headers == {"X-API-Key": "test-warehouse-key"}
    assert client._limiter.rate == 15.0
