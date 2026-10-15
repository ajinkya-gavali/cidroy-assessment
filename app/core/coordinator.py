"""
app/core/coordinator.py

Synchronization run coordinator.

Manages the three-phase pipeline:
  Phase 1: EXTRACTING  - Fetch PIM pages, write CSV, upload to storage
  Phase 2: STAGING     - Stream CSV, transform, register batch manifests
  Phase 3: INGESTING   - Concurrent WMS batch dispatch with checkpointing

The coordinator generates a unique run_id, persists run state to the
ledger at each phase transition, and finalises the run status on
completion or failure.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from app import config
from app.core.logging import get_logger
from app.core.metrics import MetricsClient, build_metrics_client
from app.services.catalogue_export import export_catalogue
from app.services.transformer import stream_transformed_batches
from app.services.warehouse_sync import dispatch_batches
from app.storage.models import BatchRecord, BatchStatus, RunRecord, RunStatus
from app.storage.s3 import StorageAdapter, build_storage_adapter
from app.storage.state import StateStore, build_state_store

logger = logging.getLogger(__name__)


def generate_run_id() -> str:
    """Generate a short, unique, human-readable run identifier."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_uuid = str(uuid.uuid4()).split("-")[0]
    return f"run_{ts}_{short_uuid}"


def run_sync(
    run_id: str | None = None,
    state: StateStore | None = None,
    storage: StorageAdapter | None = None,
    metrics: MetricsClient | None = None,
) -> RunRecord:
    """Execute a full catalogue synchronization run.

    Args:
        run_id: Optional run ID to resume. If None, a new ID is generated.
        state: State store override (for testing or custom backend).
        storage: Storage adapter override (for testing or custom backend).
        metrics: Metrics client override (for testing or custom backend).

    Returns:
        Finalized RunRecord with status, counts, and export path.
    """
    run_id = run_id or generate_run_id()
    state = state or build_state_store(db_path=config.STATE_DB_PATH)
    storage = storage or build_storage_adapter()
    metrics = metrics or build_metrics_client(run_id=run_id)

    log = get_logger(__name__, run_id=run_id)
    log.info("Starting synchronization run", extra={"run_id": run_id})

    # Check for an existing run to resume
    existing_run = state.get_run(run_id)
    if existing_run:
        log.info(
            "Resuming existing run",
            extra={"run_id": run_id, "status": existing_run.status.value},
        )
        run = existing_run
    else:
        run = RunRecord(run_id=run_id, status=RunStatus.INITIALIZING)
        state.create_run(run)

    # -------------------------------------------------------------------
    # Phase 1: Extraction
    # -------------------------------------------------------------------
    export_key_path = run.export_path
    total_products = run.total_products

    if run.status in (RunStatus.INITIALIZING, RunStatus.EXTRACTING) and not export_key_path:
        run.status = RunStatus.EXTRACTING
        state.update_run(run)

        try:
            export_key_path, total_products = export_catalogue(
                run_id=run_id,
                storage=storage,
                local_export_dir=config.EXPORT_DIR,
            )
        except Exception as exc:
            log.error("Extraction failed", extra={"run_id": run_id, "error": str(exc)})
            run.status = RunStatus.FAILED
            run.error_message = f"Extraction failed: {exc}"
            state.update_run(run)
            return run

        run.export_path = export_key_path
        run.total_products = total_products
        run.status = RunStatus.STAGING
        state.update_run(run)
        log.info(
            "Extraction complete",
            extra={"run_id": run_id, "total_products": total_products, "export_key": export_key_path},
        )
    else:
        log.info("Skipping extraction (already complete)", extra={"run_id": run_id})

    # -------------------------------------------------------------------
    # Phase 2: Staging (Transform + Register Batches)
    # -------------------------------------------------------------------
    local_csv_path = _resolve_local_csv(run_id, config.EXPORT_DIR)
    batch_products: dict[str, list] = {}
    batch_records: list[BatchRecord] = []

    if run.status in (RunStatus.STAGING,):
        try:
            total_batches = 0

            for batch_index, products in stream_transformed_batches(
                csv_path=local_csv_path,
                batch_size=config.BATCH_SIZE,
            ):
                batch_id = f"batch_{batch_index:05d}"
                total_batches += 1
                batch_products[batch_id] = products

                # Register batch in ledger only if not already present
                existing_batch = state.get_batch(run_id, batch_id)
                if existing_batch is None:
                    record = BatchRecord(
                        run_id=run_id,
                        batch_id=batch_id,
                        status=BatchStatus.PENDING,
                        batch_size=len(products),
                    )
                    state.create_batch(record)
                    batch_records.append(record)
                else:
                    batch_records.append(existing_batch)

            run.total_batches = total_batches
            run.status = RunStatus.INGESTING
            state.update_run(run)
            log.info(
                "Staging complete",
                extra={"run_id": run_id, "total_batches": total_batches},
            )

        except Exception as exc:
            log.error("Staging failed", extra={"run_id": run_id, "error": str(exc)})
            run.status = RunStatus.FAILED
            run.error_message = f"Staging failed: {exc}"
            state.update_run(run)
            return run
    else:
        # Reload batch records for dispatch phase
        batch_records = state.list_batches(run_id)
        # Regenerate batch_products from the CSV for pending batches
        if Path(local_csv_path).exists():
            for batch_index, products in stream_transformed_batches(
                csv_path=local_csv_path,
                batch_size=config.BATCH_SIZE,
            ):
                batch_id = f"batch_{batch_index:05d}"
                batch_products[batch_id] = products

    # -------------------------------------------------------------------
    # Phase 3: Ingestion (Concurrent WMS Dispatch)
    # -------------------------------------------------------------------
    if run.status == RunStatus.INGESTING:
        try:
            summary = dispatch_batches(
                run_id=run_id,
                batch_records=batch_records,
                batch_products=batch_products,
                state=state,
                worker_count=config.WMS_WORKER_COUNT,
            )
        except Exception as exc:
            log.error("Ingestion failed", extra={"run_id": run_id, "error": str(exc)})
            run.status = RunStatus.FAILED
            run.error_message = f"Ingestion failed: {exc}"
            state.update_run(run)
            return run

        run.accepted_count = summary.total_accepted_skus
        run.rejected_count = summary.rejected_item_count
        run.ambiguous_count = summary.ambiguous_batch_count
        run.completed_at = datetime.now(timezone.utc)

        # Emit final metrics
        metrics.gauge("WmsProductsAccepted", float(summary.total_accepted_skus))
        metrics.gauge("WmsProductsRejected", float(summary.rejected_item_count))
        metrics.gauge("WmsAmbiguousTimeouts", float(summary.ambiguous_batch_count))
        metrics.flush()

        if summary.ambiguous_batch_count > 0 or summary.rejected_item_count > 0:
            run.status = RunStatus.COMPLETED_WITH_REJECTIONS
        elif summary.failed_batch_count > 0:
            run.status = RunStatus.FAILED
        else:
            run.status = RunStatus.COMPLETED

        state.update_run(run)
        log.info(
            "Synchronization run complete",
            extra={"run_id": run_id, "status": run.status.value, "summary": summary.as_dict()},
        )

    return run


def _resolve_local_csv(run_id: str, export_dir: str) -> str:
    """Resolve the local CSV file path for a given run."""
    return str(Path(export_dir) / f"catalogue_{run_id}.csv")
