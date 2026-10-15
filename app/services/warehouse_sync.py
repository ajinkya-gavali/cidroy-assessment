"""
app/services/warehouse_sync.py

Concurrent WMS batch dispatcher.

Responsibilities:
- Pre-submission state check: batches already ACCEPTED are skipped (no duplicates)
- Rate-limited concurrent submission using a shared TokenBucket
- Post-submission state commit: accepted SKUs written to ledger
- Rejected SKUs routed to the Dead-Letter ledger with failure reasons
- AMBIGUOUS_TIMEOUT batches quarantined (not retried) to honour the
  warehouse non-duplication mandate
- Worker pool (default 6 workers) to meet the 30-minute throughput target
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from app import config
from app.clients.warehouse_api import BatchResult, WarehouseApiClient
from app.core.secrets import get_api_keys
from app.services.transformer import transform_row
from app.storage.models import BatchRecord, BatchStatus, DeadLetterRecord
from app.storage.state import StateStore

logger = logging.getLogger(__name__)

# Backward compatibility alias for existing tests
transform = transform_row


class DispatchSummary:
    """Aggregated results from dispatching all batches in a run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total_batches = 0
        self.accepted_batches = 0
        self.skipped_batches = 0  # Already accepted on previous run
        self.rejected_item_count = 0
        self.ambiguous_batch_count = 0
        self.failed_batch_count = 0
        self.total_accepted_skus = 0

    def record_skipped(self) -> None:
        with self._lock:
            self.skipped_batches += 1

    def record_result(self, result: BatchResult) -> None:
        with self._lock:
            if result.ambiguous_timeout:
                self.ambiguous_batch_count += 1
            else:
                self.accepted_batches += 1
                self.total_accepted_skus += len(result.accepted)
                self.rejected_item_count += len(result.rejected)

    def record_failed(self) -> None:
        with self._lock:
            self.failed_batch_count += 1

    def as_dict(self) -> dict[str, int]:
        return {
            "total_batches": self.total_batches,
            "accepted_batches": self.accepted_batches,
            "skipped_batches": self.skipped_batches,
            "rejected_item_count": self.rejected_item_count,
            "ambiguous_batch_count": self.ambiguous_batch_count,
            "failed_batch_count": self.failed_batch_count,
            "total_accepted_skus": self.total_accepted_skus,
        }


def _dispatch_batch(
    batch_record: BatchRecord,
    products: list[dict[str, Any]],
    wms_client: WarehouseApiClient,
    state: StateStore,
    summary: DispatchSummary,
) -> None:
    """Dispatch a single batch to the WMS and update the state ledger.

    This function is designed to run in a thread pool worker.

    Args:
        batch_record: Current state record for this batch.
        products: Transformed product dicts to send.
        wms_client: Shared WarehouseApiClient instance.
        state: Durable state store for checkpointing.
        summary: Thread-safe summary accumulator.
    """
    run_id = batch_record.run_id
    batch_id = batch_record.batch_id

    # Guard: skip batches already successfully processed in a previous run
    current = state.get_batch(run_id, batch_id)
    if current and current.status in (
        BatchStatus.ACCEPTED,
        BatchStatus.PARTIAL_ACCEPTED,
    ):
        logger.info(
            "Skipping already-accepted batch",
            extra={"run_id": run_id, "batch_id": batch_id, "status": current.status.value},
        )
        summary.record_skipped()
        return

    # Mark as IN_FLIGHT so a concurrent crash can be detected on resume
    batch_record.status = BatchStatus.IN_FLIGHT
    batch_record.attempt_count += 1
    state.update_batch(batch_record)

    try:
        result: BatchResult = wms_client.send_batch(products, batch_id=batch_id)
    except Exception as exc:
        logger.error(
            "Batch dispatch failed",
            extra={"run_id": run_id, "batch_id": batch_id, "error": str(exc)},
        )
        batch_record.status = BatchStatus.FAILED_RETRYABLE
        batch_record.error_message = str(exc)
        state.update_batch(batch_record)
        summary.record_failed()
        return

    # Handle ambiguous post-send timeout
    if result.ambiguous_timeout:
        logger.warning(
            "AMBIGUOUS_TIMEOUT: quarantining batch",
            extra={"run_id": run_id, "batch_id": batch_id},
        )
        batch_record.status = BatchStatus.AMBIGUOUS_TIMEOUT
        batch_record.error_message = result.error_message
        state.update_batch(batch_record)
        # Record each product in the batch as a dead-letter for review
        for product in products:
            state.add_dead_letter(DeadLetterRecord(
                run_id=run_id,
                batch_id=batch_id,
                sku=product.get("sku"),
                reason="AMBIGUOUS_TIMEOUT: WMS outcome unknown",
                original_payload=product,
            ))
        summary.record_result(result)
        return

    # Commit accepted SKUs and record rejections
    batch_record.accepted_skus = result.accepted
    batch_record.rejected_skus = result.rejected

    for rejected_item in result.rejected:
        state.add_dead_letter(DeadLetterRecord(
            run_id=run_id,
            batch_id=batch_id,
            sku=rejected_item.get("sku"),
            reason=rejected_item.get("reason", "Unknown"),
            original_payload=next(
                (p for p in products if p.get("sku") == rejected_item.get("sku")),
                {},
            ),
        ))

    if result.rejected:
        batch_record.status = BatchStatus.PARTIAL_ACCEPTED
        logger.info(
            "Batch partially accepted",
            extra={
                "run_id": run_id,
                "batch_id": batch_id,
                "accepted": len(result.accepted),
                "rejected": len(result.rejected),
            },
        )
    else:
        batch_record.status = BatchStatus.ACCEPTED
        logger.info(
            "Batch fully accepted",
            extra={
                "run_id": run_id,
                "batch_id": batch_id,
                "accepted": len(result.accepted),
            },
        )

    state.update_batch(batch_record)
    summary.record_result(result)


def dispatch_batches(
    run_id: str,
    batch_records: list[BatchRecord],
    batch_products: dict[str, list[dict[str, Any]]],
    state: StateStore,
    worker_count: int = config.WMS_WORKER_COUNT,
) -> DispatchSummary:
    """Dispatch all pending WMS batches using a concurrent worker pool.

    The worker pool shares a single WarehouseApiClient (and thus a single
    rate-limit token bucket) to enforce the global 17.5 req/s ceiling.

    Args:
        run_id: Synchronization run identifier.
        batch_records: List of BatchRecord objects registered in the ledger.
        batch_products: Mapping of batch_id -> list of WMS-formatted products.
        state: Durable state store for checkpointing.
        worker_count: Number of concurrent worker threads.

    Returns:
        DispatchSummary with aggregate statistics.
    """
    summary = DispatchSummary()
    summary.total_batches = len(batch_records)

    keys = get_api_keys()

    with WarehouseApiClient(
        base_url=config.WAREHOUSE_API_URL,
        api_key=keys.warehouse_api_key,
    ) as wms_client:
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="wms-worker") as pool:
            futures = {
                pool.submit(
                    _dispatch_batch,
                    batch_record,
                    batch_products[batch_record.batch_id],
                    wms_client,
                    state,
                    summary,
                ): batch_record.batch_id
                for batch_record in batch_records
                if batch_record.batch_id in batch_products
            }

            for future in as_completed(futures):
                batch_id = futures[future]
                exc = future.exception()
                if exc:
                    logger.error(
                        "Unhandled exception in worker for batch %s: %s",
                        batch_id,
                        exc,
                    )

    logger.info(
        "Dispatch complete",
        extra={"run_id": run_id, "summary": summary.as_dict()},
    )
    return summary
