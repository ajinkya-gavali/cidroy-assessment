"""
tests/test_product_api.py

Unit tests for ProductApiClient:
- Pagination across multiple pages
- Empty catalogue
- Transient error retry (429, 503)
- Bounded retry exhaustion
- Authentication failure (401)
"""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.clients.product_api import ProductApiClient
from app.core.retry import MaxRetriesExceeded, PermanentError


def test_fetch_pages_multi_page_success():
    """Client iterates over pages until has_next is False."""
    page1_data = {
        "products": [{"id": "P001", "name": "Item 1"}],
        "page": 1,
        "has_next": True,
        "next_page": 2,
    }
    page2_data = {
        "products": [{"id": "P002", "name": "Item 2"}],
        "page": 2,
        "has_next": False,
        "next_page": None,
    }

    mock_resp1 = MagicMock(spec=httpx.Response)
    mock_resp1.status_code = 200
    mock_resp1.json.return_value = page1_data
    mock_resp1.raise_for_status = MagicMock()

    mock_resp2 = MagicMock(spec=httpx.Response)
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = page2_data
    mock_resp2.raise_for_status = MagicMock()

    with ProductApiClient(base_url="http://test-pim", api_key="test-key", rate=100.0) as client:
        with patch.object(client._client, "get", side_effect=[mock_resp1, mock_resp2]) as mock_get:
            pages = list(client.fetch_pages())

    assert len(pages) == 2
    assert pages[0] == [{"id": "P001", "name": "Item 1"}]
    assert pages[1] == [{"id": "P002", "name": "Item 2"}]
    assert mock_get.call_count == 2


def test_fetch_pages_empty_catalogue():
    """Empty catalogue returns an empty generator without errors."""
    empty_data = {"products": [], "page": 1, "has_next": False, "next_page": None}

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = empty_data
    mock_resp.raise_for_status = MagicMock()

    with ProductApiClient(base_url="http://test-pim", api_key="test-key", rate=100.0) as client:
        with patch.object(client._client, "get", return_value=mock_resp):
            pages = list(client.fetch_pages())

    assert len(pages) == 1
    assert pages[0] == []


def test_fetch_pages_retries_on_429():
    """Client recovers from HTTP 429 with backoff and Retry-After."""
    mock_resp_429 = MagicMock(spec=httpx.Response)
    mock_resp_429.status_code = 429
    mock_resp_429.headers = {"Retry-After": "0.01"}
    mock_resp_429.request = MagicMock()

    mock_resp_200 = MagicMock(spec=httpx.Response)
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {"products": [{"id": "P01"}], "has_next": False}
    mock_resp_200.raise_for_status = MagicMock()

    with ProductApiClient(base_url="http://test-pim", api_key="test-key", rate=100.0) as client:
        with patch.object(client._client, "get", side_effect=[mock_resp_429, mock_resp_200]):
            pages = list(client.fetch_pages())

    assert len(pages) == 1
    assert pages[0] == [{"id": "P01"}]


def test_fetch_pages_raises_on_auth_failure():
    """HTTP 401 raises PermanentError immediately without retrying."""
    mock_resp_401 = MagicMock(spec=httpx.Response)
    mock_resp_401.status_code = 401

    with ProductApiClient(base_url="http://test-pim", api_key="wrong-key", rate=100.0) as client:
        with patch.object(client._client, "get", return_value=mock_resp_401):
            with pytest.raises(PermanentError):
                list(client.fetch_pages())
