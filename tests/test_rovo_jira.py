"""RovoJira is the only code here that writes to a real Jira.

Its tools are injected, so every path can be exercised without a network. The
error paths matter most: a failure that escapes as something other than
JiraError would bypass the graph's no-retry handling.
"""

import pytest
from hitl.jira import JiraError, JiraPort, RovoJira
from hitl.policy import Action

CLOUD = "cloud-1"
PROJECT = "KAN"


class Spy:
    """Records the kwargs it was called with; optionally returns or raises."""

    def __init__(self, returns=None, raises=None):
        self.calls: list[dict] = []
        self._returns = returns
        self._raises = raises

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises
        return self._returns


def _rovo(**tools):
    return RovoJira(CLOUD, PROJECT, **tools)


def _transitions(*names_to_ids):
    return {
        "transitions": [
            {"id": tid, "to": {"name": name}} for name, tid in names_to_ids
        ]
    }


def test_rovo_satisfies_the_port():
    assert isinstance(_rovo(), JiraPort)


# --- create_issue ---------------------------------------------------------


def test_create_issue_passes_cloud_and_project():
    create = Spy(returns={"key": "KAN-7"})
    _rovo(create_issue=create).execute(Action(kind="create_issue", body="crash on save"))

    assert create.calls == [
        {
            "cloudId": CLOUD,
            "projectKey": PROJECT,
            "issueTypeName": "Task",
            "summary": "crash on save",
        }
    ]


def test_create_issue_returns_the_new_key():
    create = Spy(returns={"key": "KAN-7"})
    result = _rovo(create_issue=create).execute(Action(kind="create_issue", body="x"))
    assert result == "KAN-7"


def test_create_issue_falls_back_to_str_for_an_unexpected_shape():
    create = Spy(returns="KAN-9")
    assert _rovo(create_issue=create).execute(Action(kind="create_issue", body="x")) == "KAN-9"


def test_create_issue_without_a_bound_tool_raises():
    with pytest.raises(JiraError, match="create_issue tool not bound"):
        _rovo().execute(Action(kind="create_issue", body="x"))


# --- transition -----------------------------------------------------------


def test_transition_looks_up_transitions_for_the_issue():
    get = Spy(returns=_transitions(("Done", "31")))
    _rovo(get_transitions=get, transition=Spy()).execute(
        Action(kind="transition", issue_key="KAN-1", target_status="Done")
    )
    assert get.calls == [{"cloudId": CLOUD, "issueIdOrKey": "KAN-1"}]


def test_transition_sends_the_id_matching_the_target_status():
    get = Spy(returns=_transitions(("In Progress", "21"), ("Done", "31")))
    move = Spy()

    _rovo(get_transitions=get, transition=move).execute(
        Action(kind="transition", issue_key="KAN-1", target_status="Done")
    )

    assert move.calls == [
        {"cloudId": CLOUD, "issueIdOrKey": "KAN-1", "transition": {"id": "31"}}
    ]


def test_transition_confirms_the_move():
    result = _rovo(
        get_transitions=Spy(returns=_transitions(("Done", "31"))), transition=Spy()
    ).execute(Action(kind="transition", issue_key="KAN-1", target_status="Done"))
    assert result == "KAN-1 -> Done"


def test_transition_to_an_unavailable_status_raises_and_sends_nothing():
    # The workflow may simply not allow this move; guessing an id would be worse
    # than failing, because the approved action would land somewhere else.
    move = Spy()
    with pytest.raises(JiraError, match="no transition to 'Done'"):
        _rovo(
            get_transitions=Spy(returns=_transitions(("In Progress", "21"))),
            transition=move,
        ).execute(Action(kind="transition", issue_key="KAN-1", target_status="Done"))

    assert move.calls == []


def test_transition_handles_an_empty_transition_list():
    with pytest.raises(JiraError, match="no transition"):
        _rovo(
            get_transitions=Spy(returns={"transitions": []}), transition=Spy()
        ).execute(Action(kind="transition", issue_key="KAN-1", target_status="Done"))


