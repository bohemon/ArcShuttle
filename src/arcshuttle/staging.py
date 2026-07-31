"""Shared non-destructive output selection and owned staging operations."""

from __future__ import annotations

import os
import uuid
from contextlib import suppress
from pathlib import Path

from .util import UsageError, unique_path


def resolve_existing(desired: Path, policy: str, *, suffix: str = "") -> tuple[Path, bool]:
    """Apply a non-destructive policy and optionally preserve a file suffix."""

    if not desired.exists():
        return desired, False
    if policy == "fail":
        raise FileExistsError(f"output already exists: {desired}")
    if policy == "skip":
        return desired, True
    if policy == "rename":
        if suffix and desired.name.endswith(suffix):
            return unique_path(desired.with_name(desired.name[: -len(suffix)]), suffix), False
        return unique_path(desired), False
    raise UsageError(f"unsupported existing-output policy: {policy}")


def create_staging(final: Path, job_id: str, *, prefix: str = ".arcshuttle-") -> Path:
    """Create a private owned staging directory beside the final destination."""

    final.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        name = f"{prefix}{job_id[:12]}-{uuid.uuid4().hex[:8]}.tmp"
        staging = final.parent / name
        try:
            staging.mkdir(mode=0o700)
            marker = staging / ".arcshuttle-owned"
            marker.write_text(job_id + "\n", encoding="utf-8")
            return staging
        except FileExistsError:
            continue
    raise OSError(f"unable to allocate staging directory beside {final}")


def finalize_directory(staging: Path, final: Path) -> None:
    """Atomically rename an owned staging directory to a final directory."""

    marker = staging / ".arcshuttle-owned"
    if not marker.is_file():
        raise OSError(f"refusing to finalize unowned staging directory: {staging}")
    if final.exists():
        raise FileExistsError(f"output appeared before finalization: {final}")
    os.replace(staging, final)
    with suppress(OSError):
        (final / marker.name).unlink()


def retain_failed(staging: Path) -> Path:
    """Rename an owned staging directory so partial output remains recoverable."""

    if not staging.exists():
        return staging
    if not (staging / ".arcshuttle-owned").is_file():
        raise OSError(f"refusing to rename unowned staging directory: {staging}")
    base_name = staging.name[:-4] if staging.name.endswith(".tmp") else staging.name
    desired = staging.with_name(base_name + ".failed")
    destination = unique_path(desired)
    os.replace(staging, destination)
    return destination
