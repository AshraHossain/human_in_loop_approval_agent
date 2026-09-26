"""Health checks, and finishing what we started before shutting down.

Two severities, and the distinction is the whole design:

  * `failing` means this process is broken and restarting it might help --
    the checkpoint is corrupt, the audit directory is not writable.
  * `degraded` means the service is working correctly but cannot do useful
    work: Jira is down, or nobody is registered to approve anything.
    Restarting does not conjure approvers or revive Jira, so a probe that
    kills the process over it just adds an outage to an outage.

So `/health` answers 503 only for `failing`.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from hitl.audit import verify_chain
from hitl.logging import log_event

OK = "ok"
DEGRADED = "degraded"
FAILING = "failing"

_RANK = {OK: 0, DEGRADED: 1, FAILING: 2}

# Stages that close a request. Anything gated and not followed by one of
# these is still waiting on a human.
TERMINAL_STAGES = frozenset({"completed"})


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def status(self) -> str:
        return max(
            (c.status for c in self.checks), key=lambda s: _RANK[s], default=OK
        )

    @property
    def ok(self) -> bool:
        """False only when a restart might actually help."""
        return self.status != FAILING

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail}
                for c in self.checks
            ],
        }


def _check_checkpoints(path: Path) -> Check:
    if not path.exists():
        # A fresh install has not written one yet. That is not a fault.
        return Check("checkpoints", OK, "not created yet")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            # Reads the file header and the schema, so a truncated or
            # non-SQLite file fails here rather than at the first approval.
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as exc:
        return Check("checkpoints", FAILING, f"unreadable: {exc}")
    return Check("checkpoints", OK, str(path))


def _check_audit_dir(path: Path) -> Check:
    """Actually write, rather than asking the OS whether we could.

    `os.access` reports the permission bits, which is not the same question
    on a read-only mount, a full disk, or NFS.
    """
    probe = path / ".health-probe"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check("audit_dir", FAILING, f"not writable: {exc}")
    return Check("audit_dir", OK, str(path))


def _check_identities(path: Path) -> Check:
    if not path.exists():
        return Check("identities", DEGRADED, "no approvers registered")
    try:
        users = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # Unreadable is worse than absent: absent fails closed cleanly, while
        # a corrupt file means someone thinks they configured approvers.
        return Check("identities", FAILING, f"unreadable: {exc}")
    if not isinstance(users, dict) or not users:
        return Check("identities", DEGRADED, "no approvers registered")
    return Check("identities", OK, f"{len(users)} approver(s)")


def _check_jira(jira) -> Check:
    """Prefer the circuit breaker's opinion to a fresh network call.

    The breaker already knows whether Jira has been answering, and asking it
    costs nothing -- a health probe that opens its own connection every few
    seconds is a load generator wearing a stethoscope.
    """
    if jira is None:
        return Check("jira", OK, "not bound")

    breaker = getattr(jira, "_breaker", None)
    if breaker is not None and breaker.state == "open":
        return Check(
            "jira",
            DEGRADED,
            f"circuit open after {breaker.failures} consecutive failures",
        )
    if breaker is not None:
        return Check("jira", OK, f"circuit {breaker.state}")
    return Check("jira", OK, "reachable (no breaker configured)")


def _check_chain(audit_dir: Path) -> Check:
    problems = verify_chain(audit_dir)
    if problems:
        return Check(
            "audit_chain", FAILING, f"{len(problems)} problem(s): {problems[0]}"
        )
    return Check("audit_chain", OK, "intact")


def _check_pending(audit_dir: Path, stale_hours: float) -> Check:
    """Requests that reached the gate and never got an answer.

    This is the "stuck approval" the ticket is about: a submit that paused,
    whose approver never came back. Nothing is broken, but somebody is
    waiting, and no other signal would show it.
    """
    gated: dict[str, str] = {}
    closed: set[str] = set()
    if audit_dir.exists():
        for file in sorted(audit_dir.glob("*.jsonl")):
            for line in file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # _check_chain is the one that reports this
                request_id = record.get("request_id")
                if record.get("stage") == "uncertain":
                    gated[request_id] = record.get("timestamp", "")
                elif record.get("stage") in TERMINAL_STAGES:
                    closed.add(request_id)

    pending = {r: ts for r, ts in gated.items() if r not in closed}
    if not pending:
        return Check("pending_approvals", OK, "none waiting")

    oldest = min(pending.values())
    age_hours = _age_hours(oldest)
    detail = f"{len(pending)} waiting, oldest {age_hours:.1f}h"
    if age_hours >= stale_hours:
        return Check("pending_approvals", DEGRADED, f"{detail} (over {stale_hours}h)")
    return Check("pending_approvals", OK, detail)


def _age_hours(timestamp: str) -> float:
    try:
        then = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return 0.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return (datetime.now(UTC) - then).total_seconds() / 3600


def check_health(config, jira=None, *, deep: bool = False, stale_hours: float = 24.0) -> Report:
    """Run the checks. `deep` adds the ones that read the whole audit trail.

    The cheap set is what a liveness probe should call every few seconds; the
    deep set walks every record, which is fine for an operator or a nightly
    job and wasteful at probe frequency.
    """
    checks = [
        _check_checkpoints(config.checkpoint_db),
        _check_audit_dir(config.audit_dir),
        _check_identities(config.identities_path),
        _check_jira(jira),
    ]
    if deep:
        checks.append(_check_chain(config.audit_dir))
        checks.append(_check_pending(config.audit_dir, stale_hours))

    report = Report(checks)
    log_event("health_checked", status=report.status, deep=deep)
    return report


@contextmanager
def defer_signals(*signals_to_defer: int):
    """Let the block finish before honouring SIGTERM or SIGINT.

    A signal arriving between executing an approved action and writing its
    audit record would leave a Jira write with no trail -- the single outcome
    this whole system exists to prevent. So the handler notes the signal, the
    block runs to completion, and the signal is delivered on the way out.

    A second signal is not caught: an operator who sends SIGTERM twice means
    it, and refusing to die is worse than a missing audit line.
    """
    received: list[int] = []
    wanted = signals_to_defer or (signal.SIGTERM, signal.SIGINT)

    if threading.current_thread() is not threading.main_thread():
        # Only the main thread may install handlers. A worker is no worse off
        # than it was before, so do not make this an error.
        yield
        return

    def handler(signum, _frame):
        received.append(signum)
        log_event(
            "shutdown_deferred",
            signal=signum,
            reason="finishing the current write before exiting",
        )
        signal.signal(signum, previous[signum])

    previous = {sig: signal.getsignal(sig) for sig in wanted}
    for sig in wanted:
        signal.signal(sig, handler)

    try:
        yield
    finally:
        for sig, old in previous.items():
            if signal.getsignal(sig) is handler:
                signal.signal(sig, old)
        if received:
            log_event("shutdown_resuming", signal=received[0])
            os.kill(os.getpid(), received[0])
