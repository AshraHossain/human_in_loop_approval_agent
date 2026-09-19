"""Runnable-pipeline flavour of the HITL approval agent.

Two entry points by design: `hitl_pipeline` detects and stops at the gate;
the caller inspects `status` and re-invokes `resume_pipeline` with the human's
answer. Run as a module from the parent directory:

    uv run -m runnable_pipeline_version.pipeline --self-check
"""

from __future__ import annotations

import json
import sys

from langchain_core.runnables import RunnableLambda

from .audit import make_audit

UNCERTAINTY_MARKERS = ["maybe", "not sure", "unclear", "unknown", "ambiguous"]


def detect_uncertainty(input_dict: dict) -> dict:
    text = input_dict["input"]
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
            "status": "HUMAN_APPROVAL_REQUIRED",
            "audit": audit,
        }

    audit = make_audit(
        stage="analysis",
        confidence="high",
        risk="No obvious ambiguity detected",
        human_required=False,
    )
    return {
        "status": "OK",
        "audit": audit,
    }


def resume_with_human(input_dict: dict) -> dict:
    human = input_dict.get("human_input")
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


hitl_pipeline = RunnableLambda(detect_uncertainty)
resume_pipeline = RunnableLambda(resume_with_human)


def _self_check() -> None:
    """Offline proof: both halves of the gate, and that resume carries the human's answer."""
    gated = hitl_pipeline.invoke({"input": "maybe ship it"})
    assert gated["status"] == "HUMAN_APPROVAL_REQUIRED", gated

    clear = hitl_pipeline.invoke({"input": "ship release 1.2"})
    assert clear["status"] == "OK", clear

    resumed = resume_pipeline.invoke({"input": "maybe ship it", "human_input": "approved: ship it"})
    assert resumed["stage"] == "completed", resumed
    assert resumed["audit"]["human_intervention"]["human_response"] == "approved: ship it", resumed
    print("self-check OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--self-check":
        _self_check()
    else:
        print(json.dumps(hitl_pipeline.invoke({"input": " ".join(args)}), indent=2, default=str))

