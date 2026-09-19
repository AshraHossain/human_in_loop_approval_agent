# HITL Approval Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one LangGraph agent that gates Jira writes behind a durable, auditable human approval step that survives process death.

**Architecture:** A `StateGraph` assesses each request against a deterministic policy tier, and calls `interrupt()` when approval is required — the process then exits with state persisted to a SQLite checkpointer. A separate CLI command resumes the graph from that checkpoint in a fresh process via `Command(resume=...)`. All Jira access goes through a `JiraPort` protocol so the entire graph is testable with no network.

**Tech Stack:** Python 3.11, LangGraph 1.2.11, `langgraph-checkpoint-sqlite` 3.1.1, pytest, uv, ruff.

**Spec:** `docs/superpowers/specs/2026-09-18-hitl-approval-agent-design.md`

## Global Constraints

- `requires-python = ">=3.11"` (root cockpit Python is 3.11).
- Dependencies: `langgraph>=1.2`, `langgraph-checkpoint-sqlite>=3.1`. No LLM dependency is required by this plan — confidence scoring is rule-based (spec §6). Do not add `langchain-openai`.
- **Verified API (do not substitute from memory):**
  - `from langgraph.types import interrupt, Command`
  - `from langgraph.checkpoint.sqlite import SqliteSaver`
  - `SqliteSaver.from_conn_string(path)` **is a context manager** — use `with ... as cp:`. It is not a plain constructor.
  - A paused invoke returns a dict containing the key `__interrupt__`.
- Timestamps: `datetime.now(timezone.utc)`. **Never** `datetime.utcnow()` (spec §7).
- `request_id` is minted **once** at submit and threaded through every stage. **Never** regenerate it inside `make_audit` (spec §7).
- The root `config/ruff.toml` excludes `projects/`, so this project configures its own ruff. Any module that prints needs `[tool.ruff.lint.per-file-ignores]` with `["T20"]`.
- Audit JSON schema is fixed — exactly these keys:
  `timestamp, request_id, stage, input_summary, policy_checks, confidence_level, risk_assessment, human_intervention{required, reason, human_decision, human_id}, final_decision, actions_taken`
- Baseline restore point already exists: commit `0e2ea7b`, pushed to `github.com/AshraHossain/human_in_loop_approval_agent`. Spec §3.1's "commit first" prerequisite is **already satisfied**; do not redo it.

---

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` (root, new) | Project metadata, deps, `[tool.pytest.ini_options]` to opt into `make test-all`, ruff per-file-ignores |
| `src/hitl/audit.py` | The single `make_audit` + append-only JSONL writer |
| `src/hitl/policy.py` | Risk tiering, confidence, and the pause decision (owns the §6 invariant) |
| `src/hitl/jira.py` | `JiraPort` protocol, `FakeJira`, `RovoJira` |
| `src/hitl/graph.py` | `State` TypedDict, nodes, `StateGraph`, checkpointer wiring |
| `src/hitl/cli.py` | `submit` / `pending` / `approve` / `deny` / `audit` commands |
| `tests/` | One test module per source module |
| `archive/` | Retired `agent_executor_version/`, `runnable_pipeline_version/` |

---

## Task 1: Restructure the repository

**Files:**
- Create: `pyproject.toml`, `src/hitl/__init__.py`, `tests/__init__.py`
- Move: `human_in_loop_approval_agent/agent_executor_version/` → `archive/agent_executor_version/`
- Move: `human_in_loop_approval_agent/runnable_pipeline_version/` → `archive/runnable_pipeline_version/`
- Move: `human_in_loop_approval_agent/diagrams/` → `diagrams/`
- Modify: `human_in_loop_approval_agent/README.md` → move to `README.md`, update run commands

**Interfaces:**
- Consumes: nothing.
- Produces: the `src/hitl/` package root that every later task imports as `hitl.*`; a working `pytest` invocation.

- [ ] **Step 1: Move the retired variants and diagrams**

```bash
cd projects/human_in_loop_approval_agent
mkdir -p archive src/hitl tests
git mv human_in_loop_approval_agent/agent_executor_version archive/agent_executor_version
git mv human_in_loop_approval_agent/runnable_pipeline_version archive/runnable_pipeline_version
git mv human_in_loop_approval_agent/diagrams diagrams
git mv human_in_loop_approval_agent/README.md README.md
git mv human_in_loop_approval_agent/langgraph_version/state.py src/hitl/_old_state.py
rmdir human_in_loop_approval_agent/langgraph_version 2>/dev/null || true
```

Note: `langgraph_version/graph.py` and `audit.py` are **replaced**, not moved — Tasks 2 and 5 write their successors from scratch. Delete them:

```bash
git rm -q human_in_loop_approval_agent/langgraph_version/graph.py human_in_loop_approval_agent/langgraph_version/audit.py 2>/dev/null || true
git rm -q src/hitl/_old_state.py
rm -rf human_in_loop_approval_agent
```

- [ ] **Step 2: Write the root `pyproject.toml`**

```toml
[project]
name = "hitl-approval-agent"
version = "0.1.0"
description = "Human-in-the-loop approval agent gating Jira writes behind a durable approval step"
requires-python = ">=3.11"

