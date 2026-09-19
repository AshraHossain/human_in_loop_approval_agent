from .audit import make_audit

UNCERTAINTY_MARKERS = ["maybe", "not sure", "unclear", "unknown", "ambiguous"]


def detect_uncertainty(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in UNCERTAINTY_MARKERS)


def hitl_check(input_text: str) -> dict:
    if detect_uncertainty(input_text):
        audit = make_audit(
            stage="uncertain",
            input_summary=input_text,
            confidence="low",
            risk_assessment="Ambiguous or low-confidence request",
            human_required=True,
        )
        return {
            "status": "HUMAN_APPROVAL_REQUIRED",
            "audit": audit,
            "questions": [
                "Please clarify the goal.",
                "What constraints or policies apply?",
            ],
        }

    audit = make_audit(
        stage="analysis",
        input_summary=input_text,
        confidence="high",
        risk_assessment="No obvious ambiguity detected",
        human_required=False,
    )
    return {
        "status": "OK",
        "audit": audit,
    }
