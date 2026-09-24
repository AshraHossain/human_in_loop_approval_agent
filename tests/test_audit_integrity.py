"""The chain is only worth having if it actually catches tampering.

Every test here mutates a written trail the way an attacker (or a bug) would,
and asserts verify_chain reports it.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from hitl.audit import (
    GENESIS_HASH,
    append_audit,
    hash_record,
    last_hash,
    make_audit,
    verify_chain,
)


def _rec(stage="analysis", request_id="req-1"):
    return make_audit(
        request_id=request_id,
        stage=stage,
        input_summary="do a thing",
        policy_checks=["tier:low"],
        confidence_level="high",
        risk_assessment="none",
        human_required=False,
    )


def _read(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().strip().splitlines()]


def _rewrite(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


# --- chain construction ---------------------------------------------------


def test_first_record_links_to_genesis(tmp_path):
    path = append_audit(_rec(), tmp_path)
    assert _read(path)[0]["prev_hash"] == GENESIS_HASH


def test_each_record_links_to_its_predecessor(tmp_path):
    append_audit(_rec(stage="uncertain"), tmp_path)
    append_audit(_rec(stage="resumed"), tmp_path)
    path = append_audit(_rec(stage="completed"), tmp_path)

    records = _read(path)
    assert records[1]["prev_hash"] == records[0]["hash"]
    assert records[2]["prev_hash"] == records[1]["hash"]


def test_last_hash_is_genesis_for_an_empty_dir(tmp_path):
    assert last_hash(tmp_path) == GENESIS_HASH


def test_last_hash_is_genesis_for_a_missing_dir(tmp_path):
    assert last_hash(tmp_path / "nope") == GENESIS_HASH


def test_last_hash_tracks_the_newest_record(tmp_path):
    append_audit(_rec(stage="one"), tmp_path)
    path = append_audit(_rec(stage="two"), tmp_path)
    assert last_hash(tmp_path) == _read(path)[-1]["hash"]


def test_hash_excludes_the_hash_field_itself(tmp_path):
    path = append_audit(_rec(), tmp_path)
    stored = _read(path)[0]
    # Recomputing over the stored record (which now contains `hash`) must
    # reproduce that same hash, or verification could never succeed.
    assert hash_record(stored) == stored["hash"]


def test_hash_is_independent_of_key_order():
    record = _rec()
    shuffled = dict(reversed(list(record.items())))
    assert hash_record(record) == hash_record(shuffled)


def test_make_audit_does_not_carry_chain_fields():
    # The chain belongs to the stored trail, not to a constructed record.
    record = _rec()
    assert "hash" not in record
    assert "prev_hash" not in record


# --- tamper detection -----------------------------------------------------


def test_intact_trail_verifies_clean(tmp_path):
    for stage in ("uncertain", "resumed", "completed"):
        append_audit(_rec(stage=stage), tmp_path)
    assert verify_chain(tmp_path) == []


def test_verify_clean_on_empty_dir(tmp_path):
    assert verify_chain(tmp_path) == []


def test_verify_clean_on_missing_dir(tmp_path):
    assert verify_chain(tmp_path / "nope") == []


def test_modifying_a_record_is_detected(tmp_path):
    append_audit(_rec(stage="uncertain"), tmp_path)
    path = append_audit(_rec(stage="completed"), tmp_path)

    records = _read(path)
    records[0]["human_intervention"]["human_id"] = "mallory"
    _rewrite(path, records)

    problems = verify_chain(tmp_path)
    assert any("modified" in p for p in problems)


def test_flipping_a_denial_to_an_approval_is_detected(tmp_path):
    append_audit(_rec(stage="uncertain"), tmp_path)
    path = append_audit(_rec(stage="completed"), tmp_path)

    records = _read(path)
    records[1]["final_decision"] = "executed"
    _rewrite(path, records)

    assert verify_chain(tmp_path) != []


def test_deleting_a_record_is_detected(tmp_path):
    append_audit(_rec(stage="uncertain"), tmp_path)
    append_audit(_rec(stage="resumed"), tmp_path)
    path = append_audit(_rec(stage="completed"), tmp_path)

    records = _read(path)
    _rewrite(path, [records[0], records[2]])  # drop the middle one

    problems = verify_chain(tmp_path)
    assert any("breaks the chain" in p for p in problems)


def test_deleting_the_last_record_is_not_silently_lost(tmp_path):
    # Truncation is the one edit a chain alone cannot see, so the next append
    # must not paper over it: the new record links to the surviving tail.
    append_audit(_rec(stage="one"), tmp_path)
    path = append_audit(_rec(stage="two"), tmp_path)
    records = _read(path)
    _rewrite(path, records[:1])

    append_audit(_rec(stage="three"), tmp_path)
    after = _read(path)
    assert after[1]["prev_hash"] == after[0]["hash"]
    assert verify_chain(tmp_path) == []


def test_reordering_records_is_detected(tmp_path):
    append_audit(_rec(stage="uncertain"), tmp_path)
    append_audit(_rec(stage="resumed"), tmp_path)
    path = append_audit(_rec(stage="completed"), tmp_path)

    records = _read(path)
    _rewrite(path, [records[0], records[2], records[1]])

    assert verify_chain(tmp_path) != []


def test_appending_a_forged_record_is_detected(tmp_path):
    path = append_audit(_rec(stage="uncertain"), tmp_path)

    forged = _rec(stage="completed")
    forged["prev_hash"] = _read(path)[0]["hash"]
    forged["hash"] = "f" * 64  # attacker cannot produce a valid digest
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged) + "\n")

    problems = verify_chain(tmp_path)
    assert any("modified" in p for p in problems)


def test_corrupt_json_is_reported_not_raised(tmp_path):
    path = append_audit(_rec(), tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")

    problems = verify_chain(tmp_path)
    assert any("not valid JSON" in p for p in problems)


# --- the chain spans day files -------------------------------------------


def _on_day(day: str):
    """Pin the audit module's clock so append_audit writes that day's file."""
    stamp = datetime(2026, 1, int(day), tzinfo=UTC)

    class _Clock:
        @staticmethod
        def now(tz=None):  # noqa: ARG004  -- matches datetime.now's signature
            return stamp

    return patch("hitl.audit.datetime", _Clock)


def test_chain_continues_across_day_files(tmp_path):
    with _on_day("01"):
        append_audit(_rec(stage="day-one"), tmp_path)
    with _on_day("02"):
        append_audit(_rec(stage="day-two"), tmp_path)

    files = sorted(tmp_path.glob("*.jsonl"))
    assert len(files) == 2, "expected one file per day"

    first = _read(files[0])[-1]
    second = _read(files[1])[0]
    assert second["prev_hash"] == first["hash"]
    assert verify_chain(tmp_path) == []


def test_deleting_a_whole_day_file_is_detected(tmp_path):
    with _on_day("01"):
        append_audit(_rec(stage="day-one"), tmp_path)
    with _on_day("02"):
        append_audit(_rec(stage="day-two"), tmp_path)
    with _on_day("03"):
        append_audit(_rec(stage="day-three"), tmp_path)

    sorted(tmp_path.glob("*.jsonl"))[1].unlink()  # drop the middle day

    problems = verify_chain(tmp_path)
    assert any("breaks the chain" in p for p in problems)
