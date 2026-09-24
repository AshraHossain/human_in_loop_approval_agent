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


def _register(home, user_id="ash", level="lead"):
    """Give `home` an approver. Without one the CLI approves nothing."""
    path = home / "identities.json"
    users = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    users[user_id] = level
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(users), encoding="utf-8")


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
    _register(tmp_path)
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
    _register(tmp_path)
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
    _register(tmp_path)
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


def test_audit_for_an_unknown_request_exits_nonzero(tmp_path, capsys):
    rc = main(["--home", str(tmp_path), "audit", "no-such-request"])
    assert rc == 1
    assert "no audit records" in capsys.readouterr().out


def test_submit_with_an_unparseable_request_exits_two(tmp_path, capsys):
    rc = main(["--home", str(tmp_path), "submit", "do something vague"])
    assert rc == 2
    assert "cannot parse" in capsys.readouterr().out


def test_an_unparseable_request_writes_no_audit_trail(tmp_path, capsys):
    main(["--home", str(tmp_path), "submit", "do something vague"])
    capsys.readouterr()
    assert not list((tmp_path / "audit").glob("*.jsonl"))


def test_verify_reports_an_intact_trail(tmp_path, capsys):
    _register(tmp_path)
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

    rc = main(["--home", str(tmp_path), "verify"])
    assert rc == 0
    assert "intact" in capsys.readouterr().out


def test_verify_on_an_empty_home_is_clean(tmp_path, capsys):
    rc = main(["--home", str(tmp_path), "verify"])
    assert rc == 0
    assert "intact" in capsys.readouterr().out


def test_verify_catches_an_edited_trail(tmp_path, capsys):
    """The whole point of the chain: an edited decision cannot pass verify."""
    _register(tmp_path)
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
    main(["--home", str(tmp_path), "deny", rid, "--as", "ash", "--seed", "P-1=To Do"])
    capsys.readouterr()

    trail = next((tmp_path / "audit").glob("*.jsonl"))
    records = [json.loads(ln) for ln in trail.read_text().strip().splitlines()]
    records[-1]["final_decision"] = "executed"  # rewrite a denial into an approval
    trail.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    rc = main(["--home", str(tmp_path), "verify"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "COMPROMISED" in out


def test_verify_catches_a_removed_record(tmp_path, capsys):
    _register(tmp_path)
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

    trail = next((tmp_path / "audit").glob("*.jsonl"))
    lines = trail.read_text().strip().splitlines()
    trail.write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")

    assert main(["--home", str(tmp_path), "verify"]) == 1


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
