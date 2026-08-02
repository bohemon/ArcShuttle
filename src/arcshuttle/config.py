"""Configuration loading and precedence handling."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import UsageError, parse_size


@dataclass(frozen=True, slots=True)
class ConfigProvenance:
    """Record whether I/O controls came from an explicit public setting.

    Direct ``Config`` construction is treated as explicit so internal callers and tests keep
    the exact budgets they supplied. ``resolve_config`` replaces these defaults with provenance
    derived from CLI, environment, and TOML inputs.
    """

    io_slots_explicit: bool = True
    storage_profile_explicit: bool = True


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved configuration shared by planning and execution."""

    sevenzip: str | None = None
    output_dir: Path | None = None
    existing: str = "fail"
    cpu_budget: int = max(1, (os.cpu_count() or 1) - 1)
    max_processes: int = min(4, max(1, (os.cpu_count() or 1) - 1))
    storage_profile: str = "auto"
    io_slots: int = min(2, min(4, max(1, (os.cpu_count() or 1) - 1)))
    heavy_threads: int = min(4, max(1, (os.cpu_count() or 1) - 1))
    small_threshold: int = 64 * 1024 * 1024
    inspect_threshold: int = 64 * 1024 * 1024
    inspect_timeout: float = 30.0
    reservation_delay: float = 30.0
    sequential_if_total_below: int = 0
    log_dir: Path | None = None
    quiet: bool = False
    fail_fast: bool = False
    allow_changed: bool = False
    on_input_error: str = "fail"
    create_format: str = "7z"
    compression_level: int = 5
    provenance: ConfigProvenance = field(
        default_factory=ConfigProvenance, repr=False, compare=False
    )

    @property
    def uses_auto_io_slots(self) -> bool:
        """Return whether runtime endpoint detection may replace the conservative default."""

        return not self.provenance.io_slots_explicit and self.storage_profile == "auto"


_ENV_NAMES = {
    "sevenzip": "ARCSHUTTLE_7Z",
    "output_dir": "ARCSHUTTLE_OUTPUT_DIR",
    "existing": "ARCSHUTTLE_EXISTING",
    "cpu_budget": "ARCSHUTTLE_CPU_BUDGET",
    "max_processes": "ARCSHUTTLE_MAX_PROCESSES",
    "storage_profile": "ARCSHUTTLE_STORAGE_PROFILE",
    "io_slots": "ARCSHUTTLE_IO_SLOTS",
    "heavy_threads": "ARCSHUTTLE_HEAVY_THREADS",
    "small_threshold": "ARCSHUTTLE_SMALL_THRESHOLD",
    "inspect_threshold": "ARCSHUTTLE_INSPECT_THRESHOLD",
    "inspect_timeout": "ARCSHUTTLE_INSPECT_TIMEOUT",
    "reservation_delay": "ARCSHUTTLE_RESERVATION_DELAY",
    "sequential_if_total_below": "ARCSHUTTLE_SEQUENTIAL_IF_TOTAL_BELOW",
    "log_dir": "ARCSHUTTLE_LOG_DIR",
    "quiet": "ARCSHUTTLE_QUIET",
    "fail_fast": "ARCSHUTTLE_FAIL_FAST",
    "allow_changed": "ARCSHUTTLE_ALLOW_CHANGED",
    "on_input_error": "ARCSHUTTLE_ON_INPUT_ERROR",
    "create_format": "ARCSHUTTLE_CREATE_FORMAT",
    "compression_level": "ARCSHUTTLE_COMPRESSION_LEVEL",
}

_CREATE_FIELDS = {"create_format", "compression_level"}
_LEGACY_ENV_NAMES = {
    name: env_name.replace("ARCSHUTTLE_", "PARXTRACT_", 1)
    for name, env_name in _ENV_NAMES.items()
    if name not in _CREATE_FIELDS
}

_SIZE_FIELDS = {"small_threshold", "inspect_threshold", "sequential_if_total_below"}
_INT_FIELDS = {"cpu_budget", "max_processes", "io_slots", "heavy_threads"}
_FLOAT_FIELDS = {"inspect_timeout", "reservation_delay"}
_BOOL_FIELDS = {"quiet", "fail_fast", "allow_changed"}
_PATH_FIELDS = {"output_dir", "log_dir"}


def _parse_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"1", "true", "yes", "on"}:
        return True
    if isinstance(value, str) and value.lower() in {"0", "false", "no", "off"}:
        return False
    raise UsageError(f"{name} must be a boolean")


