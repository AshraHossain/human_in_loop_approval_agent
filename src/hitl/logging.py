"""Structured JSON logging with metrics."""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class Metrics:
    """Approval metrics."""
    approvals_total: int = 0
    denials_total: int = 0
    approvals_seconds: float = 0.0
    jira_latency_seconds: float = 0.0
    errors_total: int = 0


class JSONFormatter(logging.Formatter):
    """JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_fields"):
            log_obj.update(record.extra_fields)
        # default=str: a logger that raises on an odd value takes down the call
        # site it was only meant to describe.
        return json.dumps(log_obj, ensure_ascii=False, default=str)


def setup_logging(name: str | None = None, level: str = "INFO") -> logging.Logger:
    """Configure JSON logging.

    Safe to call again: the handler is added once, but the level is applied
    every time, so a later call with a different level takes effect instead
    of being silently ignored.
    """
    logger = logging.getLogger(name or __name__)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger


metrics = Metrics()
logger = setup_logging("hitl")


def log_event(
    event: str,
    level: str = "info",
    **fields: Any,
) -> None:
    """Log structured event."""
    record = logger.makeRecord(
        logger.name, getattr(logging, level.upper()),
        "(unknown file)", 0, event, (), None,
    )
    record.extra_fields = fields
    logger.handle(record)


@contextmanager
def measure_approval_time():
    """Measure and record approval latency."""
    start = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start
        metrics.approvals_seconds += elapsed
        log_event("approval_completed", latency_seconds=elapsed)


@contextmanager
def measure_jira_latency():
    """Measure and record Jira API latency."""
    start = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start
        metrics.jira_latency_seconds += elapsed
        log_event("jira_api_call", latency_seconds=elapsed)


def record_approval(approved: bool) -> None:
    """Record approval or denial."""
    if approved:
        metrics.approvals_total += 1
        log_event("approval_recorded", status="approved")
    else:
        metrics.denials_total += 1
        log_event("approval_recorded", status="denied")


def record_error(msg: str) -> None:
    """Record error."""
    metrics.errors_total += 1
    log_event(msg, level="error")


def get_metrics() -> dict[str, Any]:
    """Get current metrics snapshot."""
    avg_approval_time = (
        metrics.approvals_seconds / metrics.approvals_total
        if metrics.approvals_total > 0 else 0
    )
    avg_jira_latency = (
        metrics.jira_latency_seconds / max(1, metrics.approvals_total + metrics.denials_total)
    )
    return {
        "approvals_total": metrics.approvals_total,
        "denials_total": metrics.denials_total,
        "avg_approval_time_seconds": avg_approval_time,
        "avg_jira_latency_seconds": avg_jira_latency,
        "errors_total": metrics.errors_total,
    }
