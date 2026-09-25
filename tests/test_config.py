"""Configuration loading.

A config file is input from outside the program, so the interesting cases are
the hostile ones: a typo'd key, a secret somewhere it must not be, a value
that parses but cannot work.
"""

import json
from pathlib import Path

import pytest
from hitl.config import (
    DEFAULT_PROFILE,
    Config,
    ConfigError,
    env_name,
    load_config,
    load_dotenv,
)


def _write(tmp_path, text, name="config.toml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _load(tmp_path, text=None, env=None, **kw):
    """Load from a config file written into `tmp_path`, with no ambient env."""
    path = _write(tmp_path, text) if text is not None else None
    kw.setdefault("dotenv", tmp_path / "nonexistent.env")
    return load_config(path=path, env=env or {}, **kw)


# --- defaults -------------------------------------------------------------


def test_everything_has_a_working_default():
    cfg = load_config(env={}, dotenv=Path("/nonexistent/.env"))
    assert cfg.profile == DEFAULT_PROFILE
    assert cfg.attempts == 3
    assert cfg.log_level == "INFO"
    assert cfg.siem_token is None


def test_paths_are_derived_from_home(tmp_path):
    cfg = _load(tmp_path, home=tmp_path)
    assert cfg.audit_dir == tmp_path / "audit"
    assert cfg.checkpoint_db == tmp_path / "checkpoints.sqlite"
    assert cfg.identities_path == tmp_path / "identities.json"


def test_a_missing_conventional_config_file_is_not_an_error(tmp_path):
    assert _load(tmp_path, home=tmp_path).attempts == 3


def test_a_missing_named_config_file_is_an_error(tmp_path):
    """Asking for a file by name and not getting it is a mistake worth saying."""
    with pytest.raises(ConfigError, match="no such config file"):
        load_config(path=tmp_path / "gone.toml", env={})


# --- the file -------------------------------------------------------------


def test_the_default_section_is_read(tmp_path):
    assert _load(tmp_path, "[default]\nattempts = 7\n").attempts == 7


def test_the_conventional_file_is_found_under_home(tmp_path):
    _write(tmp_path, "[default]\nattempts = 9\n")
    assert load_config(home=tmp_path, env={}, dotenv=tmp_path / "no.env").attempts == 9


def test_types_come_from_the_toml(tmp_path):
    cfg = _load(tmp_path, "[default]\nbackoff = 2.5\nbreaker_threshold = 8\n")
    assert cfg.backoff == 2.5
    assert cfg.breaker_threshold == 8


def test_broken_toml_names_the_file(tmp_path):
    with pytest.raises(ConfigError, match=r"config\.toml"):
        _load(tmp_path, "[default\nattempts = 1\n")


# --- profiles -------------------------------------------------------------

PROFILED = """
[default]
attempts = 3
log_level = "INFO"

[profiles.dev]
log_level = "DEBUG"

[profiles.prod]
attempts = 5
breaker_threshold = 10
"""


def test_a_profile_overrides_the_default_section(tmp_path):
    cfg = _load(tmp_path, PROFILED, profile="prod")
    assert cfg.attempts == 5
    assert cfg.breaker_threshold == 10


def test_settings_the_profile_does_not_mention_fall_through(tmp_path):
    assert _load(tmp_path, PROFILED, profile="prod").log_level == "INFO"


def test_the_file_may_name_the_active_profile(tmp_path):
    cfg = _load(tmp_path, 'profile = "prod"\n' + PROFILED)
    assert cfg.profile == "prod"
    assert cfg.attempts == 5


def test_an_explicit_profile_beats_the_file(tmp_path):
    cfg = _load(tmp_path, 'profile = "prod"\n' + PROFILED, profile="dev")
    assert cfg.log_level == "DEBUG"


def test_the_environment_can_select_the_profile(tmp_path):
    cfg = _load(tmp_path, PROFILED, env={env_name("profile"): "prod"})
    assert cfg.attempts == 5


def test_an_unknown_profile_is_an_error(tmp_path):
    """Silently falling back to defaults would deploy dev settings to prod."""
    with pytest.raises(ConfigError, match="unknown profile 'staging'"):
        _load(tmp_path, PROFILED, profile="staging")


def test_the_error_lists_the_profiles_that_do_exist(tmp_path):
    with pytest.raises(ConfigError, match=r"\['dev', 'prod'\]"):
        _load(tmp_path, PROFILED, profile="staging")


# --- precedence -----------------------------------------------------------


def test_the_environment_beats_the_file(tmp_path):
    cfg = _load(tmp_path, "[default]\nattempts = 3\n", env={env_name("attempts"): "11"})
    assert cfg.attempts == 11


def test_an_explicit_argument_beats_the_environment(tmp_path):
    cfg = _load(
        tmp_path, "[default]\nattempts = 3\n", env={env_name("attempts"): "11"}, attempts=2
    )
    assert cfg.attempts == 2


def test_an_omitted_argument_does_not_override(tmp_path):
    """A flag left off the command line must fall through to the file rather
    than overwrite it with argparse's idea of a default."""
    cfg = _load(tmp_path, "[default]\nattempts = 7\n", attempts=None, home=None)
    assert cfg.attempts == 7


def test_a_dotenv_file_is_read(tmp_path):
    env_file = _write(tmp_path, "HITL_ATTEMPTS=4\n", name=".env")
    cfg = load_config(env={}, dotenv=env_file)
    assert cfg.attempts == 4


def test_the_real_environment_beats_a_dotenv_file(tmp_path):
    """A stale .env must not override what an operator just exported."""
    env_file = _write(tmp_path, "HITL_ATTEMPTS=4\n", name=".env")
    cfg = load_config(env={env_name("attempts"): "9"}, dotenv=env_file)
    assert cfg.attempts == 9


def test_a_dotenv_file_beats_the_config_file(tmp_path):
    env_file = _write(tmp_path, "HITL_ATTEMPTS=4\n", name=".env")
    path = _write(tmp_path, "[default]\nattempts = 3\n")
    assert load_config(path=path, env={}, dotenv=env_file).attempts == 4


# --- dotenv parsing -------------------------------------------------------


def test_a_missing_dotenv_is_empty(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == {}


@pytest.mark.parametrize(
    "line,expected",
    [
        ("A=1", {"A": "1"}),
        ("export A=1", {"A": "1"}),
        ("  A = 1  ", {"A": "1"}),
        ('A="quoted"', {"A": "quoted"}),
        ("A='quoted'", {"A": "quoted"}),
        ("# comment", {}),
        ("", {}),
        ("no_equals_sign", {}),
        ("A=", {"A": ""}),
        ("A=b=c", {"A": "b=c"}),
    ],
)
def test_dotenv_lines(tmp_path, line, expected):
    assert load_dotenv(_write(tmp_path, line + "\n", name=".env")) == expected


# --- rejecting nonsense ---------------------------------------------------


def test_an_unknown_key_in_the_file_is_an_error(tmp_path):
    """`attemps = 10` quietly doing nothing is the 3am bug this prevents."""
    with pytest.raises(ConfigError, match="unknown setting 'attemps'"):
        _load(tmp_path, "[default]\nattemps = 10\n")


def test_an_unknown_key_in_a_profile_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match=r"\[profiles.prod\]: unknown setting"):
        _load(tmp_path, "[profiles.prod]\nnonsense = 1\n", profile="prod")


def test_an_unknown_override_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="unknown setting 'nope'"):
        _load(tmp_path, nope=1)


