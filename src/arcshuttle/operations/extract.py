"""Extraction planning and execution."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..classify import classify
from ..config import Config
from ..manifest import (
    LEGACY_SCHEMA_VERSION,
    SCHEMA_VERSION,
    calculate_integrity,
    deterministic_job_id,
    legacy_job_id,
    source_identity,
)
from ..multipart import MultipartInfo, archive_stem, inferred_format
from ..results import job_result
from ..scheduler import ScheduledJob
from ..sevenzip import InspectionResult, ProcessOutcome, SevenZip
from ..staging import create_staging, finalize_directory, resolve_existing, retain_failed
from ..util import isoformat, path_key, utc_now


@dataclass(slots=True)
class PlanningResult:
    """Complete extraction plan output and input-level diagnostics."""

    jobs: list[dict[str, Any]]
    errors: list[str]
    warnings: list[str]


def default_output_path(archive: Path, root: Path | None) -> Path:
    """Build the independent output directory for an archive."""

    parent = archive.parent if root is None else root
    return (parent / archive_stem(archive)).resolve(strict=False)


def _archive_defaults(info: MultipartInfo, size: int) -> dict[str, Any]:
    return {
        "format": inferred_format(info.first_volume),
        "methods": [],
        "packed_size": size,
        "unpacked_size": None,
        "entries": None,
        "solid": None,
        "blocks": None,
        "encrypted": None,
        "multipart": info.multipart,
    }


def _job_record(
    *,
    schema_version: int,
    path: Path,
    output: Path,
    stat_size: int,
    stat_mtime_ns: int,
    plan_index: int,
    archive: dict[str, Any],
    classification,
    estimated: int,
    warnings: list[str],
) -> dict[str, Any]:
    scheduling = {
        "profile": classification.profile,
        "profile_source": "auto",
        "classification_reason": classification.reason,
        "priority": 0,
        "estimated_weight": int(estimated),
        "cpu_tokens": classification.cpu_tokens,
        "threads": classification.threads,
        "io_tokens": classification.io_tokens,
    }
    if schema_version == LEGACY_SCHEMA_VERSION:
        job: dict[str, Any] = {
            "schema_version": LEGACY_SCHEMA_VERSION,
            "record_type": "job",
            "job_id": legacy_job_id(path, stat_size, stat_mtime_ns),
            "plan_index": plan_index,
            "path": str(path),
            "output_dir": str(output),
            "source": {"size": stat_size, "mtime_ns": stat_mtime_ns},
            "archive": archive,
            "scheduling": scheduling,
            "tags": [],
            "warnings": warnings,
        }
    else:
        identity = source_identity(
            kind="file",
            size=stat_size,
            mtime_ns=stat_mtime_ns,
            entry_count=1,
        )
        job = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "job",
            "operation": "extract",
            "job_id": deterministic_job_id("extract", path, identity),
            "plan_index": plan_index,
            "source": {
                "path": str(path),
                "kind": "file",
                "size": stat_size,
                "mtime_ns": stat_mtime_ns,
                "entry_count": 1,
                "identity": identity,
            },
            "destination": {"path": str(output), "kind": "directory"},
            "archive": archive,
            "scheduling": scheduling,
            "tags": [],
            "warnings": warnings,
        }
    job["integrity"] = calculate_integrity(job)
    return job


def make_plan(
    inputs: Iterable[MultipartInfo],
    config: Config,
    inspector: Callable[[Path, float], InspectionResult],
    *,
    schema_version: int,
) -> PlanningResult:
    """Inspect, classify, and plan normalized archive first volumes."""

    jobs: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for plan_index, info in enumerate(inputs):
        path = info.first_volume
        try:
            stat = path.stat()
        except OSError as exc:
            errors.append(f"{path}: cannot stat source: {exc}")
            continue
        archive = _archive_defaults(info, stat.st_size)
        should_inspect = stat.st_size >= config.inspect_threshold or archive["format"] is None
        inspection_failed = False
        job_warnings: list[str] = []
        if should_inspect:
            outcome = inspector(path, config.inspect_timeout)
            details = outcome.inspection.as_dict()
            for key, value in details.items():
                if value is not None and value != []:
                    archive[key] = value
            archive["packed_size"] = archive["packed_size"] or stat.st_size
            archive["multipart"] = bool(archive["multipart"] or info.multipart)
            if outcome.error:
                inspection_failed = True
                job_warnings.append(outcome.error)
                warnings.append(f"{path}: {outcome.error}")

        classification = classify(
            packed_size=stat.st_size,
            small_threshold=config.small_threshold,
            archive=archive,
            cpu_budget=config.cpu_budget,
            heavy_threads=config.heavy_threads,
            inspection_failed=inspection_failed,
        )
        output = default_output_path(path, config.output_dir)
        estimated = archive["unpacked_size"] or archive["packed_size"] or stat.st_size
        jobs.append(
            _job_record(
                schema_version=schema_version,
                path=path,
                output=output,
                stat_size=stat.st_size,
                stat_mtime_ns=stat.st_mtime_ns,
                plan_index=plan_index,
                archive=archive,
                classification=classification,
                estimated=estimated,
                warnings=job_warnings,
            )
        )

    collisions: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        output = job.get("output_dir") or job["destination"]["path"]
        collisions.setdefault(path_key(Path(output)), []).append(job)
    for group in collisions.values():
        if len(group) > 1:
            paths = ", ".join(job.get("path") or job["source"]["path"] for job in group)
            output = group[0].get("output_dir") or group[0]["destination"]["path"]
            errors.append(f"output collision at {output}: {paths}")
    return PlanningResult(jobs, errors, warnings)


def make_legacy_plan(
    inputs: Iterable[MultipartInfo],
    config: Config,
    inspector: Callable[[Path, float], InspectionResult],
) -> PlanningResult:
    """Create manifest v1 for the compatibility CLI."""

    return make_plan(inputs, config, inspector, schema_version=LEGACY_SCHEMA_VERSION)


def make_extract_plan(
    inputs: Iterable[MultipartInfo],
    config: Config,
    inspector: Callable[[Path, float], InspectionResult],
) -> PlanningResult:
    """Create manifest v2 for the ArcShuttle CLI."""

    return make_plan(inputs, config, inspector, schema_version=SCHEMA_VERSION)


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
    """Execute one normalized extraction job safely."""

    job = scheduled.payload
    started = isoformat(utc_now())
    start_clock = time.monotonic()
    desired = Path(job["destination"]["path"])
    final = desired
    staging: Path | None = None
    log_path = log_root / job["job_id"]
    warnings = list(job["warnings"])

    def finish(status: str, exit_code: int | None, *, error: str | None = None) -> dict[str, Any]:
        if error:
            warnings.append(error)
        finished = isoformat(utc_now())
        duration_ms = round((time.monotonic() - start_clock) * 1000)
        result = job_result(
            job=job,
            run_id=run_id,
            status=status,
            started_at=started,
            finished_at=finished,
            duration_ms=duration_ms,
            exit_code=exit_code,
            output_path=str(final),
            staging_path=str(staging) if staging is not None else None,
            log_path=str(log_path) if log_path.exists() else None,
            warnings=warnings,
        )
        if not config.quiet:
            with progress_lock:
                print(
                    f"{program_name}: {status} {duration_ms / 1000:.2f}s {job['source']['path']}",
                    file=sys.stderr,
                )
        return result

    if stop_event.is_set():
        return finish("interrupted", None, error="not started after interruption")
    if job["archive"].get("encrypted") is True:
        return finish("failed", None, error="encrypted archives are not supported")
    try:
        stat = Path(job["source"]["path"]).stat()
    except OSError as exc:
        return finish("failed", None, error=f"cannot stat source before extraction: {exc}")
    source = job["source"]
    if stat.st_size != source["size"] or stat.st_mtime_ns != source["mtime_ns"]:
        message = "source size or modification time changed after planning"
        if not config.allow_changed:
            return finish("failed", None, error=message)
        warnings.append(message + "; continuing because --allow-changed was supplied")
    try:
        final, skipped = resolve_existing(desired, config.existing)
    except FileExistsError as exc:
        return finish("failed", None, error=str(exc))
    if skipped:
        return finish("skipped", None, error="output already exists")
    try:
        staging = create_staging(final, job["job_id"])
    except OSError as exc:
        return finish("failed", None, error=f"cannot create staging directory: {exc}")

    outcome: ProcessOutcome = sevenzip.extract(
        archive=Path(job["source"]["path"]),
        staging=staging,
        threads=job["scheduling"]["threads"],
        log_directory=log_path,
        cpu_tokens=job["scheduling"]["cpu_tokens"],
        stop_event=stop_event,
    )
    if outcome.interrupted:
        try:
            staging = retain_failed(staging)
        except OSError as exc:
            warnings.append(str(exc))
        return finish("interrupted", outcome.exit_code, error=outcome.error)
    if outcome.error is not None or outcome.exit_code is None or outcome.exit_code >= 2:
        try:
            staging = retain_failed(staging)
        except OSError as exc:
            warnings.append(str(exc))
        return finish("failed", outcome.exit_code, error=outcome.error)
    if outcome.exit_code == 1:
        try:
            staging = retain_failed(staging)
        except OSError as exc:
            warnings.append(str(exc))
        return finish("warning", 1, error="7-Zip completed with warnings; partial output retained")

    if final.exists() and config.existing == "rename":
        final, _ = resolve_existing(final, "rename")
    try:
        finalize_directory(staging, final)
        staging = None
    except OSError as exc:
        try:
            staging = retain_failed(staging)
        except OSError as retain_exc:
            warnings.append(str(retain_exc))
        return finish("failed", 0, error=f"cannot finalize output: {exc}")
    return finish("success", 0)
