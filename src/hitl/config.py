"""Configuration: built-in defaults, a TOML file, profiles, and the environment.

Precedence, highest first:

    1. an explicit argument (a CLI flag)
    2. a real environment variable        HITL_ATTEMPTS=5
    3. a `.env` file                      dev convenience only
    4. the selected profile               [profiles.prod]
    5. the file's shared section          [default]
    6. the built-in default

TOML, not YAML: `tomllib` is in the standard library and YAML is not, so
supporting both would mean taking a dependency to parse a second spelling of
the same three tables.

Two things this is deliberately strict about, because a config file is input
from outside the program:

  * A key nobody recognises is an error, not a no-op. `attemps = 10` silently
    doing nothing is precisely the bug that surfaces at 3am.
  * A secret may never come from the file. Config files get committed; the
    token has to come from the environment.

Everything is validated on load, and every problem is reported at once --
fixing one typo only to be told about the next is a miserable way to bring a
service up.
"""

from __future__ import annotations

import os
import tomllib
import urllib.parse
from dataclasses import dataclass, fields, replace
from pathlib import Path

DEFAULT_HOME = Path(".hitl")
DEFAULT_PROFILE = "dev"
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

# Never read from a TOML file, only from the environment.
SECRET_FIELDS = frozenset({"siem_token"})


class ConfigError(Exception):
    """The configuration could not be loaded, or is not usable."""


@dataclass(frozen=True)
class Config:
    home: Path = DEFAULT_HOME
    profile: str = DEFAULT_PROFILE
    log_level: str = "INFO"

    # Retry (see resilience.py for what is and is not retried).
    attempts: int = 3
    backoff: float = 0.5

    # Circuit breaker.
    breaker_threshold: int = 5
    breaker_recovery: float = 30.0

    # SIEM export.
    siem_url: str | None = None
    siem_token: str | None = None
    siem_batch_size: int = 100

    # Live Jira.
    jira_cloud_id: str | None = None
    jira_project_key: str = "KAN"

    # Paths are derived, never configured separately: three settings that
    # must agree is three chances for them to disagree.
    @property
    def audit_dir(self) -> Path:
        return self.home / "audit"

    @property
    def checkpoint_db(self) -> Path:
        return self.home / "checkpoints.sqlite"

    @property
    def identities_path(self) -> Path:
        return self.home / "identities.json"

    def redacted(self) -> dict:
        """Every setting, with secrets masked. Safe to print or log."""
        out = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in SECRET_FIELDS and value:
                value = "***"
            out[f.name] = str(value) if isinstance(value, Path) else value
        return out


_COERCE = {
    "home": Path,
    "profile": str,
    "log_level": lambda v: str(v).upper(),
    "attempts": int,
    "backoff": float,
    "breaker_threshold": int,
    "breaker_recovery": float,
    "siem_url": str,
    "siem_token": str,
    "siem_batch_size": int,
    "jira_cloud_id": str,
    "jira_project_key": str,
}

FIELD_NAMES = frozenset(_COERCE)


def env_name(field: str) -> str:
    """`attempts` -> `HITL_ATTEMPTS`."""
    return f"HITL_{field.upper()}"


def load_dotenv(path: Path) -> dict[str, str]:
    """Parse a `.env` file. Missing file is not an error.

    Deliberately tiny: `KEY=value`, `#` comments, an optional `export` prefix
    and optional surrounding quotes. Anything fancier belongs in the real
    environment, and a dependency to read eight lines of parsing is not a
    trade worth making.
    """
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _reject_unknown(section: dict, where: str, problems: list[str]) -> dict:
    for key in section:
        if key not in FIELD_NAMES:
            problems.append(f"{where}: unknown setting {key!r}")
        elif key in SECRET_FIELDS:
            problems.append(
                f"{where}: {key!r} is a secret and must come from "
                f"{env_name(key)}, not from a config file"
            )
    return {k: v for k, v in section.items() if k in FIELD_NAMES and k not in SECRET_FIELDS}


