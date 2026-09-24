"""Integration tests: identity verification with approval workflow."""

from dataclasses import asdict

from hitl.graph import build_graph
from hitl.identity import ApprovalLevel, MockIdentityProvider
from hitl.jira import FakeJira
from hitl.policy import Action
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command


def test_identity_provider_integration():
    """Identity provider can be instantiated and used."""
    provider = MockIdentityProvider()
    provider.register("alice", ApprovalLevel.SENIOR)

    identity = provider.verify("alice")
    assert identity is not None
    assert identity.level == ApprovalLevel.SENIOR


def test_approval_gate_captures_human_id():
    """Human ID is captured and recorded in audit trail on approval."""
    jira = FakeJira(existing={"P-1": "To Do"})
    app = build_graph(jira, InMemorySaver())

    action = asdict(Action(kind="transition", issue_key="P-1", target_status="Done"))

    app.invoke(
        {"request": "move P-1 to Done", "request_id": "req-1", "action": action},
        {"configurable": {"thread_id": "req-1"}},
    )

    out = app.invoke(
        Command(resume={"decision": "approve", "human_id": "alice"}),
        {"configurable": {"thread_id": "req-1"}},
    )

    assert out["stage"] == "completed"
    final_audit = out["audits"][-1]
    assert final_audit["human_intervention"]["human_id"] == "alice"
    assert final_audit["human_intervention"]["human_decision"] == "approve"


def test_approval_gate_captures_human_id_on_denial():
    """Human ID is captured when action is denied."""
    jira = FakeJira(existing={"P-2": "To Do"})
    app = build_graph(jira, InMemorySaver())

    action = asdict(Action(kind="transition", issue_key="P-2", target_status="Done"))

    app.invoke(
        {"request": "move P-2 to Done", "request_id": "req-2", "action": action},
        {"configurable": {"thread_id": "req-2"}},
    )

    out = app.invoke(
        Command(resume={"decision": "deny", "human_id": "bob"}),
        {"configurable": {"thread_id": "req-2"}},
    )

    assert out["stage"] == "denied"
    final_audit = out["audits"][-1]
    assert final_audit["human_intervention"]["human_id"] == "bob"
    assert final_audit["final_decision"] == "denied"


def test_multiple_approval_levels_registered():
    """Multiple approval levels can coexist in system."""
    provider = MockIdentityProvider()
    provider.register("junior_user", ApprovalLevel.JUNIOR)
    provider.register("senior_user", ApprovalLevel.SENIOR)
    provider.register("lead_user", ApprovalLevel.LEAD)

    junior = provider.verify("junior_user")
    senior = provider.verify("senior_user")
    lead = provider.verify("lead_user")

    assert junior.level == ApprovalLevel.JUNIOR
    assert senior.level == ApprovalLevel.SENIOR
    assert lead.level == ApprovalLevel.LEAD
