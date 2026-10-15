"""
tests/test_http_client.py

Unit tests for http_client factory.
"""
from app.core.http_client import build_client


def test_build_client_defaults():
    """Client is built with configured timeouts and connection limits."""
    client = build_client(
        connect_timeout=3.0,
        read_timeout=15.0,
        max_connections=30,
        max_keepalive_connections=15,
    )
    try:
        assert client.timeout.connect == 3.0
        assert client.timeout.read == 15.0
    finally:
        client.close()
