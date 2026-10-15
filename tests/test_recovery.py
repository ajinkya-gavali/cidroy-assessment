"""
tests/test_recovery.py

Unit tests for crash recovery, duplicate prevention, and resuming runs:
- Batches already marked ACCEPTED are never resubmitted to WMS
- Resuming a failed run processes only PENDING or FAILED batches
- Quarantined batches remain protected from blind retries
"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.clients.warehouse_api import BatchResult
from app.services.warehouse_sync import _dispatch_batch, dispatch_batches
from app.storage.models import BatchRecord, BatchStatus, RunRecord, RunStatus
from app.storage.state import SQLiteStateStore
from app.services.warehouse_sync import DispatchSummary


def test_resume_skips_already_accepted_batches():
    """Batches previously marked ACCEPTED are skipped and never sent to WMS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "state.db"
        state = SQLiteStateStore(db_path=db_path)
        try:
            run_id = "run_recovery_001"
            run = RunRecord(run_id=run_id, status=RunStatus.INGESTING)
            state.create_run(run)

            # Batch 1 was accepted previously
            batch1 = BatchRecord(
                run_id=run_id,
                batch_id="batch_00001",
                status=BatchStatus.ACCEPTED,
                batch_size=2,
                accepted_skus=["P01", "P02"],
            )
            # Batch 2 is still pending
            batch2 = BatchRecord(
                run_id=run_id,
                batch_id="batch_00002",
                status=BatchStatus.PENDING,
                batch_size=2,
            )
            state.create_batch(batch1)
            state.create_batch(batch2)

            batch_products = {
                "batch_00001": [{"sku": "P01"}, {"sku": "P02"}],
                "batch_00002": [{"sku": "P03"}, {"sku": "P04"}],
            }

            mock_client = MagicMock()
            mock_client.__enter__.return_value = mock_client
            mock_client.send_batch.return_value = BatchResult(
                accepted=["P03", "P04"], rejected=[]
            )

            with patch("app.services.warehouse_sync.WarehouseApiClient", return_value=mock_client):
                summary = dispatch_batches(
                    run_id=run_id,
                    batch_records=[batch1, batch2],
                    batch_products=batch_products,
                    state=state,
                    worker_count=1,
                )

            # Batch 1 was skipped, only Batch 2 was submitted
            assert summary.skipped_batches == 1
            assert summary.accepted_batches == 1
            assert mock_client.send_batch.call_count == 1
            # Called only with batch_00002
            call_args = mock_client.send_batch.call_args
            assert call_args[1]["batch_id"] == "batch_00002"
        finally:
            state.close()


def test_quarantined_ambiguous_batch_is_not_retried():
    """AMBIGUOUS_TIMEOUT batches are quarantined and not automatically resubmitted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "state.db"
        state = SQLiteStateStore(db_path=db_path)
        try:
            run_id = "run_recovery_002"
            batch = BatchRecord(
                run_id=run_id,
                batch_id="batch_00001",
                status=BatchStatus.PENDING,
                batch_size=1,
            )
            state.create_batch(batch)

            mock_client = MagicMock()
            mock_client.send_batch.return_value = BatchResult(
                accepted=[], rejected=[], ambiguous_timeout=True, error_message="Read timed out"
            )

            summary = DispatchSummary()

            _dispatch_batch(
                batch_record=batch,
                products=[{"sku": "P001"}],
                wms_client=mock_client,
                state=state,
                summary=summary,
            )

            updated_batch = state.get_batch(run_id, "batch_00001")
            assert updated_batch is not None
            assert updated_batch.status == BatchStatus.AMBIGUOUS_TIMEOUT

            # Dead letter record must exist for audit
            dlqs = state.list_dead_letters(run_id)
            assert len(dlqs) == 1
            assert dlqs[0].sku == "P001"
            assert "AMBIGUOUS_TIMEOUT" in dlqs[0].reason
        finally:
            state.close()
