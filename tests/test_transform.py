"""
tests/test_transform.py

Unit tests for product schema transformation, price validation,
SKU deduplication, and streaming batch slicing.
Preserves original test_transform().
"""
import csv
import tempfile
from pathlib import Path

import pytest

from app.services.transformer import (
    TransformError,
    stream_transformed_batches,
    transform_row,
)
from app.services.warehouse_sync import transform


def test_transform():
    """Preserved original test: standard transformation mappings."""
    row = {
        "id": "P0000001",
        "name": "Test Product",
        "category": "SPICES",
        "price": "249.50",
        "currency": "INR",
        "updated_at": "2026-09-25T08:30:00Z",
    }
    result = transform(row)
    assert result["sku"] == "P0000001"
    assert result["selling_price"] == 249.50
    assert result["category_code"] == "SPICES"
    assert result["description"] == "Test Product"
    assert result["currency"] == "INR"
    assert result["source_updated_at"] == "2026-09-25T08:30:00Z"


def test_transform_missing_id_raises():
    """Missing or empty 'id' field raises TransformError."""
    row = {"id": "", "name": "No ID", "price": "10.0"}
    with pytest.raises(TransformError, match="Missing required field 'id'"):
        transform_row(row)


def test_transform_missing_name_raises():
    """Missing or empty 'name' field raises TransformError."""
    row = {"id": "P001", "name": "", "price": "10.0"}
    with pytest.raises(TransformError, match="Missing required field 'name'"):
        transform_row(row)


def test_transform_invalid_price_raises():
    """Non-numeric price string raises TransformError."""
    row = {"id": "P001", "name": "Bad Price", "price": "abc"}
    with pytest.raises(TransformError, match="Invalid price"):
        transform_row(row)


def test_stream_transformed_batches_slicing_and_deduplication():
    """Streaming transformation enforces max batch size and eliminates duplicate SKUs."""
    rows = [
        {"id": f"P{i:07d}", "name": f"Product {i}", "price": "100.0", "category": "HOME", "currency": "INR", "updated_at": "2026-09-25T08:30:00Z"}
        for i in range(1, 251)
    ]
    # Inject a duplicate SKU
    rows.append({"id": "P0000001", "name": "Duplicate P1", "price": "100.0", "category": "HOME", "currency": "INR", "updated_at": "2026-09-25T08:30:00Z"})

    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", delete=False) as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "price", "category", "currency", "updated_at"])
        writer.writeheader()
        writer.writerows(rows)
        temp_path = f.name

    try:
        batches = list(stream_transformed_batches(temp_path, batch_size=100))
        # 250 unique items: batch 1 (100), batch 2 (100), batch 3 (50)
        assert len(batches) == 3

        batch_1_idx, batch_1_items = batches[0]
        assert batch_1_idx == 1
        assert len(batch_1_items) == 100

        batch_2_idx, batch_2_items = batches[1]
        assert batch_2_idx == 2
        assert len(batch_2_items) == 100

        batch_3_idx, batch_3_items = batches[2]
        assert batch_3_idx == 3
        assert len(batch_3_items) == 50

        # Verify duplicate P0000001 was not appended a second time
        all_skus = [p["sku"] for _, items in batches for p in items]
        assert len(all_skus) == 250
        assert len(set(all_skus)) == 250
    finally:
        Path(temp_path).unlink(missing_ok=True)
