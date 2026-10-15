"""
app/main.py

Application entry point for the catalogue synchronization service.

Supports both CLI arguments and direct programmatic execution:
  python -m app.main                        -> Run a new synchronization
  python -m app.main --resume-run-id=<id>   -> Resume an existing run
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

from app import config
from app.core.logging import configure_logging

from app.core.coordinator import run_sync

from app.storage.models import RunStatus

def run(resume_run_id: str | None = None) -> dict[str, Any]:
    """Execute the synchronization run and return summary dict.

    Provided for backward compatibility and programmatic invocation.
    """

    record = run_sync(run_id=resume_run_id)
    return {
        "run_id": record.run_id,
        "status": record.status.value,
        "total_products": record.total_products,
        "total_batches": record.total_batches,
        "accepted_count": record.accepted_count,
        "rejected_count": record.rejected_count,
        "ambiguous_count": record.ambiguous_count,
        "export_path": record.export_path,
        "error_message": record.error_message,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code (0=success, 1=failure)."""

    parser = argparse.ArgumentParser(
        description="PIM -> WMS Product Catalogue Synchronization",
    )
    parser.add_argument(
        "--resume-run-id",
        default=None,
        help="Resume an existing run by its run_id (skips completed batches)",
    )
    args = parser.parse_args(argv)

    result = run(resume_run_id=args.resume_run_id)

    status = result["status"]
    if status in (RunStatus.COMPLETED.value, RunStatus.COMPLETED_WITH_REJECTIONS.value):
        print(
            f"Run {result['run_id']} completed with status {status}. "
            f"Accepted: {result['accepted_count']}, Rejected: {result['rejected_count']}, "
            f"Ambiguous: {result['ambiguous_count']}"
        )
        return 0
    else:
        print(
            f"Run {result['run_id']} failed with status {status}. "
            f"Error: {result['error_message']}"
        )
        return 1


if __name__ == "__main__":
    configure_logging(level=config.LOG_LEVEL)
    sys.exit(main())
