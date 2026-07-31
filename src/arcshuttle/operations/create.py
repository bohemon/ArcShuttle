"""Archive creation inventory and planning."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Config
from ..manifest import (
    SCHEMA_VERSION,
    calculate_integrity,
    deterministic_job_id,
    source_identity,
)
from ..results import job_result
from ..scheduler import ScheduledJob
from ..sevenzip import ProcessOutcome, SevenZip
from ..staging import create_staging, finalize_archive, resolve_existing, retain_failed
from ..util import isoformat, path_key, utc_now
from .extract import PlanningResult

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """One regular file or directory relative to a create source."""

    relative_path: str
    kind: str
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class SourceInventory:
    """Stable metadata inventory used by create planning and revalidation."""

    path: Path
    kind: str
    size: int
    mtime_ns: int
    file_count: int
    directory_count: int
    entries: tuple[InventoryEntry, ...]
    digest: str
    identity: str

    @property
    def entry_count(self) -> int:
        return self.file_count + self.directory_count


def _is_reparse_point(metadata: os.stat_result) -> bool:
    return bool(getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT)


def _entry_kind(path: Path, metadata: os.stat_result) -> str:
    if stat.S_ISLNK(metadata.st_mode) or _is_reparse_point(metadata):
        raise OSError(f"{path}: symbolic links and reparse points are not supported")
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    raise OSError(f"{path}: non-regular filesystem entries are not supported")


def normalize_create_paths(
    values: Iterable[str], cwd: Path | None = None
) -> tuple[list[Path], list[str]]:
    """Normalize create sources without resolving or accepting links."""

    base = Path.cwd() if cwd is None else cwd
    result: list[Path] = []
    errors: list[str] = []
    seen: set[str] = set()
    for raw in values:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        candidate = Path(os.path.abspath(candidate))
        try:
            _entry_kind(candidate, candidate.lstat())
        except OSError as exc:
            errors.append(f"{raw}: {exc}")
            continue
        key = path_key(candidate)
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result, errors


def _digest_entries(entries: Iterable[InventoryEntry]) -> str:
    ordered = sorted(entries, key=lambda entry: path_key(Path(entry.relative_path)))
    payload = [
        {
            "path": entry.relative_path,
            "kind": entry.kind,
            "size": entry.size,
            "mtime_ns": entry.mtime_ns,
        }
        for entry in ordered
    ]
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(serialized).hexdigest()


def inventory_source(path: Path) -> SourceInventory:
    """Recursively inventory a file or directory without following links."""

    root_metadata = path.lstat()
    kind = _entry_kind(path, root_metadata)
    discovered: list[tuple[Path, str]] = []
    if kind == "file":
        discovered.append((path, "file"))
    else:
        pending = [path]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as children:
                for child in children:
                    child_path = Path(child.path)
                    metadata = child.stat(follow_symlinks=False)
                    child_kind = _entry_kind(child_path, metadata)
                    discovered.append((child_path, child_kind))
                    if child_kind == "directory":
                        pending.append(child_path)

    # Re-stat after traversal so directory mtimes changed by earlier child creation are not
    # captured from a stale directory-entry cache on the first pass.
    entries: list[InventoryEntry] = []
    for entry_path, discovered_kind in discovered:
        metadata = entry_path.lstat()
        current_kind = _entry_kind(entry_path, metadata)
        if current_kind != discovered_kind:
            raise OSError(f"{entry_path}: entry kind changed while inventorying")
        relative_path = (
            entry_path.name if kind == "file" else entry_path.relative_to(path).as_posix()
        )
        entries.append(
            InventoryEntry(
                relative_path,
                current_kind,
                metadata.st_size if current_kind == "file" else 0,
                metadata.st_mtime_ns,
            )
        )
    root_metadata = path.lstat()
    if _entry_kind(path, root_metadata) != kind:
        raise OSError(f"{path}: source kind changed while inventorying")

    file_count = sum(entry.kind == "file" for entry in entries)
    directory_count = sum(entry.kind == "directory" for entry in entries)
    total_size = sum(entry.size for entry in entries if entry.kind == "file")
    latest_mtime = max(
        (root_metadata.st_mtime_ns, *(entry.mtime_ns for entry in entries)),
    )
    digest = _digest_entries(entries)
    identity = source_identity(
        kind=kind,
        size=total_size,
        mtime_ns=latest_mtime,
        entry_count=file_count + directory_count,
        digest=digest,
    )
    return SourceInventory(
        path=path,
        kind=kind,
        size=total_size,
        mtime_ns=latest_mtime,
        file_count=file_count,
        directory_count=directory_count,
        entries=tuple(sorted(entries, key=lambda entry: path_key(Path(entry.relative_path)))),
        digest=digest,
        identity=identity,
    )


def default_output_path(source: Path, root: Path | None, archive_format: str) -> Path:
    """Build the independent output archive path for a source."""

    parent = source.parent if root is None else root
    return (parent / f"{source.name}.{archive_format}").resolve(strict=False)


def _contains(directory: Path, candidate: Path) -> bool:
    try:
        common = os.path.commonpath((path_key(directory), path_key(candidate)))
    except ValueError:
        return False
    return common == path_key(directory)


def _scheduling(inventory: SourceInventory, config: Config) -> dict[str, Any]:
    if inventory.size < config.small_threshold:
        profile = "small"
        reason = "create-below-small-threshold"
        cpu_tokens = 1
    elif config.compression_level == 0:
        profile = "heavy-serial"
        reason = "create-store-mode"
        cpu_tokens = 1
    else:
        profile = "heavy-scalable"
        reason = "create-7z-lzma2" if config.create_format == "7z" else "create-zip-deflate"
        cpu_tokens = min(config.heavy_threads, config.cpu_budget)
    return {
        "profile": profile,
        "profile_source": "auto",
        "classification_reason": reason,
        "priority": 0,
        "estimated_weight": inventory.size,
        "cpu_tokens": cpu_tokens,
        "threads": cpu_tokens,
        "io_tokens": 1,
    }


def make_create_plan(inputs: Iterable[Path], config: Config) -> PlanningResult:
    """Inventory normalized sources and build manifest-v2 create jobs."""

    jobs: list[dict[str, Any]] = []
    errors: list[str] = []
    for plan_index, path in enumerate(inputs):
        try:
            inventory = inventory_source(path)
        except OSError as exc:
            errors.append(f"{path}: cannot inventory source: {exc}")
            continue
        destination = default_output_path(path, config.output_dir, config.create_format)
        if inventory.kind == "directory":
            unsafe: list[tuple[str, Path]] = [("destination", destination)]
            log_base = config.log_dir or (Path.cwd() / ".arcshuttle" / "logs")
            unsafe.append(("log directory", log_base.resolve(strict=False)))
            unsafe_path = False
            for label, candidate in unsafe:
                if _contains(path, candidate):
                    errors.append(f"{path}: {label} is inside the source directory: {candidate}")
                    unsafe_path = True
                    break
            if unsafe_path:
                continue
        archive_format = config.create_format
        method = "LZMA2" if archive_format == "7z" else "Deflate"
        job: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "job",
            "operation": "create",
            "job_id": deterministic_job_id("create", path, inventory.identity),
            "plan_index": plan_index,
            "source": {
                "path": str(path),
                "kind": inventory.kind,
                "size": inventory.size,
                "mtime_ns": inventory.mtime_ns,
                "entry_count": inventory.entry_count,
                "file_count": inventory.file_count,
                "directory_count": inventory.directory_count,
                "digest": inventory.digest,
                "identity": inventory.identity,
            },
            "destination": {"path": str(destination), "kind": "archive"},
            "archive": {
                "format": archive_format,
                "method": method,
                "compression_level": config.compression_level,
            },
            "scheduling": _scheduling(inventory, config),
            "tags": [],
            "warnings": [],
        }
        job["integrity"] = calculate_integrity(job)
        jobs.append(job)

    collisions: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        collisions.setdefault(path_key(Path(job["destination"]["path"])), []).append(job)
    for group in collisions.values():
        if len(group) > 1:
            sources = ", ".join(job["source"]["path"] for job in group)
            errors.append(f"output collision at {group[0]['destination']['path']}: {sources}")
    return PlanningResult(jobs, errors, [])


def _record_commit(log_directory: Path, **values: object) -> str | None:
    """Add executor commit state and return a non-fatal logging warning."""

    metadata_path = log_directory / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    metadata["commit"] = values
    try:
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        return f"could not record commit metadata in {metadata_path}: {exc}"
    return None


def execute_job(
    scheduled: ScheduledJob[dict[str, Any]],
    stop_event: threading.Event,
    *,
    config: Config,
    sevenzip: SevenZip,
    run_id: str,
    log_root: Path,
    progress_lock: threading.Lock,
    program_name: str,
) -> dict[str, Any]:
    """Create, verify, and atomically commit one archive job."""

    job = scheduled.payload
    started = isoformat(utc_now())
    start_clock = time.monotonic()
    desired = Path(job["destination"]["path"])
    final = desired
    staging: Path | None = None
    log_path = log_root / job["job_id"]
    warnings = list(job["warnings"])
    create_exit_code: int | None = None
    test_exit_code: int | None = None

    def finish(status: str, *, error: str | None = None) -> dict[str, Any]:
        if error:
            warnings.append(error)
        duration_ms = round((time.monotonic() - start_clock) * 1000)
        result = job_result(
            job=job,
            run_id=run_id,
            status=status,
            started_at=started,
            finished_at=isoformat(utc_now()),
            duration_ms=duration_ms,
            exit_code=create_exit_code,
            output_path=str(final),
            staging_path=str(staging) if staging is not None else None,
            log_path=str(log_path) if log_path.exists() else None,
            warnings=warnings,
        )
        result["create_exit_code"] = create_exit_code
        result["test_exit_code"] = test_exit_code
        if not config.quiet:
            with progress_lock:
                print(
                    f"{program_name}: {status} {duration_ms / 1000:.2f}s {job['source']['path']}",
                    file=sys.stderr,
                )
        return result

    def retain(status: str, error: str) -> dict[str, Any]:
        nonlocal staging
        if staging is not None:
            try:
                staging = retain_failed(staging, job["job_id"])
            except OSError as exc:
                warnings.append(str(exc))
        metadata_warning = _record_commit(
            log_path,
            status="not-committed",
            final_path=str(final),
            staging_path=str(staging) if staging is not None else None,
            error=error,
        )
        if metadata_warning:
            warnings.append(metadata_warning)
        return finish(status, error=error)

    if stop_event.is_set():
        return finish("interrupted", error="not started after interruption")
    source_path = Path(job["source"]["path"])
    if job["source"]["kind"] == "directory":
        log_base = config.log_dir or (Path.cwd() / ".arcshuttle" / "logs")
        for label, candidate in (
            ("destination", desired),
            ("log directory", log_base.resolve(strict=False)),
        ):
            if _contains(source_path, candidate) or _contains(
                source_path.resolve(strict=False), candidate.resolve(strict=False)
            ):
                return finish(
                    "failed", error=f"{label} is inside the source directory: {candidate}"
                )
    try:
        current = inventory_source(source_path)
    except OSError as exc:
        return finish("failed", error=f"cannot inventory source before creation: {exc}")
    if current.kind != job["source"]["kind"]:
        return finish("failed", error="source kind changed after planning")
    if current.identity != job["source"]["identity"]:
        message = "source identity changed after planning"
        if not config.allow_changed:
            return finish("failed", error=message)
        warnings.append(message + "; continuing because --allow-changed was supplied")
    try:
        final, skipped = resolve_existing(desired, config.existing, suffix=desired.suffix)
    except FileExistsError as exc:
        return finish("failed", error=str(exc))
    if skipped:
        return finish("skipped", error="output already exists")
    try:
        staging = create_staging(final, job["job_id"])
    except OSError as exc:
        return finish("failed", error=f"cannot create staging directory: {exc}")
    staged_archive = staging / final.name
    try:
        create_outcome: ProcessOutcome = sevenzip.create(
            source=source_path,
            source_kind=job["source"]["kind"],
            archive=staged_archive,
            archive_format=job["archive"]["format"],
            method=job["archive"]["method"],
            compression_level=job["archive"]["compression_level"],
            threads=job["scheduling"]["threads"],
            log_directory=log_path,
            cpu_tokens=job["scheduling"]["cpu_tokens"],
            stop_event=stop_event,
        )
    except OSError as exc:
        return retain("failed", f"cannot run archive creation: {exc}")
    create_exit_code = create_outcome.exit_code
    if create_outcome.interrupted:
        return retain("interrupted", create_outcome.error or "archive creation was interrupted")
    if (
        create_outcome.error is not None
        or create_outcome.exit_code is None
        or create_outcome.exit_code >= 2
    ):
        return retain("failed", create_outcome.error or "7-Zip archive creation failed")
    if create_outcome.exit_code == 1:
        return retain("warning", "7-Zip archive creation completed with warnings")
    if not staged_archive.is_file():
        return retain("failed", "7-Zip reported success but did not create a regular archive")

    try:
        test_outcome: ProcessOutcome = sevenzip.test(
            archive=staged_archive,
            log_directory=log_path,
            stop_event=stop_event,
        )
    except OSError as exc:
        return retain("failed", f"cannot run archive verification: {exc}")
    test_exit_code = test_outcome.exit_code
    if test_outcome.interrupted:
        return retain("interrupted", test_outcome.error or "archive verification was interrupted")
    if (
        test_outcome.error is not None
        or test_outcome.exit_code is None
        or test_outcome.exit_code >= 2
    ):
        return retain("failed", test_outcome.error or "7-Zip archive verification failed")
    if test_outcome.exit_code == 1:
        return retain("warning", "7-Zip archive verification completed with warnings")

    if os.path.lexists(final):
        if config.existing == "rename":
            final, _ = resolve_existing(final, "rename", suffix=final.suffix)
        else:
            return retain("failed", f"output appeared before finalization: {final}")
    try:
        cleanup_warning = finalize_archive(staging, staged_archive, final, job["job_id"])
    except OSError as exc:
        return retain("failed", f"cannot commit verified archive: {exc}")
    staging = None
    if cleanup_warning:
        warnings.append(cleanup_warning)
    metadata_warning = _record_commit(
        log_path, status="committed", final_path=str(final), error=cleanup_warning
    )
    if metadata_warning:
        warnings.append(metadata_warning)
    return finish("success")
