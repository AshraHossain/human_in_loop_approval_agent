"""The approval gate is only worth something if it rejects the wrong people.

`test_identity.py` covers the identity primitives in isolation. These tests
cover the thing that matters: an unverified or under-privileged approval must
not reach Jira, and the attempt must land in the audit trail.
"""

import json
from dataclasses import asdict

import pytest
from hitl.graph import build_graph, checkpointer_for
from hitl.identity import (
    ApprovalLevel,
    FileIdentityProvider,
    MockIdentityProvider,
    level_for_tier,
)
from hitl.jira import FakeJira
from hitl.policy import Action
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

HIGH = Action(kind="transition", issue_key="P-1", target_status="Done")
MEDIUM = Action(kind="create_issue", body="crash on save")
LOW_GATED = Action(kind="add_comment", issue_key="P-1", body="x")


def _cfg(rid="req-1"):
    return {"configurable": {"thread_id": rid}}


def _provider(**users):
    p = MockIdentityProvider()
    for user_id, level in users.items():
        p.register(user_id, level)
    return p


def _run(action, request, identities, decision="approve", human_id="ash", jira=None):
    """Submit to the gate, then resume with a decision. Returns (state, jira)."""
    jira = jira or FakeJira(existing={"P-1": "To Do"})
    app = build_graph(jira, InMemorySaver(), identities)
    out = app.invoke(
        {"request": request, "request_id": "req-1", "action": asdict(action)}, _cfg()
    )
    assert "__interrupt__" in out, "these fixtures must all reach the gate"
    state = app.invoke(
        Command(resume={"decision": decision, "human_id": human_id}), _cfg()
    )
    return state, jira


# --- the load-bearing rejections -----------------------------------------


def test_an_unknown_approver_cannot_execute_the_action():
    state, jira = _run(HIGH, "move P-1 to Done", _provider(sam=ApprovalLevel.LEAD))

    assert state["stage"] == "denied"
    assert jira.calls == [], "an unverified approval must reach no backend at all"
    assert jira.statuses["P-1"] == "To Do"
    assert "unknown user: ash" in state["refusal"]


def test_an_under_privileged_approver_cannot_execute_the_action():
    state, jira = _run(HIGH, "move P-1 to Done", _provider(ash=ApprovalLevel.JUNIOR))

    assert state["stage"] == "denied"
    assert jira.calls == []
    assert "cannot approve at LEAD" in state["refusal"]


def test_a_missing_human_id_is_rejected():
    state, jira = _run(
        HIGH, "move P-1 to Done", _provider(ash=ApprovalLevel.LEAD), human_id=None
    )
    assert state["stage"] == "denied"
    assert jira.calls == []


def test_an_empty_human_id_is_rejected():
    state, _ = _run(
        HIGH, "move P-1 to Done", _provider(ash=ApprovalLevel.LEAD), human_id=""
    )
    assert state["stage"] == "denied"


# --- and the approvals it must still let through --------------------------


def test_a_sufficiently_privileged_approver_executes_the_action():
    state, jira = _run(HIGH, "move P-1 to Done", _provider(ash=ApprovalLevel.LEAD))

    assert state["stage"] == "completed"
    assert state.get("refusal") is None
    assert jira.statuses["P-1"] == "Done"


def test_a_level_above_the_requirement_is_accepted():
    # LEAD approving a medium-tier action: the check is a floor, not equality.
    state, jira = _run(MEDIUM, "create a bug", _provider(ash=ApprovalLevel.LEAD))
    assert state["stage"] == "completed"
    assert len(jira.calls) == 1


@pytest.mark.parametrize(
    "action,request_text,level,expected",
    [
        (HIGH, "move P-1 to Done", ApprovalLevel.LEAD, "completed"),
        (HIGH, "move P-1 to Done", ApprovalLevel.SENIOR, "denied"),
        (MEDIUM, "create a bug", ApprovalLevel.SENIOR, "completed"),
        (MEDIUM, "create a bug", ApprovalLevel.JUNIOR, "denied"),
        (LOW_GATED, "maybe add a comment, unclear", ApprovalLevel.JUNIOR, "completed"),
    ],
)
def test_the_tier_boundary_is_exact(action, request_text, level, expected):
    """One rung below the tier's requirement is a rejection, every time."""
    state, _ = _run(action, request_text, _provider(ash=level))
    assert state["stage"] == expected


def test_a_low_tier_action_escalated_by_ambiguity_only_needs_junior():
    # Confidence escalated this to the gate, but the ACTION is still low risk --
    # demanding a LEAD for an ambiguous comment would train people to over-grant.
    state, jira = _run(
        LOW_GATED, "maybe add some kind of comment", _provider(ash=ApprovalLevel.JUNIOR)
    )
    assert state["stage"] == "completed"
    assert len(jira.calls) == 1


# --- denials --------------------------------------------------------------


def test_an_unknown_user_cannot_even_deny():
    """A denial is harmless, but an unattributable one corrupts the trail."""
    state, jira = _run(
        HIGH, "move P-1 to Done", _provider(sam=ApprovalLevel.LEAD), decision="deny"
    )
    assert state["stage"] == "denied"
    assert jira.calls == []
    assert "unknown user: ash" in state["refusal"]


def test_a_junior_may_deny_an_action_they_could_not_approve():
    # Level gates approval, not refusal: anyone identified may stop an action.
    state, _ = _run(
        HIGH, "move P-1 to Done", _provider(ash=ApprovalLevel.JUNIOR), decision="deny"
    )
    assert state["stage"] == "denied"
    assert state.get("refusal") is None
    assert state["audits"][-1]["policy_checks"] == ["human-denied"]


# --- what the trail has to say about it ----------------------------------


