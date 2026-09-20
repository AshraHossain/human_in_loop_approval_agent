import json

import pytest

from hitl.cli import main, parse_action


def test_parse_transition():
    a = parse_action("transition P-1 to Done")
    assert (a.kind, a.issue_key, a.target_status) == ("transition", "P-1", "Done")


def test_parse_comment():
    a = parse_action("comment P-1 deploy finished")
    assert (a.kind, a.issue_key, a.body) == ("add_comment", "P-1", "deploy finished")


def test_parse_create():
    a = parse_action("create crash on save")
    assert (a.kind, a.body) == ("create_issue", "crash on save")


def test_parse_unknown_raises():
    with pytest.raises(ValueError, match="cannot parse"):
        parse_action("do something vague")


def _request_id_from(out: str) -> str:
    return next(ln.split()[-1] for ln in out.splitlines() if "request_id" in ln)


def test_submit_low_risk_completes(tmp_path, capsys):
    rc = main(
        [
            "--home",
            str(tmp_path),
            "submit",
            "comment P-1 deploy finished",
            "--seed",
            "P-1=To Do",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "completed" in out


def test_submit_high_risk_pauses_and_approve_resumes(tmp_path, capsys):
    rc = main(
        [
            "--home",
            str(tmp_path),
            "submit",
            "transition P-1 to Done",
            "--seed",
            "P-1=To Do",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "APPROVAL REQUIRED" in out
    rid = _request_id_from(out)

    rc = main(
        ["--home", str(tmp_path), "approve", rid, "--as", "ash", "--seed", "P-1=To Do"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "completed" in out


def test_audit_command_replays_the_trail(tmp_path, capsys):
    main(
        [
            "--home",
            str(tmp_path),
            "submit",
            "transition P-1 to Done",
            "--seed",
            "P-1=To Do",
        ]
    )
    rid = _request_id_from(capsys.readouterr().out)
    main(
        ["--home", str(tmp_path), "deny", rid, "--as", "ash", "--seed", "P-1=To Do"]
    )
    capsys.readouterr()

    rc = main(["--home", str(tmp_path), "audit", rid])
    out = capsys.readouterr().out
    assert rc == 0
    records = [json.loads(ln) for ln in out.strip().splitlines()]
    assert {r["request_id"] for r in records} == {rid}
    assert records[-1]["final_decision"] == "denied"


def test_audit_trail_has_no_duplicate_records(tmp_path, capsys):
    """Regression: resume carries the accumulated audits list, so the CLI used
    to re-write records the submit process had already persisted."""
    main(
        [
            "--home",
            str(tmp_path),
            "submit",
            "transition P-1 to Done",
            "--seed",
            "P-1=To Do",
        ]
    )
    rid = _request_id_from(capsys.readouterr().out)
    main(
        ["--home", str(tmp_path), "approve", rid, "--as", "ash", "--seed", "P-1=To Do"]
    )
    capsys.readouterr()

    main(["--home", str(tmp_path), "audit", rid])
    lines = [ln for ln in capsys.readouterr().out.strip().splitlines() if ln.startswith("{")]
    records = [json.loads(ln) for ln in lines]

    identities = [(r["timestamp"], r["stage"]) for r in records]
    assert len(identities) == len(set(identities)), f"duplicate audit records: {identities}"
    assert [r["stage"] for r in records] == ["uncertain", "resumed", "completed"]


def test_checkpoint_holds_no_pickled_classes(tmp_path, capsys):
    """Regression: the Action dataclass was being pickled into the checkpoint,
    which LangGraph warns it will block in a future version."""
    main(
        [
            "--home",
            str(tmp_path),
            "submit",
            "transition P-1 to Done",
            "--seed",
            "P-1=To Do",
        ]
    )
    capsys.readouterr()
    blob = (tmp_path / "checkpoints.sqlite").read_bytes()
    assert b"hitl.policy" not in blob, "no app class may be serialized into a checkpoint"
