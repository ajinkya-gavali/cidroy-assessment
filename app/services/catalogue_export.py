"""
app/services/catalogue_export.py

Catalogue extraction service.

Fetches all products from the PIM API using the streaming generator in
ProductApiClient, writes records to a local CSV file row-by-row (constant
memory), then uploads the completed CSV to the configured storage backend
(local filesystem or Amazon S3).

The exported file is named using the run_id for uniqueness across runs.
"""
from __future__ import annotations

import csv
import logging
import os
from datetime import date, timezone, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app import config
from app.clients.product_api import ProductApiClient
from app.core.secrets import get_api_keys
from app.storage.s3 import StorageAdapter, export_key

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Field order that is written to CSV and must match the DictWriter header
CSV_FIELDNAMES = ["id", "name", "category", "price", "currency", "updated_at"]


def export_catalogue(
    run_id: str,
    storage: StorageAdapter,
    local_export_dir: str = config.EXPORT_DIR,
) -> tuple[str, int]:
    """Extract all products from PIM and export them as a CSV.

    Steps:
    1. Streams pages from the PIM API using ProductApiClient.fetch_pages().
    2. Writes each page's products immediately to a local CSV file.
    3. After all pages are fetched, uploads the CSV to the storage backend.

    Args:
        run_id: Unique identifier for this synchronization run.
        storage: StorageAdapter to upload the completed CSV.
        local_export_dir: Temporary local directory for the CSV file.

    Returns:
        Tuple of (storage_key, total_product_count).
    """
    keys = get_api_keys()

    # Temporary local file for streaming write
    local_dir = Path(local_export_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"catalogue_{run_id}.csv"

    total_count = 0

    logger.info("Starting PIM extraction", extra={"run_id": run_id})

    with open(local_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=CSV_FIELDNAMES,
            extrasaction="ignore",  # Ignore extra PIM fields gracefully
        )
        writer.writeheader()

        with ProductApiClient(
            base_url=config.PRODUCT_API_URL,
            api_key=keys.product_api_key,
        ) as pim:
            for page_products in pim.fetch_pages():
                writer.writerows(page_products)
                csvfile.flush()  # Flush after each page for crash resilience
                total_count += len(page_products)
                logger.info(
                    "PIM page written to CSV",
                    extra={"run_id": run_id, "cumulative_count": total_count},
                )

    logger.info(
        "PIM extraction complete, uploading export",
        extra={"run_id": run_id, "total_count": total_count},
    )

    # Upload to storage backend (local FS or S3)
    date_str = date.today().isoformat()
    key = export_key(run_id=run_id, date_str=date_str)
    storage.put_file(local_path=local_path, key=key)

    logger.info(
        "Export uploaded",
        extra={"run_id": run_id, "storage_key": key, "total_count": total_count},
    )

    return key, total_count
