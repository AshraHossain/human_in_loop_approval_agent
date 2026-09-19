# Graph Report - human_in_loop_approval_agent  (2026-09-18)

## Corpus Check
- Corpus is ~2,393 words - fits in a single context window. You may not need a graph.

## Summary
- 75 nodes · 103 edges · 16 communities (11 shown, 5 thin omitted)
- Extraction: 88% EXTRACTED · 11% INFERRED · 1% AMBIGUOUS · INFERRED: 11 edges (avg confidence: 0.88)
- Token cost: 65,346 input · 0 output

## Community Hubs (Navigation)
- Runnable Pipeline Variant
- LangGraph State Machine
- AgentExecutor Wiring
- AgentExecutor Dependencies
- Scaffold Damage and Run Layout
- HITL Pattern and Detection Gaps
- Audit Module Triplication
- Variant Comparison Notes
- HITL Check Tool
- Resume Hook Naming
- Four-Stage Contract
- Audit Trail Defects
- Agent Run Entry Point
- Package: agent-executor
- Package: langgraph
- Package: runnable-pipeline

## God Nodes (most connected - your core abstractions)
1. `Four-Stage Contract (Detect/Pause/Resume/Audit)` - 8 edges
2. `_hitl_check_tool()` - 6 edges
3. `build_agent()` - 6 edges
4. `make_audit()` - 5 edges
5. `hitl_check()` - 5 edges
6. `run()` - 5 edges
7. `State` - 5 edges
8. `agent_executor_version` - 5 edges
9. `_self_check()` - 4 edges
10. `make_audit()` - 4 edges

## Surprising Connections (you probably didn't know these)
- `resume_pipeline Re-Invocation` --semantically_similar_to--> `resume_with_human Re-Invocation`  [AMBIGUOUS] [semantically similar]
  human_in_loop_approval_agent/README.md → CLAUDE.md
- `No Policy Tier For Destructive Actions` --references--> `Human-in-the-Loop (HITL) Approval Pattern`  [INFERRED]
  human_in_loop_approval_agent/README.md → CLAUDE.md
- `langchain-classic Dependency Choice` --rationale_for--> `agent_executor_version`  [EXTRACTED]
  human_in_loop_approval_agent/README.md → CLAUDE.md
- `Mermaid Diagrams (architecture_overview, hitl_sequence_diagram)` --references--> `Double-Scaffold Artifacts In Tree`  [EXTRACTED]
  human_in_loop_approval_agent/README.md → CLAUDE.md
- `Run As Modules From Parent Directory` --conceptually_related_to--> `Per-Version uv Workspace Layout`  [INFERRED]
  human_in_loop_approval_agent/README.md → CLAUDE.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Three Architectures Implementing One HITL Contract** — human_in_loop_approval_agent_claude_agent_executor_version, human_in_loop_approval_agent_claude_langgraph_version, human_in_loop_approval_agent_claude_runnable_pipeline_version, human_in_loop_approval_agent_claude_four_stage_contract [EXTRACTED 1.00]
- **Audit Stage Defects That Break The Audit Requirement** — human_in_loop_approval_agent_claude_make_audit, human_in_loop_approval_agent_readme_request_id_correlation, human_in_loop_approval_agent_readme_naive_timestamp, human_in_loop_approval_agent_claude_duplicated_audit_module [INFERRED 0.85]
- **Scaffold Re-Run Damage Pattern** — human_in_loop_approval_agent_claude_scaffold_hitl_repo, human_in_loop_approval_agent_claude_scaffold_artifacts, human_in_loop_approval_agent_claude_agentexecutor_misuse, human_in_loop_approval_agent_claude_runnable_import_breakage [INFERRED 0.75]

## Communities (16 total, 5 thin omitted)

### Community 0 - "Runnable Pipeline Variant"
Cohesion: 0.24
Nodes (9): make_audit(), detect_uncertainty(), Runnable-pipeline flavour of the HITL approval agent. Two entry points by…, Offline proof: both halves of the gate, and that resume carries the human's…, resume_with_human(), _self_check(), json, langchain_core_runnables (+1 more)

