"""
tests/test_retry.py

Unit tests for retry utilities, exponential backoff, jitter,
and transient vs permanent error classification.
"""
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.retry import (
    MaxRetriesExceeded,
    PermanentError,
    _jittered_backoff,
    _parse_retry_after,
    with_retry,
)


def test_with_retry_succeeds_first_attempt():
    """Successful function call returns immediately on attempt 1."""
    fn = MagicMock(return_value="success")
    result = with_retry(fn, max_attempts=3)
    assert result == "success"
    assert fn.call_count == 1


def test_with_retry_retries_on_transient_status():
    """Retries on HTTP 429/503 and returns on subsequent success."""
    mock_resp_429 = MagicMock(spec=httpx.Response)
    mock_resp_429.status_code = 429
    mock_resp_429.headers = {"Retry-After": "0.01"}
    mock_resp_429.request = MagicMock()

    mock_resp_200 = MagicMock(spec=httpx.Response)
    mock_resp_200.status_code = 200

    fn = MagicMock(side_effect=[mock_resp_429, mock_resp_200])

    result = with_retry(fn, max_attempts=3, base_wait=0.01, max_wait=0.05)
    assert result == mock_resp_200
    assert fn.call_count == 2


def test_with_retry_raises_permanent_error_immediately():
    """HTTP 401 / 400 raises PermanentError immediately without retrying."""
    mock_resp_401 = MagicMock(spec=httpx.Response)
    mock_resp_401.status_code = 401

    fn = MagicMock(return_value=mock_resp_401)

    with pytest.raises(PermanentError):
        with_retry(fn, max_attempts=5)

    assert fn.call_count == 1  # No retries on 401


def test_with_retry_exhausted_raises_max_retries():
    """Repeated transient errors exhaust attempts and raise MaxRetriesExceeded."""
    mock_resp_503 = MagicMock(spec=httpx.Response)
    mock_resp_503.status_code = 503
    mock_resp_503.headers = {}
    mock_resp_503.request = MagicMock()

    fn = MagicMock(return_value=mock_resp_503)

    with pytest.raises(MaxRetriesExceeded) as exc_info:
        with_retry(fn, max_attempts=3, base_wait=0.001, max_wait=0.005)

    assert exc_info.value.attempts == 3
    assert fn.call_count == 3


def test_parse_retry_after_header():
    """Correctly parses valid and invalid Retry-After headers."""
    resp = MagicMock(spec=httpx.Response)

    resp.headers = {"Retry-After": "2"}
    assert _parse_retry_after(resp) == 2.0

    resp.headers = {"Retry-After": "0.5"}
    assert _parse_retry_after(resp) == 0.5

    resp.headers = {"Retry-After": "invalid"}
    assert _parse_retry_after(resp) is None

    resp.headers = {}
    assert _parse_retry_after(resp) is None


def test_jittered_backoff_bounds():
    """Jittered backoff always stays between 0 and the capped ceiling."""
    for attempt in range(5):
        delay = _jittered_backoff(attempt=attempt, base=0.5, max_wait=4.0)
        ceiling = min(4.0, 0.5 * (2 ** attempt))
        assert 0.0 <= delay <= ceiling
