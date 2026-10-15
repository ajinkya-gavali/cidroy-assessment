"""
tests/test_coordinator.py

Unit tests for the run coordinator and multi-phase synchronization lifecycle.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.core.coordinator import generate_run_id, run_sync
from app.core.metrics import ConsoleMetricsClient
from app.storage.models import RunStatus
from app.storage.s3 import LocalStorageAdapter
from app.storage.state import SQLiteStateStore
from app.clients.warehouse_api import BatchResult

def test_generate_run_id_format():
    """Run IDs follow format run_YYYYMMDD_HHMMSS_<short_uuid>."""
    run_id = generate_run_id()
    assert run_id.startswith("run_")
    parts = run_id.split("_")
    assert len(parts) >= 3


def test_run_sync_full_success_lifecycle():
    """Coordinator transitions through EXTRACTING, STAGING, INGESTING, COMPLETED."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "state.db"
        export_dir = Path(tmpdir) / "exports"
        s3_root = Path(tmpdir) / "s3"

        state = SQLiteStateStore(db_path=db_path)
        try:
            storage = LocalStorageAdapter(root_dir=s3_root)
            metrics = ConsoleMetricsClient(run_id="run_test_coord_01")

            mock_pim_page = [
                {"id": "P0000001", "name": "Item 1", "category": "HOME", "price": "100.0",
                    "currency": "INR", "updated_at": "2026-09-25T08:30:00Z"},
                {"id": "P0000002", "name": "Item 2", "category": "SPICES", "price": "50.0",
                    "currency": "INR", "updated_at": "2026-09-25T08:30:00Z"},
            ]

            mock_wms_result = BatchResult(
                accepted=["P0000001", "P0000002"], rejected=[])

            with patch("app.clients.product_api.ProductApiClient.fetch_pages", return_value=[mock_pim_page]):
                with patch("app.clients.warehouse_api.WarehouseApiClient.send_batch", return_value=mock_wms_result):
                    with patch("app.config.EXPORT_DIR", str(export_dir)):
                        run = run_sync(
                            run_id="run_test_coord_01",
                            state=state,
                            storage=storage,
                            metrics=metrics,
                        )

            assert run.status == RunStatus.COMPLETED
            assert run.total_products == 2
            assert run.total_batches == 1
            assert run.accepted_count == 2
            assert run.rejected_count == 0
        finally:
            state.close()


def test_run_sync_completed_with_rejections():
    """Runs with rejected items finish with status COMPLETED_WITH_REJECTIONS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "state.db"
        export_dir = Path(tmpdir) / "exports"
        s3_root = Path(tmpdir) / "s3"

        state = SQLiteStateStore(db_path=db_path)
        try:
            storage = LocalStorageAdapter(root_dir=s3_root)
            metrics = ConsoleMetricsClient(run_id="run_test_coord_02")

            mock_pim_page = [
                {"id": "P0000001", "name": "Item 1", "category": "HOME", "price": "100.0",
                    "currency": "INR", "updated_at": "2026-09-25T08:30:00Z"},
                {"id": "P0000999", "name": "Invalid Item", "category": "HOME",
                    "price": "10.0", "currency": "INR", "updated_at": "2026-09-25T08:30:00Z"},
            ]

            mock_wms_result = BatchResult(
                accepted=["P0000001"],
                rejected=[
                    {"sku": "P0000999", "reason": "Invalid warehouse product"}],
            )

            with patch("app.clients.product_api.ProductApiClient.fetch_pages", return_value=[mock_pim_page]):
                with patch("app.clients.warehouse_api.WarehouseApiClient.send_batch", return_value=mock_wms_result):
                    with patch("app.config.EXPORT_DIR", str(export_dir)):
                        run = run_sync(
                            run_id="run_test_coord_02",
                            state=state,
                            storage=storage,
                            metrics=metrics,
                        )

            assert run.status == RunStatus.COMPLETED_WITH_REJECTIONS
            assert run.accepted_count == 1
            assert run.rejected_count == 1
            # Dead letters must be recorded
            dlqs = state.list_dead_letters("run_test_coord_02")
            assert len(dlqs) == 1
            assert dlqs[0].sku == "P0000999"
        finally:
            state.close()
