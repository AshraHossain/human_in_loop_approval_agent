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
from langgraph.types import interrupt

from hitl.audit import make_audit
from hitl.identity import (
    IdentityProvider,
    InsufficientLevelError,
    UnknownIdentityError,
    level_for_tier,
    require_level,
    verify_identity,
)
from hitl.jira import JiraError, JiraPort
from hitl.logging import (
    log_event,
    measure_jira_latency,
    record_approval,
    record_error,
)
from hitl.policy import Action, decide


class State(TypedDict, total=False):
    request: str
    # A plain dict, never the Action dataclass: checkpoints outlive this
    # process and LangGraph blocks deserializing unregistered classes. Keep
    # what lands on disk to primitives.
    action: dict
    request_id: str
    # The tier assessed at submit, checkpointed so the approval is judged
    # against the policy that gated it -- not against whatever policy happens
    # to be loaded in the process that resumes, hours later.
    tier: str
    human_id: str | None
    decision: str | None
    refusal: str | None
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


def _action(state: State) -> Action:
    return Action(**state["action"])


def build_graph(
    jira: JiraPort, checkpointer: Any, identities: IdentityProvider | None = None
):
    """Compile the approval graph.

    `identities` is the RBAC boundary. Passing None disables identity checks
    entirely, which is only appropriate for tests of the graph's own mechanics
    -- the CLI always supplies a provider.
    """

    def assess(state: State) -> State:
        d = decide(_action(state), state["request"])
        log_event(
            "policy_decision",
            action_kind=_action(state).kind,
            gate_required=d.gate,
            confidence=d.confidence,
            risk_tier=d.reason,
        )
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
            "tier": d.tier,
            "audits": [audit],
        }

    def approval_gate(state: State) -> State:
        log_event(
            "approval_gate_opened",
            request_id=state["request_id"],
            action=state["action"]["kind"],
            reason=state["audits"][-1]["risk_assessment"],
        )
        answer = interrupt(
            {
                "request_id": state["request_id"],
                "request": state["request"],
                "action": state["action"]["kind"],
                "reason": state["audits"][-1]["risk_assessment"],
            }
        )
        decision = answer.get("decision", "deny")
        human_id = answer.get("human_id")

        # The resume value arrives from outside the process, so this is the
        # first moment `human_id` can be checked -- and the only one every
        # caller routes through. A decision from someone we cannot identify,
        # or an approval from someone below the tier's level, becomes a
        # denial: approval fails closed, and the attempt is on the record.
        #
        # ponytail: a rejected attempt closes the request, so a typo in --as
        # costs a resubmit. Re-interrupting instead would keep it pending, but
        # that means re-entering the gate with a consumed resume value; worth
        # doing only once someone actually hits the typo case.
        refusal = None
        if identities is not None:
            required = level_for_tier(state.get("tier", "high"))
            try:
                identity = verify_identity(identities, human_id or "")
                if decision == "approve":
                    require_level(identity, required)
            except (UnknownIdentityError, InsufficientLevelError) as exc:
                refusal = str(exc)
                decision = "deny"

        log_event(
            "approval_gate_closed",
            request_id=state["request_id"],
            decision=decision,
            human_id=human_id,
            refusal=refusal,
        )
        audit = make_audit(
            request_id=state["request_id"],
            stage="resumed",
            input_summary=state["request"],
            policy_checks=["identity-rejected"] if refusal else ["human-reviewed"],
            confidence_level="high",
            risk_assessment=refusal or "human provided an explicit decision",
            human_required=True,
            human_reason=state["audits"][-1]["risk_assessment"],
            human_decision=decision,
            human_id=human_id,
        )
        record_approval(decision == "approve")
        return {
            "decision": decision,
            "human_id": human_id,
            "refusal": refusal,
            "stage": "approved" if decision == "approve" else "denied",
            "audits": [audit],
        }

    def execute(state: State) -> State:
        try:
            with measure_jira_latency():
                result = jira.execute(_action(state))
            log_event(
                "action_executed",
                request_id=state["request_id"],
                action=state["action"]["kind"],
                result=result,
            )
        except JiraError as exc:
            # Deliberately no retry: a retry is a new approval cycle.
            record_error(f"execution failed: {exc}")
            log_event(
                "action_failed",
                request_id=state["request_id"],
                action=state["action"]["kind"],
                error=str(exc),
            )
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
                    actions_taken=[f"{state['action']['kind']}:{result}"],
                )
            ],
        }

    def denied(state: State) -> State:
        refusal = state.get("refusal")
        log_event(
            "action_denied",
            request_id=state["request_id"],
            action=state["action"]["kind"],
            human_id=state.get("human_id"),
            refusal=refusal,
        )
        return {
            "stage": "denied",
            "audits": [
                make_audit(
                    request_id=state["request_id"],
                    stage="completed",
                    input_summary=state["request"],
                    policy_checks=["identity-rejected"] if refusal else ["human-denied"],
                    confidence_level="high",
                    risk_assessment=refusal or "human denied the action",
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
