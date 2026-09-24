"""The CLI is where `--as <who>` enters the system, so it is where an
unauthorised approval has to visibly fail -- with a non-zero exit code an
operator can gate on, and a trail that still verifies afterwards.
"""

import json

from hitl.cli import main

SUBMIT_HIGH = ["submit", "transition P-1 to Done", "--seed", "P-1=To Do"]


def _submit(tmp_path, capsys, argv=None):
    main(["--home", str(tmp_path), *(argv or SUBMIT_HIGH)])
    out = capsys.readouterr().out
    return next(ln.split()[-1] for ln in out.splitlines() if "request_id" in ln)


def _run(tmp_path, *argv):
    return main(["--home", str(tmp_path), *argv])


def _trail(tmp_path):
    records = []
    for f in sorted((tmp_path / "audit").glob("*.jsonl")):
        records += [json.loads(ln) for ln in f.read_text().strip().splitlines()]
    return records


# --- users ----------------------------------------------------------------


def test_users_add_writes_the_identities_file(tmp_path, capsys):
    assert _run(tmp_path, "users", "add", "ash", "--level", "lead") == 0
    assert json.loads((tmp_path / "identities.json").read_text()) == {"ash": "lead"}


def test_users_add_keeps_existing_users(tmp_path, capsys):
    _run(tmp_path, "users", "add", "ash", "--level", "lead")
    _run(tmp_path, "users", "add", "sam", "--level", "junior")
    assert json.loads((tmp_path / "identities.json").read_text()) == {
        "ash": "lead",
        "sam": "junior",
    }


def test_users_add_updates_a_level(tmp_path, capsys):
    _run(tmp_path, "users", "add", "ash", "--level", "junior")
    _run(tmp_path, "users", "add", "ash", "--level", "lead")
    assert json.loads((tmp_path / "identities.json").read_text()) == {"ash": "lead"}


def test_users_rm_revokes(tmp_path, capsys):
    _run(tmp_path, "users", "add", "ash", "--level", "lead")
    assert _run(tmp_path, "users", "rm", "ash") == 0
    assert json.loads((tmp_path / "identities.json").read_text()) == {}


def test_users_rm_of_an_unknown_user_exits_nonzero(tmp_path, capsys):
    assert _run(tmp_path, "users", "rm", "nobody") == 1
    assert "no such user" in capsys.readouterr().out


def test_users_list_shows_levels(tmp_path, capsys):
    _run(tmp_path, "users", "add", "ash", "--level", "lead")
    _run(tmp_path, "users", "add", "sam", "--level", "junior")
    capsys.readouterr()

    assert _run(tmp_path, "users", "list") == 0
    assert capsys.readouterr().out.splitlines() == ["ash: lead", "sam: junior"]


def test_users_list_on_a_fresh_home_is_empty(tmp_path, capsys):
    assert _run(tmp_path, "users", "list") == 0
    assert capsys.readouterr().out == ""


# --- the rejection path ---------------------------------------------------


def test_a_fresh_install_approves_nothing(tmp_path, capsys):
    """No identities file means no approvers. Out of the box, nothing executes."""
    rid = _submit(tmp_path, capsys)
    rc = _run(tmp_path, "approve", rid, "--as", "ash", "--seed", "P-1=To Do")

    assert rc == 3
    assert "REJECTED" in capsys.readouterr().out
    assert _trail(tmp_path)[-1]["final_decision"] == "denied"


def test_an_unregistered_approver_is_rejected(tmp_path, capsys):
    _run(tmp_path, "users", "add", "sam", "--level", "lead")
    rid = _submit(tmp_path, capsys)

    assert _run(tmp_path, "approve", rid, "--as", "ash", "--seed", "P-1=To Do") == 3
    assert "unknown user: ash" in capsys.readouterr().out


def test_an_under_privileged_approver_is_rejected(tmp_path, capsys):
    _run(tmp_path, "users", "add", "ash", "--level", "junior")
    rid = _submit(tmp_path, capsys)

    assert _run(tmp_path, "approve", rid, "--as", "ash", "--seed", "P-1=To Do") == 3
    out = capsys.readouterr().out
    assert "cannot approve at LEAD" in out


def test_a_registered_approver_succeeds(tmp_path, capsys):
    _run(tmp_path, "users", "add", "ash", "--level", "lead")
    rid = _submit(tmp_path, capsys)

    assert _run(tmp_path, "approve", rid, "--as", "ash", "--seed", "P-1=To Do") == 0
    assert "completed" in capsys.readouterr().out


def test_revocation_takes_effect_on_a_pending_request(tmp_path, capsys):
    """Someone approved-eligible at submit time, revoked before they act."""
    _run(tmp_path, "users", "add", "ash", "--level", "lead")
    rid = _submit(tmp_path, capsys)
    _run(tmp_path, "users", "rm", "ash")
    capsys.readouterr()

    assert _run(tmp_path, "approve", rid, "--as", "ash", "--seed", "P-1=To Do") == 3


def test_a_rejected_approval_lands_in_the_audit_trail(tmp_path, capsys):
    _run(tmp_path, "users", "add", "ash", "--level", "junior")
    rid = _submit(tmp_path, capsys)
    _run(tmp_path, "approve", rid, "--as", "ash", "--seed", "P-1=To Do")
    capsys.readouterr()

    records = [r for r in _trail(tmp_path) if r["request_id"] == rid]
    resumed = next(r for r in records if r["stage"] == "resumed")
    assert resumed["policy_checks"] == ["identity-rejected"]
    assert resumed["human_intervention"]["human_id"] == "ash"
    assert records[-1]["actions_taken"] == []


def test_the_chain_still_verifies_after_a_rejection(tmp_path, capsys):
    _run(tmp_path, "users", "add", "ash", "--level", "junior")
    rid = _submit(tmp_path, capsys)
    _run(tmp_path, "approve", rid, "--as", "ash", "--seed", "P-1=To Do")
    capsys.readouterr()

    assert _run(tmp_path, "verify") == 0


def test_a_junior_can_approve_a_low_tier_escalation(tmp_path, capsys):
    """The gate fired on ambiguity, not on risk -- a junior clears it."""
    _run(tmp_path, "users", "add", "sam", "--level", "junior")
    rid = _submit(
        tmp_path,
        capsys,
        ["submit", "comment P-1 maybe the deploy finished, unclear", "--seed", "P-1=To Do"],
    )

    assert _run(tmp_path, "approve", rid, "--as", "sam", "--seed", "P-1=To Do") == 0
    assert "completed" in capsys.readouterr().out


def test_a_bad_level_in_a_hand_edited_file_grants_nothing(tmp_path, capsys):
    (tmp_path / "identities.json").write_text(json.dumps({"ash": "admin"}))
    rid = _submit(tmp_path, capsys)

    assert _run(tmp_path, "approve", rid, "--as", "ash", "--seed", "P-1=To Do") == 3
