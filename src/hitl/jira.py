"""Jira access behind a port."""

from __future__ import annotations

from collections.abc import Callable
from itertools import count
from typing import Protocol, runtime_checkable

from hitl.policy import Action


class JiraError(Exception):
    """Any failure performing a Jira action."""


@runtime_checkable
class JiraPort(Protocol):
    def execute(self, action: Action) -> str:
        """Perform the action. Returns a human-readable result string."""
        ...


class FakeJira:
    """In-memory Jira. Records calls so tests can assert nothing ran on deny."""

    def __init__(
        self,
        existing: dict[str, str] | None = None,
        fail_with: str | None = None,
    ) -> None:
        self.statuses: dict[str, str] = dict(existing or {})
        self.calls: list[Action] = []
        self._fail_with = fail_with
        self._counter = count(1)

    def execute(self, action: Action) -> str:
        self.calls.append(action)
        if self._fail_with:
            raise JiraError(self._fail_with)

        if action.kind == "create_issue":
            key = f"FAKE-{next(self._counter)}"
            self.statuses[key] = "To Do"
            return key

        if action.kind == "transition":
            if action.issue_key not in self.statuses:
                raise JiraError(f"unknown issue {action.issue_key}")
            self.statuses[action.issue_key] = action.target_status or ""
            return f"{action.issue_key} -> {action.target_status}"

        if action.kind == "add_comment":
            if action.issue_key not in self.statuses:
                raise JiraError(f"unknown issue {action.issue_key}")
            return f"commented on {action.issue_key}"

        raise JiraError(f"unsupported action kind: {action.kind}")


class RovoJira:
    """Live Jira via Atlassian Rovo MCP connector.

    Accepts tool callables for testing; at runtime, claudeai/code injects
    the actual MCP endpoints.
    """

    def __init__(
        self,
        cloud_id: str,
        project_key: str,
        *,
        create_issue: Callable | None = None,
        get_transitions: Callable | None = None,
        transition: Callable | None = None,
        add_comment: Callable | None = None,
    ) -> None:
        self.cloud_id = cloud_id
        self.project_key = project_key
        self._create_issue_tool = create_issue
        self._get_transitions_tool = get_transitions
        self._transition_tool = transition
        self._add_comment_tool = add_comment

    def execute(self, action: Action) -> str:
        try:
            if action.kind == "create_issue":
                return self._exec_create(action)
            if action.kind == "transition":
                return self._exec_transition(action)
            if action.kind == "add_comment":
                return self._exec_add_comment(action)
            raise JiraError(f"unsupported action kind: {action.kind}")
        except JiraError:
            raise
        except Exception as exc:
            raise JiraError(f"jira error: {exc}") from exc

    def _exec_create(self, action: Action) -> str:
        if not self._create_issue_tool:
            raise JiraError("create_issue tool not bound")
        result = self._create_issue_tool(
            cloudId=self.cloud_id,
            projectKey=self.project_key,
            issueTypeName="Task",
            summary=action.body,
        )
        if isinstance(result, dict) and "key" in result:
            return result["key"]
        return str(result)

    def _exec_transition(self, action: Action) -> str:
        if not self._get_transitions_tool or not self._transition_tool:
            raise JiraError("transition tools not bound")

        transitions = self._get_transitions_tool(
            cloudId=self.cloud_id, issueIdOrKey=action.issue_key
        )
        trans_dict = (
            transitions.get("transitions", [])
            if isinstance(transitions, dict)
            else []
        )

        trans_id = None
        for t in trans_dict:
            if t.get("to", {}).get("name") == action.target_status:
                trans_id = t.get("id")
                break

        if not trans_id:
            raise JiraError(
                f"no transition to {action.target_status!r} "
                f"from {action.issue_key}"
            )

        self._transition_tool(
            cloudId=self.cloud_id,
            issueIdOrKey=action.issue_key,
            transition={"id": trans_id},
        )
        return f"{action.issue_key} -> {action.target_status}"

    def _exec_add_comment(self, action: Action) -> str:
        if not self._add_comment_tool:
            raise JiraError("add_comment tool not bound")
        self._add_comment_tool(
            cloudId=self.cloud_id,
            issueIdOrKey=action.issue_key,
            commentBody=action.body,
        )
        return f"commented on {action.issue_key}"
