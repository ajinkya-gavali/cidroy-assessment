"""
tests/test_rate_limiter.py

Unit tests for the thread-safe TokenBucket rate limiter.
"""
import time

from app.core.rate_limiter import TokenBucket


def test_token_bucket_initial_capacity():
    """TokenBucket initializes with configured rate and capacity."""
    bucket = TokenBucket(rate=10.0, capacity=10.0)
    assert bucket.rate == 10.0
    # Consuming available capacity should succeed without blocking
    start = time.monotonic()
    for _ in range(10):
        bucket.acquire(1.0)
    duration = time.monotonic() - start
    assert duration < 0.2


def test_token_bucket_pacing():
    """TokenBucket enforces pacing when capacity is exhausted."""
    bucket = TokenBucket(rate=50.0, capacity=1.0)
    # Drain the single token
    bucket.acquire(1.0)

    # Next acquire must wait for token refill (1/50 = 0.02s)
    start = time.monotonic()
    bucket.acquire(1.0)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.015


def test_token_bucket_default_capacity():
    """When capacity is None, it defaults to rate."""
    bucket = TokenBucket(rate=15.0)
    assert bucket._capacity == 15.0
