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
from hitl.jira import JiraError, JiraPort
from hitl.policy import Action, decide


class State(TypedDict, total=False):
    request: str
    # A plain dict, never the Action dataclass: checkpoints outlive this
    # process and LangGraph blocks deserializing unregistered classes. Keep
    # what lands on disk to primitives.
    action: dict
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


def _action(state: State) -> Action:
    return Action(**state["action"])


def build_graph(jira: JiraPort, checkpointer: Any):
    def assess(state: State) -> State:
        d = decide(_action(state), state["request"])
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
                "action": state["action"]["kind"],
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
            result = jira.execute(_action(state))
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
                    actions_taken=[f"{state['action']['kind']}:{result}"],
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
