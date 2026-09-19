# HITL Approval Agent — Design

**Date:** 2026-09-18
**Status:** Approved (design). Not yet planned or implemented.
**Supersedes:** the three-variant comparison as the project's active goal.

---

## 1. Goal

Replace three broken demonstrations of a HITL approval pattern with **one
working agent**: a LangGraph StateGraph that gates Jira writes behind a durable,
auditable human approval step.

"Working" means the approve→execute path runs against a real Jira instance, the
pause survives process death, and the audit trail can be replayed from disk.

### Decisions locked during brainstorming

| # | Decision | Rationale |
|---|---|---|
| 1 | LangGraph; archive the other two variants | Only architecture with a genuine durable interrupt (`interrupt()` + checkpointer) |
| 2 | Gate Jira issue create / transition | Real integration; reversible, so the full execute path can be exercised safely |
| 3 | Async + durable approval | Agent exits at the gate; a separate CLI resumes from a checkpoint in a fresh process |
| 4 | Build behind a `JiraPort`, bind the live API last | Jira is currently unreachable (§2); the port is correct design regardless |

Gmail was considered and rejected for #2: sending mail is irreversible, which
would have forced a permanent draft-only mode and left the execute path untested.

---

## 2. Known blocker: Jira is unreachable

The Atlassian account authenticates (`Ashrafuzzaman Hossain`, active, verified),
but `getAccessibleAtlassianResources()` returns `[]` — **no Atlassian site is
reachable from the connector**. Every Jira tool requires a `cloudId`, and there
is no site to obtain one from. The same OAuth grant covers Confluence, so that is
equally unavailable.

Cause is one of: no Jira Cloud site provisioned, or the connector authorized
without site scope. Both are resolved by the user, not by this project.

**Mitigation:** all work targets a `JiraPort` protocol with an in-memory
`FakeJira`. The entire graph is buildable and testable with no network. Binding
`RovoJira` to the live MCP calls is the final, isolated task and the only one
that blocks on access being restored.

---

## 3. Scope changes before building

### 3.1 The scaffold is already gone

`scaffold_hitl_repo.py` wrote every file in its `FILES` dict with `"w"`. It had
already been run twice with divergent contents, which is what corrupted
`agent_executor_version/main.py` into holding its own generator source.

**As of 2026-09-18 the file no longer exists.** It was present at the start of
that day's session (1185 bytes) and removed outside it. It is not on disk, not in
git, and not in the trash — this project is entirely **untracked**
(`git ls-files` returns 0 files), so there is no copy to restore from.

No further action is required to neutralize it. The threat it posed is closed.

**The wider lesson stands and is now the first task of the plan: commit the
repaired state.** Every repair described in this document currently exists only
as untracked working-tree files. A second accidental deletion would take all of
it, exactly as it took the scaffold.

### 3.2 Archive the retired variants

`agent_executor_version/` and `runnable_pipeline_version/` move to `archive/`
unmodified. Both currently pass offline self-checks; they are retired as *working*
references, not broken ones.

Note for the plan: moving them changes their module paths, so the run commands
documented in `README.md` must be updated in the same commit or they become
wrong again.

### 3.3 Flatten the layout

`human_in_loop_approval_agent/human_in_loop_approval_agent/` collapses to a
conventional `src/` layout. A root `pyproject.toml` with
`[tool.pytest.ini_options]` opts the project into `make test-all`, which
currently skips it — `scripts/run-tests.sh` requires a top-level `pyproject.toml`
and there is none.

---

## 4. Layout

```
projects/human_in_loop_approval_agent/
  pyproject.toml          # root; opts into make test-all
  src/hitl/
    audit.py              # ONE make_audit
    policy.py             # risk tiering + confidence + the pause decision
    jira.py               # JiraPort protocol, FakeJira, RovoJira
    graph.py              # State + StateGraph + nodes
    cli.py                # submit / pending / approve / deny / audit
  tests/
  archive/                # retired variants (agent_executor, runnable_pipeline)
  diagrams/
```

Five source modules. `state.py` folds into `graph.py` (it is one `TypedDict`).
Both Jira implementations share `jira.py`: a Protocol and its implementations are
one concern.

