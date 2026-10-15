"""
app/clients/product_api.py

Resilient PIM API client with:
- Token Bucket rate limiting (default: 9 req/s, below the 10 req/s API limit)
- Bounded exponential backoff with full jitter and Retry-After compliance
- Streaming generator that yields page data without accumulating in memory
- Persistent HTTP session with connection pooling and keep-alive
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx

from app.core.http_client import build_client
from app.core.rate_limiter import TokenBucket
from app.core.retry import MaxRetriesExceeded, PermanentError, with_retry

from app import config

logger = logging.getLogger(__name__)


class ProductApiClient:
    """Resilient, rate-limited PIM API client.

    Args:
        base_url: PIM API base URL.
        api_key: API key for authentication.
        page_size: Records to request per page (max 500).
        rate: Token bucket rate in requests/second.
        max_retries: Maximum retry attempts per request.
    """

    def __init__(
        self,
        base_url: str = config.PRODUCT_API_URL,
        api_key: str = "",
        page_size: int = config.PAGE_SIZE,
        rate: float = config.PIM_RATE_LIMIT,
        max_retries: int = config.MAX_RETRY_ATTEMPTS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._page_size = min(page_size, 500)  # Enforce API max
        self._limiter = TokenBucket(rate=rate, capacity=rate)
        self._max_retries = max_retries
        self._client: httpx.Client | None = None

    def __enter__(self) -> ProductApiClient:
        self._client = build_client()
        return self

    def __exit__(self, *args: object) -> None:
        if self._client:
            self._client.close()
            self._client = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key}

    def _fetch_page(self, page: int) -> dict[str, Any]:
        """Fetch a single page from the PIM API with rate limiting and retry.

        Args:
            page: Page number (1-indexed).

        Returns:
            Parsed JSON response dictionary.

        Raises:
            PermanentError: On non-retryable HTTP errors.
            MaxRetriesExceeded: When retries are exhausted.
        """
        if self._client is None:
            raise RuntimeError(
                "ProductApiClient must be used as a context manager")

        client = self._client
        params = {"page": page, "page_size": self._page_size}
        headers = self._headers
        url = f"{self._base_url}/products"

        # Acquire rate-limit token BEFORE the network call
        self._limiter.acquire()

        def _do_request() -> httpx.Response:
            return client.get(url, params=params, headers=headers)

        response = with_retry(
            _do_request,
            max_attempts=self._max_retries,
            context=f"PIM page {page}",
        )
        response.raise_for_status()
        return response.json()

    def fetch_pages(self) -> Iterator[list[dict[str, Any]]]:
        """Stream all product pages from the PIM API as a generator.

        Each iteration yields a list of product dicts for a single page.
        No more than one page's worth of data is held in memory at a time.

        Yields:
            List of product dictionaries for each page.

        Raises:
            PermanentError: On authentication or validation failures.
            MaxRetriesExceeded: When a page cannot be fetched after all retries.
        """
        page = 1
        total_fetched = 0

        while True:
            logger.info("Fetching PIM page", extra={"page": page})
            data = self._fetch_page(page)

            products = data.get("products", [])
            if not isinstance(products, list):
                raise ValueError(
                    f"Unexpected 'products' type on page {page}: {type(products)}")

            total_fetched += len(products)
            logger.debug(
                "Fetched PIM page",
                extra={"page": page, "count": len(
                    products), "total": total_fetched},
            )

            yield products

            has_next = data.get("has_next", False)
            if not has_next:
                break

            next_page = data.get("next_page")
            if next_page is None:
                logger.warning(
                    "has_next=True but next_page is None on page %d; stopping.", page)
                break

            page = int(next_page)

        logger.info("PIM extraction complete", extra={
                    "total_fetched": total_fetched})
