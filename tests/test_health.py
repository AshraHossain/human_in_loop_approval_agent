"""Health checks and deferred shutdown.

The distinction under test throughout: `failing` means restarting this
process might help, `degraded` means it would not. Getting that backwards
turns a Jira outage into a crash loop.
"""

import json
import os
import signal
import sqlite3
import subprocess
import sys
import textwrap

import pytest

from hitl.config import Config
from hitl.health import (
    DEGRADED,
    FAILING,
    OK,
    Check,
    Report,
    check_health,
    defer_signals,
)
from hitl.jira import RovoJira
from hitl.resilience import CircuitBreaker


def _cfg(tmp_path, **kw):
    return Config(home=tmp_path, **kw)


def _named(report, name):
    return next(c for c in report.checks if c.name == name)


def _sqlite(path):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE checkpoints (id TEXT)")
    return path


# --- the report -----------------------------------------------------------


def test_an_empty_report_is_ok():
    assert Report().status == OK


def test_the_worst_check_decides_the_status():
    report = Report([Check("a", OK, ""), Check("b", DEGRADED, ""), Check("c", OK, "")])
    assert report.status == DEGRADED


def test_failing_beats_degraded():
    report = Report([Check("a", DEGRADED, ""), Check("b", FAILING, "")])
    assert report.status == FAILING


def test_degraded_is_still_ok_to_keep_running():
    """Restarting does not conjure approvers or revive Jira."""
    assert Report([Check("a", DEGRADED, "")]).ok is True


def test_failing_is_not_ok():
    assert Report([Check("a", FAILING, "")]).ok is False


def test_the_report_serialises():
    payload = json.loads(json.dumps(Report([Check("a", OK, "fine")]).to_dict()))
    assert payload == {
        "status": OK,
        "checks": [{"name": "a", "status": OK, "detail": "fine"}],
    }


# --- checkpoints ----------------------------------------------------------


def test_a_missing_checkpoint_file_is_fine(tmp_path):
    """A fresh install has not written one yet."""
    check = _named(check_health(_cfg(tmp_path)), "checkpoints")
    assert check.status == OK
    assert "not created yet" in check.detail


def test_a_readable_checkpoint_file_passes(tmp_path):
    _sqlite(tmp_path / "checkpoints.sqlite")
    assert _named(check_health(_cfg(tmp_path)), "checkpoints").status == OK


def test_a_corrupt_checkpoint_file_is_failing(tmp_path):
    """Restarting genuinely might help here, so this one is failing."""
    (tmp_path / "checkpoints.sqlite").write_bytes(b"not a database at all")
    check = _named(check_health(_cfg(tmp_path)), "checkpoints")
    assert check.status == FAILING
    assert "unreadable" in check.detail


def test_a_truncated_checkpoint_file_is_caught(tmp_path):
    path = _sqlite(tmp_path / "checkpoints.sqlite")
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 3])
    assert _named(check_health(_cfg(tmp_path)), "checkpoints").status == FAILING


# --- the audit directory --------------------------------------------------


def test_a_writable_audit_dir_passes(tmp_path):
    assert _named(check_health(_cfg(tmp_path)), "audit_dir").status == OK


def test_the_probe_file_does_not_linger(tmp_path):
    check_health(_cfg(tmp_path))
    assert list((tmp_path / "audit").iterdir()) == []


def test_an_unwritable_audit_dir_is_failing(tmp_path):
    audit = tmp_path / "audit"
    audit.mkdir()
    audit.chmod(0o500)
    try:
        check = _named(check_health(_cfg(tmp_path)), "audit_dir")
        assert check.status == FAILING
        assert "not writable" in check.detail
    finally:
        audit.chmod(0o700)


def test_a_file_where_the_audit_dir_should_be_is_failing(tmp_path):
    (tmp_path / "audit").write_text("not a directory")
    assert _named(check_health(_cfg(tmp_path)), "audit_dir").status == FAILING


# --- identities -----------------------------------------------------------


def test_no_identities_file_is_degraded(tmp_path):
    """Nothing is broken, but nothing can be approved either."""
    check = _named(check_health(_cfg(tmp_path)), "identities")
    assert check.status == DEGRADED
    assert "no approvers" in check.detail


def test_an_empty_identities_file_is_degraded(tmp_path):
    (tmp_path / "identities.json").write_text("{}")
    assert _named(check_health(_cfg(tmp_path)), "identities").status == DEGRADED


def test_registered_approvers_pass(tmp_path):
    (tmp_path / "identities.json").write_text('{"ash": "lead", "sam": "junior"}')
    check = _named(check_health(_cfg(tmp_path)), "identities")
    assert check.status == OK
    assert "2 approver(s)" in check.detail