def test_a_value_of_the_wrong_type_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read 'lots' as int"):
        _load(tmp_path, env={env_name("attempts"): "lots"})


def test_every_problem_is_reported_at_once(tmp_path):
    """Fixing one typo only to be told about the next is a miserable way to
    bring a service up."""
    with pytest.raises(ConfigError) as excinfo:
        _load(tmp_path, "[default]\nattempts = 0\nbackoff = -1\nlog_level = 'LOUD'\n")

    message = str(excinfo.value)
    assert "attempts must be >= 1" in message
    assert "backoff must be >= 0" in message
    assert "log_level" in message


@pytest.mark.parametrize(
    "toml,expected",
    [
        ("[default]\nattempts = 0\n", "attempts must be >= 1"),
        ("[default]\nbackoff = -0.5\n", "backoff must be >= 0"),
        ("[default]\nbreaker_threshold = 0\n", "breaker_threshold must be >= 1"),
        ("[default]\nbreaker_recovery = -1\n", "breaker_recovery must be >= 0"),
        ("[default]\nsiem_batch_size = 0\n", "siem_batch_size must be >= 1"),
        ("[default]\nlog_level = 'CHATTY'\n", "log_level"),
    ],
)
def test_values_that_parse_but_cannot_work_are_rejected(tmp_path, toml, expected):
    with pytest.raises(ConfigError, match=expected):
        _load(tmp_path, toml)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/x", "/just/a/path"])
def test_a_non_http_siem_url_is_rejected(tmp_path, url):
    """Same trust boundary siem.py guards: a file: URL reads local disk."""
    with pytest.raises(ConfigError, match="siem_url must be http or https"):
        _load(tmp_path, f'[default]\nsiem_url = "{url}"\n')


@pytest.mark.parametrize("url", ["http://siem.local/x", "https://siem.example.com/e"])
def test_an_http_siem_url_is_accepted(tmp_path, url):
    assert _load(tmp_path, f'[default]\nsiem_url = "{url}"\n').siem_url == url


# --- secrets --------------------------------------------------------------


def test_a_secret_in_the_config_file_is_refused(tmp_path):
    """Config files get committed. Tokens must not live in one."""
    with pytest.raises(ConfigError, match="is a secret and must come from"):
        _load(tmp_path, '[default]\nsiem_token = "s3cret"\n')


def test_the_refusal_names_the_variable_to_use_instead(tmp_path):
    with pytest.raises(ConfigError, match="HITL_SIEM_TOKEN"):
        _load(tmp_path, '[default]\nsiem_token = "s3cret"\n')


def test_a_secret_in_a_profile_is_refused_too(tmp_path):
    with pytest.raises(ConfigError, match="is a secret"):
        _load(tmp_path, '[profiles.prod]\nsiem_token = "s3cret"\n', profile="prod")


def test_a_secret_from_the_environment_is_accepted(tmp_path):
    cfg = _load(tmp_path, env={env_name("siem_token"): "s3cret"})
    assert cfg.siem_token == "s3cret"


def test_a_secret_from_a_dotenv_file_is_accepted(tmp_path):
    """Which is the whole reason .env support is here."""
    env_file = _write(tmp_path, "HITL_SIEM_TOKEN=s3cret\n", name=".env")
    assert load_config(env={}, dotenv=env_file).siem_token == "s3cret"


def test_redacted_masks_the_token():
    cfg = Config(siem_token="s3cret")
    assert cfg.redacted()["siem_token"] == "***"


def test_redacted_does_not_invent_a_mask_for_an_absent_token():
    assert Config().redacted()["siem_token"] is None


def test_redacted_keeps_everything_else():
    out = Config(attempts=7).redacted()
    assert out["attempts"] == 7
    assert out["home"] == ".hitl"


def test_redacted_is_json_serialisable():
    """It exists to be printed and logged, so Paths must already be strings."""
    assert json.loads(json.dumps(Config().redacted()))["profile"] == DEFAULT_PROFILE
