"""Configuration as the CLI actually resolves it.

`test_config.py` covers the loader. This covers the wiring: that the flags
reach it, that a bad config stops the run before anything is written, and
that `hitl config` reports what was actually resolved.
"""

import json

import pytest
from hitl.cli import main


def _run(tmp_path, *argv):
    return main(["--home", str(tmp_path), *argv])


def _config(tmp_path, capsys, *global_flags):
    """Global flags precede the subcommand, as they do for --home."""
    assert _run(tmp_path, *global_flags, "config", "--json") == 0
    return json.loads(capsys.readouterr().out)


# --- the config command ---------------------------------------------------


def test_config_prints_the_resolved_settings(tmp_path, capsys):
    resolved = _config(tmp_path, capsys)
    assert resolved["attempts"] == 3
    assert resolved["home"] == str(tmp_path)


def test_config_prints_readable_text_without_json(tmp_path, capsys):
    assert _run(tmp_path, "config") == 0
    assert "attempts = 3" in capsys.readouterr().out


def test_config_reflects_the_config_file(tmp_path, capsys):
    (tmp_path / "config.toml").write_text("[default]\nattempts = 8\n")
    assert _config(tmp_path, capsys)["attempts"] == 8


def test_config_reflects_the_selected_profile(tmp_path, capsys):
    (tmp_path / "config.toml").write_text(
        "[default]\nattempts = 3\n\n[profiles.prod]\nattempts = 6\n"
    )
    resolved = _config(tmp_path, capsys, "--profile", "prod")
    assert resolved["profile"] == "prod"
    assert resolved["attempts"] == 6


def test_config_never_prints_the_token(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HITL_SIEM_TOKEN", "s3cret")
    out = _config(tmp_path, capsys)
    assert out["siem_token"] == "***"
    assert "s3cret" not in json.dumps(out)


def test_an_explicit_config_file_is_used(tmp_path, capsys):
    elsewhere = tmp_path / "custom.toml"
    elsewhere.write_text("[default]\nattempts = 12\n")
    assert _config(tmp_path, capsys, "--config", str(elsewhere))["attempts"] == 12


# --- the environment ------------------------------------------------------


def test_the_environment_configures_the_cli(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HITL_ATTEMPTS", "7")
    assert _config(tmp_path, capsys)["attempts"] == 7


def test_home_can_come_from_the_environment(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HITL_HOME", str(tmp_path / "elsewhere"))
    assert main(["config", "--json"]) == 0
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["home"] == str(tmp_path / "elsewhere")


def test_the_home_flag_beats_the_environment(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HITL_HOME", str(tmp_path / "ignored"))
    assert _config(tmp_path, capsys)["home"] == str(tmp_path)


def test_a_dotenv_file_in_the_working_directory_is_read(tmp_path, capsys):
    # conftest puts every test in its own empty cwd, so this .env is ours.
    from pathlib import Path

    Path(".env").write_text("HITL_ATTEMPTS=5\n", encoding="utf-8")
    assert _config(tmp_path, capsys)["attempts"] == 5


# --- failing before doing damage ------------------------------------------


def test_a_broken_config_exits_two_and_explains(tmp_path, capsys):
    (tmp_path / "config.toml").write_text("[default]\nattempts = 0\n")
    assert _run(tmp_path, "config") == 2
    assert "attempts must be >= 1" in capsys.readouterr().out


def test_a_broken_config_stops_a_submit_before_anything_is_written(tmp_path, capsys):
    """Config is validated at startup precisely so a run cannot get halfway."""
    (tmp_path / "config.toml").write_text("[default]\nlog_level = 'LOUD'\n")

    rc = _run(tmp_path, "submit", "transition P-1 to Done", "--seed", "P-1=To Do")

    assert rc == 2
    assert not (tmp_path / "audit").exists(), "no trail from a run that never started"
    assert not (tmp_path / "checkpoints.sqlite").exists()


def test_a_typo_in_the_config_file_is_refused(tmp_path, capsys):
    (tmp_path / "config.toml").write_text("[default]\nattemps = 10\n")
    assert _run(tmp_path, "config") == 2
    assert "unknown setting 'attemps'" in capsys.readouterr().out


def test_a_token_in_the_config_file_is_refused(tmp_path, capsys):
    (tmp_path / "config.toml").write_text('[default]\nsiem_token = "s3cret"\n')
    assert _run(tmp_path, "config") == 2
    assert "must come from HITL_SIEM_TOKEN" in capsys.readouterr().out


def test_an_unknown_profile_is_refused(tmp_path, capsys):
    (tmp_path / "config.toml").write_text("[profiles.prod]\nattempts = 5\n")
    assert _run(tmp_path, "--profile", "staging", "config") == 2
    assert "unknown profile" in capsys.readouterr().out


# --- config drives the real commands --------------------------------------


def test_the_approval_flow_still_works_under_a_profile(tmp_path, capsys):
    (tmp_path / "config.toml").write_text(
        "[default]\nattempts = 3\n\n[profiles.prod]\nbreaker_threshold = 10\n"
    )
    (tmp_path / "identities.json").write_text('{"ash": "lead"}')

    assert (
        _run(tmp_path, "--profile", "prod", "submit", "transition P-1 to Done",
             "--seed", "P-1=To Do") == 0
    )
    out = capsys.readouterr().out
    rid = next(ln.split()[-1] for ln in out.splitlines() if "request_id" in ln)

    rc = _run(tmp_path, "--profile", "prod", "approve", rid, "--as", "ash",
              "--seed", "P-1=To Do")
    assert rc == 0
    assert "completed" in capsys.readouterr().out


def test_home_from_the_environment_places_the_audit_trail(tmp_path, capsys, monkeypatch):
    home = tmp_path / "configured"
    monkeypatch.setenv("HITL_HOME", str(home))

    assert main(["submit", "comment P-1 deploy finished", "--seed", "P-1=To Do"]) == 0
    capsys.readouterr()
    assert list((home / "audit").glob("*.jsonl")), "trail follows configured home"


@pytest.mark.parametrize("level", ["DEBUG", "WARNING"])
def test_the_log_level_is_applied(tmp_path, capsys, level):
    import logging

    (tmp_path / "config.toml").write_text(f"[default]\nlog_level = '{level}'\n")
    _run(tmp_path, "config")
    assert logging.getLogger("hitl").level == getattr(logging, level)
