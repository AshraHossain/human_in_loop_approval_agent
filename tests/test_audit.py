import json
from datetime import datetime
from pathlib import Path

from hitl.audit import append_audit, make_audit, new_request_id

SCHEMA_KEYS = {
    "timestamp", "request_id", "stage", "input_summary", "policy_checks",
    "confidence_level", "risk_assessment", "human_intervention",
    "final_decision", "actions_taken",
}


def _rec(**kw):
    base = {
        "request_id": "req-1",
        "stage": "analysis",
        "input_summary": "do a thing",
        "policy_checks": ["tier:low"],
        "confidence_level": "high",
        "risk_assessment": "none",
        "human_required": False,
    }
    base.update(kw)
    return make_audit(**base)


def test_schema_keys_exact():
    assert set(_rec()) == SCHEMA_KEYS


def test_timestamp_is_timezone_aware_utc():
    ts = datetime.fromisoformat(_rec()["timestamp"])
    assert ts.tzinfo is not None, "audit timestamps must be tz-aware"
    assert ts.utcoffset().total_seconds() == 0


def test_request_id_is_never_regenerated():
    # The whole point: two stages of one request share an ID.
    a = _rec(stage="analysis")
    b = _rec(stage="completed")
    assert a["request_id"] == b["request_id"] == "req-1"


def test_new_request_id_is_unique():
    assert new_request_id() != new_request_id()


def test_human_intervention_block_shape():
    r = _rec(human_required=True, human_reason="high tier",
             human_decision="approve", human_id="ash")
    assert r["human_intervention"] == {
        "required": True, "reason": "high tier",
        "human_decision": "approve", "human_id": "ash",
    }


def test_append_audit_is_append_only_jsonl(tmp_path: Path):
    p1 = append_audit(_rec(stage="analysis"), tmp_path)
    p2 = append_audit(_rec(stage="completed"), tmp_path)
    assert p1 == p2, "same day -> same file"
    lines = p1.read_text().strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(x)["stage"] for x in lines] == ["analysis", "completed"]
