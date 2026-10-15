"""
app/core/metrics.py

Dual-mode metrics emitter.

- APP_ENV=local  → logs metric summaries to stdout as structured JSON.
- APP_ENV=production → publishes custom CloudWatch metrics via boto3.

Metric names follow the convention: CatalogueSync/<MetricName>
"""
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

NAMESPACE = "CatalogueSync"


class MetricsClient:
    """Abstract metrics client interface."""

    def increment(self, name: str, value: float = 1.0, dimensions: dict[str, str] | None = None) -> None:
        raise NotImplementedError

    def gauge(self, name: str, value: float, dimensions: dict[str, str] | None = None) -> None:
        raise NotImplementedError

    def flush(self) -> None:
        """Flush any buffered metrics to the backend."""


class ConsoleMetricsClient(MetricsClient):
    """Logs metrics to stdout as structured JSON (for local development)."""

    def __init__(self, run_id: str = "") -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._run_id = run_id

    def increment(self, name: str, value: float = 1.0, dimensions: dict[str, str] | None = None) -> None:
        self._counters[name] += value

    def gauge(self, name: str, value: float, dimensions: dict[str, str] | None = None) -> None:
        self._gauges[name] = value

    def flush(self) -> None:
        summary: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "INFO",
            "component": "metrics",
            "message": "metrics_flush",
            "run_id": self._run_id,
            "counters": dict(self._counters),
            "gauges": self._gauges,
        }
        print(json.dumps(summary, default=str))


class CloudWatchMetricsClient(MetricsClient):
    """Publishes custom metrics to Amazon CloudWatch (for production)."""

    def __init__(self, run_id: str = "", region: str | None = None) -> None:
        import boto3  # type: ignore[import-untyped]
        self._cw = boto3.client("cloudwatch", region_name=region)
        self._run_id = run_id
        self._buffer: list[dict[str, Any]] = []

    def _datum(self, name: str, value: float, unit: str = "Count", dimensions: dict[str, str] | None = None) -> dict[str, Any]:
        dims = [{"Name": "RunId", "Value": self._run_id}]
        if dimensions:
            dims.extend({"Name": k, "Value": v} for k, v in dimensions.items())
        return {
            "MetricName": name,
            "Value": value,
            "Unit": unit,
            "Timestamp": datetime.now(timezone.utc).isoformat(),
            "Dimensions": dims,
        }

    def increment(self, name: str, value: float = 1.0, dimensions: dict[str, str] | None = None) -> None:
        self._buffer.append(self._datum(name, value, "Count", dimensions))
        if len(self._buffer) >= 20:  # CloudWatch max per call is 20 data points
            self.flush()

    def gauge(self, name: str, value: float, dimensions: dict[str, str] | None = None) -> None:
        self._buffer.append(self._datum(name, value, "None", dimensions))

    def flush(self) -> None:
        if not self._buffer:
            return
        try:
            self._cw.put_metric_data(Namespace=NAMESPACE, MetricData=self._buffer)
        except Exception as exc:
            logger.warning("Failed to publish CloudWatch metrics: %s", exc)
        finally:
            self._buffer.clear()


def build_metrics_client(run_id: str = "") -> MetricsClient:
    """Factory: returns Console or CloudWatch client based on APP_ENV.

    Args:
        run_id: Current synchronization run identifier.

    Returns:
        Appropriate MetricsClient implementation.
    """
    env = os.getenv("APP_ENV", "local").lower()
    if env == "production":
        region = os.getenv("AWS_REGION", "ap-south-1")
        return CloudWatchMetricsClient(run_id=run_id, region=region)
    return ConsoleMetricsClient(run_id=run_id)
