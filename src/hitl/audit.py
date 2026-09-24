"""Audit records for the HITL approval agent.

One schema, one writer. `request_id` is minted once per request by the caller
and threaded through every stage -- regenerating it per record is what made the
earlier implementations' trails impossible to correlate.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

# First record in a trail links to this instead of a predecessor.
GENESIS_HASH = "0" * 64


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
        "timestamp": datetime.now(UTC).isoformat(),
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


def _canonical(record: dict) -> bytes:
    """Stable serialization: key order must not change the hash."""
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def hash_record(record: dict) -> str:
    """Hash a record over every field except `hash` itself."""
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(_canonical(body)).hexdigest()


def _lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def last_hash(audit_dir: Path) -> str:
    """Hash of the newest record in the trail, across day files."""
    if not audit_dir.exists():
        return GENESIS_HASH
    for path in sorted(audit_dir.glob("*.jsonl"), reverse=True):
        lines = _lines(path)
        if lines:
            return json.loads(lines[-1]).get("hash", GENESIS_HASH)
    return GENESIS_HASH


def append_audit(record: dict, audit_dir: Path) -> Path:
    """Append one record to today's JSONL file. Returns the file written.

    Each stored record carries `prev_hash` (the record before it, spanning day
    files) and its own `hash`. Altering, deleting or reordering any record
    breaks the chain at that point, which `verify_chain` reports. The chain is
    what makes the trail evidence; without it a JSONL file is just a text file
    anyone can edit.
    """
    audit_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    path = audit_dir / f"{day}.jsonl"

    sealed = dict(record)
    sealed["prev_hash"] = last_hash(audit_dir)
    sealed["hash"] = hash_record(sealed)

    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(sealed, default=str) + "\n")
    return path


def verify_chain(audit_dir: Path) -> list[str]:
    """Walk the whole trail. Returns a list of problems -- empty means intact."""
    problems: list[str] = []
    if not audit_dir.exists():
        return problems

    expected_prev = GENESIS_HASH
    for path in sorted(audit_dir.glob("*.jsonl")):
        for lineno, line in enumerate(_lines(path), 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                problems.append(f"{path.name}:{lineno} is not valid JSON")
                return problems

            where = f"{path.name}:{lineno}"
            if record.get("prev_hash") != expected_prev:
                problems.append(
                    f"{where} breaks the chain: expected prev_hash "
                    f"{expected_prev[:12]}..., got "
                    f"{str(record.get('prev_hash'))[:12]}..."
                )
            if record.get("hash") != hash_record(record):
                problems.append(f"{where} has been modified since it was written")
            expected_prev = record.get("hash")

    return problems
