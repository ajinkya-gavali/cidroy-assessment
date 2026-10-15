"""
app/storage/state.py

Dual-mode durable state ledger for tracking synchronization run and batch progress.

- APP_ENV=local (or STATE_BACKEND=sqlite): Uses SQLiteStateStore backed by
  ./runtime/state.db
- APP_ENV=production (or STATE_BACKEND=dynamodb): Uses DynamoDBStateStore
  backed by CatalogueSyncRuns and CatalogueSyncBatches tables.

Both implementations expose the same interface so the application code is
entirely backend-agnostic.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.storage.models import (
    BatchRecord,
    BatchStatus,
    DeadLetterRecord,
    RunRecord,
    RunStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class StateStore(ABC):
    """Abstract state ledger interface."""

    @abstractmethod
    def create_run(self, run: RunRecord) -> None:
        """Persist a new run record."""

    @abstractmethod
    def update_run(self, run: RunRecord) -> None:
        """Update an existing run record."""

    @abstractmethod
    def get_run(self, run_id: str) -> RunRecord | None:
        """Retrieve a run record by ID, or None if not found."""

    @abstractmethod
    def create_batch(self, batch: BatchRecord) -> None:
        """Persist a new batch record."""

    @abstractmethod
    def update_batch(self, batch: BatchRecord) -> None:
        """Update an existing batch record."""

    @abstractmethod
    def get_batch(self, run_id: str, batch_id: str) -> BatchRecord | None:
        """Retrieve a batch record, or None if not found."""

    @abstractmethod
    def list_batches(self, run_id: str, status: BatchStatus | None = None) -> list[BatchRecord]:
        """List all batches for a run, optionally filtered by status."""

    @abstractmethod
    def add_dead_letter(self, record: DeadLetterRecord) -> None:
        """Persist a dead-letter record for a rejected or ambiguous item."""

    @abstractmethod
    def list_dead_letters(self, run_id: str) -> list[DeadLetterRecord]:
        """List all dead-letter records for a run."""

    def close(self) -> None:
        """Close any resources held by the state store."""


# ---------------------------------------------------------------------------
# SQLite implementation (local mode)
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    total_products  INTEGER DEFAULT 0,
    total_batches   INTEGER DEFAULT 0,
    accepted_count  INTEGER DEFAULT 0,
    rejected_count  INTEGER DEFAULT 0,
    ambiguous_count INTEGER DEFAULT 0,
    export_path     TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    completed_at    TEXT,
    error_message   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS batches (
    run_id          TEXT NOT NULL,
    batch_id        TEXT NOT NULL,
    status          TEXT NOT NULL,
    attempt_count   INTEGER DEFAULT 0,
    batch_size      INTEGER DEFAULT 0,
    accepted_skus   TEXT DEFAULT '[]',
    rejected_skus   TEXT DEFAULT '[]',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    error_message   TEXT DEFAULT '',
    PRIMARY KEY (run_id, batch_id)
);

CREATE TABLE IF NOT EXISTS dead_letters (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL,
    batch_id          TEXT NOT NULL,
    sku               TEXT,
    reason            TEXT NOT NULL,
    original_payload  TEXT DEFAULT '{}',
    created_at        TEXT NOT NULL
);
"""


