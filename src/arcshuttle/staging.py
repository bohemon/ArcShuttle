"""Shared non-destructive output selection and owned staging operations."""

from __future__ import annotations

import os
import stat
import uuid
from contextlib import suppress
from pathlib import Path

from .util import UsageError, unique_path

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _require_owned(staging: Path, job_id: str | None = None) -> Path:
    try:
        staging_metadata = staging.lstat()
    except OSError as exc:
        raise OSError(f"refusing to modify unowned staging directory: {staging}") from exc
    if (
        stat.S_ISLNK(staging_metadata.st_mode)
        or not stat.S_ISDIR(staging_metadata.st_mode)
        or bool(getattr(staging_metadata, "st_file_attributes", 0) & _REPARSE_POINT)
    ):
        raise OSError(f"refusing to modify unowned staging directory: {staging}")
    marker = staging / ".arcshuttle-owned"
    try:
        metadata = marker.lstat()
    except OSError as exc:
        raise OSError(f"refusing to modify unowned staging directory: {staging}") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or bool(getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT)
    ):
        raise OSError(f"refusing to modify unowned staging directory: {staging}")
    if job_id is not None:
        try:
            owner = marker.read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise OSError(f"cannot read staging ownership marker: {marker}") from exc
        if owner != job_id:
            raise OSError(f"staging directory belongs to a different job: {staging}")
    return marker


def resolve_existing(desired: Path, policy: str, *, suffix: str = "") -> tuple[Path, bool]:
    """Apply a non-destructive policy and optionally preserve a file suffix."""

    if not os.path.lexists(desired):
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
            try:
                marker.write_text(job_id + "\n", encoding="utf-8")
            except OSError:
                with suppress(OSError):
                    staging.rmdir()
                raise
            return staging
        except FileExistsError:
            continue
    raise OSError(f"unable to allocate staging directory beside {final}")


def finalize_directory(staging: Path, final: Path) -> None:
    """Atomically rename an owned staging directory to a final directory."""

    marker = _require_owned(staging)
    if os.path.lexists(final):
        raise FileExistsError(f"output appeared before finalization: {final}")
    os.replace(staging, final)
    with suppress(OSError):
        (final / marker.name).unlink()


def finalize_archive(staging: Path, staged_archive: Path, final: Path, job_id: str) -> str | None:
    """Atomically commit without clobbering and return a cleanup warning if needed."""

    marker = _require_owned(staging, job_id)
    if staged_archive.parent != staging:
        raise OSError(f"staged archive is outside its owned staging directory: {staged_archive}")
    metadata = staged_archive.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or bool(getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT)
    ):
        raise OSError(f"staged archive is not a regular file: {staged_archive}")
    if os.path.lexists(final):
        raise FileExistsError(f"output appeared before finalization: {final}")
    os.link(staged_archive, final, follow_symlinks=False)
    try:
        staged_archive.unlink()
        if set(staging.iterdir()) != {marker}:
            return f"committed archive but retained non-empty staging directory: {staging}"
        marker.unlink()
        staging.rmdir()
    except OSError as exc:
        return f"committed archive but could not remove owned staging directory {staging}: {exc}"
    return None


def retain_failed(staging: Path, job_id: str | None = None) -> Path:
    """Rename an owned staging directory so partial output remains recoverable."""

    if not staging.exists():
        return staging
    _require_owned(staging, job_id)
    base_name = staging.name[:-4] if staging.name.endswith(".tmp") else staging.name
    desired = staging.with_name(base_name + ".failed")
    destination = unique_path(desired)
    os.replace(staging, destination)
    return destination
