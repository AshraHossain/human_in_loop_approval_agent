"""Audit records for the HITL approval agent.

One schema, one writer. `request_id` is minted once per request by the caller
and threaded through every stage -- regenerating it per record is what made the
earlier implementations' trails impossible to correlate.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def new_request_id() -> str:
    """Mint a request ID. Call this exactly once per request, at submit."""
    return str(uuid.uuid4())


def make_audit(
    *,
    request_id: str,
    stage: str,
    input_summary: str,
    policy_checks: list[str],
    confidence_level: str,
    risk_assessment: str,
    human_required: bool,
    human_reason: str | None = None,
    human_decision: str | None = None,
    human_id: str | None = None,
    final_decision: str | None = None,
    actions_taken: list[str] | None = None,
) -> dict:
    """Build one audit record. Keyword-only: positional order is a footgun here."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "stage": stage,
        "input_summary": input_summary,
        "policy_checks": policy_checks,
        "confidence_level": confidence_level,
        "risk_assessment": risk_assessment,
        "human_intervention": {
            "required": human_required,
            "reason": human_reason,
            "human_decision": human_decision,
            "human_id": human_id,
        },
        "final_decision": final_decision,
        "actions_taken": actions_taken or [],
    }


def append_audit(record: dict, audit_dir: Path) -> Path:
    """Append one record to today's JSONL file. Returns the file written."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = audit_dir / f"{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
    return path