### Community 1 - "LangGraph State Machine"
Cohesion: 0.36
Nodes (7): make_audit(), analyze(), resume(), State, langgraph_graph, TypedDict, typing

### Community 2 - "AgentExecutor Wiring"
Cohesion: 0.33
Nodes (7): AgentExecutor, build_agent(), _hitl_check_tool(), Tool wrapper: the executor needs a string back, hitl_check returns a dict., Build the executor. Lazy on purpose -- constructing ChatOpenAI at import time…, Offline proof: gate logic and executor wiring. Makes no API call., _self_check()

### Community 3 - "AgentExecutor Dependencies"
Cohesion: 0.29
Nodes (6): AgentExecutor flavour of the HITL approval agent. Relative imports mean this…, langchain_classic_agents, langchain_core_prompts, langchain_core_tools, langchain_openai, os

### Community 4 - "Scaffold Damage and Run Layout"
Cohesion: 0.29
Nodes (7): Relative Imports vs Bare-Script Invocation, Double-Scaffold Artifacts In Tree, scaffold_hitl_repo.py (Destructive One-Shot Bootstrap), make test-all Skips This Project, Per-Version uv Workspace Layout, Run As Modules From Parent Directory, Offline --self-check Entry Points

### Community 5 - "HITL Pattern and Detection Gaps"
Cohesion: 0.33
Nodes (6): Human-in-the-Loop (HITL) Approval Pattern, UNCERTAINTY_MARKERS, Mermaid Diagrams (architecture_overview, hitl_sequence_diagram), AgentExecutor-vs-LangGraph Contrast Is Historical, Uncertainty Detection Is Keyword Grep, Not Confidence, No Policy Tier For Destructive Actions

### Community 7 - "Variant Comparison Notes"
Cohesion: 0.40
Nodes (5): agent_executor_version, ChatOpenAI Passed As AgentExecutor Agent, Deliberately Duplicated audit.py With Divergent Signatures, langgraph_version, langchain-classic Dependency Choice

### Community 8 - "HITL Check Tool"
Cohesion: 0.83
Nodes (3): make_audit(), detect_uncertainty(), hitl_check()

### Community 9 - "Resume Hook Naming"
Cohesion: 0.50
Nodes (4): resume_with_human Re-Invocation, RunnableLambda Imported From langchain.schema, runnable_pipeline_version, resume_pipeline Re-Invocation

### Community 10 - "Four-Stage Contract"
Cohesion: 1.00
Nodes (3): Four-Stage Contract (Detect/Pause/Resume/Audit), HUMAN_APPROVAL_REQUIRED / awaiting_human, human_input Resume Payload

### Community 11 - "Audit Trail Defects"
Cohesion: 0.67
Nodes (3): make_audit Audit Record, datetime.utcnow() Naive Timestamp In Audit Log, Fresh request_id Per make_audit Call Breaks Correlation

## Ambiguous Edges - Review These
- `resume_pipeline Re-Invocation` → `resume_with_human Re-Invocation`  [AMBIGUOUS]
  human_in_loop_approval_agent/README.md · relation: semantically_similar_to

## Knowledge Gaps
- **7 isolated node(s):** `hitl-agent-executor`, `hitl-langgraph`, `hitl-runnable-pipeline`, `RunnableLambda Imported From langchain.schema`, `ChatOpenAI Passed As AgentExecutor Agent` (+2 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 27 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `resume_pipeline Re-Invocation` and `resume_with_human Re-Invocation`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **Why does `Four-Stage Contract (Detect/Pause/Resume/Audit)` connect `Four-Stage Contract` to `Resume Hook Naming`, `Audit Trail Defects`, `HITL Pattern and Detection Gaps`, `Variant Comparison Notes`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Why does `agent_executor_version` connect `Variant Comparison Notes` to `Four-Stage Contract`, `Scaffold Damage and Run Layout`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Why does `Double-Scaffold Artifacts In Tree` connect `Scaffold Damage and Run Layout` to `HITL Pattern and Detection Gaps`, `Variant Comparison Notes`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **What connects `hitl-agent-executor`, `hitl-langgraph`, `hitl-runnable-pipeline` to the rest of the system?**
  _7 weakly-connected nodes found - possible documentation gaps or missing edges._