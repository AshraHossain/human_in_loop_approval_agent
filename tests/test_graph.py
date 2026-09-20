from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from hitl.graph import build_graph, checkpointer_for
from hitl.jira import FakeJira
from hitl.policy import Action


def _cfg(rid="req-1"):
    return {"configurable": {"thread_id": rid}}


def test_low_risk_action_runs_without_pausing():
    jira = FakeJira(existing={"P-1": "To Do"})
    app = build_graph(jira, InMemorySaver())
    out = app.invoke(
        {
            "request": "comment on P-1 that deploy finished",
            "request_id": "req-1",
            "action": Action(kind="add_comment", issue_key="P-1", body="done"),
        },
        _cfg(),
    )
    assert "__interrupt__" not in out
    assert out["stage"] == "completed"
    assert len(jira.calls) == 1


def test_high_risk_action_pauses_at_the_gate():
    jira = FakeJira(existing={"P-1": "To Do"})
    app = build_graph(jira, InMemorySaver())
    out = app.invoke(
        {
            "request": "move P-1 to Done",
            "request_id": "req-1",
            "action": Action(kind="transition", issue_key="P-1", target_status="Done"),
        },
        _cfg(),
    )
    assert "__interrupt__" in out
    assert jira.calls == [], "nothing may execute before approval"


def test_denial_executes_nothing():
    jira = FakeJira(existing={"P-1": "To Do"})
    app = build_graph(jira, InMemorySaver())
    app.invoke(
        {
            "request": "move P-1 to Done",
            "request_id": "req-1",
            "action": Action(kind="transition", issue_key="P-1", target_status="Done"),
        },
        _cfg(),
    )
    out = app.invoke(Command(resume={"decision": "deny", "human_id": "ash"}), _cfg())
    assert out["stage"] == "denied"
    assert jira.calls == []
    assert out["audits"][-1]["actions_taken"] == []


def test_approval_executes_the_action():
    jira = FakeJira(existing={"P-1": "To Do"})
    app = build_graph(jira, InMemorySaver())
    app.invoke(
        {
            "request": "move P-1 to Done",
            "request_id": "req-1",
            "action": Action(kind="transition", issue_key="P-1", target_status="Done"),
        },
        _cfg(),
    )
    out = app.invoke(Command(resume={"decision": "approve", "human_id": "ash"}), _cfg())
    assert out["stage"] == "completed"
    assert jira.statuses["P-1"] == "Done"
    assert out["audits"][-1]["human_intervention"]["human_id"] == "ash"


def test_request_id_is_stable_across_every_stage():
    jira = FakeJira(existing={"P-1": "To Do"})
    app = build_graph(jira, InMemorySaver())
    app.invoke(
        {
            "request": "move P-1 to Done",
            "request_id": "req-1",
            "action": Action(kind="transition", issue_key="P-1", target_status="Done"),
        },
        _cfg(),
    )
    out = app.invoke(Command(resume={"decision": "approve", "human_id": "ash"}), _cfg())
    ids = {a["request_id"] for a in out["audits"]}
    assert ids == {"req-1"}, f"trail must correlate, got {ids}"


def test_execution_failure_does_not_retry():
    jira = FakeJira(existing={"P-1": "To Do"}, fail_with="rate limited")
    app = build_graph(jira, InMemorySaver())
    app.invoke(
        {
            "request": "move P-1 to Done",
            "request_id": "req-1",
            "action": Action(kind="transition", issue_key="P-1", target_status="Done"),
        },
        _cfg(),
    )
    out = app.invoke(Command(resume={"decision": "approve", "human_id": "ash"}), _cfg())
    assert out["stage"] == "failed"
    assert len(jira.calls) == 1, "an approved action must not be retried automatically"


def test_interrupt_survives_a_new_checkpointer_instance(tmp_path: Path):
    """Simulates process death: a fresh SqliteSaver over the same file resumes."""
    db = tmp_path / "cp.sqlite"
    action = Action(kind="transition", issue_key="P-1", target_status="Done")

    jira_a = FakeJira(existing={"P-1": "To Do"})
    with checkpointer_for(db) as cp:
        app = build_graph(jira_a, cp)
        out = app.invoke(
            {"request": "move P-1 to Done", "request_id": "req-1", "action": action},
            _cfg(),
        )
        assert "__interrupt__" in out

    # Entirely new objects -- new saver, new graph, new fake.
    jira_b = FakeJira(existing={"P-1": "To Do"})
    with checkpointer_for(db) as cp:
        app = build_graph(jira_b, cp)
        out = app.invoke(
            Command(resume={"decision": "approve", "human_id": "ash"}), _cfg()
        )

    assert out["stage"] == "completed"
    assert jira_b.statuses["P-1"] == "Done"