def _coerce(values: dict, problems: list[str]) -> dict:
    out = {}
    for key, value in values.items():
        try:
            out[key] = _COERCE[key](value)
        except (TypeError, ValueError):
            problems.append(f"{key}: cannot read {value!r} as {_COERCE[key].__name__}")
    return out


def _validate(config: Config, problems: list[str]) -> None:
    if config.attempts < 1:
        problems.append("attempts must be >= 1")
    if config.backoff < 0:
        problems.append("backoff must be >= 0")
    if config.breaker_threshold < 1:
        problems.append("breaker_threshold must be >= 1")
    if config.breaker_recovery < 0:
        problems.append("breaker_recovery must be >= 0")
    if config.siem_batch_size < 1:
        problems.append("siem_batch_size must be >= 1")
    if config.log_level not in LOG_LEVELS:
        problems.append(
            f"log_level {config.log_level!r} is not one of {sorted(LOG_LEVELS)}"
        )
    if config.siem_url:
        # Same trust boundary siem.py guards: a `file:` URL would make the
        # exporter read local disk instead of shipping anywhere.
        scheme = urllib.parse.urlparse(config.siem_url).scheme.lower()
        if scheme not in ("http", "https"):
            problems.append(f"siem_url must be http or https, got {scheme or '(none)'!r}")


def load_config(
    *,
    path: Path | None = None,
    env: dict[str, str] | None = None,
    dotenv: Path | None = None,
    **overrides,
) -> Config:
    """Resolve the configuration, or raise `ConfigError` listing every problem.

    `overrides` are the highest-precedence layer and exist for CLI flags.
    Passing None for one means "not supplied", so a flag left off never
    overrides the file with its own default.
    """
    problems: list[str] = []
    supplied = {}
    for key, value in overrides.items():
        if value is None:
            continue  # a flag that was left off, not a request for the default
        if key not in FIELD_NAMES:
            # Recorded and then dropped: carrying it further only trades this
            # message for a KeyError in `_coerce`.
            problems.append(f"unknown setting {key!r}")
            continue
        supplied[key] = value

    merged_env = dict(os.environ if env is None else env)
    # A `.env` file is a dev convenience and must never beat the real
    # environment -- otherwise a stale file silently overrides what an
    # operator just exported.
    for key, value in load_dotenv(Path(".env") if dotenv is None else dotenv).items():
        merged_env.setdefault(key, value)

    # `home` has to settle first, because it is where the config file lives.
    home = Path(
        supplied.get("home") or merged_env.get(env_name("home")) or DEFAULT_HOME
    )
    config_file = (
        path
        or (Path(merged_env["HITL_CONFIG"]) if merged_env.get("HITL_CONFIG") else None)
        or home / "config.toml"
    )

    data: dict = {}
    if config_file.exists():
        try:
            data = tomllib.loads(config_file.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as exc:
            raise ConfigError(f"{config_file}: {exc}") from exc
    elif path is not None:
        # An explicitly named file that is not there is a mistake, unlike the
        # conventional one that simply may not exist yet.
        raise ConfigError(f"no such config file: {config_file}")

    profiles = data.get("profiles", {})
    profile = (
        supplied.get("profile")
        or merged_env.get(env_name("profile"))
        or data.get("profile")
        or DEFAULT_PROFILE
    )
    if profiles and profile not in profiles and profile != DEFAULT_PROFILE:
        problems.append(
            f"unknown profile {profile!r}; {config_file.name} defines "
            f"{sorted(profiles)}"
        )

    values: dict = {"profile": profile}
    values.update(_reject_unknown(data.get("default", {}), "[default]", problems))
    values.update(
        _reject_unknown(profiles.get(profile, {}), f"[profiles.{profile}]", problems)
    )
    values.update(
        {f: merged_env[env_name(f)] for f in FIELD_NAMES if env_name(f) in merged_env}
    )
    values.update(supplied)

    config = replace(Config(), **_coerce(values, problems))
    _validate(config, problems)

    if problems:
        raise ConfigError(
            "invalid configuration:\n" + "\n".join(f"  - {p}" for p in problems)
        )
    return config