def test_a_corrupt_identities_file_is_failing(tmp_path):
    """Worse than absent: absent fails closed cleanly, while a broken file
    means someone believes they configured approvers."""
    (tmp_path / "identities.json").write_text("{not json")
    assert _named(check_health(_cfg(tmp_path)), "identities").status == FAILING


def test_an_identities_file_of_the_wrong_shape_is_degraded(tmp_path):
    (tmp_path / "identities.json").write_text('["ash"]')
    assert _named(check_health(_cfg(tmp_path)), "identities").status == DEGRADED


# --- jira -----------------------------------------------------------------


def test_no_jira_bound_is_fine(tmp_path):
    assert _named(check_health(_cfg(tmp_path)), "jira").status == OK


def test_a_closed_circuit_passes(tmp_path):
    jira = RovoJira("c", "K", breaker=CircuitBreaker())
    check = _named(check_health(_cfg(tmp_path), jira), "jira")
    assert check.status == OK
    assert "closed" in check.detail


def test_an_open_circuit_is_degraded_not_failing(tmp_path):
    """Jira being down is not a reason to restart us."""
    breaker = CircuitBreaker(threshold=1)
    with pytest.raises(ConnectionRefusedError):
        breaker.call(lambda: (_ for _ in ()).throw(ConnectionRefusedError("refused")))

    check = _named(check_health(_cfg(tmp_path), RovoJira("c", "K", breaker=breaker)), "jira")
    assert check.status == DEGRADED
    assert "circuit open" in check.detail


def test_the_health_check_makes_no_network_call(tmp_path):
    """A probe that opens a connection every few seconds is a load generator
    wearing a stethoscope. The breaker already knows."""
    calls = []
    jira = RovoJira(
        "c", "K", breaker=CircuitBreaker(), create_issue=lambda **kw: calls.append(kw)
    )
    check_health(_cfg(tmp_path), jira)
    assert calls == []


# --- deep checks ----------------------------------------------------------


def test_the_cheap_checks_skip_the_chain(tmp_path):
    names = {c.name for c in check_health(_cfg(tmp_path)).checks}
    assert "audit_chain" not in names
    assert "pending_approvals" not in names


def test_deep_adds_the_chain_and_pending_counts(tmp_path):
    names = {c.name for c in check_health(_cfg(tmp_path), deep=True).checks}
    assert {"audit_chain", "pending_approvals"} <= names


def test_a_broken_chain_is_failing(tmp_path, capsys):
    from hitl.cli import main

    (tmp_path / "identities.json").write_text('{"ash": "lead"}')
    main(["--home", str(tmp_path), "submit", "transition P-1 to Done", "--seed", "P-1=To Do"])
    capsys.readouterr()

    trail = next((tmp_path / "audit").glob("*.jsonl"))
    records = [json.loads(ln) for ln in trail.read_text().strip().splitlines()]
    records[0]["risk_assessment"] = "tampered"
    trail.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    report = check_health(_cfg(tmp_path), deep=True)
    assert _named(report, "audit_chain").status == FAILING
    assert report.ok is False


def test_an_intact_chain_passes(tmp_path):
    assert _named(check_health(_cfg(tmp_path), deep=True), "audit_chain").status == OK


# --- stuck approvals ------------------------------------------------------


def _trail(tmp_path, *records):
    from hitl.audit import append_audit

    for record in records:
        append_audit(record, tmp_path / "audit")


def _record(request_id, stage, timestamp):
    return {
        "timestamp": timestamp,
        "request_id": request_id,
        "stage": stage,
        "input_summary": "x",
        "policy_checks": [],
        "confidence_level": "high",
        "risk_assessment": "x",
        "human_intervention": {},
        "final_decision": None,
        "actions_taken": [],
    }


NOW = "2999-01-01T00:00:00+00:00"
LONG_AGO = "2000-01-01T00:00:00+00:00"


def test_nothing_waiting_passes(tmp_path):
    check = _named(check_health(_cfg(tmp_path), deep=True), "pending_approvals")
    assert check.status == OK
    assert "none waiting" in check.detail


def test_a_recently_gated_request_is_counted_but_fine(tmp_path):
    _trail(tmp_path, _record("r1", "uncertain", NOW))
    check = _named(check_health(_cfg(tmp_path), deep=True), "pending_approvals")
    assert check.status == OK
    assert "1 waiting" in check.detail