def test_a_rejected_approval_is_recorded_as_such():
    state, _ = _run(HIGH, "move P-1 to Done", _provider(ash=ApprovalLevel.JUNIOR))

    resumed = next(a for a in state["audits"] if a["stage"] == "resumed")
    assert resumed["policy_checks"] == ["identity-rejected"]
    assert "cannot approve at LEAD" in resumed["risk_assessment"]
    # The attempt is attributed even though it was refused.
    assert resumed["human_intervention"]["human_id"] == "ash"
    assert resumed["human_intervention"]["human_decision"] == "deny"


def test_a_rejected_approval_closes_the_request_as_denied():
    state, _ = _run(HIGH, "move P-1 to Done", _provider(ash=ApprovalLevel.JUNIOR))

    final = state["audits"][-1]
    assert final["final_decision"] == "denied"
    assert final["actions_taken"] == []
    assert "cannot approve at LEAD" in final["risk_assessment"]


def test_an_accepted_approval_records_no_refusal():
    state, _ = _run(HIGH, "move P-1 to Done", _provider(ash=ApprovalLevel.LEAD))
    resumed = next(a for a in state["audits"] if a["stage"] == "resumed")
    assert resumed["policy_checks"] == ["human-reviewed"]


# --- the tier is the one that gated the request ---------------------------


def test_the_tier_is_checkpointed_not_recomputed(tmp_path):
    """Submit and approve are different processes. The level demanded at
    approval must be the one the request was gated at, so a policy edit between
    the two cannot quietly lower the bar on an already-pending request."""
    db = tmp_path / "cp.sqlite"
    with checkpointer_for(db) as cp:
        app = build_graph(FakeJira(existing={"P-1": "To Do"}), cp)
        app.invoke(
            {"request": "move P-1 to Done", "request_id": "req-1", "action": asdict(HIGH)},
            _cfg(),
        )

    with checkpointer_for(db) as cp:
        assert build_graph(FakeJira(), cp).get_state(_cfg()).values["tier"] == "high"


def test_a_checkpoint_without_a_tier_demands_the_highest_level():
    """Fail closed on a checkpoint written before tiers were stored."""
    jira = FakeJira(existing={"P-1": "To Do"})
    app = build_graph(jira, InMemorySaver(), _provider(ash=ApprovalLevel.SENIOR))
    app.invoke(
        {
            "request": "move P-1 to Done",
            "request_id": "req-1",
            "action": asdict(HIGH),
            "tier": None,
        },
        _cfg(),
    )
    # assess overwrites tier, so force the pre-migration shape directly.
    app.update_state(_cfg(), {"tier": None})
    state = app.invoke(
        Command(resume={"decision": "approve", "human_id": "ash"}), _cfg()
    )
    assert state["stage"] == "denied"
    assert jira.calls == []


# --- the opt-out ----------------------------------------------------------


def test_omitting_a_provider_disables_verification():
    """Documented escape hatch for graph-mechanics tests. The CLI never uses it."""
    state, jira = _run(HIGH, "move P-1 to Done", None, human_id="nobody-at-all")
    assert state["stage"] == "completed"
    assert jira.statuses["P-1"] == "Done"


# --- level_for_tier -------------------------------------------------------


@pytest.mark.parametrize(
    "tier,level",
    [
        ("low", ApprovalLevel.JUNIOR),
        ("medium", ApprovalLevel.SENIOR),
        ("high", ApprovalLevel.LEAD),
    ],
)
def test_level_for_tier(tier, level):
    assert level_for_tier(tier) == level


@pytest.mark.parametrize("tier", ["", "critical", "LOW", None])
def test_an_unrecognised_tier_demands_a_lead(tier):
    assert level_for_tier(tier) == ApprovalLevel.LEAD


# --- FileIdentityProvider -------------------------------------------------


def _file(tmp_path, payload):
    path = tmp_path / "identities.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return FileIdentityProvider(path)


def test_a_missing_identities_file_verifies_nobody(tmp_path):
    assert FileIdentityProvider(tmp_path / "nope.json").verify("ash") is None


def test_an_empty_identities_file_verifies_nobody(tmp_path):
    assert _file(tmp_path, {}).verify("ash") is None


def test_a_known_user_gets_their_level(tmp_path):
    identity = _file(tmp_path, {"ash": "lead"}).verify("ash")
    assert identity.user_id == "ash"
    assert identity.level == ApprovalLevel.LEAD


def test_levels_are_read_case_insensitively(tmp_path):
    assert _file(tmp_path, {"ash": "SeNiOr"}).verify("ash").level == ApprovalLevel.SENIOR


def test_an_unlisted_user_is_not_an_identity(tmp_path):
    assert _file(tmp_path, {"sam": "lead"}).verify("ash") is None


@pytest.mark.parametrize("level", ["admin", "", "root", 3, None, ["lead"]])
def test_a_level_the_file_cannot_mean_is_not_an_identity(tmp_path, level):
    """Fail closed: a typo'd or hand-edited level grants nothing."""
    assert _file(tmp_path, {"ash": level}).verify("ash") is None


def test_the_file_is_reread_so_revocation_is_immediate(tmp_path):
    path = tmp_path / "identities.json"
    path.write_text(json.dumps({"ash": "lead"}), encoding="utf-8")
    provider = FileIdentityProvider(path)
    assert provider.verify("ash") is not None

    path.write_text(json.dumps({}), encoding="utf-8")
    assert provider.verify("ash") is None, "revocation must not wait for a restart"


def test_a_file_provider_drives_the_real_gate(tmp_path):
    state, jira = _run(HIGH, "move P-1 to Done", _file(tmp_path, {"ash": "junior"}))
    assert state["stage"] == "denied"
    assert jira.calls == []
