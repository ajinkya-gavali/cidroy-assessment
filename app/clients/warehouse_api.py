"""
app/clients/warehouse_api.py

Resilient WMS API client with:
- Token Bucket rate limiting (default: 17.5 req/s, below the 20 req/s API limit)
- Bounded exponential backoff with full jitter and Retry-After compliance
- Explicit handling of partial WMS acceptance / rejection (HTTP 200)
- AMBIGUOUS_TIMEOUT detection: post-send read timeouts are NOT blindly retried
- Persistent HTTP session with connection pooling and keep-alive
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.http_client import build_client
from app.core.rate_limiter import TokenBucket
from app.core.retry import MaxRetriesExceeded, PermanentError, with_retry

from app import config

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Structured result from a WMS batch submission."""
    accepted: list[str]               # List of accepted SKUs
    rejected: list[dict[str, Any]]    # List of {sku, reason} dicts
    ambiguous_timeout: bool = False    # True if the outcome is uncertain
    error_message: str = ""


class WarehouseApiClient:
    """Resilient, rate-limited WMS API client.

    Args:
        base_url: WMS API base URL.
        api_key: API key for authentication.
        rate: Token bucket rate in requests/second.
        max_retries: Maximum retry attempts per request.
    """

    def __init__(
        self,
        base_url: str = config.WAREHOUSE_API_URL,
        api_key: str = "",
        rate: float = config.WMS_RATE_LIMIT,
        max_retries: int = config.MAX_RETRY_ATTEMPTS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._limiter = TokenBucket(rate=rate, capacity=rate)
        self._max_retries = max_retries
        self._client: httpx.Client | None = None

    def __enter__(self) -> WarehouseApiClient:
        self._client = build_client()
        return self

    def __exit__(self, *args: object) -> None:
        if self._client:
            self._client.close()
            self._client = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key}

    def send_batch(self, products: list[dict[str, Any]], batch_id: str = "") -> BatchResult:
        """Send a single batch of products to the WMS.

        Enforces the 100-product batch size limit, acquires a rate-limit token,
        retries on transient errors, and classifies post-send timeouts as
        AMBIGUOUS_TIMEOUT rather than retrying blindly.

        Args:
            products: List of WMS-formatted product dicts (max 100).
            batch_id: Human-readable batch identifier for logging.

        Returns:
            BatchResult with accepted SKUs, rejected items, and ambiguity flag.

        Raises:
            ValueError: If products list exceeds MAX_BATCH_SIZE (100).
            PermanentError: On non-retryable HTTP errors (e.g. 401, 413).
            MaxRetriesExceeded: When retries are exhausted for transient errors.
        """
        if len(products) > config.BATCH_SIZE:
            raise ValueError(
                f"Batch size {len(products)} exceeds maximum of {config.BATCH_SIZE}"
            )
        if not products:
            return BatchResult(accepted=[], rejected=[])

        if self._client is None:
            raise RuntimeError("WarehouseApiClient must be used as a context manager")

        client = self._client
        url = f"{self._base_url}/products/batch"
        headers = self._headers
        payload = {"products": products}
        context = f"WMS batch {batch_id}" if batch_id else "WMS batch"

        # Acquire rate-limit token BEFORE the network call
        self._limiter.acquire()

        # Detect post-send ambiguous timeouts separately from pre-send failures.
        # httpx.ReadTimeout means the request body was sent, but the response
        # never arrived — we cannot know if the WMS processed it.
        try:
            def _do_request() -> httpx.Response:
                return client.post(url, json=payload, headers=headers)

            response = with_retry(
                _do_request,
                max_attempts=self._max_retries,
                context=context,
                retry_read_timeout=False,
            )
        except (httpx.ReadTimeout, MaxRetriesExceeded) as exc:
            # If it's a MaxRetriesExceeded wrapping ReadTimeout or a direct ReadTimeout
            if isinstance(exc, MaxRetriesExceeded) and not isinstance(exc.last_error, httpx.ReadTimeout):
                raise
            err_msg = str(exc.last_error) if isinstance(exc, MaxRetriesExceeded) else str(exc)
            logger.error(
                "AMBIGUOUS_TIMEOUT: post-send read timeout for %s. "
                "WMS may or may not have processed the batch.",
                context,
            )
            return BatchResult(
                accepted=[],
                rejected=[],
                ambiguous_timeout=True,
                error_message=err_msg,
            )

        response.raise_for_status()
        return self._parse_response(response.json())

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> BatchResult:
        """Parse the WMS batch response into a structured BatchResult.

        The WMS returns HTTP 200 with both 'accepted' and 'rejected' arrays.
        We treat every item in 'rejected' as a dead-letter candidate.

        Args:
            data: Parsed JSON response from the WMS.

        Returns:
            BatchResult with populated accepted and rejected lists.
        """
        accepted = data.get("accepted", []) or []
        rejected = data.get("rejected", []) or []

        # Normalise to list[str] for accepted
        accepted_skus: list[str] = [str(s) for s in accepted if s is not None]

        # Normalise rejected to list[{sku, reason}]
        rejected_items: list[dict[str, Any]] = []
        for item in rejected:
            if isinstance(item, dict):
                rejected_items.append({
                    "sku": item.get("sku"),
                    "reason": item.get("reason", "Unknown reason"),
                })

        return BatchResult(accepted=accepted_skus, rejected=rejected_items)
