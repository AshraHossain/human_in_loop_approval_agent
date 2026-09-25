"""Jira access behind a port."""

from __future__ import annotations

import time
from collections.abc import Callable
from itertools import count
from typing import Protocol, runtime_checkable

from hitl.policy import Action
from hitl.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    never_applied,
    retry,
    transient,
)


class JiraError(Exception):
    """Any failure performing a Jira action."""


class JiraUnavailableError(JiraError):
    """Jira was never reached, so nothing was applied.

    The distinction from a plain `JiraError` is the whole point: a failure
    means Jira considered the action and refused it, while this means the
    action never happened and resubmitting it is safe. An ambiguous failure --
    a timeout, a reset connection -- is deliberately NOT this, because the
    write may have landed.
    """


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
        breaker: CircuitBreaker | None = None,
        attempts: int = 3,
        backoff: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cloud_id = cloud_id
        self.project_key = project_key
        self._create_issue_tool = create_issue
        self._get_transitions_tool = get_transitions
        self._transition_tool = transition
        self._add_comment_tool = add_comment
        self._breaker = breaker
        self._attempts = attempts
        self._backoff = backoff
        self._sleep = sleep

    def _call(self, tool: Callable, *, retryable, label: str, **kwargs):
        return retry(
            lambda: tool(**kwargs),
            attempts=self._attempts,
            backoff=self._backoff,
            retryable=retryable,
            sleep=self._sleep,
            label=label,
        )

    def execute(self, action: Action) -> str:
        def run() -> str:
            return self._dispatch(action)

        try:
            return self._breaker.call(run) if self._breaker else run()
        except CircuitOpenError as exc:
            raise JiraUnavailableError(str(exc)) from exc
        except JiraError:
            raise
        except Exception as exc:
            # Only a failure that PROVES nothing was applied may be reported as
            # safe to resubmit. A timeout or a reset connection might have
            # landed, so it stays a plain JiraError and spends the approval --
            # a duplicate Jira write is worse than a re-approval.
            if never_applied(exc):
                raise JiraUnavailableError(
                    f"jira unreachable after {self._attempts} attempt(s): {exc}"
                ) from exc
            raise JiraError(f"jira error: {exc}") from exc

    def _dispatch(self, action: Action) -> str:
        if action.kind == "create_issue":
            return self._exec_create(action)
        if action.kind == "transition":
            return self._exec_transition(action)
        if action.kind == "add_comment":
            return self._exec_add_comment(action)
        raise JiraError(f"unsupported action kind: {action.kind}")

    def _exec_create(self, action: Action) -> str:
        if not self._create_issue_tool:
            raise JiraError("create_issue tool not bound")
        result = self._call(
            self._create_issue_tool,
            retryable=never_applied,
            label="create_issue",
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

        # A read: no side effect, so it may be retried on anything transient.
        transitions = self._call(
            self._get_transitions_tool,
            retryable=transient,
            label="get_transitions",
            cloudId=self.cloud_id,
            issueIdOrKey=action.issue_key,
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

        self._call(
            self._transition_tool,
            retryable=never_applied,
            label="transition",
            cloudId=self.cloud_id,
            issueIdOrKey=action.issue_key,
            transition={"id": trans_id},
        )
        return f"{action.issue_key} -> {action.target_status}"

    def _exec_add_comment(self, action: Action) -> str:
        if not self._add_comment_tool:
            raise JiraError("add_comment tool not bound")
        self._call(
            self._add_comment_tool,
            retryable=never_applied,
            label="add_comment",
            cloudId=self.cloud_id,
            issueIdOrKey=action.issue_key,
            commentBody=action.body,
        )
        return f"commented on {action.issue_key}"
