import pytest

from hitl.jira import FakeJira, JiraError, JiraPort
from hitl.policy import Action


def test_fake_satisfies_the_port():
    assert isinstance(FakeJira(), JiraPort)


def test_create_issue_returns_a_key_and_records_the_call():
    j = FakeJira()
    key = j.execute(Action(kind="create_issue", body="crash on save"))
    assert key.startswith("FAKE-")
    assert len(j.calls) == 1
    assert j.calls[0].kind == "create_issue"


def test_transition_returns_confirmation():
    j = FakeJira(existing={"P-1": "To Do"})
    out = j.execute(Action(kind="transition", issue_key="P-1", target_status="Done"))
    assert "P-1" in out and "Done" in out
    assert j.statuses["P-1"] == "Done"


def test_transition_unknown_issue_raises():
    j = FakeJira()
    with pytest.raises(JiraError, match="unknown issue"):
        j.execute(Action(kind="transition", issue_key="NOPE-9", target_status="Done"))


def test_unsupported_action_raises():
    with pytest.raises(JiraError, match="unsupported"):
        FakeJira().execute(Action(kind="launch_missiles"))


def test_fake_can_be_made_to_fail_for_error_path_tests():
    j = FakeJira(fail_with="rate limited")
    with pytest.raises(JiraError, match="rate limited"):
        j.execute(Action(kind="create_issue", body="x"))
