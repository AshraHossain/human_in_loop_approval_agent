import uuid
import datetime


def make_audit(stage: str, confidence: str, risk: str, human_required: bool, human_response=None):
    return {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "request_id": str(uuid.uuid4()),
        "stage": stage,
        "confidence_level": confidence,
        "risk_assessment": risk,
        "human_intervention": {
            "required": human_required,
            "human_response": human_response,
        },
    }
