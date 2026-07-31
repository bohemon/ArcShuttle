"""Planning, JSON Lines schema, integrity, and manifest validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .classify import classify
from .config import Config
from .multipart import MultipartInfo, inferred_format
from .output import default_output_path
from .sevenzip import InspectionResult
from .util import UsageError, ensure_int, path_key

SCHEMA_VERSION = 1


@dataclass(slots=True)
class PlanningResult:
    """Complete plan output and all input-level diagnostics."""

    jobs: list[dict[str, Any]]
    errors: list[str]
    warnings: list[str]


def deterministic_job_id(path: Path, size: int, mtime_ns: int) -> str:
    """Derive a stable ID from the normalized path and source identity."""

    payload = f"{path_key(path)}\0{size}\0{mtime_ns}".encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def _integrity_payload(job: dict[str, Any]) -> dict[str, Any]:
    scheduling = dict(job["scheduling"])
    for editable in ("profile", "priority", "cpu_tokens", "threads"):
        scheduling.pop(editable, None)
    return {
        "schema_version": job["schema_version"],
        "record_type": job["record_type"],
        "job_id": job["job_id"],
        "plan_index": job["plan_index"],
        "path": job["path"],
        "source": job["source"],
        "archive": job["archive"],
        "scheduling": scheduling,
        "warnings": job["warnings"],
    }


def calculate_integrity(job: dict[str, Any]) -> str:
    """Hash immutable manifest fields so external filters cannot silently alter them."""

    serialized = json.dumps(
        _integrity_payload(job), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(serialized).hexdigest()


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


def make_plan(
    inputs: Iterable[MultipartInfo],
    config: Config,
    inspector: Callable[[Path, float], InspectionResult],
) -> PlanningResult:
    """Inspect and classify all normalized first volumes before emitting any records."""

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
        job: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "job",
            "job_id": deterministic_job_id(path, stat.st_size, stat.st_mtime_ns),
            "plan_index": plan_index,
            "path": str(path),
            "output_dir": str(output),
            "source": {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
            "archive": archive,
            "scheduling": {
                "profile": classification.profile,
                "profile_source": "auto",
                "classification_reason": classification.reason,
                "priority": 0,
                "estimated_weight": int(estimated),
                "cpu_tokens": classification.cpu_tokens,
                "threads": classification.threads,
                "io_tokens": classification.io_tokens,
            },
            "tags": [],
            "warnings": job_warnings,
        }
        job["integrity"] = calculate_integrity(job)
        jobs.append(job)

    collisions: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        collisions.setdefault(path_key(Path(job["output_dir"])), []).append(job)
    for group in collisions.values():
        if len(group) > 1:
            paths = ", ".join(job["path"] for job in group)
            errors.append(f"output collision at {group[0]['output_dir']}: {paths}")
    return PlanningResult(jobs, errors, warnings)


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UsageError(f"{name} must be an object")
    return value


def validate_manifest(records: list[dict[str, Any]], config: Config) -> list[dict[str, Any]]:
    """Validate complete manifest input and clamp editable scheduling fields safely."""

    if not records:
        raise UsageError("manifest contains no jobs")
    validated: list[dict[str, Any]] = []
    ids: set[str] = set()
    outputs: dict[str, str] = {}
    for index, source_record in enumerate(records, 1):
        job = json.loads(json.dumps(source_record))
        prefix = f"manifest record {index}"
        if job.get("schema_version") != SCHEMA_VERSION or job.get("record_type") != "job":
            raise UsageError(f"{prefix}: expected schema_version=1 record_type=job")
        required = {
            "job_id",
            "plan_index",
            "path",
            "output_dir",
            "source",
            "archive",
            "scheduling",
            "tags",
            "warnings",
            "integrity",
        }
        missing = required - set(job)
        if missing:
            raise UsageError(f"{prefix}: missing field(s): {', '.join(sorted(missing))}")
        if not isinstance(job["path"], str) or not Path(job["path"]).is_absolute():
            raise UsageError(f"{prefix}: path must be absolute")
        path = Path(job["path"])
        source = _require_mapping(job["source"], f"{prefix}.source")
        size = ensure_int(source.get("size"), f"{prefix}.source.size")
        mtime_ns = ensure_int(source.get("mtime_ns"), f"{prefix}.source.mtime_ns")
        expected_id = deterministic_job_id(path, size, mtime_ns)
        if job["job_id"] != expected_id:
            raise UsageError(f"{prefix}: job_id does not match path/source identity")
        if job["job_id"] in ids:
            raise UsageError(f"{prefix}: duplicate job_id {job['job_id']}")
        ids.add(job["job_id"])
        if job["integrity"] != calculate_integrity(job):
            raise UsageError(f"{prefix}: immutable manifest fields were modified")

        ensure_int(job["plan_index"], f"{prefix}.plan_index")
        archive = _require_mapping(job["archive"], f"{prefix}.archive")
        scheduling = _require_mapping(job["scheduling"], f"{prefix}.scheduling")
        profile = scheduling.get("profile")
        if profile not in {"small", "heavy-serial", "heavy-scalable"}:
            raise UsageError(f"{prefix}.scheduling.profile is invalid")
        scheduling["priority"] = ensure_int(
            scheduling.get("priority"), f"{prefix}.scheduling.priority", minimum=-(2**31)
        )
        scheduling["estimated_weight"] = ensure_int(
            scheduling.get("estimated_weight"), f"{prefix}.scheduling.estimated_weight"
        )
        scheduling["io_tokens"] = ensure_int(
            scheduling.get("io_tokens"), f"{prefix}.scheduling.io_tokens", minimum=1
        )
        cpu = ensure_int(scheduling.get("cpu_tokens"), f"{prefix}.scheduling.cpu_tokens", minimum=1)
        threads = ensure_int(scheduling.get("threads"), f"{prefix}.scheduling.threads", minimum=1)
        warnings = job["warnings"]
        if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
            raise UsageError(f"{prefix}.warnings must be an array of strings")
        if cpu > config.cpu_budget:
            warnings.append(f"cpu_tokens clamped from {cpu} to {config.cpu_budget}")
            cpu = config.cpu_budget
        if threads > cpu:
            warnings.append(f"threads clamped from {threads} to allocated cpu_tokens {cpu}")
            threads = cpu
        scheduling["cpu_tokens"] = cpu
        scheduling["threads"] = threads
        original_profiles = {
            "below-small-threshold": "small",
            "bzip2-method": "heavy-scalable",
            "multi-block-7z": "heavy-scalable",
            "conservative-fallback": "heavy-serial",
            "inspection-failed": "heavy-serial",
        }
        planned_profile = original_profiles.get(scheduling.get("classification_reason"))
        if planned_profile is not None and profile != planned_profile:
            scheduling["profile_source"] = "manifest"
            scheduling["classification_reason"] = "manifest-override"
            warnings.append(f"scheduling profile overridden from {planned_profile} to {profile}")
        if scheduling["io_tokens"] > config.io_slots:
            raise UsageError(f"{prefix}: io_tokens exceeds configured I/O slots")
        if not isinstance(job["tags"], list) or not all(
            isinstance(tag, str) for tag in job["tags"]
        ):
            raise UsageError(f"{prefix}.tags must be an array of strings")
        if not isinstance(job["output_dir"], str) or not Path(job["output_dir"]).is_absolute():
            raise UsageError(f"{prefix}.output_dir must be absolute")
        output_key = path_key(Path(job["output_dir"]))
        if output_key in outputs:
            raise UsageError(
                f"{prefix}: output collision with {outputs[output_key]} at {job['output_dir']}"
            )
        outputs[output_key] = job["job_id"]
        if archive.get("encrypted") not in {True, False, None}:
            raise UsageError(f"{prefix}.archive.encrypted must be true, false, or null")
        job["integrity"] = calculate_integrity(job)
        validated.append(job)
    return validated
