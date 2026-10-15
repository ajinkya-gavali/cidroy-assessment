"""
tests/test_state_store.py

Unit tests for SQLiteStateStore (local durable state ledger).
"""
import tempfile
from pathlib import Path

from app.storage.models import (
    BatchRecord,
    BatchStatus,
    DeadLetterRecord,
    RunRecord,
    RunStatus,
)
from app.storage.state import SQLiteStateStore, build_state_store


def test_sqlite_state_store_run_lifecycle():
    """Create, retrieve, and update a run record."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_state.db"
        store = SQLiteStateStore(db_path=db_path)
        try:
            run = RunRecord(run_id="run_test_001", status=RunStatus.INITIALIZING)
            store.create_run(run)

            fetched = store.get_run("run_test_001")
            assert fetched is not None
            assert fetched.run_id == "run_test_001"
            assert fetched.status == RunStatus.INITIALIZING

            # Update run status and product count
            fetched.status = RunStatus.EXTRACTING
            fetched.total_products = 500
            store.update_run(fetched)

            updated = store.get_run("run_test_001")
            assert updated is not None
            assert updated.status == RunStatus.EXTRACTING
            assert updated.total_products == 500
        finally:
            store.close()


def test_sqlite_state_store_batch_operations():
    """Create, update, and list batch records with status filtering."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_state.db"
        store = SQLiteStateStore(db_path=db_path)
        try:
            batch1 = BatchRecord(
                run_id="run_test_002",
                batch_id="batch_00001",
                status=BatchStatus.PENDING,
                batch_size=100,
            )
            batch2 = BatchRecord(
                run_id="run_test_002",
                batch_id="batch_00002",
                status=BatchStatus.PENDING,
                batch_size=50,
            )
            store.create_batch(batch1)
            store.create_batch(batch2)

            # Mark batch1 as ACCEPTED
            batch1.status = BatchStatus.ACCEPTED
            batch1.accepted_skus = ["P001", "P002"]
            store.update_batch(batch1)

            # Query all batches
            all_batches = store.list_batches("run_test_002")
            assert len(all_batches) == 2

            # Filter by status
            accepted_batches = store.list_batches("run_test_002", status=BatchStatus.ACCEPTED)
            assert len(accepted_batches) == 1
            assert accepted_batches[0].batch_id == "batch_00001"
            assert accepted_batches[0].accepted_skus == ["P001", "P002"]
        finally:
            store.close()


def test_sqlite_state_store_dead_letters():
    """Add and list dead-letter records."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_state.db"
        store = SQLiteStateStore(db_path=db_path)
        try:
            dlq_item = DeadLetterRecord(
                run_id="run_test_003",
                batch_id="batch_00001",
                sku="P0000999",
                reason="Invalid warehouse product",
                original_payload={"sku": "P0000999"},
            )
            store.add_dead_letter(dlq_item)

            dlq_records = store.list_dead_letters("run_test_003")
            assert len(dlq_records) == 1
            assert dlq_records[0].sku == "P0000999"
            assert dlq_records[0].reason == "Invalid warehouse product"
        finally:
            store.close()


def test_build_state_store_local_default():
    """build_state_store defaults to SQLiteStateStore when APP_ENV is local."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "state.db")
        store = build_state_store(db_path=db_path)
        try:
            assert isinstance(store, SQLiteStateStore)
        finally:
            store.close()
