"""Configuration loading and precedence handling."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .util import UsageError, parse_size


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


_ENV_NAMES = {
    "sevenzip": "PARXTRACT_7Z",
    "output_dir": "PARXTRACT_OUTPUT_DIR",
    "existing": "PARXTRACT_EXISTING",
    "cpu_budget": "PARXTRACT_CPU_BUDGET",
    "max_processes": "PARXTRACT_MAX_PROCESSES",
    "storage_profile": "PARXTRACT_STORAGE_PROFILE",
    "io_slots": "PARXTRACT_IO_SLOTS",
    "heavy_threads": "PARXTRACT_HEAVY_THREADS",
    "small_threshold": "PARXTRACT_SMALL_THRESHOLD",
    "inspect_threshold": "PARXTRACT_INSPECT_THRESHOLD",
    "inspect_timeout": "PARXTRACT_INSPECT_TIMEOUT",
    "reservation_delay": "PARXTRACT_RESERVATION_DELAY",
    "sequential_if_total_below": "PARXTRACT_SEQUENTIAL_IF_TOTAL_BELOW",
    "log_dir": "PARXTRACT_LOG_DIR",
    "quiet": "PARXTRACT_QUIET",
    "fail_fast": "PARXTRACT_FAIL_FAST",
    "allow_changed": "PARXTRACT_ALLOW_CHANGED",
    "on_input_error": "PARXTRACT_ON_INPUT_ERROR",
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


def _read_toml(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        with path.open("rb") as stream:
            loaded = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise UsageError(f"cannot read config {path}: {exc}") from exc
    section = loaded.get("parxtract", loaded)
    if not isinstance(section, dict):
        raise UsageError("config [parxtract] section must be a table")
    known = set(asdict(Config()))
    unknown = set(section) - known
    if unknown:
        raise UsageError(f"unknown config option(s): {', '.join(sorted(unknown))}")
    return dict(section)


def resolve_config(
    cli_values: Mapping[str, Any],
    *,
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Resolve CLI, environment, TOML, and defaults in descending precedence."""

    values: dict[str, Any] = asdict(Config())
    toml_values = _read_toml(config_path)
    values.update(toml_values)
    env = os.environ if environ is None else environ
    for name, env_name in _ENV_NAMES.items():
        if env_name in env:
            values[name] = env[env_name]
    for name, value in cli_values.items():
        if name in values and value is not None:
            values[name] = value
    values = {name: _coerce(name, value) for name, value in values.items()}

    def explicitly_set(name: str) -> bool:
        return cli_values.get(name) is not None or _ENV_NAMES[name] in env or name in toml_values

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

    # I/O defaults depend on the resolved process/profile settings unless explicitly set.
    explicit_io = explicitly_set("io_slots")
    if not explicit_io:
        profile_slots = {"hdd": 1, "ssd": 2, "nvme": 4}
        values["io_slots"] = profile_slots.get(
            values["storage_profile"], min(2, values["max_processes"])
        )
    values["heavy_threads"] = min(values["heavy_threads"], values["cpu_budget"])
    return Config(**values)
