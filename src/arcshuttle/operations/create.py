"""Archive creation inventory and planning."""

from __future__ import annotations

import hashlib
import json
import os
import stat
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
from ..util import path_key
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
