"""
app/core/logging.py

Structured JSON logging for the catalogue synchronization service.

All log records are emitted as single-line JSON objects with mandatory
correlation fields (timestamp, level, run_id, component).
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any


class StructuredJsonFormatter(logging.Formatter):
    """Logging formatter that emits records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
        }
        # Merge any extra fields attached to the log record
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with structured JSON output.

    Call once at application startup.

    Args:
        level: Log level string (e.g. 'DEBUG', 'INFO', 'WARNING').
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredJsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str, **context: Any) -> logging.Logger:
    """Return a logger that automatically injects `context` into every record.

    Args:
        name: Logger name (usually __name__).
        **context: Key-value pairs to attach to every log record.

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)
    if context:
        logger = logging.LoggerAdapter(logger, context)  # type: ignore[assignment]
    return logger