class SQLiteStateStore(StateStore):
    """State store backed by a local SQLite database.

    Connections are opened and closed per transaction with foreign keys enabled,
    ensuring zero connection leaks on Windows or Linux.

    Args:
        db_path: Filesystem path to the SQLite database file.
    """

    def __init__(self, db_path: str | Path = "./runtime/state.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Context manager yielding a SQLite connection that is reliably closed on exit."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:  # Commits on clean exit, rolls back on exception
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)

    def close(self) -> None:
        """Close state store resources."""
        pass

    def __enter__(self) -> SQLiteStateStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # --- Run operations ---

    def create_run(self, run: RunRecord) -> None:
        sql = """
            INSERT INTO runs (run_id, status, total_products, total_batches,
                accepted_count, rejected_count, ambiguous_count, export_path,
                created_at, updated_at, completed_at, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            conn.execute(sql, (
                run.run_id, run.status.value, run.total_products, run.total_batches,
                run.accepted_count, run.rejected_count, run.ambiguous_count,
                run.export_path, run.created_at.isoformat(),
                run.updated_at.isoformat(),
                run.completed_at.isoformat() if run.completed_at else None,
                run.error_message,
            ))

    def update_run(self, run: RunRecord) -> None:
        run.updated_at = datetime.now(timezone.utc)
        sql = """
            UPDATE runs SET status=?, total_products=?, total_batches=?,
                accepted_count=?, rejected_count=?, ambiguous_count=?,
                export_path=?, updated_at=?, completed_at=?, error_message=?
            WHERE run_id=?
        """
        with self._connect() as conn:
            conn.execute(sql, (
                run.status.value, run.total_products, run.total_batches,
                run.accepted_count, run.rejected_count, run.ambiguous_count,
                run.export_path, run.updated_at.isoformat(),
                run.completed_at.isoformat() if run.completed_at else None,
                run.error_message, run.run_id,
            ))

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        return RunRecord(
            run_id=row["run_id"],
            status=RunStatus(row["status"]),
            total_products=row["total_products"],
            total_batches=row["total_batches"],
            accepted_count=row["accepted_count"],
            rejected_count=row["rejected_count"],
            ambiguous_count=row["ambiguous_count"],
            export_path=row["export_path"] or "",
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            error_message=row["error_message"] or "",
        )

    # --- Batch operations ---

    def create_batch(self, batch: BatchRecord) -> None:
        sql = """
            INSERT INTO batches (run_id, batch_id, status, attempt_count, batch_size,
                accepted_skus, rejected_skus, created_at, updated_at, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            conn.execute(sql, (
                batch.run_id, batch.batch_id, batch.status.value,
                batch.attempt_count, batch.batch_size,
                json.dumps(batch.accepted_skus), json.dumps(batch.rejected_skus),
                batch.created_at.isoformat(), batch.updated_at.isoformat(),
                batch.error_message,
            ))

    def update_batch(self, batch: BatchRecord) -> None:
        batch.updated_at = datetime.now(timezone.utc)
        sql = """
            UPDATE batches SET status=?, attempt_count=?, batch_size=?,
                accepted_skus=?, rejected_skus=?, updated_at=?, error_message=?
            WHERE run_id=? AND batch_id=?
        """
        with self._connect() as conn:
            conn.execute(sql, (
                batch.status.value, batch.attempt_count, batch.batch_size,
                json.dumps(batch.accepted_skus), json.dumps(batch.rejected_skus),
                batch.updated_at.isoformat(), batch.error_message,
                batch.run_id, batch.batch_id,
            ))

    def get_batch(self, run_id: str, batch_id: str) -> BatchRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM batches WHERE run_id=? AND batch_id=?",
                (run_id, batch_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_batch(row)

    def list_batches(self, run_id: str, status: BatchStatus | None = None) -> list[BatchRecord]:
        with self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM batches WHERE run_id=? ORDER BY batch_id",
                    (run_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM batches WHERE run_id=? AND status=? ORDER BY batch_id",
                    (run_id, status.value),
                ).fetchall()
        return [self._row_to_batch(row) for row in rows]

    @staticmethod
    def _row_to_batch(row: sqlite3.Row) -> BatchRecord:
        return BatchRecord(
            run_id=row["run_id"],
            batch_id=row["batch_id"],
            status=BatchStatus(row["status"]),
            attempt_count=row["attempt_count"],
            batch_size=row["batch_size"],
            accepted_skus=json.loads(row["accepted_skus"]),
            rejected_skus=json.loads(row["rejected_skus"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            error_message=row["error_message"] or "",
        )

    # --- Dead-letter operations ---

    def add_dead_letter(self, record: DeadLetterRecord) -> None:
        sql = """
            INSERT INTO dead_letters (run_id, batch_id, sku, reason, original_payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            conn.execute(sql, (
                record.run_id, record.batch_id, record.sku, record.reason,
                json.dumps(record.original_payload, default=str),
                record.created_at.isoformat(),
            ))

    def list_dead_letters(self, run_id: str) -> list[DeadLetterRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM dead_letters WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        return [
            DeadLetterRecord(
                run_id=row["run_id"],
                batch_id=row["batch_id"],
                sku=row["sku"],
                reason=row["reason"],
                original_payload=json.loads(row["original_payload"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]


# ---------------------------------------------------------------------------
# DynamoDB implementation (production mode)
# ---------------------------------------------------------------------------

class DynamoDBStateStore(StateStore):
    """State store backed by Amazon DynamoDB.

    Tables:
    - CatalogueSyncRuns    PK: run_id
    - CatalogueSyncBatches PK: run_id, SK: batch_id
    - CatalogueSyncDLQ     PK: run_id, SK: sku#timestamp

    Args:
        runs_table: DynamoDB table name for run records.
        batches_table: DynamoDB table name for batch records.
        dlq_table: DynamoDB table name for dead-letter records.
        region: AWS region name.
    """

    def __init__(
        self,
        runs_table: str = "CatalogueSyncRuns",
        batches_table: str = "CatalogueSyncBatches",
        dlq_table: str = "CatalogueSyncDLQ",
        region: str | None = None,
    ) -> None:
        import boto3  # type: ignore[import-untyped]
        dynamodb = boto3.resource("dynamodb", region_name=region)
        self._runs = dynamodb.Table(runs_table)
        self._batches = dynamodb.Table(batches_table)
        self._dlq = dynamodb.Table(dlq_table)

    def create_run(self, run: RunRecord) -> None:
        self._runs.put_item(Item=self._run_to_item(run))

    def update_run(self, run: RunRecord) -> None:
        run.updated_at = datetime.now(timezone.utc)
        self._runs.put_item(Item=self._run_to_item(run))

    def get_run(self, run_id: str) -> RunRecord | None:
        resp = self._runs.get_item(Key={"run_id": run_id})
        item = resp.get("Item")
        if item is None:
            return None
        return self._item_to_run(item)

    def create_batch(self, batch: BatchRecord) -> None:
        self._batches.put_item(Item=self._batch_to_item(batch))

    def update_batch(self, batch: BatchRecord) -> None:
        batch.updated_at = datetime.now(timezone.utc)
        self._batches.put_item(Item=self._batch_to_item(batch))

    def get_batch(self, run_id: str, batch_id: str) -> BatchRecord | None:
        resp = self._batches.get_item(Key={"run_id": run_id, "batch_id": batch_id})
        item = resp.get("Item")
        if item is None:
            return None
        return self._item_to_batch(item)

    def list_batches(self, run_id: str, status: BatchStatus | None = None) -> list[BatchRecord]:
        from boto3.dynamodb.conditions import Key, Attr  # type: ignore[import-untyped]
        kwargs: dict = {"KeyConditionExpression": Key("run_id").eq(run_id)}
        if status is not None:
            kwargs["FilterExpression"] = Attr("status").eq(status.value)
        resp = self._batches.query(**kwargs)
        return [self._item_to_batch(item) for item in resp.get("Items", [])]

    def add_dead_letter(self, record: DeadLetterRecord) -> None:
        self._dlq.put_item(Item={
            "run_id": record.run_id,
            "sk": f"{record.sku or 'NONE'}#{record.created_at.isoformat()}",
            "batch_id": record.batch_id,
            "sku": record.sku,
            "reason": record.reason,
            "original_payload": json.dumps(record.original_payload, default=str),
            "created_at": record.created_at.isoformat(),
        })

    def list_dead_letters(self, run_id: str) -> list[DeadLetterRecord]:
        from boto3.dynamodb.conditions import Key  # type: ignore[import-untyped]
        resp = self._dlq.query(KeyConditionExpression=Key("run_id").eq(run_id))
        return [
            DeadLetterRecord(
                run_id=item["run_id"],
                batch_id=item["batch_id"],
                sku=item.get("sku"),
                reason=item["reason"],
                original_payload=json.loads(item.get("original_payload", "{}")),
                created_at=datetime.fromisoformat(item["created_at"]),
            )
            for item in resp.get("Items", [])
        ]

    # --- Serialization helpers ---

    @staticmethod
    def _run_to_item(run: RunRecord) -> dict:
        return {
            "run_id": run.run_id,
            "status": run.status.value,
            "total_products": run.total_products,
            "total_batches": run.total_batches,
            "accepted_count": run.accepted_count,
            "rejected_count": run.rejected_count,
            "ambiguous_count": run.ambiguous_count,
            "export_path": run.export_path,
            "created_at": run.created_at.isoformat(),
            "updated_at": run.updated_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "error_message": run.error_message,
        }

    @staticmethod
    def _item_to_run(item: dict) -> RunRecord:
        return RunRecord(
            run_id=item["run_id"],
            status=RunStatus(item["status"]),
            total_products=int(item.get("total_products", 0)),
            total_batches=int(item.get("total_batches", 0)),
            accepted_count=int(item.get("accepted_count", 0)),
            rejected_count=int(item.get("rejected_count", 0)),
            ambiguous_count=int(item.get("ambiguous_count", 0)),
            export_path=item.get("export_path", ""),
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
            completed_at=datetime.fromisoformat(item["completed_at"]) if item.get("completed_at") else None,
            error_message=item.get("error_message", ""),
        )

    @staticmethod
    def _batch_to_item(batch: BatchRecord) -> dict:
        return {
            "run_id": batch.run_id,
            "batch_id": batch.batch_id,
            "status": batch.status.value,
            "attempt_count": batch.attempt_count,
            "batch_size": batch.batch_size,
            "accepted_skus": json.dumps(batch.accepted_skus),
            "rejected_skus": json.dumps(batch.rejected_skus),
            "created_at": batch.created_at.isoformat(),
            "updated_at": batch.updated_at.isoformat(),
            "error_message": batch.error_message,
        }

    @staticmethod
    def _item_to_batch(item: dict) -> BatchRecord:
        return BatchRecord(
            run_id=item["run_id"],
            batch_id=item["batch_id"],
            status=BatchStatus(item["status"]),
            attempt_count=int(item.get("attempt_count", 0)),
            batch_size=int(item.get("batch_size", 0)),
            accepted_skus=json.loads(item.get("accepted_skus", "[]")),
            rejected_skus=json.loads(item.get("rejected_skus", "[]")),
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
            error_message=item.get("error_message", ""),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_state_store(
    db_path: str = "./runtime/state.db",
    runs_table: str = "CatalogueSyncRuns",
    batches_table: str = "CatalogueSyncBatches",
    dlq_table: str = "CatalogueSyncDLQ",
) -> StateStore:
    """Factory: returns SQLite or DynamoDB state store based on APP_ENV.

    Args:
        db_path: SQLite file path (local mode only).
        runs_table: DynamoDB table name for runs (production only).
        batches_table: DynamoDB table name for batches (production only).
        dlq_table: DynamoDB table name for dead-letters (production only).

    Returns:
        Appropriate StateStore implementation.
    """
    env = os.getenv("APP_ENV", "local").lower()
    backend = os.getenv("STATE_BACKEND", "").lower()

    if env == "production" or backend == "dynamodb":
        region = os.getenv("AWS_REGION", "ap-south-1")
        return DynamoDBStateStore(
            runs_table=runs_table,
            batches_table=batches_table,
            dlq_table=dlq_table,
            region=region,
        )
    return SQLiteStateStore(db_path=db_path)
