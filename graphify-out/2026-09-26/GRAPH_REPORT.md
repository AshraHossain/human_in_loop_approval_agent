# Graph Report - human_in_loop_approval_agent  (2026-09-21)

## Corpus Check
- 21 files · ~11,389 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 224 nodes · 350 edges · 14 communities
- Extraction: 90% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 33 edges (avg confidence: 0.59)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `95c79907`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Runnable Pipeline Variant|Runnable Pipeline Variant]]
- [[_COMMUNITY_LangGraph State Machine|LangGraph State Machine]]
- [[_COMMUNITY_AgentExecutor Wiring|AgentExecutor Wiring]]
- [[_COMMUNITY_AgentExecutor Dependencies|AgentExecutor Dependencies]]
- [[_COMMUNITY_Scaffold Damage and Run Layout|Scaffold Damage and Run Layout]]
- [[_COMMUNITY_HITL Pattern and Detection Gaps|HITL Pattern and Detection Gaps]]
- [[_COMMUNITY_Audit Module Triplication|Audit Module Triplication]]
- [[_COMMUNITY_Variant Comparison Notes|Variant Comparison Notes]]
- [[_COMMUNITY_HITL Check Tool|HITL Check Tool]]
- [[_COMMUNITY_Resume Hook Naming|Resume Hook Naming]]
- [[_COMMUNITY_Four-Stage Contract|Four-Stage Contract]]

## God Nodes (most connected - your core abstractions)
1. `Action` - 16 edges
2. `JiraError` - 13 edges
3. `HITL Approval Agent — Design` - 13 edges
4. `main()` - 12 edges
5. `build_graph()` - 11 edges
6. `HITL Approval Agent Implementation Plan` - 11 edges
7. `decide()` - 10 edges
8. `FakeJira` - 9 edges
9. `JiraPort` - 8 edges
10. `RovoJira` - 8 edges

## Surprising Connections (you probably didn't know these)
- `resume_pipeline Re-Invocation` --semantically_similar_to--> `resume_with_human Re-Invocation`  [AMBIGUOUS] [semantically similar]
  human_in_loop_approval_agent/README.md → CLAUDE.md
- `Path` --uses--> `FakeJira`  [INFERRED]
  tests/test_graph.py → src/hitl/jira.py
- `Path` --uses--> `Action`  [INFERRED]
  tests/test_graph.py → src/hitl/policy.py
- `test_parse_comment()` --calls--> `parse_action()`  [EXTRACTED]
  tests/test_cli.py → src/hitl/cli.py
- `test_parse_create()` --calls--> `parse_action()`  [EXTRACTED]
  tests/test_cli.py → src/hitl/cli.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Three Architectures Implementing One HITL Contract** — human_in_loop_approval_agent_claude_agent_executor_version, human_in_loop_approval_agent_claude_langgraph_version, human_in_loop_approval_agent_claude_runnable_pipeline_version, human_in_loop_approval_agent_claude_four_stage_contract [EXTRACTED 1.00]
- **Scaffold Re-Run Damage Pattern** — human_in_loop_approval_agent_claude_scaffold_hitl_repo, human_in_loop_approval_agent_claude_scaffold_artifacts, human_in_loop_approval_agent_claude_agentexecutor_misuse, human_in_loop_approval_agent_claude_runnable_import_breakage [INFERRED 0.75]
- **Audit Stage Defects That Break The Audit Requirement** — human_in_loop_approval_agent_claude_make_audit, human_in_loop_approval_agent_readme_request_id_correlation, human_in_loop_approval_agent_readme_naive_timestamp, human_in_loop_approval_agent_claude_duplicated_audit_module [INFERRED 0.85]

## Communities (14 total, 0 thin omitted)

### Community 0 - "Runnable Pipeline Variant"
Cohesion: 0.10
Nodes (26): datetime, append_audit(), make_audit(), new_request_id(), Audit records for the HITL approval agent.  One schema, one writer. `request_id`, Mint a request ID. Call this exactly once per request, at submit., Build one audit record. Keyword-only: positional order is a footgun here., Append one record to today's JSONL file. Returns the file written. (+18 more)

### Community 1 - "LangGraph State Machine"
Cohesion: 0.18
Nodes (18): _action(), build_graph(), checkpointer_for(), The approval graph.      submit -> assess -+-(auto)-----------------> execute ->, Yield a SqliteSaver over `db_path`.      `SqliteSaver.from_conn_string` is itsel, State, langgraph_graph, _cfg() (+10 more)

