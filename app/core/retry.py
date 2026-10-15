"""
app/core/retry.py

Retry utilities implementing bounded exponential backoff with full jitter
and Retry-After header compliance.

Formula:
    sleep = max(retry_after_header, min(max_wait, uniform(0, base * 2^attempt)))

Transient status codes (safe to retry):
    429, 500, 502, 503, 504

Permanent status codes (do not retry):
    400, 401, 403, 404, 413
"""
import logging
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

logger = logging.getLogger(__name__)

TRETURN = TypeVar("TRETURN")

TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
PERMANENT_STATUS_CODES = frozenset({400, 401, 403, 404, 413})

DEFAULT_BASE_WAIT = 0.5      # seconds
DEFAULT_MAX_WAIT = 8.0       # seconds
DEFAULT_MAX_ATTEMPTS = 5


class PermanentError(Exception):
    """Raised when an HTTP error that should not be retried is received."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"Permanent HTTP error: {response.status_code}")


class MaxRetriesExceeded(Exception):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"Exhausted {attempts} attempts. Last error: {last_error}")


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Parse the Retry-After header from an HTTP response.

    Returns the value in seconds, or None if the header is absent or invalid.
    """
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        return None


def _jittered_backoff(attempt: int, base: float, max_wait: float) -> float:
    """Compute a full-jitter backoff delay.

    sleep = uniform(0, min(max_wait, base * 2^attempt))

    Args:
        attempt: Zero-indexed attempt number.
        base: Base wait time in seconds.
        max_wait: Maximum wait time cap in seconds.

    Returns:
        Sleep duration in seconds.
    """
    ceiling = min(max_wait, base * (2 ** attempt))
    return random.uniform(0, ceiling)


def with_retry(
    fn: Callable[[], TRETURN],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_wait: float = DEFAULT_BASE_WAIT,
    max_wait: float = DEFAULT_MAX_WAIT,
    context: str = "",
    retry_read_timeout: bool = True,
) -> TRETURN:
    """Execute `fn()` with bounded exponential backoff and full jitter.

    Retries on:
    - httpx.RequestError (connection failures, timeouts before response)
    - HTTP 429, 500, 502, 503, 504

    Raises immediately on:
    - httpx.ReadTimeout when retry_read_timeout is False
    - HTTP 400, 401, 403, 404, 413 (PermanentError)
    - Any other unhandled exception
    - MaxRetriesExceeded after all attempts exhausted

    Args:
        fn: Zero-argument callable to execute.
        max_attempts: Maximum number of total attempts.
        base_wait: Base wait time for exponential backoff.
        max_wait: Maximum wait time cap.
        context: Human-readable context for log messages.
        retry_read_timeout: If False, raises httpx.ReadTimeout without retry (for post-send ambiguous timeouts).

    Returns:
        The return value of fn() on success.

    Raises:
        PermanentError: On non-retryable HTTP errors.
        MaxRetriesExceeded: When retries are exhausted.
        httpx.ReadTimeout: When retry_read_timeout is False.
    """
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            response = fn()

            # Handle HTTP error status codes
            if hasattr(response, "status_code"):
                status = response.status_code
                if status in PERMANENT_STATUS_CODES:
                    raise PermanentError(response)
                if status in TRANSIENT_STATUS_CODES:
                    retry_after = _parse_retry_after(response)
                    backoff = _jittered_backoff(attempt, base_wait, max_wait)
                    sleep_time = max(retry_after or 0.0, backoff)
                    logger.warning(
                        "Transient HTTP %d on attempt %d/%d%s. Sleeping %.2fs.",
                        status,
                        attempt + 1,
                        max_attempts,
                        f" [{context}]" if context else "",
                        sleep_time,
                    )
                    last_error = httpx.HTTPStatusError(
                        f"HTTP {status}",
                        request=response.request,
                        response=response,
                    )
                    time.sleep(sleep_time)
                    continue

            return response  # type: ignore[return-value]

        except PermanentError:
            raise
        except httpx.ReadTimeout as exc:
            if not retry_read_timeout:
                raise
            backoff = _jittered_backoff(attempt, base_wait, max_wait)
            logger.warning(
                "Read timeout on attempt %d/%d%s: %s. Sleeping %.2fs.",
                attempt + 1,
                max_attempts,
                f" [{context}]" if context else "",
                exc,
                backoff,
            )
            last_error = exc
            time.sleep(backoff)
            continue
        except httpx.RequestError as exc:
            # Connection-level errors (before response received) — safe to retry
            backoff = _jittered_backoff(attempt, base_wait, max_wait)
            logger.warning(
                "Network error on attempt %d/%d%s: %s. Sleeping %.2fs.",
                attempt + 1,
                max_attempts,
                f" [{context}]" if context else "",
                exc,
                backoff,
            )
            last_error = exc
            time.sleep(backoff)
            continue

    raise MaxRetriesExceeded(max_attempts, last_error or RuntimeError("Unknown error"))
