# Graph Report - human_in_loop_approval_agent  (2026-09-27)

## Corpus Check
- 52 files · ~30,028 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1056 nodes · 2503 edges · 39 communities (33 shown, 6 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 342 edges (avg confidence: 0.94)
- Token cost: 1,055,417 input · 44,448 output

## Community Hubs (Navigation)
- Health Check Probes
- Configuration Loading
- Jira Port and Resilience
- Failure Classification and Retry
- CLI Entry and Audit Records
- SIEM Export
- Notifier Chain
- Structured Logging and Metrics
- Health Server and Fixtures
- Identity Enforcement Tests
- Rovo Jira Tests
- Backup and Archive
- README and Jira Surface
- Archived AgentExecutor Version
- Approval Levels and RBAC
- Audit Chain Integrity Tests
- CLI Config Tests
- Approval Graph and Identity Provider
- CLI Identity Tests
- Design Spec Sections
- Policy Design and Invariant
- Graph Stage Functions
- Audit Hashing Internals
- Policy Engine Implementation
- Archived Three-Version Comparison
- Policy Module and Identity Integration
- Jira Port Plan Tasks
- Audit Restore
- RovoJira Live Client
- Durable Approval Decisions
- Audit Schema Tests
- CLAUDE.md Repo Guidance
- File Identity Provider
- uv Workspace Layout
- hitl-agent-executor Package
- hitl-approval-agent Package
- hitl-runnable-pipeline Package

## God Nodes (most connected - your core abstractions)
1. `Action` - 70 edges
2. `JiraError` - 45 edges
3. `main()` - 44 edges
4. `check_health()` - 41 edges
5. `build_graph()` - 40 edges
6. `ApprovalLevel` - 37 edges
7. `log_event()` - 36 edges
8. `FakeJira` - 35 edges
9. `_load()` - 31 edges
10. `_cfg()` - 29 edges

## Surprising Connections (you probably didn't know these)
- `Decisions locked during brainstorming` --references--> `JiraPort`  [INFERRED]
  docs/superpowers/specs/2026-09-18-hitl-approval-agent-design.md → src/hitl/jira.py
- `9. Testing` --references--> `FakeJira`  [INFERRED]
  docs/superpowers/specs/2026-09-18-hitl-approval-agent-design.md → src/hitl/jira.py
- `5. The graph` --references--> `approval_gate()`  [INFERRED]
  docs/superpowers/specs/2026-09-18-hitl-approval-agent-design.md → src/hitl/graph.py
- `Task 5: The graph` --references--> `State`  [INFERRED]
  docs/superpowers/plans/2026-09-18-hitl-approval-agent.md → src/hitl/graph.py
- `HITL Approval Agent Implementation Plan` --references--> `JiraPort`  [INFERRED]
  docs/superpowers/plans/2026-09-18-hitl-approval-agent.md → src/hitl/jira.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Correlatable Audit Trail (one schema, one request_id, tz-aware, append-only)** — docs_superpowers_plans_2026_09_18_hitl_approval_agent_make_audit, docs_superpowers_plans_2026_09_18_hitl_approval_agent_new_request_id, docs_superpowers_plans_2026_09_18_hitl_approval_agent_append_audit, docs_superpowers_plans_2026_09_18_hitl_approval_agent_audit_json_schema, docs_superpowers_specs_2026_09_18_hitl_approval_agent_design_request_id_minted_per_call_defect, docs_superpowers_specs_2026_09_18_hitl_approval_agent_design_naive_utcnow_defect [EXTRACTED 1.00]
- **Durable Pause Across Process Boundaries** — readme_durable_approval_step, readme_approval_gate_interrupt, readme_sqlite_checkpointer, readme_three_process_approval_cycle, docs_superpowers_plans_2026_09_18_hitl_approval_agent_checkpointer_for, docs_superpowers_plans_2026_09_18_hitl_approval_agent_build_graph, docs_superpowers_plans_2026_09_18_hitl_approval_agent_main, docs_superpowers_specs_2026_09_18_hitl_approval_agent_design_decision_async_durable_approval [EXTRACTED 1.00]
- **The Escalate-Only Gate Decision (tier + confidence + invariant)** — docs_superpowers_specs_2026_09_18_hitl_approval_agent_design_escalate_only_invariant, docs_superpowers_specs_2026_09_18_hitl_approval_agent_design_policy_tier_table, docs_superpowers_specs_2026_09_18_hitl_approval_agent_design_confidence_signal, docs_superpowers_plans_2026_09_18_hitl_approval_agent_decide, docs_superpowers_plans_2026_09_18_hitl_approval_agent_risk_tier, docs_superpowers_plans_2026_09_18_hitl_approval_agent_estimate_confidence, readme_escalate_only_invariant [EXTRACTED 1.00]
- **Three Architectures Implementing One HITL Contract** — human_in_loop_approval_agent_claude_agent_executor_version, human_in_loop_approval_agent_claude_langgraph_version, human_in_loop_approval_agent_claude_runnable_pipeline_version, human_in_loop_approval_agent_claude_four_stage_contract [EXTRACTED 1.00]
- **Scaffold Re-Run Damage Pattern** — human_in_loop_approval_agent_claude_scaffold_hitl_repo, human_in_loop_approval_agent_claude_scaffold_artifacts, human_in_loop_approval_agent_claude_agentexecutor_misuse, human_in_loop_approval_agent_claude_runnable_import_breakage [INFERRED 0.75]

## Communities (39 total, 6 thin omitted)

### Community 0 - "Health Check Probes"
Cohesion: 0.06
Nodes (81): sqlite3, _age_hours(), Check, _check_audit_dir(), _check_chain(), _check_checkpoints(), check_health(), _check_identities() (+73 more)

### Community 1 - "Configuration Loading"
Cohesion: 0.05
Nodes (72): _coerce(), Config, ConfigError, env_name(), load_config(), load_dotenv(), Exception, Path (+64 more)

### Community 2 - "Jira Port and Resilience"
Cohesion: 0.06
Nodes (59): collections_abc, itertools, socket, JiraUnavailableError, Jira access behind a port., Build from a `Config`, so the retry and breaker knobs are the ones an operator…, Jira was never reached, so nothing was applied. The distinction from a plain…, CircuitBreaker (+51 more)

### Community 3 - "Failure Classification and Retry"
Cohesion: 0.08
Nodes (53): BaseException, ambiguous(), never_applied(), True when the failure proves Jira did not process the request., True for infrastructure failures, as opposed to Jira's own answer., Transient, but it may already have been applied. This is the set a mutation…, Call `fn`, retrying with exponential backoff while `retryable` allows. The…, retry() (+45 more)

### Community 4 - "CLI Entry and Audit Records"
Cohesion: 0.07
Nodes (53): argparse, append_audit, Fixed Audit JSON Schema, checkpointer_for, main (hitl CLI), make_audit, new_request_id, parse_action (+45 more)

### Community 5 - "SIEM Export"
Cohesion: 0.08
Nodes (46): _batched(), export_records(), ExportResult, _http_sender(), send(), Exception, Ship audit records to an external SIEM (Splunk HEC, Datadog, any webhook).…, A batch could not be delivered after every retry. (+38 more)

### Community 6 - "Notifier Chain"
Cohesion: 0.05
Nodes (44): abc, httpx, _build_notifiers(), Build notifier chain from config. Returns None if no notifiers are configured.…, EmailNotifier, NotificationError, Notifier, NotifierChain (+36 more)

### Community 7 - "Structured Logging and Metrics"
Cohesion: 0.07
Nodes (46): BaseHTTPRequestHandler, contextlib, io, Logger, LogRecord, get_metrics(), JSONFormatter, log_event() (+38 more)

### Community 8 - "Health Server and Fixtures"
Cohesion: 0.09
Nodes (37): http_server, os, pytest, signal, HealthServer, A probe endpoint, for when this runs as a service rather than a command. GET…, subprocess, _isolate_config() (+29 more)

### Community 9 - "Identity Enforcement Tests"
Cohesion: 0.10
Nodes (39): _cfg(), _file(), _provider(), parametrize, The approval gate is only worth something if it rejects the wrong people.…, One rung below the tier's requirement is a rejection, every time., A denial is harmless, but an unattributable one corrupts the trail., Submit and approve are different processes. The level demanded at approval must… (+31 more)

### Community 10 - "Rovo Jira Tests"
Cohesion: 0.19
Nodes (32): JiraError, Exception, Any failure performing a Jira action., Action, RovoJira is the only code here that writes to a real Jira. Its tools are…, Records the kwargs it was called with; optionally returns or raises., _rovo(), Spy (+24 more)

### Community 11 - "Backup and Archive"
Cohesion: 0.08
Nodes (32): datetime, pathlib, shutil, archive(), backup(), Path, Backup and restore audit trails. Simple file-based backup: copy JSONL files to…, Backup audit trail to timestamped directory. Returns the path of the created… (+24 more)

### Community 12 - "README and Jira Surface"
Cohesion: 0.09
Nodes (29): File Structure, Self-Review, 2. Known blocker: Jira is unreachable, `archive/` — the retired variants, Current status, FakeJira (README), Human-in-the-Loop Approval Agent, JiraPort (README) (+21 more)

### Community 13 - "Archived AgentExecutor Version"
Cohesion: 0.10
Nodes (26): AgentExecutor, make_audit(), detect_uncertainty(), hitl_check(), build_agent(), _hitl_check_tool(), AgentExecutor flavour of the HITL approval agent. Relative imports mean this…, Tool wrapper: the executor needs a string back, hitl_check returns a dict. (+18 more)

### Community 14 - "Approval Levels and RBAC"
Cohesion: 0.14
Nodes (24): ApprovalLevel, Identity, MockIdentityProvider, Verify identity can approve at this level or raise InsufficientLevelError., Approver authorization levels., Verified identity with level., Check if this identity can approve at the required level., In-memory identity provider for testing. (+16 more)

### Community 15 - "Audit Chain Integrity Tests"
Cohesion: 0.22
Nodes (24): append_audit(), Append one record to today's JSONL file. Returns the file written. Each stored…, _on_day(), Path, The chain is only worth having if it actually catches tampering. Every test…, Pin the audit module's clock so append_audit writes that day's file., _read(), _rec() (+16 more)

### Community 16 - "CLI Config Tests"
Cohesion: 0.14
Nodes (24): _config(), parametrize, Configuration as the CLI actually resolves it. `test_config.py` covers the…, Config is validated at startup precisely so a run cannot get halfway., Global flags precede the subcommand, as they do for --home., _run(), test_a_broken_config_exits_two_and_explains(), test_a_broken_config_stops_a_submit_before_anything_is_written() (+16 more)

### Community 17 - "Approval Graph and Identity Provider"
Cohesion: 0.12
Nodes (21): Enum, langgraph_checkpoint_sqlite, langgraph_graph, operator, approval_gate(), The approval graph. submit -> assess -+-(auto)-----------------> execute -> END…, IdentityProvider, InsufficientLevelError (+13 more)

### Community 18 - "CLI Identity Tests"
Cohesion: 0.18
Nodes (23): The CLI is where `--as <who>` enters the system, so it is where an unauthorised…, Someone approved-eligible at submit time, revoked before they act., The gate fired on ambiguity, not on risk -- a junior clears it., No identities file means no approvers. Out of the box, nothing executes., _run(), _submit(), test_a_bad_level_in_a_hand_edited_file_grants_nothing(), test_a_fresh_install_approves_nothing() (+15 more)

### Community 19 - "Design Spec Sections"
Cohesion: 0.10
Nodes (21): 10. Known limitation, 11. Out of scope, 12. Dependency note, 1. Goal, 3.1 The scaffold is already gone, 3.2 Archive the retired variants, 3.3 Flatten the layout, 3. Scope changes before building (+13 more)

### Community 20 - "Policy Design and Invariant"
Cohesion: 0.13
Nodes (20): Action (dataclass), AMBIGUITY_MARKERS, decide, Decision (dataclass), estimate_confidence, No LLM Dependency, risk_tier, Task 3: Policy engine (+12 more)

### Community 21 - "Graph Stage Functions"
Cohesion: 0.19
Nodes (19): make_audit(), Build one audit record. Keyword-only: positional order is a footgun here., _action(), build_graph(), assess(), denied(), execute(), Any (+11 more)

### Community 22 - "Audit Hashing Internals"
Cohesion: 0.14
Nodes (18): hashlib, json, _canonical(), hash_record(), last_hash(), _lines(), Path, Audit records for the HITL approval agent. One schema, one writer. `request_id`… (+10 more)

### Community 23 - "Policy Engine Implementation"
Cohesion: 0.17
Nodes (17): decide(), estimate_confidence(), Tier derived from the ACTION, never from how the request was worded., Rule-based ambiguity estimate. Swap for structured LLM output later., Combine tier and confidence into a gate decision. Escalate-only: `gate` is True…, risk_tier(), parametrize, test_a_gated_tier_and_an_ambiguous_request_reports_both_reasons() (+9 more)

### Community 24 - "Archived Three-Version Comparison"
Cohesion: 0.16
Nodes (16): agent_executor_version, ChatOpenAI Passed As AgentExecutor Agent, Deliberately Duplicated audit.py With Divergent Signatures, Four-Stage Contract (Detect/Pause/Resume/Audit), Human-in-the-Loop (HITL) Approval Pattern, HUMAN_APPROVAL_REQUIRED / awaiting_human, human_input Resume Payload, langgraph_version (+8 more)

### Community 25 - "Policy Module and Identity Integration"
Cohesion: 0.14
Nodes (13): dataclasses, langgraph_checkpoint_memory, langgraph_types, Risk tiering, confidence, and the pause decision. The invariant this module…, Integration tests: identity verification with approval workflow., Identity provider can be instantiated and used., Human ID is captured and recorded in audit trail on approval., Human ID is captured when action is denied. (+5 more)

### Community 26 - "Jira Port Plan Tasks"
Cohesion: 0.18
Nodes (14): FakeJira, Global Constraints, HITL Approval Agent Implementation Plan, JiraError, JiraPort (Protocol), RovoJira, Task 1: Restructure the repository, Task 4: Jira port and fake (+6 more)

### Community 27 - "Audit Restore"
Cohesion: 0.20
Nodes (10): Restore audit trail from a backup. Overwrites files in audit_dir with those…, restore(), Restore raises if backup_dir does not exist., Restore creates audit_dir if needed., Restore copies audit files from backup to audit_dir., Restore verifies chain integrity after restore., test_restore_copies_files_back(), test_restore_creates_audit_dir_if_missing() (+2 more)

### Community 28 - "RovoJira Live Client"
Cohesion: 0.36
Nodes (3): Live Jira via Atlassian Rovo MCP connector. Accepts tool callables for testing;…, RovoJira, run()

### Community 29 - "Durable Approval Decisions"
Cohesion: 0.32
Nodes (8): build_graph, State (TypedDict), Task 5: The graph, Decision 3: Async + durable approval, Decision 2: Gate Jira issue create / transition, Denial Executes Nothing, Four Load-Bearing Tests (spec §9), No Auto-Retry After Approved Execution Fails

### Community 30 - "Audit Schema Tests"
Cohesion: 0.43
Nodes (7): Path, _rec(), test_append_audit_is_append_only_jsonl(), test_human_intervention_block_shape(), test_request_id_is_never_regenerated(), test_schema_keys_exact(), test_timestamp_is_timezone_aware_utc()

### Community 31 - "CLAUDE.md Repo Guidance"
Cohesion: 0.29
Nodes (5): Commands, Known breakage in the generated sources, Layout gotcha, scaffold_hitl_repo.py is destructive, What this is

### Community 32 - "File Identity Provider"
Cohesion: 0.40
Nodes (3): FileIdentityProvider, Path, Identities from a JSON file: `{"ash": "lead", "sam": "junior"}`. Read on every…

## Ambiguous Edges - Review These
- `parse_action` → `TERMINAL_STATUSES`  [AMBIGUOUS]
  docs/superpowers/plans/2026-09-18-hitl-approval-agent.md · relation: shares_data_with

## Knowledge Gaps
- **30 isolated node(s):** `Metrics`, `Global Constraints`, ``archive/` — the retired variants`, `Known limitation`, `Running it` (+25 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 310 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `parse_action` and `TERMINAL_STATUSES`?**
  _Edge tagged AMBIGUOUS (relation: shares_data_with) - confidence is low._
- **Why does `Action` connect `Rovo Jira Tests` to `Jira Port and Resilience`, `CLI Entry and Audit Records`, `README and Jira Surface`, `Approval Graph and Identity Provider`, `Policy Design and Invariant`, `Graph Stage Functions`, `Policy Engine Implementation`, `Policy Module and Identity Integration`, `Jira Port Plan Tasks`, `RovoJira Live Client`, `Durable Approval Decisions`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Why does `main()` connect `CLI Entry and Audit Records` to `Health Check Probes`, `Configuration Loading`, `File Identity Provider`, `Jira Port and Resilience`, `Notifier Chain`, `Structured Logging and Metrics`, `Backup and Archive`, `README and Jira Surface`, `CLI Config Tests`, `CLI Identity Tests`, `Graph Stage Functions`, `Audit Hashing Internals`, `Audit Restore`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Why does `log_event()` connect `Structured Logging and Metrics` to `Health Check Probes`, `Jira Port and Resilience`, `Failure Classification and Retry`, `SIEM Export`, `Notifier Chain`, `Health Server and Fixtures`, `Backup and Archive`, `Approval Graph and Identity Provider`, `Graph Stage Functions`, `Audit Restore`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Are the 54 inferred relationships involving `Action` (e.g. with `Self-Review` and `Task 3: Policy engine`) actually correct?**
  _`Action` has 54 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `JiraError` (e.g. with `Self-Review` and `Task 5: The graph`) actually correct?**
  _`JiraError` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `main()` (e.g. with `Self-Review` and `ConfigError`) actually correct?**
  _`main()` has 3 INFERRED edges - model-reasoned connections that need verification._