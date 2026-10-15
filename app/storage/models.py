"""
app/storage/models.py

Domain model dataclasses for the catalogue synchronization state ledger.
These models are backend-agnostic and used by both SQLiteStateStore
and DynamoDBStateStore.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class RunStatus(str, Enum):
    """Lifecycle states for a synchronization run."""
    INITIALIZING = "INITIALIZING"
    EXTRACTING = "EXTRACTING"
    STAGING = "STAGING"
    INGESTING = "INGESTING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_REJECTIONS = "COMPLETED_WITH_REJECTIONS"
    FAILED = "FAILED"


class BatchStatus(str, Enum):
    """Lifecycle states for an individual WMS batch."""
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    ACCEPTED = "ACCEPTED"
    PARTIAL_ACCEPTED = "PARTIAL_ACCEPTED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    AMBIGUOUS_TIMEOUT = "AMBIGUOUS_TIMEOUT"


@dataclass
class RunRecord:
    """Top-level record tracking a complete synchronization run."""
    run_id: str
    status: RunStatus = RunStatus.INITIALIZING
    total_products: int = 0
    total_batches: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    ambiguous_count: int = 0
    export_path: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_message: str = ""


@dataclass
class BatchRecord:
    """Record tracking the status of a single WMS batch within a run."""
    run_id: str
    batch_id: str
    status: BatchStatus = BatchStatus.PENDING
    attempt_count: int = 0
    batch_size: int = 0
    accepted_skus: list[str] = field(default_factory=list)
    rejected_skus: list[dict] = field(default_factory=list)   # [{sku, reason}]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: str = ""


@dataclass
class DeadLetterRecord:
    """Record for a permanently rejected or ambiguous product."""
    run_id: str
    batch_id: str
    sku: str | None
    reason: str
    original_payload: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