def test_transition_handles_a_non_dict_response():
    with pytest.raises(JiraError, match="no transition"):
        _rovo(get_transitions=Spy(returns="nonsense"), transition=Spy()).execute(
            Action(kind="transition", issue_key="KAN-1", target_status="Done")
        )


def test_transition_handles_a_response_without_transitions():
    with pytest.raises(JiraError, match="no transition"):
        _rovo(get_transitions=Spy(returns={}), transition=Spy()).execute(
            Action(kind="transition", issue_key="KAN-1", target_status="Done")
        )


def test_transition_status_match_is_exact():
    with pytest.raises(JiraError, match="no transition"):
        _rovo(
            get_transitions=Spy(returns=_transitions(("done", "31"))), transition=Spy()
        ).execute(Action(kind="transition", issue_key="KAN-1", target_status="Done"))


def test_transition_without_bound_tools_raises():
    with pytest.raises(JiraError, match="transition tools not bound"):
        _rovo().execute(
            Action(kind="transition", issue_key="KAN-1", target_status="Done")
        )


def test_transition_needs_both_tools():
    with pytest.raises(JiraError, match="transition tools not bound"):
        _rovo(get_transitions=Spy(returns=_transitions(("Done", "31")))).execute(
            Action(kind="transition", issue_key="KAN-1", target_status="Done")
        )


# --- add_comment ----------------------------------------------------------


def test_add_comment_passes_the_body():
    comment = Spy()
    _rovo(add_comment=comment).execute(
        Action(kind="add_comment", issue_key="KAN-1", body="deploy finished")
    )
    assert comment.calls == [
        {"cloudId": CLOUD, "issueIdOrKey": "KAN-1", "commentBody": "deploy finished"}
    ]


def test_add_comment_confirms():
    result = _rovo(add_comment=Spy()).execute(
        Action(kind="add_comment", issue_key="KAN-1", body="x")
    )
    assert result == "commented on KAN-1"


def test_add_comment_without_a_bound_tool_raises():
    with pytest.raises(JiraError, match="add_comment tool not bound"):
        _rovo().execute(Action(kind="add_comment", issue_key="KAN-1", body="x"))


# --- the error boundary ---------------------------------------------------


def test_unsupported_action_kind_raises():
    with pytest.raises(JiraError, match="unsupported action kind: delete"):
        _rovo().execute(Action(kind="delete", issue_key="KAN-1"))


def test_arbitrary_tool_failures_become_jira_errors():
    # Anything escaping as a non-JiraError would bypass the graph's failure
    # path and be treated as a crash rather than a failed action.
    rovo = _rovo(create_issue=Spy(raises=RuntimeError("connection reset")))

    with pytest.raises(JiraError, match="jira error: connection reset"):
        rovo.execute(Action(kind="create_issue", body="x"))


def test_transition_lookup_failures_become_jira_errors():
    rovo = _rovo(
        get_transitions=Spy(raises=TimeoutError("timed out")), transition=Spy()
    )
    with pytest.raises(JiraError, match="jira error: timed out"):
        rovo.execute(Action(kind="transition", issue_key="KAN-1", target_status="Done"))


def test_jira_errors_are_not_double_wrapped():
    rovo = _rovo(add_comment=Spy(raises=JiraError("issue is archived")))

    with pytest.raises(JiraError) as excinfo:
        rovo.execute(Action(kind="add_comment", issue_key="KAN-1", body="x"))

    assert str(excinfo.value) == "issue is archived"


def test_a_failed_transition_call_surfaces_as_a_jira_error():
    rovo = _rovo(
        get_transitions=Spy(returns=_transitions(("Done", "31"))),
        transition=Spy(raises=RuntimeError("403 forbidden")),
    )
    with pytest.raises(JiraError, match="403 forbidden"):
        rovo.execute(Action(kind="transition", issue_key="KAN-1", target_status="Done"))