def _coerce(name: str, value: Any) -> Any:
    try:
        if name in _SIZE_FIELDS:
            return parse_size(value)
        if name in _INT_FIELDS:
            if isinstance(value, str) and name == "cpu_budget" and value.lower() == "auto":
                return max(1, (os.cpu_count() or 1) - 1)
            result = int(value)
            if result < 1:
                raise ValueError
            return result
        if name == "compression_level":
            result = int(value)
            if not 0 <= result <= 9:
                raise ValueError
            return result
        if name in _FLOAT_FIELDS:
            result = float(value)
            if result < 0:
                raise ValueError
            return result
        if name in _BOOL_FIELDS:
            return _parse_bool(value, name)
        if name in _PATH_FIELDS:
            return Path(value).expanduser().resolve(strict=False) if value is not None else None
        return value
    except (TypeError, ValueError) as exc:
        raise UsageError(f"invalid value for {name}: {value!r}") from exc


def _validate_toml_values(
    values: Mapping[str, Any], source: str, *, allow_create: bool = True
) -> dict[str, Any]:
    known = set(_ENV_NAMES)
    if not allow_create:
        known -= _CREATE_FIELDS
    unknown = set(values) - known
    if unknown:
        raise UsageError(f"unknown config option(s) in {source}: {', '.join(sorted(unknown))}")
    return dict(values)


def _read_toml(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        with path.open("rb") as stream:
            loaded = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise UsageError(f"cannot read config {path}: {exc}") from exc
    values = _validate_toml_values(
        {name: value for name, value in loaded.items() if name not in {"parxtract", "arcshuttle"}},
        "config root",
        allow_create=False,
    )
    for section_name in ("parxtract", "arcshuttle"):
        if section_name not in loaded:
            continue
        section = loaded[section_name]
        if not isinstance(section, dict):
            raise UsageError(f"config [{section_name}] section must be a table")
        values.update(
            _validate_toml_values(
                section,
                f"config [{section_name}]",
                allow_create=section_name == "arcshuttle",
            )
        )
    return values


def resolve_config(
    cli_values: Mapping[str, Any],
    *,
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Resolve CLI, environment, TOML, and defaults in descending precedence."""

    defaults = Config()
    values: dict[str, Any] = {name: getattr(defaults, name) for name in _ENV_NAMES}
    toml_values = _read_toml(config_path)
    values.update(toml_values)
    env = os.environ if environ is None else environ
    for name, env_name in _LEGACY_ENV_NAMES.items():
        if env_name in env:
            values[name] = env[env_name]
    for name, env_name in _ENV_NAMES.items():
        if env_name in env:
            values[name] = env[env_name]
    for name, value in cli_values.items():
        if name in values and value is not None:
            values[name] = value
    values = {name: _coerce(name, value) for name, value in values.items()}

    def explicitly_set(name: str) -> bool:
        legacy_env_name = _LEGACY_ENV_NAMES.get(name)
        return (
            cli_values.get(name) is not None
            or _ENV_NAMES[name] in env
            or (legacy_env_name is not None and legacy_env_name in env)
            or name in toml_values
        )

    if not explicitly_set("max_processes"):
        values["max_processes"] = min(4, values["cpu_budget"])
    if not explicitly_set("heavy_threads"):
        values["heavy_threads"] = min(4, values["cpu_budget"])

    if values["existing"] not in {"fail", "skip", "rename"}:
        raise UsageError("existing must be fail, skip, or rename")
    if values["storage_profile"] not in {"auto", "hdd", "ssd", "nvme"}:
        raise UsageError("storage_profile must be auto, hdd, ssd, or nvme")
    if values["on_input_error"] not in {"fail", "skip"}:
        raise UsageError("on_input_error must be fail or skip")
    if values["create_format"] not in {"7z", "zip"}:
        raise UsageError("create_format must be 7z or zip")

    # I/O defaults depend on the resolved process/profile settings unless explicitly set.
    explicit_io = explicitly_set("io_slots")
    explicit_storage_profile = explicitly_set("storage_profile")
    if not explicit_io:
        profile_slots = {"hdd": 1, "ssd": 2, "nvme": 4}
        values["io_slots"] = profile_slots.get(
            values["storage_profile"], min(2, values["max_processes"])
        )
    values["heavy_threads"] = min(values["heavy_threads"], values["cpu_budget"])
    return Config(
        **values,
        provenance=ConfigProvenance(
            io_slots_explicit=explicit_io,
            storage_profile_explicit=explicit_storage_profile,
        ),
    )
