"""
app/core/rate_limiter.py

Thread-safe Token Bucket rate limiter.

The token bucket allows bursting up to `capacity` tokens, then enforces
a steady-state rate of `rate` tokens/second. Callers block in `acquire()`
until a token is available.
"""
import threading
import time


class TokenBucket:
    """Thread-safe Token Bucket rate limiter.

    Args:
        rate: Tokens refilled per second (target dispatch rate).
        capacity: Maximum burst size (number of tokens the bucket can hold).
    """

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self._rate = rate
        self._capacity = capacity if capacity is not None else rate
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._rate
        self._tokens = min(self._capacity, self._tokens + added)
        self._last_refill = now

    def acquire(self, tokens: float = 1.0) -> None:
        """Block until `tokens` tokens are available, then consume them.

        Args:
            tokens: Number of tokens to consume (default 1).
        """
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                # Calculate how long to wait for the deficit
                deficit = tokens - self._tokens
                wait_time = deficit / self._rate
            # Sleep outside the lock to allow other threads to make progress
            time.sleep(wait_time)

    @property
    def rate(self) -> float:
        """Current configured rate (tokens/second)."""
        return self._rate
