"""Safe staging, destination selection, and atomic finalization."""

from __future__ import annotations

import os
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .multipart import archive_stem
from .util import UsageError, unique_path


@dataclass(frozen=True, slots=True)
class OutputPaths:
    """Final and staging paths allocated for one job."""

    final: Path
    staging: Path | None
    skipped: bool = False


def default_output_path(archive: Path, root: Path | None) -> Path:
    """Build the independent output directory for an archive."""

    parent = archive.parent if root is None else root
    return (parent / archive_stem(archive)).resolve(strict=False)


def resolve_existing(desired: Path, policy: str) -> tuple[Path, bool]:
    """Apply the non-destructive existing-output policy."""

    if not desired.exists():
        return desired, False
    if policy == "fail":
        raise FileExistsError(f"output already exists: {desired}")
    if policy == "skip":
        return desired, True
    if policy == "rename":
        return unique_path(desired), False
    raise UsageError(f"unsupported existing-output policy: {policy}")


def create_staging(final: Path, job_id: str) -> Path:
    """Create a private staging directory beside the final destination."""

    final.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        name = f".parxtract-{job_id[:12]}-{uuid.uuid4().hex[:8]}.tmp"
        staging = final.parent / name
        try:
            staging.mkdir(mode=0o700)
            marker = staging / ".parxtract-owned"
            marker.write_text(job_id + "\n", encoding="utf-8")
            return staging
        except FileExistsError:
            continue
    raise OSError(f"unable to allocate staging directory beside {final}")


def finalize(staging: Path, final: Path) -> None:
    """Atomically rename a tool-owned staging directory to its final path."""

    marker = staging / ".parxtract-owned"
    if not marker.is_file():
        raise OSError(f"refusing to finalize unowned staging directory: {staging}")
    if final.exists():
        raise FileExistsError(f"output appeared before finalization: {final}")
    os.replace(staging, final)
    with suppress(OSError):
        (final / marker.name).unlink()


def retain_failed(staging: Path) -> Path:
    """Rename a tool-owned staging directory so partial output remains recoverable."""

    if not staging.exists():
        return staging
    if not (staging / ".parxtract-owned").is_file():
        raise OSError(f"refusing to rename unowned staging directory: {staging}")
    base_name = staging.name[:-4] if staging.name.endswith(".tmp") else staging.name
    desired = staging.with_name(base_name + ".failed")
    destination = unique_path(desired)
    os.replace(staging, destination)
    return destination
