from langgraph.graph import StateGraph, END
from .state import State
from .audit import make_audit

UNCERTAINTY_MARKERS = ["maybe", "not sure", "unclear", "unknown", "ambiguous"]


def analyze(state: State) -> State:
    text = state["input"]
    lower = text.lower()
    uncertain = any(m in lower for m in UNCERTAINTY_MARKERS)

    if uncertain:
        audit = make_audit(
            stage="uncertain",
            confidence="low",
            risk="Ambiguous or low-confidence request",
            human_required=True,
        )
        return {
            "stage": "awaiting_human",
            "audit": audit,
        }

    audit = make_audit(
        stage="analysis",
        confidence="high",
        risk="No obvious ambiguity detected",
        human_required=False,
    )
    return {
        "stage": "analysis_complete",
        "audit": audit,
    }


def resume(state: State) -> State:
    human = state.get("human_input")
    audit = make_audit(
        stage="resumed",
        confidence="high",
        risk="Human clarified intent and constraints",
        human_required=True,
        human_response=human,
    )
    return {
        "stage": "completed",
        "audit": audit,
        "result": "Proceeding with validated context.",
    }


graph = StateGraph(State)
graph.add_node("analyze", analyze)
graph.add_node("resume", resume)

graph.set_entry_point("analyze")

graph.add_conditional_edges(
    "analyze",
    lambda s: s["stage"],
    {
        "awaiting_human": END,          # interrupt for HITL
        "analysis_complete": "resume",  # auto-resume when confident
    },
)

graph.add_edge("resume", END)

app = graph.compile()
