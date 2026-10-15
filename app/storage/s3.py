"""
app/storage/s3.py

Dual-mode storage adapter for catalogue export files.

- APP_ENV=local (or STORAGE_BACKEND=local): writes to the local filesystem
  under ./runtime/s3/exports/<date>/catalogue_<run_id>.csv
- APP_ENV=production (or STORAGE_BACKEND=s3): streams to Amazon S3 via
  boto3 multipart upload.

Both adapters implement the StorageAdapter interface so application code
is fully backend-agnostic.
"""
from __future__ import annotations

import io
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class StorageAdapter(ABC):
    """Abstract file storage adapter."""

    @abstractmethod
    def put_file(
        self,
        local_path: str | Path,
        key: str,
        content_type: str = "text/csv",
    ) -> str:
        """Upload a local file to the storage backend.

        Args:
            local_path: Path to the file on the local filesystem.
            key: Destination key / path within the storage backend.
            content_type: MIME type of the file.

        Returns:
            The full storage URI or path of the uploaded file.
        """

    @abstractmethod
    def open_for_read(self, key: str) -> io.IOBase:
        """Open a stored file for reading.

        Args:
            key: Key / path of the file in the storage backend.

        Returns:
            A file-like object opened for reading.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if the given key exists in the storage backend."""


# ---------------------------------------------------------------------------
# Local filesystem implementation
# ---------------------------------------------------------------------------

class LocalStorageAdapter(StorageAdapter):
    """Storage adapter that writes files to the local filesystem.

    This adapter mirrors the S3 key structure as a directory path under
    `root_dir`, enabling identical application code in both local and
    production modes.

    Args:
        root_dir: Base directory for local storage (e.g. './runtime/s3').
    """

    def __init__(self, root_dir: str | Path = "./runtime/s3") -> None:
        self._root = Path(root_dir)

    def _resolve(self, key: str) -> Path:
        return self._root / key

    def put_file(
        self,
        local_path: str | Path,
        key: str,
        content_type: str = "text/csv",
    ) -> str:
        src = Path(local_path)
        dst = self._resolve(key)
        dst.parent.mkdir(parents=True, exist_ok=True)

        # Stream copy to avoid reading the whole file into memory
        with src.open("rb") as fin, dst.open("wb") as fout:
            while chunk := fin.read(64 * 1024):
                fout.write(chunk)

        logger.info("Stored local file key=%s path=%s", key, dst)
        return str(dst)

    def open_for_read(self, key: str) -> io.IOBase:
        path = self._resolve(key)
        return path.open("rb")

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()


# ---------------------------------------------------------------------------
# Amazon S3 implementation
# ---------------------------------------------------------------------------

class S3StorageAdapter(StorageAdapter):
    """Storage adapter that streams files to Amazon S3.

    Uses multipart upload for large files and streaming get for downloads.

    Args:
        bucket: S3 bucket name.
        region: AWS region name.
    """

    def __init__(self, bucket: str, region: str | None = None) -> None:
        import boto3  # type: ignore[import-untyped]
        self._bucket = bucket
        self._s3 = boto3.client("s3", region_name=region)

    def put_file(
        self,
        local_path: str | Path,
        key: str,
        content_type: str = "text/csv",
    ) -> str:
        src = Path(local_path)
        self._s3.upload_file(
            Filename=str(src),
            Bucket=self._bucket,
            Key=key,
            ExtraArgs={"ContentType": content_type},
        )
        uri = f"s3://{self._bucket}/{key}"
        logger.info("Uploaded to S3 uri=%s", uri)
        return uri

    def open_for_read(self, key: str) -> io.IOBase:
        obj = self._s3.get_object(Bucket=self._bucket, Key=key)
        return obj["Body"]

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
            return True
        except self._s3.exceptions.ClientError:
            return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_storage_adapter() -> StorageAdapter:
    """Factory: returns Local or S3 adapter based on APP_ENV / STORAGE_BACKEND.

    Returns:
        Appropriate StorageAdapter implementation.
    """
    env = os.getenv("APP_ENV", "local").lower()
    backend = os.getenv("STORAGE_BACKEND", "").lower()

    if env == "production" or backend == "s3":
        bucket = os.getenv("S3_BUCKET_NAME", "catalogue-sync-exports")
        region = os.getenv("AWS_REGION", "ap-south-1")
        return S3StorageAdapter(bucket=bucket, region=region)

    root_dir = os.getenv("LOCAL_STORAGE_ROOT", "./runtime/s3")
    return LocalStorageAdapter(root_dir=root_dir)


def export_key(run_id: str, date_str: str) -> str:
    """Generate the deterministic export key for a given run.

    Format: exports/<date>/catalogue_<run_id>.csv

    Args:
        run_id: Synchronization run identifier.
        date_str: ISO date string (YYYY-MM-DD).

    Returns:
        Storage key string.
    """
    return f"exports/{date_str}/catalogue_{run_id}.csv"
