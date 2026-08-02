"""Planning, JSON Lines schemas, integrity, and manifest normalization."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .config import Config
from .util import UsageError, ensure_int, path_key

LEGACY_SCHEMA_VERSION = 1
SCHEMA_VERSION = 2
_IDENTITY_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROFILES = {"small", "heavy-serial", "heavy-scalable"}
_ORIGINAL_PROFILES = {
    "below-small-threshold": "small",
    "bzip2-method": "heavy-scalable",
    "multi-block-7z": "heavy-scalable",
    "conservative-fallback": "heavy-serial",
    "inspection-failed": "heavy-serial",
    "create-below-small-threshold": "small",
    "create-store-mode": "heavy-serial",
    "create-7z-lzma2": "heavy-scalable",
    "create-zip-deflate": "heavy-scalable",
}


def legacy_job_id(path: Path, size: int, mtime_ns: int) -> str:
    """Derive the exact deterministic ID used by manifest v1."""

    payload = f"{path_key(path)}\0{size}\0{mtime_ns}".encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def source_identity(
    *, kind: str, size: int, mtime_ns: int, entry_count: int, digest: str = ""
) -> str:
    """Derive a stable source identity from already-inventoried metadata."""

    payload = f"{kind}\0{size}\0{mtime_ns}\0{entry_count}\0{digest}".encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def deterministic_job_id(operation: str, path: Path, identity: str) -> str:
    """Derive a schema-v2 ID from operation, normalized path, and identity."""

    payload = f"{operation}\0{path_key(path)}\0{identity}".encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def _v1_integrity_payload(job: dict[str, Any]) -> dict[str, Any]:
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


def _v2_integrity_payload(job: dict[str, Any]) -> dict[str, Any]:
    payload = {
        name: value
        for name, value in json.loads(json.dumps(job)).items()
        if name != "integrity" and not name.startswith("_")
    }
    destination = dict(payload["destination"])
    destination.pop("path", None)
    payload["destination"] = destination
    scheduling = dict(payload["scheduling"])
    for editable in ("profile", "priority", "cpu_tokens", "threads"):
        scheduling.pop(editable, None)
    payload["scheduling"] = scheduling
    payload.pop("tags", None)
    return payload


def calculate_integrity(job: dict[str, Any]) -> str:
    """Hash all fields except the schema-specific external-edit allowlist."""

    version = job.get("schema_version")
    if version == LEGACY_SCHEMA_VERSION:
        payload = _v1_integrity_payload(job)
    elif version == SCHEMA_VERSION:
        payload = _v2_integrity_payload(job)
    else:
        raise UsageError(f"cannot calculate integrity for schema_version={version!r}")
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(serialized).hexdigest()


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UsageError(f"{name} must be an object")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise UsageError(f"{name} must be a non-empty string")
    return value


def _validate_string_array(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise UsageError(f"{name} must be an array of strings")
    return value


def _validate_scheduling(
    scheduling: dict[str, Any],
    warnings: list[str],
    prefix: str,
    config: Config,
    *,
    enforce_io_budget: bool,
) -> None:
    profile = scheduling.get("profile")
    if profile not in _PROFILES:
        raise UsageError(f"{prefix}.profile is invalid")
    scheduling["priority"] = ensure_int(
        scheduling.get("priority"), f"{prefix}.priority", minimum=-(2**31)
    )
    scheduling["estimated_weight"] = ensure_int(
        scheduling.get("estimated_weight"), f"{prefix}.estimated_weight"
    )
    scheduling["io_tokens"] = ensure_int(
        scheduling.get("io_tokens"), f"{prefix}.io_tokens", minimum=1
    )
    cpu = ensure_int(scheduling.get("cpu_tokens"), f"{prefix}.cpu_tokens", minimum=1)
    threads = ensure_int(scheduling.get("threads"), f"{prefix}.threads", minimum=1)
    if cpu > config.cpu_budget:
        warnings.append(f"cpu_tokens clamped from {cpu} to {config.cpu_budget}")
        cpu = config.cpu_budget
    if threads > cpu:
        warnings.append(f"threads clamped from {threads} to allocated cpu_tokens {cpu}")
        threads = cpu
    scheduling["cpu_tokens"] = cpu
    scheduling["threads"] = threads
    planned_profile = _ORIGINAL_PROFILES.get(scheduling.get("classification_reason"))
    if planned_profile is not None and profile != planned_profile:
        scheduling["profile_source"] = "manifest"
        scheduling["classification_reason"] = "manifest-override"
        warnings.append(f"scheduling profile overridden from {planned_profile} to {profile}")
    if enforce_io_budget and scheduling["io_tokens"] > config.io_slots:
        raise UsageError(f"{prefix}: io_tokens exceeds configured I/O slots")


def _convert_v1(job: dict[str, Any]) -> dict[str, Any]:
    source = job["source"]
    identity = source_identity(
        kind="file",
        size=source["size"],
        mtime_ns=source["mtime_ns"],
        entry_count=1,
    )
    converted: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "job",
        "operation": "extract",
        "job_id": job["job_id"],
        "plan_index": job["plan_index"],
        "source": {
            "path": job["path"],
            "kind": "file",
            "size": source["size"],
            "mtime_ns": source["mtime_ns"],
            "entry_count": 1,
            "identity": identity,
        },
        "destination": {"path": job["output_dir"], "kind": "directory"},
        "archive": job["archive"],
        "scheduling": job["scheduling"],
        "tags": job["tags"],
        "warnings": job["warnings"],
        "_input_schema_version": LEGACY_SCHEMA_VERSION,
    }
    converted["integrity"] = calculate_integrity(converted)
    return converted


def _validate_v1(
    job: dict[str, Any],
    prefix: str,
    config: Config,
    *,
    enforce_io_budget: bool,
) -> dict[str, Any]:
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
    path_value = _require_string(job["path"], f"{prefix}.path")
    path = Path(path_value)
    if not path.is_absolute():
        raise UsageError(f"{prefix}.path must be absolute")
    source = _require_mapping(job["source"], f"{prefix}.source")
    size = ensure_int(source.get("size"), f"{prefix}.source.size")
    mtime_ns = ensure_int(source.get("mtime_ns"), f"{prefix}.source.mtime_ns")
    if job["job_id"] != legacy_job_id(path, size, mtime_ns):
        raise UsageError(f"{prefix}: job_id does not match path/source identity")
    ensure_int(job["plan_index"], f"{prefix}.plan_index")
    archive = _require_mapping(job["archive"], f"{prefix}.archive")
    if archive.get("encrypted") not in {True, False, None}:
        raise UsageError(f"{prefix}.archive.encrypted must be true, false, or null")
    warnings = _validate_string_array(job["warnings"], f"{prefix}.warnings")
    _validate_string_array(job["tags"], f"{prefix}.tags")
    scheduling = _require_mapping(job["scheduling"], f"{prefix}.scheduling")
    output = _require_string(job["output_dir"], f"{prefix}.output_dir")
    if not Path(output).is_absolute():
        raise UsageError(f"{prefix}.output_dir must be absolute")
    if job["integrity"] != calculate_integrity(job):
        raise UsageError(f"{prefix}: immutable manifest fields were modified")
    _validate_scheduling(
        scheduling,
        warnings,
        f"{prefix}.scheduling",
        config,
        enforce_io_budget=enforce_io_budget,
    )
    return _convert_v1(job)


def _validate_v2(
    job: dict[str, Any],
    prefix: str,
    config: Config,
    *,
    enforce_io_budget: bool,
) -> dict[str, Any]:
    required = {
        "operation",
        "job_id",
        "plan_index",
        "source",
        "destination",
        "archive",
        "scheduling",
        "tags",
        "warnings",
        "integrity",
    }
    missing = required - set(job)
    if missing:
        raise UsageError(f"{prefix}: missing field(s): {', '.join(sorted(missing))}")
    operation = job["operation"]
    if operation not in {"extract", "create"}:
        raise UsageError(f"{prefix}.operation must be extract or create")
    source = _require_mapping(job["source"], f"{prefix}.source")
    source_path_value = _require_string(source.get("path"), f"{prefix}.source.path")
    source_path = Path(source_path_value)
    if not source_path.is_absolute():
        raise UsageError(f"{prefix}.source.path must be absolute")
    source_kind = source.get("kind")
    allowed_source_kinds = {"file"} if operation == "extract" else {"file", "directory"}
    if source_kind not in allowed_source_kinds:
        raise UsageError(f"{prefix}.source.kind is invalid for {operation}")
    ensure_int(source.get("size"), f"{prefix}.source.size")
    ensure_int(source.get("mtime_ns"), f"{prefix}.source.mtime_ns")
    ensure_int(source.get("entry_count"), f"{prefix}.source.entry_count")
    identity = _require_string(source.get("identity"), f"{prefix}.source.identity")
    if not _IDENTITY_RE.fullmatch(identity):
        raise UsageError(f"{prefix}.source.identity must be a sha256 digest")
    expected_id = deterministic_job_id(operation, source_path, identity)
    if job["job_id"] != expected_id:
        raise UsageError(f"{prefix}: job_id does not match operation/source identity")
    ensure_int(job["plan_index"], f"{prefix}.plan_index")
    destination = _require_mapping(job["destination"], f"{prefix}.destination")
    destination_path_value = _require_string(destination.get("path"), f"{prefix}.destination.path")
    if not Path(destination_path_value).is_absolute():
        raise UsageError(f"{prefix}.destination.path must be absolute")
    expected_destination_kind = "directory" if operation == "extract" else "archive"
    if destination.get("kind") != expected_destination_kind:
        raise UsageError(
            f"{prefix}.destination.kind must be {expected_destination_kind} for {operation}"
        )
    archive = _require_mapping(job["archive"], f"{prefix}.archive")
    if operation == "extract":
        if archive.get("encrypted") not in {True, False, None}:
            raise UsageError(f"{prefix}.archive.encrypted must be true, false, or null")
    else:
        if archive.get("format") not in {"7z", "zip"}:
            raise UsageError(f"{prefix}.archive.format must be 7z or zip")
        _require_string(archive.get("method"), f"{prefix}.archive.method")
        level = ensure_int(archive.get("compression_level"), f"{prefix}.archive.compression_level")
        if level > 9:
            raise UsageError(f"{prefix}.archive.compression_level must be <= 9")
    warnings = _validate_string_array(job["warnings"], f"{prefix}.warnings")
    _validate_string_array(job["tags"], f"{prefix}.tags")
    scheduling = _require_mapping(job["scheduling"], f"{prefix}.scheduling")
    if job["integrity"] != calculate_integrity(job):
        raise UsageError(f"{prefix}: immutable manifest fields were modified")
    _validate_scheduling(
        scheduling,
        warnings,
        f"{prefix}.scheduling",
        config,
        enforce_io_budget=enforce_io_budget,
    )
    job["_input_schema_version"] = SCHEMA_VERSION
    job["integrity"] = calculate_integrity(job)
    return job


def validate_manifest(
    records: list[dict[str, Any]], config: Config, *, enforce_io_budget: bool = True
) -> list[dict[str, Any]]:
    """Validate the complete input and return canonical schema-v2 runtime jobs."""

    if not records:
        raise UsageError("manifest contains no jobs")
    validated: list[dict[str, Any]] = []
    ids: set[str] = set()
    outputs: dict[str, str] = {}
    for index, source_record in enumerate(records, 1):
        job = json.loads(json.dumps(source_record))
        prefix = f"manifest record {index}"
        if job.get("record_type") != "job":
            raise UsageError(f"{prefix}: record_type must be job")
        version = job.get("schema_version")
        if version == LEGACY_SCHEMA_VERSION:
            normalized = _validate_v1(job, prefix, config, enforce_io_budget=enforce_io_budget)
        elif version == SCHEMA_VERSION:
            normalized = _validate_v2(job, prefix, config, enforce_io_budget=enforce_io_budget)
        else:
            raise UsageError(f"{prefix}: unsupported schema_version {version!r}")
        job_id = normalized["job_id"]
        if job_id in ids:
            raise UsageError(f"{prefix}: duplicate job_id {job_id}")
        ids.add(job_id)
        destination_path = normalized["destination"]["path"]
        output_key = path_key(Path(destination_path))
        if output_key in outputs:
            raise UsageError(
                f"{prefix}: output collision with {outputs[output_key]} at {destination_path}"
            )
        outputs[output_key] = job_id
        validated.append(normalized)
    return validated
