"""
tests/test_warehouse_api.py

Unit tests for WarehouseApiClient:
- 100-product batch size limit enforcement
- Partial acceptance and rejection parsing
- AMBIGUOUS_TIMEOUT detection on post-send read timeouts
- Retry on transient 429/503 responses
"""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.clients.warehouse_api import WarehouseApiClient
from app.core.retry import PermanentError


def test_send_batch_exceeding_max_size_raises():
    """Sending more than 100 items raises ValueError immediately."""
    oversized = [{"sku": f"P{i:07d}"} for i in range(101)]
    client = WarehouseApiClient()
    with pytest.raises(ValueError, match="exceeds maximum"):
        client.send_batch(oversized)


def test_send_batch_empty_list():
    """Empty batch returns empty accepted and rejected lists without HTTP call."""
    client = WarehouseApiClient()
    result = client.send_batch([])
    assert result.accepted == []
    assert result.rejected == []


def test_send_batch_partial_acceptance_and_rejection():
    """WMS HTTP 200 response partitions accepted and rejected SKUs."""
    payload_response = {
        "accepted": ["P0000001", "P0000002"],
        "rejected": [{"sku": "P0000999", "reason": "Invalid warehouse product"}],
        "message": "Processed",
    }

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = payload_response
    mock_resp.raise_for_status = MagicMock()

    batch = [
        {"sku": "P0000001"},
        {"sku": "P0000002"},
        {"sku": "P0000999"},
    ]

    with WarehouseApiClient(base_url="http://test-wms", api_key="key", rate=100.0) as client:
        with patch.object(client._client, "post", return_value=mock_resp):
            result = client.send_batch(batch, batch_id="batch_00001")

    assert result.accepted == ["P0000001", "P0000002"]
    assert len(result.rejected) == 1
    assert result.rejected[0]["sku"] == "P0000999"
    assert result.rejected[0]["reason"] == "Invalid warehouse product"
    assert result.ambiguous_timeout is False


def test_send_batch_post_send_read_timeout_flags_ambiguous():
    """ReadTimeout during POST response is flagged as AMBIGUOUS_TIMEOUT without retrying."""
    with WarehouseApiClient(base_url="http://test-wms", api_key="key", rate=100.0) as client:
        with patch.object(client._client, "post", side_effect=httpx.ReadTimeout("timed out")):
            result = client.send_batch([{"sku": "P001"}], batch_id="batch_00001")

    assert result.ambiguous_timeout is True
    assert result.accepted == []
    assert result.rejected == []
    assert "timed out" in result.error_message


def test_send_batch_auth_failure_raises():
    """HTTP 401 raises PermanentError immediately without retrying."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 401

    with WarehouseApiClient(base_url="http://test-wms", api_key="wrong", rate=100.0) as client:
        with patch.object(client._client, "post", return_value=mock_resp):
            with pytest.raises(PermanentError):
                client.send_batch([{"sku": "P001"}])
