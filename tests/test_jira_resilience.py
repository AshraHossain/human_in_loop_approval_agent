"""Resilience where it meets the only code that writes to a real Jira.

`test_resilience.py` covers the primitives. This covers the wiring, and in
particular the one thing that must never regress: an approved mutation that
fails ambiguously is attempted exactly once.
"""

import socket
from dataclasses import asdict

import pytest
from hitl.cli import main
from hitl.graph import build_graph
from hitl.jira import JiraError, JiraUnavailable, RovoJira
from hitl.policy import Action
from hitl.resilience import CircuitBreaker, CircuitOpen, TransientError
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

CLOUD, PROJECT = "cloud-1", "KAN"

CREATE = Action(kind="create_issue", body="crash on save")
COMMENT = Action(kind="add_comment", issue_key="KAN-1", body="deploy finished")
MOVE = Action(kind="transition", issue_key="KAN-1", target_status="Done")


class Flaky:
    """Fails the first `fail_times` calls, then succeeds."""

    def __init__(self, fail_times=0, raises=None, returns=None):
        self.calls = 0
        self._fail_times = fail_times
        self._raises = raises or ConnectionRefusedError("refused")
        self._returns = returns

    def __call__(self, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._raises
        return self._returns


def _transitions():
    return {"transitions": [{"id": "31", "to": {"name": "Done"}}]}


def _rovo(**tools):
    tools.setdefault("sleep", lambda _: None)
    return RovoJira(CLOUD, PROJECT, **tools)


# --- the invariant --------------------------------------------------------


@pytest.mark.parametrize("exc", [TimeoutError("timed out"), ConnectionResetError("reset")])
@pytest.mark.parametrize(
    "action,tool",
    [(CREATE, "create_issue"), (COMMENT, "add_comment")],
)
def test_an_ambiguous_mutation_failure_is_attempted_exactly_once(exc, action, tool):
    """The write may already have landed. A second attempt is a duplicate
    issue or a duplicate comment from one human approval."""
    flaky = Flaky(fail_times=99, raises=exc)

    with pytest.raises(JiraError):
        _rovo(**{tool: flaky}, attempts=5).execute(action)

    assert flaky.calls == 1


def test_an_ambiguous_transition_failure_is_attempted_exactly_once():
    move = Flaky(fail_times=99, raises=TimeoutError("timed out"))

    with pytest.raises(JiraError):
        _rovo(
            get_transitions=Flaky(returns=_transitions()), transition=move, attempts=5
        ).execute(MOVE)

    assert move.calls == 1


@pytest.mark.parametrize("exc", [TimeoutError("timed out"), ConnectionResetError("reset")])
def test_an_ambiguous_failure_is_not_reported_as_safe_to_resubmit(exc):
    """`JiraUnavailable` means "nothing was applied". A timeout cannot promise
    that, so it must stay an ordinary failure."""
    with pytest.raises(JiraError) as excinfo:
        _rovo(create_issue=Flaky(fail_times=99, raises=exc)).execute(CREATE)

    assert not isinstance(excinfo.value, JiraUnavailable)


# --- retries that ARE safe ------------------------------------------------


@pytest.mark.parametrize(
    "exc", [ConnectionRefusedError("refused"), socket.gaierror("no dns"), TransientError("429")]
)
def test_a_mutation_is_retried_when_the_failure_proves_it_never_landed(exc):
    create = Flaky(fail_times=2, raises=exc, returns={"key": "KAN-7"})
    assert _rovo(create_issue=create, attempts=3).execute(CREATE) == "KAN-7"
    assert create.calls == 3


def test_a_read_is_retried_even_on_an_ambiguous_failure():
    """`get_transitions` has no side effect, so repeating it is free."""
    get = Flaky(fail_times=2, raises=TimeoutError("slow"), returns=_transitions())
    move = Flaky()

    assert _rovo(get_transitions=get, transition=move, attempts=3).execute(MOVE)
    assert get.calls == 3
    assert move.calls == 1


def test_exhausting_retries_on_a_never_applied_failure_is_safe_to_resubmit():
    with pytest.raises(JiraUnavailable, match="jira unreachable after 3 attempt"):
        _rovo(create_issue=Flaky(fail_times=99), attempts=3).execute(CREATE)


def test_jira_unavailable_is_still_a_jira_error():
    """Existing `except JiraError` handlers must keep catching it."""
    with pytest.raises(JiraError):
        _rovo(create_issue=Flaky(fail_times=99), attempts=2).execute(CREATE)


def test_a_rejection_is_never_retried():
    create = Flaky(fail_times=99, raises=ValueError("summary is required"))
    with pytest.raises(JiraError, match="summary is required"):
        _rovo(create_issue=create, attempts=5).execute(CREATE)
    assert create.calls == 1


# --- the breaker in place -------------------------------------------------


def test_the_breaker_opens_and_then_refuses_to_call_jira():
    breaker = CircuitBreaker(threshold=2, recovery=30.0)
    create = Flaky(fail_times=99)
    jira = _rovo(create_issue=create, attempts=1, breaker=breaker)

    for _ in range(2):
        with pytest.raises(JiraUnavailable):
            jira.execute(CREATE)
    assert breaker.state == "open"

    calls_before = create.calls
    with pytest.raises(JiraUnavailable, match="circuit open"):
        jira.execute(CREATE)
    assert create.calls == calls_before, "an open circuit must not reach the backend"


def test_an_open_circuit_reports_as_safe_to_resubmit():
    """Nothing was attempted at all, so this one is unambiguous."""
    breaker = CircuitBreaker(threshold=1, recovery=30.0)
    jira = _rovo(create_issue=Flaky(fail_times=99), attempts=1, breaker=breaker)

    with pytest.raises(JiraUnavailable):
        jira.execute(CREATE)
    with pytest.raises(JiraUnavailable) as excinfo:
        jira.execute(CREATE)

    assert isinstance(excinfo.value.__cause__, CircuitOpen)


def test_jira_rejecting_an_action_does_not_open_the_breaker():
    breaker = CircuitBreaker(threshold=2, recovery=30.0)
    jira = _rovo(create_issue=Flaky(fail_times=99, raises=ValueError("bad")), breaker=breaker)

    for _ in range(5):
        with pytest.raises(JiraError):
            jira.execute(CREATE)

    assert breaker.state == "closed", "a workflow misconfiguration is not an outage"


def test_an_unsupported_action_does_not_open_the_breaker():
    breaker = CircuitBreaker(threshold=1, recovery=30.0)
    jira = _rovo(breaker=breaker)

    with pytest.raises(JiraError, match="unsupported action kind"):
        jira.execute(Action(kind="delete_everything"))
    assert breaker.state == "closed"


def test_a_success_after_recovery_closes_the_breaker():
    now = [0.0]
    breaker = CircuitBreaker(threshold=1, recovery=10.0, clock=lambda: now[0])
    create = Flaky(fail_times=1, returns={"key": "KAN-7"})
    jira = _rovo(create_issue=create, attempts=1, breaker=breaker)

    with pytest.raises(JiraUnavailable):
        jira.execute(CREATE)
    now[0] = 10.0

    assert jira.execute(CREATE) == "KAN-7"
    assert breaker.state == "closed"


def test_without_a_breaker_nothing_changes():
    assert _rovo(create_issue=Flaky(returns={"key": "KAN-7"})).execute(CREATE) == "KAN-7"


# --- the graph's deferred path --------------------------------------------


class Unavailable:
    """A JiraPort that is simply not there."""

    def __init__(self):
        self.calls = []

    def execute(self, action):
        self.calls.append(action)
        raise JiraUnavailable("jira unreachable after 3 attempt(s): refused")


def _approve(jira):
    app = build_graph(jira, InMemorySaver())
    cfg = {"configurable": {"thread_id": "req-1"}}
    app.invoke(
        {"request": "move P-1 to Done", "request_id": "req-1", "action": asdict(MOVE)},
        cfg,
    )
    return app.invoke(Command(resume={"decision": "approve", "human_id": "ash"}), cfg)


def test_an_unreachable_jira_defers_rather_than_failing():
    state = _approve(Unavailable())
    assert state["stage"] == "deferred"


def test_a_deferred_action_is_still_attempted_only_once():
    jira = Unavailable()
    _approve(jira)
    assert len(jira.calls) == 1, "no automatic retry of an approved action"


def test_the_deferred_audit_record_says_nothing_was_applied():
    final = _approve(Unavailable())["audits"][-1]

    assert final["final_decision"] == "deferred"
    assert final["actions_taken"] == []
    assert "nothing-applied" in final["policy_checks"]
    assert "jira unavailable" in final["risk_assessment"]


def test_the_retry_count_reaches_the_audit_trail():
    """The ticket asks for retry attempts to be visible to an auditor. They
    ride on the failure message rather than as extra chain records, which
    would bloat the hash chain with sub-stage noise."""
    final = _approve(Unavailable())["audits"][-1]
    assert "after 3 attempt(s)" in final["risk_assessment"]


def test_a_refusal_still_fails_rather_than_deferring():
    """Jira saying no is not an outage, and is NOT safe to resubmit blindly."""

    class Refusing:
        def execute(self, action):
            raise JiraError("no transition to 'Done'")

    state = _approve(Refusing())
    assert state["stage"] == "failed"
    assert state["audits"][-1]["final_decision"] == "failed"


# --- the CLI's exit code --------------------------------------------------


def test_the_cli_exits_four_when_jira_is_unavailable(tmp_path, capsys, monkeypatch):
    (tmp_path / "identities.json").write_text('{"ash": "lead"}')
    main(["--home", str(tmp_path), "submit", "transition P-1 to Done", "--seed", "P-1=To Do"])
    out = capsys.readouterr().out
    rid = next(ln.split()[-1] for ln in out.splitlines() if "request_id" in ln)

    monkeypatch.setattr("hitl.cli._jira", lambda seed: Unavailable())
    rc = main(["--home", str(tmp_path), "approve", rid, "--as", "ash"])

    assert rc == 4, "a distinct exit code so a script can tell outage from rejection"
    assert "safe to resubmit" in capsys.readouterr().out
