# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A LangGraph agent that gates Jira writes behind a **durable** human approval step.
When a request clears policy it runs; when it doesn't, `approval_gate` calls
`interrupt()`, LangGraph persists the whole state to a SQLite checkpointer, and the
process **exits**. A later `approve` resumes from that checkpoint in a brand new
process.

```
submit → assess ─┬─(auto)─────────────────→ execute → END
                 └─(gate)→ approval_gate ──┬─(approve)→ execute → END
                            [interrupt()]  └─(deny)────→ denied  → END
```

A full cycle is **three separate process invocations** (`submit`, `approve`, `audit`).
Any test or change that assumes one long-lived process has missed the point —
`tests/test_graph.py::test_interrupt_survives_a_new_checkpointer_instance` is the
proof, and it works by building a *fresh* `SqliteSaver` over the same file.

## The invariant

> Confidence may only ever **escalate** to a gate. It can never clear one that
> policy requires.

Risk tier comes from the *action* (`transition → Done` is high, always), never from
how confidently the request was worded. `AMBIGUITY_MARKERS` in `policy.py` is a
confidence signal only — never a tier input. `decide()` is the single place this is
expressed, and `tests/test_policy.py::test_high_confidence_cannot_clear_a_policy_gate`
is the load-bearing test. If a change makes that test pass for the wrong reason, the
project has lost its purpose.

Unknown action kinds and unknown tiers **fail closed** to `high` / `LEAD`
(`risk_tier`, `level_for_tier`).

## Layout

```
src/hitl/        audit policy jira graph cli config identity
                 resilience logging siem notifiers health server backup
tests/           21 test modules, 431 tests
docs/superpowers/specs/   design contract
docs/superpowers/plans/   implementation plan (embeds source — see note below)
archive/         two retired variants, still runnable
diagrams/        *.mmd
config.example.toml
```

Code is at `src/hitl/` with `pythonpath = ["src"]` in `[tool.pytest.ini_options]`,
so imports are absolute (`from hitl.audit import ...`), not relative.

## Non-obvious constraints

**Retry is split by what a failure proves** (`resilience.py`). None of Jira's
mutations are idempotent — a retried `create_issue` is two issues. So reads retry on
anything transient, but mutations retry *only* on failures proving the request never
reached Jira (refused connection, DNS failure, explicit "not processed"). A timeout is
ambiguous and is **never** retried; the caller is told the outcome is unknown.
`JiraUnavailableError` means nothing was applied; a plain `JiraError` means Jira
considered the action and refused. Do not collapse them.

The circuit breaker counts **availability** failures only. Jira answering "no
transition to Done" is Jira working; tripping a breaker on it would take the system
down over one misconfigured workflow.

**One `request_id` per request**, minted once at submit by `new_request_id()` and
threaded through every stage. Regenerating it per record is what made earlier
implementations' trails impossible to correlate. `make_audit` is keyword-only on
purpose.

**Audit writes are hash-chained** (`hash_record`, `last_hash`, `GENESIS_HASH`).
`_canonical` fixes key order — changing the serialization changes every hash and
breaks `hitl verify`. The audit schema is a fixed key set asserted by
`test_audit.py::test_schema_keys_exact`.

**Graph run + audit write is one indivisible step.** `cli.py` wraps both in
`defer_signals()`; a SIGTERM landing between them would leave an executed action with
no trail, the one outcome this system exists to prevent.

**Nothing is pickled into the checkpoint.** The `Action` dataclass is stored as a dict
(`asdict`) — `test_cli.py::test_checkpoint_holds_no_pickled_classes` enforces it.

**`approve --as <id>` is self-asserted identity.** No authentication. Approvers come
from a JSON identities file re-read on every call, so revocation is immediate
(`FileIdentityProvider`). A fresh install has no approvers and therefore approves
nothing.

**No LLM dependency and no API key.** Confidence is a rule-based estimate. Do not add
a model call without being asked.

## Commands

```bash
uv sync
uv run pytest -q                              # 431 tests, ~10s
uv run python -m hitl.cli --help
uv run python -m hitl.cli config              # resolved config, secrets masked
uv run python -m hitl.cli health --json
```

CLI surface: `submit` `approve` `deny` `audit` `verify` `users {add,rm,list}` `config`
`health` `serve` `backup` `restore` `archive`.

Exit codes are meaningful: `0` ok (including "approval required"), `1` health/verify
failure, `2` unparseable request or bad config, `3` denied, `4` deferred — nothing was
applied, safe to resubmit.

Config precedence, highest first: CLI flag → `HITL_*` env var → `.env` →
`[profiles.<name>]` → `[default]` → built-in. Secrets are refused in the TOML file;
`test_cli_config.py` asserts that. See `config.example.toml`.

Repo-wide tooling lives in the parent cockpit
(`/Users/ashrafhossain/AI_Engineering_Cockpit`), run from there:

```bash
make lint format test-all precommit
```

This project **is** picked up by `make test-all` — it has a root `pyproject.toml`
with `[tool.pytest.ini_options]`, which is the condition `scripts/run-tests.sh`
checks.

## `archive/` — read as history

Started as three implementations of the same pattern to compare architectures. The
comparison stopped being meaningful: `AgentExecutor` left `langchain.agents` in
langchain 1.0, and on 1.x `create_agent` is LangGraph underneath, so the contrast no
longer exists. `archive/agent_executor_version` needs `langchain-classic` to run at
all. Both still pass offline self-checks:

```bash
uv run --project archive/agent_executor_version \
  python -m archive.agent_executor_version.main --self-check
uv run --project archive/runnable_pipeline_version \
  python -m archive.runnable_pipeline_version.pipeline --self-check
```

Do not "fix" the archived variants or re-unify their `audit.py` signatures. They are
frozen.

> The `scaffold_hitl_repo.py` that generated this tree with `"w"` writes — overwriting
> hand-edited source — was removed on 2026-09-18 and its damage repaired. Do not
> recreate it. If regeneration is ever needed, write a tool that refuses to overwrite.

## Current status

Jira is **not bound**. `getAccessibleAtlassianResources()` returns `[]` — no
Atlassian site is reachable, so there is no `cloudId`. Everything is built against the
`JiraPort` protocol with an in-memory `FakeJira`, so the graph is complete and tested
without a network. Binding the live API is one class (`RovoJira`), and
`from_config` refuses to build without a `jira_cloud_id`.

## graphify note

`graphify-out/` holds a knowledge graph of this repo (1056 nodes, 39 communities).
The plan doc at `docs/superpowers/plans/` embeds the full source of `src/hitl/*.py`,
so ~19 symbols exist twice in the graph — once under the doc's node stem, once under
`src_hitl_*` from AST extraction. They are deliberately linked with `references`
edges rather than merged, because a doc's description of `make_audit` and the real
function are different objects. Re-running `/graphify --update` reproduces the split;
that is expected, not a bug.
