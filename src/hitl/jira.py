"""Jira access behind a port.

The live Atlassian connector currently reports zero accessible sites, so
`RovoJira` is not bound yet (Task 7). Everything else in this project is
written and tested against `JiraPort`, so binding the real API later touches
one class.
"""

from __future__ import annotations

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
