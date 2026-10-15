"""
tests/test_storage_s3.py

Unit tests for storage adapters and deterministic export key generation.
"""
import tempfile
from pathlib import Path

from app.storage.s3 import (
    LocalStorageAdapter,
    build_storage_adapter,
    export_key,
)


def test_export_key_format():
    """export_key matches the documented schema exports/<date>/catalogue_<run_id>.csv."""
    key = export_key(run_id="run_12345", date_str="2026-10-14")
    assert key == "exports/2026-10-14/catalogue_run_12345.csv"


def test_local_storage_adapter_put_and_read():
    """LocalStorageAdapter streams files to local directory and opens them for read."""
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = LocalStorageAdapter(root_dir=tmpdir)

        # Create a source file with binary content to ensure cross-platform newline parity
        src_path = Path(tmpdir) / "source.csv"
        src_path.write_bytes(b"id,name\nP01,Test")

        key = "exports/2026-10-14/catalogue_001.csv"
        dest_path = adapter.put_file(local_path=src_path, key=key)

        assert Path(dest_path).exists()
        assert adapter.exists(key)

        with adapter.open_for_read(key) as f:
            content = f.read().decode("utf-8").replace("\r\n", "\n")
        assert content == "id,name\nP01,Test"


def test_build_storage_adapter_local_default():
    """build_storage_adapter returns LocalStorageAdapter when APP_ENV is unset or local."""
    adapter = build_storage_adapter()
    assert isinstance(adapter, LocalStorageAdapter)