### Community 2 - "AgentExecutor Wiring"
Cohesion: 0.15
Nodes (17): Any, Exception, FakeJira, JiraError, JiraPort, Jira access behind a port., Any failure performing a Jira action., Perform the action. Returns a human-readable result string. (+9 more)

### Community 3 - "AgentExecutor Dependencies"
Cohesion: 0.15
Nodes (18): make_audit(), detect_uncertainty(), hitl_check(), build_agent(), _hitl_check_tool(), AgentExecutor flavour of the HITL approval agent.  Relative imports mean this mu, Tool wrapper: the executor needs a string back, hitl_check returns a dict., Build the executor.      Lazy on purpose -- constructing ChatOpenAI at import ti (+10 more)

### Community 4 - "Scaffold Damage and Run Layout"
Cohesion: 0.09
Nodes (28): agent_executor_version, ChatOpenAI Passed As AgentExecutor Agent, Deliberately Duplicated audit.py With Divergent Signatures, Four-Stage Contract (Detect/Pause/Resume/Audit), Human-in-the-Loop (HITL) Approval Pattern, HUMAN_APPROVAL_REQUIRED / awaiting_human, human_input Resume Payload, langgraph_version (+20 more)

### Community 5 - "HITL Pattern and Detection Gaps"
Cohesion: 0.14
Nodes (22): FakeJira, _emit(), _jira(), main(), parse_action(), CLI for the HITL approval agent.      hitl submit "transition P-1 to Done"   ->, Append only records not already on disk.      On resume, state["audits"] carries, Action (+14 more)

### Community 6 - "Audit Module Triplication"
Cohesion: 0.16
Nodes (18): decide(), Decision, estimate_confidence(), Risk tiering, confidence, and the pause decision.  The invariant this module exi, Tier derived from the ACTION, never from how the request was worded., Rule-based ambiguity estimate. Swap for structured LLM output later., Combine tier and confidence into a gate decision.      Escalate-only: `gate` is, risk_tier() (+10 more)

### Community 7 - "Variant Comparison Notes"
Cohesion: 0.11
Nodes (18): 10. Known limitation, 11. Out of scope, 12. Dependency note, 1. Goal, 2. Known blocker: Jira is unreachable, 3.1 The scaffold is already gone, 3.2 Archive the retired variants, 3.3 Flatten the layout (+10 more)

### Community 8 - "HITL Check Tool"
Cohesion: 0.17
Nodes (11): File Structure, Global Constraints, HITL Approval Agent Implementation Plan, Self-Review, Task 1: Restructure the repository, Task 2: Audit records, Task 3: Policy engine, Task 4: Jira port and fake (+3 more)

### Community 9 - "Resume Hook Naming"
Cohesion: 0.25
Nodes (7): `archive/` — the retired variants, Current status, Human-in-the-Loop Approval Agent, Known limitation, Layout, Running it, The invariant

### Community 10 - "Four-Stage Contract"
Cohesion: 0.29
Nodes (5): Commands, Known breakage in the generated sources, Layout gotcha, scaffold_hitl_repo.py is destructive, What this is

## Ambiguous Edges - Review These
- `resume_with_human Re-Invocation` → `resume_pipeline Re-Invocation`  [AMBIGUOUS]
  human_in_loop_approval_agent/README.md · relation: semantically_similar_to

## Knowledge Gaps
- **42 isolated node(s):** `AgentExecutor`, `Path`, `Path`, `What this is`, `Layout gotcha` (+37 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `resume_with_human Re-Invocation` and `resume_pipeline Re-Invocation`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **Why does `Action` connect `AgentExecutor Wiring` to `LangGraph State Machine`, `HITL Pattern and Detection Gaps`, `Audit Module Triplication`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Why does `main()` connect `HITL Pattern and Detection Gaps` to `Runnable Pipeline Variant`, `LangGraph State Machine`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Why does `JiraError` connect `AgentExecutor Wiring` to `LangGraph State Machine`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `Action` (e.g. with `Any` and `FakeJira`) actually correct?**
  _`Action` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `JiraError` (e.g. with `Any` and `State`) actually correct?**
  _`JiraError` has 5 INFERRED edges - model-reasoned connections that need verification._
- **What connects `AgentExecutor`, `AgentExecutor flavour of the HITL approval agent.  Relative imports mean this mu`, `Tool wrapper: the executor needs a string back, hitl_check returns a dict.` to the rest of the system?**
  _73 weakly-connected nodes found - possible documentation gaps or missing edges._