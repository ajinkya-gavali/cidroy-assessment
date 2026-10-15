"""
app/services/transformer.py

Streaming CSV transformer.

Reads the catalogue CSV file iteratively (one row at a time) to avoid
loading the entire file into memory. Deduplicates SKUs within the run,
validates field types, and slices transformed records into batches of at
most MAX_BATCH_SIZE (100) records.
"""
from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app import config

logger = logging.getLogger(__name__)


class TransformError(Exception):
    """Raised when a CSV row cannot be transformed due to an unrecoverable error."""


def transform_row(row: dict[str, str]) -> dict[str, Any]:
    """Transform a single CSV row from PIM format to WMS format.

    PIM fields:  id, name, category, price, currency, updated_at
    WMS fields:  sku, description, selling_price, currency, category_code, source_updated_at

    Args:
        row: CSV row as a dict with PIM field names.

    Returns:
        WMS-formatted product dictionary.

    Raises:
        TransformError: If required fields are missing or have invalid types.
    """
    sku = row.get("id", "").strip()
    if not sku:
        raise TransformError(f"Missing required field 'id' in row: {row}")

    name = row.get("name", "").strip()
    if not name:
        raise TransformError(f"Missing required field 'name' for SKU={sku}")

    raw_price = row.get("price", "").strip()
    try:
        selling_price = float(raw_price)
    except (ValueError, TypeError) as exc:
        raise TransformError(
            f"Invalid price '{raw_price}' for SKU={sku}: {exc}"
        ) from exc

    return {
        "sku": sku,
        "description": name,
        "selling_price": selling_price,
        "currency": row.get("currency", "").strip(),
        "category_code": row.get("category", "").strip(),
        "source_updated_at": row.get("updated_at", "").strip(),
    }


def stream_transformed_batches(
    csv_path: str | Path,
    batch_size: int = config.BATCH_SIZE,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    """Stream transformed product batches from a catalogue CSV file.

    Reads the CSV row by row (constant memory), deduplicates SKUs within the
    run, transforms each record to WMS format, and yields sliced batches.

    Args:
        csv_path: Path to the catalogue CSV file.
        batch_size: Maximum products per batch (must be <= 100).

    Yields:
        Tuples of (batch_index_1based, batch_products_list).
    """
    batch_size = min(batch_size, 100)  # Enforce WMS API maximum
    seen_skus: set[str] = set()        # Deduplication within this run
    current_batch: list[dict[str, Any]] = []
    batch_index = 0
    skipped_duplicates = 0
    skipped_invalid = 0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                product = transform_row(row)
            except TransformError as exc:
                logger.warning("Skipping invalid CSV row: %s", exc)
                skipped_invalid += 1
                continue

            sku = product["sku"]
            if sku in seen_skus:
                logger.debug("Deduplicating SKU=%s (already seen in this run)", sku)
                skipped_duplicates += 1
                continue

            seen_skus.add(sku)
            current_batch.append(product)

            if len(current_batch) >= batch_size:
                batch_index += 1
                yield batch_index, current_batch
                current_batch = []

    # Yield any remaining partial batch
    if current_batch:
        batch_index += 1
        yield batch_index, current_batch

    logger.info(
        "Transformation complete",
        extra={
            "total_batches": batch_index,
            "skipped_duplicates": skipped_duplicates,
            "skipped_invalid": skipped_invalid,
        },
    )
