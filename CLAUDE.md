# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Three independent implementations of the *same* Human-in-the-Loop (HITL) approval
pattern, one per LangChain/LangGraph architecture, so they can be compared
side by side. Every version implements the same four-stage contract:

1. **Detect** — scan input for `UNCERTAINTY_MARKERS` (`maybe`, `not sure`, `unclear`, `unknown`, `ambiguous`)
2. **Pause** — emit `HUMAN_APPROVAL_REQUIRED` / stage `awaiting_human` and stop
3. **Resume** — re-enter with `human_input` in the payload
4. **Audit** — every stage transition returns a `make_audit(...)` dict

| Version | Pause mechanism | Entry point |
|---|---|---|
| `agent_executor_version/` | LLM calls `hitl_check` tool, returns status string | `main.py:run()` |
| `langgraph_version/` | Conditional edge routes `awaiting_human` → `END` | `graph.py:app` |
| `runnable_pipeline_version/` | `RunnableLambda` returns status dict; caller re-invokes `resume_with_human` | `pipeline.py:hitl_pipeline` |

`audit.py` is deliberately duplicated in all three — **and the signatures differ**:
`agent_executor_version/audit.py` takes `input_summary` + `actions_taken`, the other
two do not. Changing the audit schema means editing three files, not one.

## Layout gotcha

The tree is nested: the actual code lives at
`human_in_loop_approval_agent/human_in_loop_approval_agent/`. The outer directory
holds only `scaffold_hitl_repo.py`.

## scaffold_hitl_repo.py is destructive

`python scaffold_hitl_repo.py` writes every file in its `FILES` dict with `"w"` —
it **overwrites hand-edited source without warning**. It is a one-shot bootstrap,
not a sync tool. Do not re-run it. Edit files directly; if the scaffold must be
kept current, update its `FILES` dict to match the real files.

It has already been run twice with different `FILES` contents, which left
artifacts still present in the tree:

- `agent_executor_version/main.py` — contains the *text of the scaffold script*, not the agent; ends with `print('agent executor placeholder')`
- `langgraph_version/pyproject.toml`, `runnable_pipeline_version/pyproject.toml` — `[project]` table duplicated
- `README.md` — heading duplicated, unterminated ``` fence
- `diagrams/*.mmd` — stray trailing `flowchart TD` / `sequenceDiagram` line

Assume any file may be in this state; read before editing.

## Known breakage in the generated sources

- `runnable_pipeline_version/pipeline.py` imports `RunnableLambda, RunnablePassthrough` from `langchain.schema` — they live in `langchain_core.runnables`
- `agent_executor_version/main.py` passes a `ChatOpenAI` directly as `AgentExecutor.from_agent_and_tools(agent=...)`, which expects an agent, not an LLM; `langchain.chat_models.ChatOpenAI` is also the deprecated import path (use `langchain_openai`)
- Modules use relative imports (`from .audit import ...`) but the README says to run them as scripts (`uv run main.py`) — that raises `ImportError`. Either run as a module from the parent (`uv run -m agent_executor_version.main`) or switch to absolute imports.
- No `uv.lock`, no `tests/` in any subproject

## Commands

Each subproject is its own uv workspace — run from inside the subdirectory:

```bash
cd human_in_loop_approval_agent/langgraph_version
uv sync
uv run python -c "from graph import app; print(app.invoke({'input': 'maybe do X'}))"
```

Repo-wide tooling comes from the parent cockpit repo
(`/Users/ashrafhossain/AI_Engineering_Cockpit`), run from there:

```bash
make lint        # uv run ruff check --config config/ruff.toml .
make format      # black + ruff --fix across root and projects/*
make test-all    # scripts/run-tests.sh — iterates projects/*/pyproject.toml
make precommit   # pre-commit run --all-files -c config/.pre-commit-config.yaml
```

`scripts/run-tests.sh` skips any `projects/*/` directory without a top-level
`pyproject.toml`. This project has none (only per-version ones), so it is
currently skipped by `make test-all`. Add a root `pyproject.toml` with
`[tool.pytest.ini_options]` to opt in, as `projects/18-rag-citation-agent` does.

Root Python is 3.11; the subprojects declare `requires-python = ">=3.10"`.