def test_an_answered_request_is_not_pending(tmp_path):
    _trail(
        tmp_path,
        _record("r1", "uncertain", LONG_AGO),
        _record("r1", "resumed", LONG_AGO),
        _record("r1", "completed", LONG_AGO),
    )
    assert _named(check_health(_cfg(tmp_path), deep=True), "pending_approvals").status == OK


def test_an_old_unanswered_request_is_degraded(tmp_path):
    """The stuck approval this check exists for: a submit that paused and
    whose approver never came back."""
    _trail(tmp_path, _record("r1", "uncertain", LONG_AGO))
    check = _named(check_health(_cfg(tmp_path), deep=True), "pending_approvals")
    assert check.status == DEGRADED
    assert "over 24.0h" in check.detail


def test_the_staleness_threshold_is_configurable(tmp_path):
    _trail(tmp_path, _record("r1", "uncertain", LONG_AGO))
    report = check_health(_cfg(tmp_path), deep=True, stale_hours=10**9)
    assert _named(report, "pending_approvals").status == OK


def test_only_the_unanswered_ones_are_counted(tmp_path):
    _trail(
        tmp_path,
        _record("done", "uncertain", LONG_AGO),
        _record("done", "completed", LONG_AGO),
        _record("waiting", "uncertain", LONG_AGO),
    )
    assert "1 waiting" in _named(
        check_health(_cfg(tmp_path), deep=True), "pending_approvals"
    ).detail


# --- deferred shutdown ----------------------------------------------------


@pytest.fixture
def caught():
    """SIGUSR1 with a harmless prior handler.

    `defer_signals` re-sends the signal on the way out, and SIGUSR1's default
    action is to kill the process -- which in-process would take pytest with
    it. Installing a recorder first means the deferred delivery lands
    somewhere observable instead. That the real re-raise terminates is
    covered in a subprocess below.
    """
    received = []
    previous = signal.signal(signal.SIGUSR1, lambda *_: received.append(1))
    try:
        yield received
    finally:
        signal.signal(signal.SIGUSR1, previous)


def test_defer_signals_runs_the_block(caught):
    ran = []
    with defer_signals(signal.SIGUSR1):
        ran.append(True)
    assert ran == [True]
    assert caught == [], "no signal was sent, so none should be delivered"


def test_a_signal_during_the_block_does_not_interrupt_it(caught):
    completed = []
    with defer_signals(signal.SIGUSR1):
        os.kill(os.getpid(), signal.SIGUSR1)
        completed.append("critical section finished")

    assert completed == ["critical section finished"]
    assert caught == [1], "the signal is honoured once the block is done"


def test_handlers_are_restored_afterwards(caught):
    original = signal.getsignal(signal.SIGUSR1)
    with defer_signals(signal.SIGUSR1):
        pass
    assert signal.getsignal(signal.SIGUSR1) is original


def test_handlers_are_restored_even_when_the_block_raises(caught):
    original = signal.getsignal(signal.SIGUSR1)
    with pytest.raises(ValueError), defer_signals(signal.SIGUSR1):
        raise ValueError("boom")
    assert signal.getsignal(signal.SIGUSR1) is original


def test_a_raising_block_still_honours_the_signal(caught):
    with pytest.raises(ValueError), defer_signals(signal.SIGUSR1):
        os.kill(os.getpid(), signal.SIGUSR1)
        raise ValueError("boom")
    assert caught == [1], "a failed write must not also swallow the shutdown"


def test_off_the_main_thread_it_is_a_no_op():
    """Only the main thread may install handlers, and a worker should be no
    worse off than before."""
    import threading

    ran = []

    def work():
        with defer_signals(signal.SIGUSR1):
            ran.append(True)

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    assert ran == [True]


# --- the signal is actually honoured on the way out -----------------------

DEFERRED_SCRIPT = textwrap.dedent(
    """
    import os, signal, sys
    sys.path.insert(0, %r)
    from hitl.health import defer_signals

    with defer_signals(signal.SIGTERM):
        os.kill(os.getpid(), signal.SIGTERM)
        print("CRITICAL-SECTION-COMPLETED", flush=True)
    print("SHOULD-NOT-REACH-HERE", flush=True)
    """
)


def test_the_deferred_signal_terminates_the_process_afterwards():
    """The signal is honoured, not swallowed -- a process that ignores
    SIGTERM is a worse problem than the one this solves."""
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-c", DEFERRED_SCRIPT % os.path.join(project, "src")],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert "CRITICAL-SECTION-COMPLETED" in result.stdout
    assert "SHOULD-NOT-REACH-HERE" not in result.stdout
    assert result.returncode == -signal.SIGTERM
