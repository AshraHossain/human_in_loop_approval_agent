import uuid
import datetime


def make_audit(
    stage: str,
    input_summary: str,
    confidence: str,
    risk_assessment: str,
    human_required: bool,
    human_response: str | None = None,
    actions_taken: list[str] | None = None,
) -> dict:
    return {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "request_id": str(uuid.uuid4()),
        "stage": stage,
        "input_summary": input_summary,
        "confidence_level": confidence,
        "risk_assessment": risk_assessment,
        "human_intervention": {
            "required": human_required,
            "human_response": human_response,
        },
        "final_decision": None,
        "actions_taken": actions_taken or [],
    }
