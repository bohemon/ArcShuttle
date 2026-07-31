"""Small shared utilities."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

_SIZE_RE = re.compile(r"^\s*(\d+)\s*([kmgtpe]?)(?:i?b)?\s*$", re.IGNORECASE)


class ArcShuttleError(Exception):
    """Base class for expected, user-facing failures."""


class UsageError(ArcShuttleError):
    """An invalid CLI, configuration, input, or manifest was supplied."""


def parse_size(value: str | int) -> int:
    """Parse an integer byte count or a binary size such as ``64M``."""

    if isinstance(value, int):
        if value < 0:
            raise ValueError("size cannot be negative")
        return value
    match = _SIZE_RE.fullmatch(value)
    if not match:
        raise ValueError(f"invalid size: {value!r}")
    amount = int(match.group(1))
    suffix = match.group(2).lower()
    power = "kmgtpe".find(suffix) + 1 if suffix else 0
    return amount * (1024**power)


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(UTC)


def isoformat(value: datetime) -> str:
    """Serialize a timestamp in stable ISO-8601 form."""

    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def emit_jsonl(record: dict[str, Any], stream: TextIO | None = None) -> None:
    """Write one compact UTF-8-friendly JSON Lines record."""

    destination = sys.stdout if stream is None else stream
    destination.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    destination.flush()


def path_key(path: Path) -> str:
    """Return a platform-appropriate normalized key for path comparisons."""

    value = os.path.normpath(str(path))
    return os.path.normcase(value) if os.name == "nt" else value


def unique_path(base: Path, suffix: str = "") -> Path:
    """Choose a non-existing path by appending `` (N)`` before *suffix*."""

    candidate = base.with_name(base.name + suffix)
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = base.with_name(f"{base.name} ({index}){suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def ensure_int(value: Any, name: str, *, minimum: int = 0) -> int:
    """Validate an integer while rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise UsageError(f"{name} must be an integer >= {minimum}")
    return value


def read_json_lines(stream: TextIO, source: str) -> list[dict[str, Any]]:
    """Read and validate a complete JSON Lines stream."""

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UsageError(f"{source}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise UsageError(f"{source}:{line_number}: record must be a JSON object")
        records.append(value)
    return records


def dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    """Remove exact duplicate strings while retaining the first occurrence."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
