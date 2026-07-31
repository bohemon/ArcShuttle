"""Recognition of common split-archive naming conventions."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .util import path_key

_NUMBERED_RE = re.compile(r"^(?P<base>.+\.(?:7z|zip))\.(?P<num>\d{3,})$", re.IGNORECASE)
_PART_RAR_RE = re.compile(r"^(?P<base>.+)\.part(?P<num>\d+)\.rar$", re.IGNORECASE)
_OLD_RAR_RE = re.compile(r"^(?P<base>.+)\.r(?P<num>\d{2,})$", re.IGNORECASE)
_SPLIT_ZIP_RE = re.compile(r"^(?P<base>.+)\.z(?P<num>\d{2,})$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class MultipartInfo:
    """Canonical first volume and naming-family metadata."""

    first_volume: Path
    multipart: bool
    family: str | None = None


def identify(path: Path) -> MultipartInfo:
    """Map a volume name to the first volume, without requiring it to exist."""

    name = path.name
    match = _NUMBERED_RE.match(name)
    if match:
        first = f"{match.group('base')}.{'1'.zfill(len(match.group('num')))}"
        return MultipartInfo(path.with_name(first), True, "numbered")
    match = _PART_RAR_RE.match(name)
    if match:
        first = f"{match.group('base')}.part{'1'.zfill(len(match.group('num')))}.rar"
        return MultipartInfo(path.with_name(first), True, "part-rar")
    match = _OLD_RAR_RE.match(name)
    if match:
        return MultipartInfo(path.with_name(f"{match.group('base')}.rar"), True, "old-rar")
    match = _SPLIT_ZIP_RE.match(name)
    if match:
        return MultipartInfo(path.with_name(f"{match.group('base')}.zip"), True, "split-zip")

    lower = name.lower()
    if lower.endswith(".rar") and path.with_suffix(".r00").exists():
        return MultipartInfo(path, True, "old-rar")
    if lower.endswith(".zip") and path.with_suffix(".z01").exists():
        return MultipartInfo(path, True, "split-zip")
    return MultipartInfo(path, False, None)


def canonicalize(paths: Iterable[Path]) -> tuple[list[MultipartInfo], list[str]]:
    """Collapse supplied volumes into unique first-volume jobs."""

    result: list[MultipartInfo] = []
    errors: list[str] = []
    seen: set[str] = set()
    for path in paths:
        info = identify(path)
        first = info.first_volume
        if not first.exists() or not first.is_file():
            errors.append(f"{path}: first volume not found: {first}")
            continue
        first = first.resolve(strict=True)
        key = path_key(first)
        if key not in seen:
            seen.add(key)
            result.append(MultipartInfo(first, info.multipart, info.family))
    return result, errors


def archive_stem(path: Path) -> str:
    """Remove compound and multipart archive suffixes for an output directory name."""

    name = path.name
    numbered = _NUMBERED_RE.match(name)
    if numbered:
        name = numbered.group("base")
    part = _PART_RAR_RE.match(name)
    if part:
        return part.group("base")
    old = _OLD_RAR_RE.match(name)
    if old:
        return old.group("base")
    split_zip = _SPLIT_ZIP_RE.match(name)
    if split_zip:
        return split_zip.group("base")
    lowered = name.lower()
    for suffix in (
        ".tar.gz",
        ".tar.bz2",
        ".tar.xz",
        ".tbz2",
        ".tgz",
        ".txz",
        ".7z",
        ".zip",
        ".rar",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
    ):
        if lowered.endswith(suffix):
            stem = name[: -len(suffix)]
            return stem or "archive"
    return path.stem or "archive"


def inferred_format(path: Path) -> str | None:
    """Infer the archive format from a recognized suffix."""

    name = path.name.lower()
    info = identify(path)
    if info.family == "numbered":
        name = Path(name).stem
    if info.family in {"part-rar", "old-rar"}:
        return "rar"
    if info.family == "split-zip":
        return "zip"
    suffixes = (
        (".tar.gz", "gzip"),
        (".tgz", "gzip"),
        (".tar.bz2", "bzip2"),
        (".tbz2", "bzip2"),
        (".tar.xz", "xz"),
        (".txz", "xz"),
        (".7z", "7z"),
        (".zip", "zip"),
        (".rar", "rar"),
        (".tar", "tar"),
        (".gz", "gzip"),
        (".bz2", "bzip2"),
        (".xz", "xz"),
    )
    return next((fmt for suffix, fmt in suffixes if name.endswith(suffix)), None)
