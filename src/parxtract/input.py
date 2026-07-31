"""Input collection and path normalization."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO, TextIO

from .util import UsageError, path_key


def read_line_paths(stream: TextIO) -> list[str]:
    """Read UTF-8 newline-delimited paths, ignoring empty lines."""

    return [line.rstrip("\r\n") for line in stream if line.rstrip("\r\n")]


def read_nul_paths(stream: BinaryIO) -> list[str]:
    """Read UTF-8 NUL-delimited paths."""

    raw = stream.read()
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError(f"NUL-delimited input is not valid UTF-8: {exc}") from exc
    values = decoded.split("\0")
    if values and values[-1] == "":
        values.pop()
    if any(value == "" for value in values):
        raise UsageError("NUL-delimited input contains an empty path")
    return values


def collect_paths(
    positional: list[str],
    *,
    files_from: str | None,
    files0_from: str | None,
) -> list[str]:
    """Collect exactly one explicitly selected CLI input source."""

    sources = bool(positional) + (files_from is not None) + (files0_from is not None)
    if sources != 1:
        raise UsageError("specify exactly one of PATH..., --files-from, or --files0-from")
    if positional:
        return positional
    if files_from is not None:
        if files_from == "-":
            return read_line_paths(sys.stdin)
        try:
            with Path(files_from).open("r", encoding="utf-8", newline="") as stream:
                return read_line_paths(stream)
        except OSError as exc:
            raise UsageError(f"cannot read --files-from {files_from}: {exc}") from exc
    assert files0_from is not None
    if files0_from == "-":
        return read_nul_paths(sys.stdin.buffer)
    try:
        with Path(files0_from).open("rb") as stream:
            return read_nul_paths(stream)
    except OSError as exc:
        raise UsageError(f"cannot read --files0-from {files0_from}: {exc}") from exc


def normalize_paths(values: Iterable[str], cwd: Path | None = None) -> tuple[list[Path], list[str]]:
    """Resolve, validate, and de-duplicate archive file paths."""

    base = Path.cwd() if cwd is None else cwd
    result: list[Path] = []
    errors: list[str] = []
    seen: set[str] = set()
    for raw in values:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            errors.append(f"{raw}: {exc}")
            continue
        if not resolved.is_file():
            errors.append(f"{raw}: directories and non-files are not supported")
            continue
        key = path_key(resolved)
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result, errors
