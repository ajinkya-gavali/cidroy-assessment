"""
app/core/http_client.py

Factory helpers for httpx.Client sessions with connection pooling,
HTTP keep-alive, and sensible default timeouts.
"""
import httpx

# Default timeouts: connect quickly, allow longer reads for slow APIs
DEFAULT_CONNECT_TIMEOUT = 5.0   # seconds
DEFAULT_READ_TIMEOUT = 30.0     # seconds
DEFAULT_WRITE_TIMEOUT = 10.0    # seconds
DEFAULT_POOL_TIMEOUT = 5.0      # seconds


def build_client(
    *,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: float = DEFAULT_READ_TIMEOUT,
    write_timeout: float = DEFAULT_WRITE_TIMEOUT,
    pool_timeout: float = DEFAULT_POOL_TIMEOUT,
    max_connections: int = 20,
    max_keepalive_connections: int = 10,
) -> httpx.Client:
    """Build a reusable httpx.Client with connection pooling and keep-alive.

    The returned client should be used as a context manager or explicitly closed
    after use to release connection resources.

    Args:
        connect_timeout: Max seconds to wait for a TCP connection.
        read_timeout: Max seconds to wait for server response bytes.
        write_timeout: Max seconds to wait when sending request body.
        pool_timeout: Max seconds to wait for a connection from the pool.
        max_connections: Maximum total open connections.
        max_keepalive_connections: Maximum idle keep-alive connections.

    Returns:
        Configured httpx.Client instance.
    """
    timeout = httpx.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=write_timeout,
        pool=pool_timeout,
    )
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive_connections,
    )
    return httpx.Client(timeout=timeout, limits=limits)