dependencies = [
    "langgraph>=1.2",
    "langgraph-checkpoint-sqlite>=3.1",
]

[dependency-groups]
dev = [
    "pytest",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/hitl"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff.lint.per-file-ignores]
"src/hitl/cli.py" = ["T20"]
```

- [ ] **Step 3: Create the package markers**

```bash
touch src/hitl/__init__.py tests/__init__.py
```

- [ ] **Step 4: Verify the toolchain works**

Run: `uv sync && uv run pytest -q`
Expected: `no tests ran` — exit code 5. This confirms pytest resolves `testpaths` and `pythonpath` without error.

- [ ] **Step 5: Update README run commands**

Replace the "Running it" section of `README.md` with:

````markdown
## Running it

```bash
uv sync
uv run pytest -q                      # test suite
uv run python -m hitl.cli --help      # CLI
```

Retired variants live in `archive/` and are no longer maintained.
````

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: flatten to src/ layout, archive retired variants"
```

---

## Task 2: Audit records

**Files:**
- Create: `src/hitl/audit.py`
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `new_request_id() -> str`
  - `make_audit(*, request_id: str, stage: str, input_summary: str, policy_checks: list[str], confidence_level: str, risk_assessment: str, human_required: bool, human_reason: str | None = None, human_decision: str | None = None, human_id: str | None = None, final_decision: str | None = None, actions_taken: list[str] | None = None) -> dict`
  - `append_audit(record: dict, audit_dir: Path) -> Path`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_audit.py
import json
from datetime import datetime
from pathlib import Path

from hitl.audit import append_audit, make_audit, new_request_id

SCHEMA_KEYS = {
    "timestamp", "request_id", "stage", "input_summary", "policy_checks",
    "confidence_level", "risk_assessment", "human_intervention",
    "final_decision", "actions_taken",
}


def _rec(**kw):
    base = dict(
        request_id="req-1", stage="analysis", input_summary="do a thing",
        policy_checks=["tier:low"], confidence_level="high",
        risk_assessment="none", human_required=False,
    )
    base.update(kw)
    return make_audit(**base)


def test_schema_keys_exact():
    assert set(_rec()) == SCHEMA_KEYS


def test_timestamp_is_timezone_aware_utc():
    ts = datetime.fromisoformat(_rec()["timestamp"])
    assert ts.tzinfo is not None, "audit timestamps must be tz-aware"
    assert ts.utcoffset().total_seconds() == 0


def test_request_id_is_never_regenerated():
    # The whole point: two stages of one request share an ID.
    a = _rec(stage="analysis")
    b = _rec(stage="completed")
    assert a["request_id"] == b["request_id"] == "req-1"


def test_new_request_id_is_unique():
    assert new_request_id() != new_request_id()


def test_human_intervention_block_shape():
    r = _rec(human_required=True, human_reason="high tier",
             human_decision="approve", human_id="ash")
    assert r["human_intervention"] == {
        "required": True, "reason": "high tier",
        "human_decision": "approve", "human_id": "ash",
    }


def test_append_audit_is_append_only_jsonl(tmp_path: Path):
    p1 = append_audit(_rec(stage="analysis"), tmp_path)
    p2 = append_audit(_rec(stage="completed"), tmp_path)
    assert p1 == p2, "same day -> same file"
    lines = p1.read_text().strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(x)["stage"] for x in lines] == ["analysis", "completed"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hitl.audit'`

- [ ] **Step 3: Write the implementation**

```python
# src/hitl/audit.py
"""Audit records for the HITL approval agent.

One schema, one writer. `request_id` is minted once per request by the caller
and threaded through every stage -- regenerating it per record is what made the
earlier implementations' trails impossible to correlate.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def new_request_id() -> str:
    """Mint a request ID. Call this exactly once per request, at submit."""
    return str(uuid.uuid4())


def make_audit(
    *,
    request_id: str,
    stage: str,
    input_summary: str,
    policy_checks: list[str],
    confidence_level: str,
    risk_assessment: str,
    human_required: bool,
    human_reason: str | None = None,
    human_decision: str | None = None,
    human_id: str | None = None,
    final_decision: str | None = None,
    actions_taken: list[str] | None = None,
) -> dict:
    """Build one audit record. Keyword-only: positional order is a footgun here."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "stage": stage,
        "input_summary": input_summary,
        "policy_checks": policy_checks,
        "confidence_level": confidence_level,
        "risk_assessment": risk_assessment,
        "human_intervention": {
            "required": human_required,
            "reason": human_reason,
            "human_decision": human_decision,
            "human_id": human_id,
        },
        "final_decision": final_decision,
        "actions_taken": actions_taken or [],
    }


def append_audit(record: dict, audit_dir: Path) -> Path:
    """Append one record to today's JSONL file. Returns the file written."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = audit_dir / f"{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audit.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/hitl/audit.py tests/test_audit.py
git commit -m "feat: single audit schema with stable request_id and tz-aware timestamps"
```

---

## Task 3: Policy engine

**Files:**
- Create: `src/hitl/policy.py`
- Test: `tests/test_policy.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Action` dataclass: `Action(kind: str, issue_key: str | None = None, target_status: str | None = None, body: str | None = None)`
  - `TERMINAL_STATUSES: frozenset[str]`
  - `risk_tier(action: Action) -> str` — returns `"low" | "medium" | "high"`
  - `estimate_confidence(request: str) -> str` — returns `"low" | "medium" | "high"`
  - `decide(action: Action, request: str) -> Decision`
  - `Decision` dataclass: `Decision(gate: bool, tier: str, confidence: str, reason: str, checks: list[str])`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_policy.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_policy.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hitl.policy'`

- [ ] **Step 3: Write the implementation**

```python
# src/hitl/policy.py
"""Risk tiering, confidence, and the pause decision.

The invariant this module exists to enforce:

    Confidence may only ever ESCALATE to a gate.
    It can never clear one that policy requires.

That is the difference between HITL and HITL theater, and `decide()` is the
only place it is expressed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TERMINAL_STATUSES = frozenset({"done", "closed", "resolved", "cancelled"})

# Ambiguity markers. Deliberately only a confidence signal -- never a
# substitute for the policy tier, which is derived from the action itself.
AMBIGUITY_MARKERS = ("maybe", "not sure", "unclear", "unknown", "ambiguous", "some kind of")

_TIER_BY_KIND = {
    "add_comment": "low",
    "create_issue": "medium",
}


@dataclass(frozen=True)
class Action:
    kind: str
    issue_key: str | None = None
    target_status: str | None = None
    body: str | None = None


@dataclass(frozen=True)
class Decision:
    gate: bool
    tier: str
    confidence: str
    reason: str
    checks: list[str] = field(default_factory=list)


def risk_tier(action: Action) -> str:
    """Tier derived from the ACTION, never from how the request was worded."""
    if action.kind == "transition":
        status = (action.target_status or "").strip().lower()
        return "high" if status in TERMINAL_STATUSES else "low"
    # Unknown kinds fail closed.
    return _TIER_BY_KIND.get(action.kind, "high")


def estimate_confidence(request: str) -> str:
    """Rule-based ambiguity estimate. Swap for structured LLM output later."""
    lowered = request.lower()
    hits = sum(marker in lowered for marker in AMBIGUITY_MARKERS)
    if hits >= 2:
        return "low"
    if hits == 1:
        return "low"
    return "high"


def decide(action: Action, request: str) -> Decision:
    """Combine tier and confidence into a gate decision.

    Escalate-only: `gate` is True if EITHER the tier requires it or confidence
    is low. There is deliberately no branch in which high confidence sets
    `gate` to False against a gating tier.
    """
    tier = risk_tier(action)
    confidence = estimate_confidence(request)

    tier_requires_gate = tier in ("medium", "high")
    confidence_requires_gate = confidence == "low"
    gate = tier_requires_gate or confidence_requires_gate

    if tier_requires_gate and confidence_requires_gate:
        reason = f"tier {tier} requires approval; request is also ambiguous"
    elif tier_requires_gate:
        reason = f"tier {tier} requires approval"
    elif confidence_requires_gate:
        reason = "request is ambiguous; escalating a low-tier action"
    else:
        reason = "low tier and unambiguous; proceeding automatically"

    return Decision(
        gate=gate,
        tier=tier,
        confidence=confidence,
        reason=reason,
        checks=[
            f"tier:{tier}",
            f"confidence:{confidence}",
            f"gate:{'required' if gate else 'not-required'}",
        ],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_policy.py -q`
Expected: PASS, 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/hitl/policy.py tests/test_policy.py
git commit -m "feat: policy tiering with escalate-only confidence invariant"
```

---

## Task 4: Jira port and fake

**Files:**
- Create: `src/hitl/jira.py`
- Test: `tests/test_jira.py`

**Interfaces:**
- Consumes: `Action` from `hitl.policy`.
- Produces:
  - `JiraPort` Protocol with `execute(self, action: Action) -> str`
  - `FakeJira` class with `.calls: list[Action]` and `.execute(action) -> str`
  - `JiraError(Exception)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_jira.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_jira.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hitl.jira'`

- [ ] **Step 3: Write the implementation**

```python
# src/hitl/jira.py
"""Jira access behind a port.

The live Atlassian connector currently reports zero accessible sites, so
`RovoJira` is a stub (Task 7). Everything else in this project is written and
tested against `JiraPort`, so binding the real API later touches one class.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_jira.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/hitl/jira.py tests/test_jira.py
git commit -m "feat: JiraPort protocol with in-memory fake"
```

---

## Task 5: The graph

**Files:**
- Create: `src/hitl/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `make_audit`, `new_request_id` (`hitl.audit`); `Action`, `decide` (`hitl.policy`); `JiraPort`, `JiraError`, `FakeJira` (`hitl.jira`).
- Produces:
  - `State` TypedDict with keys `request, action, request_id, audits, decision, result, stage, human_id`
  - `build_graph(jira: JiraPort, checkpointer) -> CompiledGraph`
  - `checkpointer_for(db_path: Path)` — context manager yielding a `SqliteSaver`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph.py
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
        {"request": "comment on P-1 that deploy finished", "request_id": "req-1",
         "action": Action(kind="add_comment", issue_key="P-1", body="done")},
        _cfg(),
    )
    assert "__interrupt__" not in out
    assert out["stage"] == "completed"
    assert len(jira.calls) == 1


def test_high_risk_action_pauses_at_the_gate():
    jira = FakeJira(existing={"P-1": "To Do"})
    app = build_graph(jira, InMemorySaver())
    out = app.invoke(
        {"request": "move P-1 to Done", "request_id": "req-1",
         "action": Action(kind="transition", issue_key="P-1", target_status="Done")},
        _cfg(),
    )
    assert "__interrupt__" in out
    assert jira.calls == [], "nothing may execute before approval"


def test_denial_executes_nothing():
    jira = FakeJira(existing={"P-1": "To Do"})
    app = build_graph(jira, InMemorySaver())
    app.invoke(
        {"request": "move P-1 to Done", "request_id": "req-1",
         "action": Action(kind="transition", issue_key="P-1", target_status="Done")},
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
        {"request": "move P-1 to Done", "request_id": "req-1",
         "action": Action(kind="transition", issue_key="P-1", target_status="Done")},
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
        {"request": "move P-1 to Done", "request_id": "req-1",
         "action": Action(kind="transition", issue_key="P-1", target_status="Done")},
        _cfg(),
    )
    out = app.invoke(Command(resume={"decision": "approve", "human_id": "ash"}), _cfg())
    ids = {a["request_id"] for a in out["audits"]}
    assert ids == {"req-1"}, f"trail must correlate, got {ids}"


def test_execution_failure_does_not_retry(tmp_path):
    jira = FakeJira(existing={"P-1": "To Do"}, fail_with="rate limited")
    app = build_graph(jira, InMemorySaver())
    app.invoke(
        {"request": "move P-1 to Done", "request_id": "req-1",
         "action": Action(kind="transition", issue_key="P-1", target_status="Done")},
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
        out = app.invoke(Command(resume={"decision": "approve", "human_id": "ash"}), _cfg())

    assert out["stage"] == "completed"
    assert jira_b.statuses["P-1"] == "Done"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hitl.graph'`

- [ ] **Step 3: Write the implementation**

```python
# src/hitl/graph.py
"""The approval graph.

    submit -> assess -+-(auto)-----------------> execute -> END
                      +-(gate)-> approval_gate -+-(approve)-> execute -> END
                                 [interrupt()]  +-(deny)----> denied  -> END

`approval_gate` calls `interrupt()`. With a SqliteSaver the process can exit
entirely at that point; a later `Command(resume=...)` in a fresh process picks
up from the checkpoint.
"""

from __future__ import annotations

import operator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from hitl.audit import make_audit
from hitl.jira import JiraError, JiraPort
from hitl.policy import Action, decide


class State(TypedDict, total=False):
    request: str
    action: Action
    request_id: str
    human_id: str | None
    decision: str | None
    result: str | None
    stage: str
    audits: Annotated[list[dict], operator.add]


@contextmanager
def checkpointer_for(db_path: Path):
    """Yield a SqliteSaver over `db_path`.

    `SqliteSaver.from_conn_string` is itself a context manager -- this wrapper
    exists so callers do not have to know that, and so the path is created.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(db_path)) as saver:
        yield saver


def build_graph(jira: JiraPort, checkpointer: Any):
    def assess(state: State) -> State:
        d = decide(state["action"], state["request"])
        audit = make_audit(
            request_id=state["request_id"],
            stage="uncertain" if d.gate else "analysis",
            input_summary=state["request"],
            policy_checks=d.checks,
            confidence_level=d.confidence,
            risk_assessment=d.reason,
            human_required=d.gate,
            human_reason=d.reason if d.gate else None,
        )
        return {
            "stage": "awaiting_human" if d.gate else "analysis_complete",
            "audits": [audit],
        }

    def approval_gate(state: State) -> State:
        answer = interrupt(
            {
                "request_id": state["request_id"],
                "request": state["request"],
                "action": state["action"].kind,
                "reason": state["audits"][-1]["risk_assessment"],
            }
        )
        decision = answer.get("decision", "deny")
        human_id = answer.get("human_id")
        audit = make_audit(
            request_id=state["request_id"],
            stage="resumed",
            input_summary=state["request"],
            policy_checks=["human-reviewed"],
            confidence_level="high",
            risk_assessment="human provided an explicit decision",
            human_required=True,
            human_reason=state["audits"][-1]["risk_assessment"],
            human_decision=decision,
            human_id=human_id,
        )
        return {
            "decision": decision,
            "human_id": human_id,
            "stage": "approved" if decision == "approve" else "denied",
            "audits": [audit],
        }

    def execute(state: State) -> State:
        try:
            result = jira.execute(state["action"])
        except JiraError as exc:
            # Deliberately no retry: a retry is a new approval cycle.
            return {
                "stage": "failed",
                "result": str(exc),
                "audits": [
                    make_audit(
                        request_id=state["request_id"],
                        stage="completed",
                        input_summary=state["request"],
                        policy_checks=["execution-failed"],
                        confidence_level="high",
                        risk_assessment=f"execution failed: {exc}",
                        human_required=False,
                        human_decision=state.get("decision"),
                        human_id=state.get("human_id"),
                        final_decision="failed",
                        actions_taken=[],
                    )
                ],
            }
        return {
            "stage": "completed",
            "result": result,
            "audits": [
                make_audit(
                    request_id=state["request_id"],
                    stage="completed",
                    input_summary=state["request"],
                    policy_checks=["executed"],
                    confidence_level="high",
                    risk_assessment="action performed",
                    human_required=state.get("human_id") is not None,
                    human_decision=state.get("decision"),
                    human_id=state.get("human_id"),
                    final_decision="executed",
                    actions_taken=[f"{state['action'].kind}:{result}"],
                )
            ],
        }

    def denied(state: State) -> State:
        return {
            "stage": "denied",
            "audits": [
                make_audit(
                    request_id=state["request_id"],
                    stage="completed",
                    input_summary=state["request"],
                    policy_checks=["human-denied"],
                    confidence_level="high",
                    risk_assessment="human denied the action",
                    human_required=True,
                    human_decision="deny",
                    human_id=state.get("human_id"),
                    final_decision="denied",
                    actions_taken=[],
                )
            ],
        }

    g = StateGraph(State)
    g.add_node("assess", assess)
    g.add_node("approval_gate", approval_gate)
    g.add_node("execute", execute)
    g.add_node("denied", denied)

    g.set_entry_point("assess")
    g.add_conditional_edges(
        "assess",
        lambda s: s["stage"],
        {"awaiting_human": "approval_gate", "analysis_complete": "execute"},
    )
    g.add_conditional_edges(
        "approval_gate",
        lambda s: s["stage"],
        {"approved": "execute", "denied": "denied"},
    )
    g.add_edge("execute", END)
    g.add_edge("denied", END)
    return g.compile(checkpointer=checkpointer)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS, 25 passed

- [ ] **Step 6: Commit**

```bash
git add src/hitl/graph.py tests/test_graph.py
git commit -m "feat: approval graph with durable interrupt and no-retry failure path"
```

---

## Task 6: CLI

**Files:**
- Create: `src/hitl/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 2–5.
- Produces: `main(argv: list[str] | None = None) -> int`, `parse_action(text: str) -> Action`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
import json

import pytest

from hitl.cli import main, parse_action


def test_parse_transition():
    a = parse_action("transition P-1 to Done")
    assert (a.kind, a.issue_key, a.target_status) == ("transition", "P-1", "Done")


def test_parse_comment():
    a = parse_action("comment P-1 deploy finished")
    assert (a.kind, a.issue_key, a.body) == ("add_comment", "P-1", "deploy finished")


def test_parse_create():
    a = parse_action("create crash on save")
    assert (a.kind, a.body) == ("create_issue", "crash on save")


def test_parse_unknown_raises():
    with pytest.raises(ValueError, match="cannot parse"):
        parse_action("do something vague")


def test_submit_low_risk_completes(tmp_path, capsys):
    rc = main(["--home", str(tmp_path), "submit", "comment P-1 deploy finished",
               "--seed", "P-1=To Do"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "completed" in out


def test_submit_high_risk_pauses_and_approve_resumes(tmp_path, capsys):
    rc = main(["--home", str(tmp_path), "submit", "transition P-1 to Done",
               "--seed", "P-1=To Do"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "APPROVAL REQUIRED" in out
    rid = [ln.split()[-1] for ln in out.splitlines() if "request_id" in ln][0]

    rc = main(["--home", str(tmp_path), "approve", rid, "--as", "ash",
               "--seed", "P-1=To Do"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "completed" in out


def test_audit_command_replays_the_trail(tmp_path, capsys):
    main(["--home", str(tmp_path), "submit", "transition P-1 to Done", "--seed", "P-1=To Do"])
    rid = [ln.split()[-1] for ln in capsys.readouterr().out.splitlines() if "request_id" in ln][0]
    main(["--home", str(tmp_path), "deny", rid, "--as", "ash", "--seed", "P-1=To Do"])
    capsys.readouterr()

    rc = main(["--home", str(tmp_path), "audit", rid])
    out = capsys.readouterr().out
    assert rc == 0
    records = [json.loads(ln) for ln in out.strip().splitlines()]
    assert {r["request_id"] for r in records} == {rid}
    assert records[-1]["final_decision"] == "denied"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hitl.cli'`

- [ ] **Step 3: Write the implementation**

```python
# src/hitl/cli.py
"""CLI for the HITL approval agent.

    hitl submit "transition P-1 to Done"   -> runs until the gate, then EXITS
    hitl approve <request_id> --as <who>   -> resumes from the checkpoint
    hitl deny    <request_id> --as <who>
    hitl audit   <request_id>

`--seed` exists so the FakeJira backing this CLI has issues to act on until
`RovoJira` is bound (Task 7).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from langgraph.types import Command

from hitl.audit import append_audit, new_request_id
from hitl.graph import build_graph, checkpointer_for
from hitl.jira import FakeJira
from hitl.policy import Action

_TRANSITION = re.compile(r"^transition\s+(\S+)\s+to\s+(.+)$", re.I)
_COMMENT = re.compile(r"^comment\s+(\S+)\s+(.+)$", re.I)
_CREATE = re.compile(r"^create\s+(.+)$", re.I)


def parse_action(text: str) -> Action:
    text = text.strip()
    if m := _TRANSITION.match(text):
        return Action(kind="transition", issue_key=m.group(1), target_status=m.group(2).strip())
    if m := _COMMENT.match(text):
        return Action(kind="add_comment", issue_key=m.group(1), body=m.group(2).strip())
    if m := _CREATE.match(text):
        return Action(kind="create_issue", body=m.group(1).strip())
    raise ValueError(f"cannot parse action from: {text!r}")


def _jira(seed: list[str] | None) -> FakeJira:
    existing = {}
    for item in seed or []:
        key, _, status = item.partition("=")
        existing[key] = status or "To Do"
    return FakeJira(existing=existing)


def _emit(state: dict, home: Path) -> None:
    for record in state.get("audits", []):
        append_audit(record, home / "audit")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hitl")
    p.add_argument("--home", default=".hitl", type=Path)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit")
    s.add_argument("request")
    s.add_argument("--seed", action="append")

    for name in ("approve", "deny"):
        d = sub.add_parser(name)
        d.add_argument("request_id")
        d.add_argument("--as", dest="human_id", required=True)
        d.add_argument("--seed", action="append")

    a = sub.add_parser("audit")
    a.add_argument("request_id")

    args = p.parse_args(argv)
    home: Path = args.home
    db = home / "checkpoints.sqlite"

    if args.cmd == "audit":
        found = []
        for f in sorted((home / "audit").glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if json.loads(line)["request_id"] == args.request_id:
                    found.append(line)
        if not found:
            print(f"no audit records for {args.request_id}")
            return 1
        print("\n".join(found))
        return 0

    jira = _jira(args.seed)
    cfg_id = args.request_id if args.cmd != "submit" else new_request_id()
    cfg = {"configurable": {"thread_id": cfg_id}}

    with checkpointer_for(db) as cp:
        app = build_graph(jira, cp)
        if args.cmd == "submit":
            try:
                action = parse_action(args.request)
            except ValueError as exc:
                print(str(exc))
                return 2
            state = app.invoke(
                {"request": args.request, "request_id": cfg_id, "action": action}, cfg
            )
        else:
            decision = "approve" if args.cmd == "approve" else "deny"
            state = app.invoke(
                Command(resume={"decision": decision, "human_id": args.human_id}), cfg
            )

    _emit(state, home)

    if "__interrupt__" in state:
        print("APPROVAL REQUIRED")
        print(f"  request_id {cfg_id}")
        print(f"  approve with: hitl approve {cfg_id} --as <your-id>")
        return 0

    print(f"stage: {state.get('stage')}")
    if state.get("result"):
        print(f"result: {state['result']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Run the whole suite and lint**

Run: `uv run pytest -q && uv run --with ruff ruff check src tests`
Expected: 32 passed; `All checks passed!`

- [ ] **Step 6: Manual smoke test across a real process boundary**

```bash
rm -rf /tmp/hitl-smoke
uv run python -m hitl.cli --home /tmp/hitl-smoke submit "transition P-1 to Done" --seed "P-1=To Do"
# copy the request_id from the output, then, in a SEPARATE invocation:
uv run python -m hitl.cli --home /tmp/hitl-smoke approve <request_id> --as ash --seed "P-1=To Do"
uv run python -m hitl.cli --home /tmp/hitl-smoke audit <request_id>
```

Expected: first command prints `APPROVAL REQUIRED` and exits; second prints `stage: completed`; third prints 3 JSONL records sharing one `request_id`.

- [ ] **Step 7: Commit**

```bash
git add src/hitl/cli.py tests/test_cli.py
git commit -m "feat: CLI with async submit/approve/deny/audit across process boundaries"
```

---

## Task 7: Bind the live Jira API — BLOCKED

> **This task cannot start until `getAccessibleAtlassianResources()` returns at
> least one site.** As of 2026-09-18 it returns `[]` (spec §2). Tasks 1–6 are
> complete and useful without it; do not fake this task's completion.

**Files:**
- Modify: `src/hitl/jira.py` (add `RovoJira`)
- Test: `tests/test_jira_live.py`

**Interfaces:**
- Consumes: `Action` (`hitl.policy`), `JiraPort`, `JiraError` (`hitl.jira`).
- Produces: `RovoJira(cloud_id: str, project_key: str)` satisfying `JiraPort`.

- [ ] **Step 1: Re-check access**

```bash
# Expect a non-empty list of sites before continuing.
# If empty, STOP -- the blocker is unresolved.
```

Resolve by provisioning a Jira Cloud site, or re-authorizing the Atlassian
connector with site scope, in claude.ai connector settings.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_jira_live.py
import pytest

from hitl.jira import JiraPort, RovoJira


def test_rovo_satisfies_the_port():
    assert isinstance(RovoJira(cloud_id="x", project_key="P"), JiraPort)


@pytest.mark.skip(reason="requires live Atlassian site; unskip once access is restored")
def test_transition_against_live_instance():
    jira = RovoJira(cloud_id="<real-cloud-id>", project_key="<real-key>")
    raise NotImplementedError("fill in with a real issue key on a scratch project")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_jira_live.py -q`
Expected: FAIL — `ImportError: cannot import name 'RovoJira'`

- [ ] **Step 4: Implement `RovoJira`**

Add to `src/hitl/jira.py`. The three Atlassian MCP tools this maps onto are
`createJiraIssue`, `transitionJiraIssue` (which needs `getTransitionsForJiraIssue`
first to resolve a status name to a transition ID), and `addCommentToJiraIssue`.
Every one requires `cloudId`.

```python
class RovoJira:
    """Live Jira via the Atlassian Rovo MCP tools.

    ponytail: transition resolves the status name to a transition ID on every
    call. Cache per project if it becomes a latency problem.
    """

    def __init__(self, cloud_id: str, project_key: str) -> None:
        self.cloud_id = cloud_id
        self.project_key = project_key

    def execute(self, action: Action) -> str:
        raise JiraError(
            "RovoJira is not bound yet -- see docs/superpowers/plans/"
            "2026-09-18-hitl-approval-agent.md Task 7"
        )
```

Replace the body once access exists, wiring each `action.kind` to its tool and
translating any transport error into `JiraError`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: PASS (the live test stays skipped until a real site is available)

- [ ] **Step 6: Commit**

```bash
git add src/hitl/jira.py tests/test_jira_live.py
git commit -m "feat: RovoJira port implementation for live Jira"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §3.1 scaffold gone / commit baseline | Already satisfied by commit `0e2ea7b` |
| §3.2 archive retired variants | Task 1 |
| §3.3 flatten layout, root pyproject, `make test-all` | Task 1 |
| §4 file layout | Task 1 + each module's task |
| §5 graph shape, interrupt, SqliteSaver | Task 5 |
| §6 policy tier + escalate-only invariant | Task 3 (`test_high_confidence_cannot_clear_a_policy_gate`) |
| §7 one audit schema, stable `request_id`, tz-aware | Task 2 |
| §8 denial executes nothing; no auto-retry | Task 5 |
| §9 four load-bearing tests | Task 3 (invariant), Task 5 (process boundary, stable ID, denial) |
| §10 self-asserted identity limitation | Task 6 (`--as`); documented, not fixed — by design |
| §11 out of scope | No tasks — correct |
| §12 dependency note | Global Constraints |

No spec requirement is unaddressed.

**Placeholder scan:** No TBD/TODO in Tasks 1–6. Task 7 contains a deliberate
`NotImplementedError` and a `raise JiraError` stub — these are the honest
representation of a blocked task, and the task is explicitly marked BLOCKED
rather than pretending to be implementable.

**Type consistency:** `Action`, `Decision`, `JiraPort`, `JiraError`, `State`,
`make_audit`, `new_request_id`, `append_audit`, `build_graph`,
`checkpointer_for`, `parse_action`, `main` — each is defined in exactly one
task and referenced with the same name and signature everywhere else. The
`make_audit` call sites all use keyword arguments matching Task 2's signature.
