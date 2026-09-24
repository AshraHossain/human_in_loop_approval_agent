import io
import json
import logging
import sys
import time
from contextlib import contextmanager
from datetime import datetime

from hitl.logging import (
    JSONFormatter,
    get_metrics,
    log_event,
    measure_approval_time,
    measure_jira_latency,
    metrics,
    record_approval,
    record_error,
    setup_logging,
)


def _record(message="test message", level=logging.INFO, **extra):
    record = logging.LogRecord(
        "hitl.test", level, "(file)", 0, message, (), None
    )
    if extra:
        record.extra_fields = extra
    return record


def test_json_formatter_emits_parseable_json():
    out = json.loads(JSONFormatter().format(_record()))

    assert out["message"] == "test message"
    assert out["level"] == "INFO"
    assert out["logger"] == "hitl.test"
    assert datetime.fromisoformat(out["timestamp"]).tzinfo is not None


def test_json_formatter_merges_extra_fields():
    out = json.loads(
        JSONFormatter().format(_record(status="active", count=42))
    )

    assert out["status"] == "active"
    assert out["count"] == 42
    assert out["message"] == "test message"


def test_json_formatter_includes_the_traceback_on_exceptions():
    try:
        raise ValueError("kaboom")
    except ValueError:
        record = _record("failed", level=logging.ERROR)
        record.exc_info = sys.exc_info()

    out = json.loads(JSONFormatter().format(record))
    assert "ValueError: kaboom" in out["exception"]


def test_json_formatter_survives_a_non_serializable_field():
    out = JSONFormatter().format(_record(obj=object()))
    assert json.loads(out)["message"] == "test message"


@contextmanager
def captured_logs():
    """Collect what the hitl logger emits, as parsed JSON.

    The module's own handler binds sys.stdout at import time, so neither capsys
    nor capfd can see it from inside a test. Attaching our own handler tests
    the thing that matters -- the JSON log_event produces -- without depending
    on which stream it happens to be pointed at.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    log = logging.getLogger("hitl")
    log.addHandler(handler)
    try:
        yield lambda: [
            json.loads(ln) for ln in stream.getvalue().strip().splitlines() if ln
        ]
    finally:
        log.removeHandler(handler)


def test_log_event_reaches_the_handler():
    with captured_logs() as records:
        log_event("test_event", status="active", count=42)

    out = records()[-1]
    assert out["message"] == "test_event"
    assert out["status"] == "active"
    assert out["count"] == 42


def test_log_event_honours_the_level():
    with captured_logs() as records:
        log_event("bad_thing", level="error", detail="x")

    assert records()[-1]["level"] == "ERROR"


def test_log_event_defaults_to_info():
    with captured_logs() as records:
        log_event("something_happened")

    assert records()[-1]["level"] == "INFO"


def test_record_approval_logs_the_outcome():
    with captured_logs() as records:
        record_approval(approved=True)
        record_approval(approved=False)

    statuses = [r["status"] for r in records() if r["message"] == "approval_recorded"]
    assert statuses == ["approved", "denied"]


def test_approval_metrics_increment():
    initial_total = metrics.approvals_total
    record_approval(approved=True)
    assert metrics.approvals_total == initial_total + 1


def test_denial_metrics_increment():
    initial_total = metrics.denials_total
    record_approval(approved=False)
    assert metrics.denials_total == initial_total + 1


def test_error_metrics_increment():
    initial_total = metrics.errors_total
    record_error("test error")
    assert metrics.errors_total == initial_total + 1


def test_measure_approval_time_records_latency():
    initial_time = metrics.approvals_seconds
    with measure_approval_time():
        time.sleep(0.001)
    assert metrics.approvals_seconds > initial_time


def test_measure_jira_latency_records_latency():
    initial_time = metrics.jira_latency_seconds
    with measure_jira_latency():
        time.sleep(0.001)
    assert metrics.jira_latency_seconds > initial_time


def test_get_metrics_calculates_averages():
    # Reset metrics for clean test
    metrics.approvals_total = 10
    metrics.approvals_seconds = 5.0
    metrics.denials_total = 2
    metrics.jira_latency_seconds = 0.1
    metrics.errors_total = 1

    stats = get_metrics()

    assert stats["approvals_total"] == 10
    assert stats["denials_total"] == 2
    assert stats["errors_total"] == 1
    assert abs(stats["avg_approval_time_seconds"] - 0.5) < 0.01  # 5s / 10
    assert stats["avg_jira_latency_seconds"] < 0.02  # 0.1 / 12


def test_get_metrics_handles_zero_approvals():
    metrics.approvals_total = 0
    metrics.approvals_seconds = 0.0
    metrics.denials_total = 0
    metrics.jira_latency_seconds = 0.0
    metrics.errors_total = 0

    stats = get_metrics()

    assert stats["avg_approval_time_seconds"] == 0
    assert stats["avg_jira_latency_seconds"] == 0


def test_setup_logging_idempotent():
    logger1 = setup_logging("test_idempotent")
    handlers_before = len(logger1.handlers)
    logger2 = setup_logging("test_idempotent")
    handlers_after = len(logger2.handlers)
    assert handlers_before == handlers_after


def test_nested_timing_contexts():
    initial_approval = metrics.approvals_seconds
    initial_jira = metrics.jira_latency_seconds

    with measure_approval_time(), measure_jira_latency():
        time.sleep(0.001)

    assert metrics.approvals_seconds > initial_approval
    assert metrics.jira_latency_seconds > initial_jira