---

## 5. The graph

```
submit → assess ─┬─(policy: auto)───────────→ execute → finalize
                 └─(policy: gate)→ approval_gate ─┬─(approve)→ execute → finalize
                                    [interrupt()]  └─(deny)───→ denied
```

`approval_gate` calls `interrupt()`. The process **exits**; state is already
durable in a `SqliteSaver` checkpointer keyed by `thread_id = request_id`. A
later `hitl approve <id>` resumes from that checkpoint in a fresh process via
`Command(resume=decision)`.

---

## 6. The pause decision

The existing detector is `any(m in text.lower() for m in UNCERTAINTY_MARKERS)`.
It is a keyword grep, not a confidence estimate: `"I am definitely not sure"` and
`"the Unknown Pleasures album"` both trip it, while a confidently-worded
destructive request passes clean.

It is replaced by two independent signals.

**Policy tier** — deterministic, derived from the *action*, never the prose:

| Action | Tier | Behavior |
|---|---|---|
| `transition` → terminal state (Done/Closed) | high | gate |
| `create_issue` | medium | gate |
| `transition` between open states | low | auto |
| `add_comment` | low | auto |

**Confidence** — from request ambiguity. Rule-based initially; structured LLM
output is a later upgrade.

### The invariant

> Confidence may only ever **escalate** to a gate. It can never clear one that
> policy requires.

A `high` confidence score on a `transition → Done` still pauses. This is the
single property that separates real HITL from HITL theater. It lives in one
function in `policy.py` and is asserted directly by a test.

---

## 7. Audit trail

One `make_audit`, matching the schema in the operating spec: `timestamp`,
`request_id`, `stage`, `input_summary`, `policy_checks[]`, `confidence_level`,
`risk_assessment`, `human_intervention{required, reason, human_decision,
human_id}`, `final_decision`, `actions_taken[]`. Append-only JSONL at
`audit/YYYY-MM-DD.jsonl`.

Two defects in the current implementations must not be carried forward:

- **`request_id` is minted per `make_audit` call**, so every stage of one request
  gets a different ID and the trail cannot be correlated. The audit requirement
  is structurally unmet today. Mint once at submit; thread through.
- **`datetime.utcnow()`** is deprecated and returns a naive timestamp, which is
  wrong for an audit log. Use `datetime.now(timezone.utc)`.

The graphify knowledge graph independently grouped these as a hyperedge at 0.85
confidence ("Audit Stage Defects That Break The Audit Requirement").

---

## 8. Errors and denial

- **Denied** → terminal state, `actions_taken: []`. Nothing executes.
- **Execution fails after approval** → audit `final_decision: "failed"`, and
  **no auto-retry**. A retry is a new approval cycle. Silently re-running an
  approved side effect is how duplicate writes happen.

---

## 9. Testing

TDD. `FakeJira` makes the whole graph testable with no network. Four tests carry
the design:

1. Policy floor cannot be bypassed by high confidence (§6 invariant).
2. Interrupt survives a **new process** — a fresh checkpointer instance, not the
   same object in memory.
3. `request_id` is stable across every stage of one request.
4. Denial executes nothing.

---

## 10. Known limitation

`hitl approve --as <human_id>` is **self-asserted identity**. There is no
authentication. For a local single-operator tool this is honest; for anything
carrying real compliance weight it is a hole. It ships with a `ponytail:` comment
naming the ceiling and the upgrade path (OS user + signed approval token).

---

## 11. Out of scope

Web UI, multi-approver quorum, notification/escalation, LLM-based confidence
scoring. Add when a second human must approve something, or when rule-based
tiering demonstrably mis-tiers.

---

## 12. Dependency note

`AgentExecutor` left `langchain.agents` in langchain 1.0; `langchain>=0.2.0`
resolves to 1.4.x today. On langchain 1.x, `create_agent` is LangGraph
underneath — the AgentExecutor-vs-LangGraph contrast the three variants exist to
demonstrate **no longer exists in current LangChain**. This is the substantive
argument for archiving them as historical references rather than maintaining
them.
