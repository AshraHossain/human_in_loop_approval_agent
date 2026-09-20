import pytest

from hitl.policy import Action, decide, estimate_confidence, risk_tier


@pytest.mark.parametrize(
    "action,expected",
    [
        (Action(kind="transition", issue_key="P-1", target_status="Done"), "high"),
        (Action(kind="transition", issue_key="P-1", target_status="Closed"), "high"),
        (Action(kind="transition", issue_key="P-1", target_status="In Progress"), "low"),
        (Action(kind="create_issue", body="new bug"), "medium"),
        (Action(kind="add_comment", issue_key="P-1", body="hi"), "low"),
    ],
)
def test_risk_tier(action, expected):
    assert risk_tier(action) == expected


def test_terminal_status_is_case_insensitive():
    assert risk_tier(Action(kind="transition", target_status="done")) == "high"


def test_unknown_action_is_high_by_default():
    # Fail closed: an action we don't recognise must not sail through.
    assert risk_tier(Action(kind="delete_everything")) == "high"


def test_confidence_low_on_ambiguous_request():
    assert estimate_confidence("maybe close it, not sure") == "low"


def test_confidence_high_on_direct_request():
    assert estimate_confidence("move PROJ-12 to In Progress") == "high"


# --- the invariant (spec section 6) ---


def test_high_confidence_cannot_clear_a_policy_gate():
    """THE load-bearing test. Confidence may escalate to a gate, never clear one."""
    action = Action(kind="transition", issue_key="P-1", target_status="Done")
    d = decide(action, "move PROJ-1 to Done")
    assert d.confidence == "high"
    assert d.tier == "high"
    assert d.gate is True, "high confidence must NOT bypass a high-tier gate"


def test_low_confidence_escalates_a_low_tier_action():
    action = Action(kind="add_comment", issue_key="P-1", body="x")
    d = decide(action, "maybe add some kind of comment, unclear")
    assert d.tier == "low"
    assert d.confidence == "low"
    assert d.gate is True, "low confidence must escalate even a low tier"


def test_low_tier_and_high_confidence_runs_automatically():
    action = Action(kind="add_comment", issue_key="P-1", body="deploy done")
    d = decide(action, "comment on PROJ-1 that deploy finished")
    assert d.gate is False


def test_decision_carries_policy_checks():
    d = decide(Action(kind="create_issue", body="x"), "create a bug for the crash")
    assert any("tier:" in c for c in d.checks)
    assert any("confidence:" in c for c in d.checks)
