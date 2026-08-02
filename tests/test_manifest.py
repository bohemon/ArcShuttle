from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from arcshuttle.config import Config
from arcshuttle.inspect import Inspection
from arcshuttle.manifest import (
    calculate_integrity,
    deterministic_job_id,
    source_identity,
    validate_manifest,
)
from arcshuttle.multipart import MultipartInfo
from arcshuttle.operations.extract import make_legacy_plan
from arcshuttle.sevenzip import InspectionResult
from arcshuttle.util import UsageError


def no_inspection(path: Path, timeout: float) -> InspectionResult:
    raise AssertionError("small known archive should not be inspected")


def plan_one(path: Path, **config_changes: object) -> tuple[dict[str, object], Config]:
    config = replace(Config(), inspect_threshold=10_000, small_threshold=10_000, **config_changes)
    result = make_legacy_plan([MultipartInfo(path, False)], config, no_inspection)
    assert result.errors == []
    return result.jobs[0], config


def v2_job(
    source_path: Path,
    destination_path: Path,
    *,
    operation: str = "extract",
    plan_index: int = 0,
) -> dict[str, object]:
    kind = "file" if source_path.is_file() else "directory"
    identity = source_identity(
        kind=kind,
        size=source_path.stat().st_size if source_path.is_file() else 0,
        mtime_ns=source_path.stat().st_mtime_ns,
        entry_count=1,
    )
    reason = "below-small-threshold" if operation == "extract" else "create-7z-lzma2"
    job: dict[str, object] = {
        "schema_version": 2,
        "record_type": "job",
        "operation": operation,
        "job_id": deterministic_job_id(operation, source_path, identity),
        "plan_index": plan_index,
        "source": {
            "path": str(source_path),
            "kind": kind,
            "size": source_path.stat().st_size if source_path.is_file() else 0,
            "mtime_ns": source_path.stat().st_mtime_ns,
            "entry_count": 1,
            "identity": identity,
        },
        "destination": {
            "path": str(destination_path),
            "kind": "directory" if operation == "extract" else "archive",
        },
        "archive": (
            {"format": "zip", "encrypted": False}
            if operation == "extract"
            else {"format": "7z", "method": "LZMA2", "compression_level": 5}
        ),
        "scheduling": {
            "profile": "small" if operation == "extract" else "heavy-scalable",
            "profile_source": "auto",
            "classification_reason": reason,
            "priority": 0,
            "estimated_weight": 1,
            "cpu_tokens": 1,
            "threads": 1,
            "io_tokens": 1,
        },
        "tags": [],
        "warnings": [],
    }
    job["integrity"] = calculate_integrity(job)
    return job


def test_json_lines_round_trip_and_validation(tmp_path: Path) -> None:
    archive = tmp_path / "日本語.zip"
    archive.write_bytes(b"zip")
    job, config = plan_one(archive)

    round_trip = json.loads(json.dumps(job, ensure_ascii=False))

    normalized = validate_manifest([round_trip], config)[0]

    assert normalized["source"]["path"] == str(archive.resolve())
    assert normalized["destination"]["path"] == job["output_dir"]
    assert normalized["operation"] == "extract"
    assert normalized["_input_schema_version"] == 1
    assert round_trip["schema_version"] == 1


def test_immutable_change_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    archive.write_bytes(b"zip")
    job, config = plan_one(archive)
    job["archive"]["format"] = "rar"  # type: ignore[index]

    with pytest.raises(UsageError, match="immutable"):
        validate_manifest([job], config)


def test_manifest_overrides_are_allowed_and_clamped(tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    archive.write_bytes(b"zip")
    job, config = plan_one(archive, cpu_budget=2)
    job["output_dir"] = str(tmp_path / "elsewhere")
    job["scheduling"]["profile"] = "heavy-scalable"  # type: ignore[index]
    job["scheduling"]["priority"] = 9  # type: ignore[index]
    job["scheduling"]["cpu_tokens"] = 99  # type: ignore[index]
    job["scheduling"]["threads"] = 20  # type: ignore[index]
    job["tags"] = ["filtered"]

    validated = validate_manifest([job], config)[0]

    assert validated["scheduling"]["cpu_tokens"] == 2
    assert validated["scheduling"]["threads"] == 2
    assert validated["scheduling"]["profile_source"] == "manifest"
    assert validated["scheduling"]["classification_reason"] == "manifest-override"
    assert "filtered" in validated["tags"]


def test_bad_job_id_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    archive.write_bytes(b"zip")
    job, config = plan_one(archive)
    job["job_id"] = "bad"

    with pytest.raises(UsageError, match="job_id"):
        validate_manifest([job], config)


def test_output_collision(tmp_path: Path) -> None:
    one = tmp_path / "same.zip"
    two = tmp_path / "same.7z"
    one.write_bytes(b"1")
    two.write_bytes(b"2")
    config = replace(Config(), inspect_threshold=100, small_threshold=100)

    result = make_legacy_plan(
        [MultipartInfo(one, False), MultipartInfo(two, False)], config, no_inspection
    )

    assert "output collision" in result.errors[0]


def test_integrity_excludes_only_editable_fields(tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    archive.write_bytes(b"zip")
    job, _ = plan_one(archive)
    original = job["integrity"]
    job["output_dir"] = str(tmp_path / "new")
    job["tags"] = ["x"]
    job["scheduling"]["priority"] = 4  # type: ignore[index]

    assert calculate_integrity(job) == original


def test_inspection_failure_is_conservative(tmp_path: Path) -> None:
    archive = tmp_path / "large.7z"
    archive.write_bytes(b"large")
    config = replace(Config(), inspect_threshold=0, small_threshold=1)

    result = make_legacy_plan(
        [MultipartInfo(archive, False)],
        config,
        lambda path, timeout: InspectionResult(Inspection(format="7z"), "timeout", True),
    )

    assert result.jobs[0]["scheduling"]["profile"] == "heavy-serial"
    assert result.jobs[0]["scheduling"]["classification_reason"] == "inspection-failed"


def test_v2_extract_and_create_jobs_can_share_a_manifest(tmp_path: Path) -> None:
    archive = tmp_path / "input.zip"
    archive.write_bytes(b"zip")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    extract = v2_job(archive.resolve(), (tmp_path / "out").resolve())
    create = v2_job(
        source_dir.resolve(),
        (tmp_path / "source.7z").resolve(),
        operation="create",
        plan_index=1,
    )

    validated = validate_manifest([extract, create], Config(cpu_budget=2, io_slots=2))

    assert [job["operation"] for job in validated] == ["extract", "create"]
    assert all(job["_input_schema_version"] == 2 for job in validated)


def test_v2_edit_allowlist_preserves_integrity(tmp_path: Path) -> None:
    archive = tmp_path / "input.zip"
    archive.write_bytes(b"zip")
    job = v2_job(archive.resolve(), (tmp_path / "out").resolve())
    original = job["integrity"]
    job["destination"]["path"] = str((tmp_path / "elsewhere").resolve())  # type: ignore[index]
    job["scheduling"]["profile"] = "heavy-scalable"  # type: ignore[index]
    job["scheduling"]["priority"] = 10  # type: ignore[index]
    job["scheduling"]["cpu_tokens"] = 8  # type: ignore[index]
    job["scheduling"]["threads"] = 8  # type: ignore[index]
    job["tags"] = ["urgent"]

    assert calculate_integrity(job) == original
    validated = validate_manifest([job], Config(cpu_budget=2, io_slots=1))[0]
    assert validated["destination"]["path"] == str((tmp_path / "elsewhere").resolve())
    assert validated["scheduling"]["cpu_tokens"] == 2
    assert validated["scheduling"]["threads"] == 2


def test_v2_immutable_change_and_integrity_mismatch_are_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "input.zip"
    archive.write_bytes(b"zip")
    job = v2_job(archive.resolve(), (tmp_path / "out").resolve())
    job["source"]["size"] = 99  # type: ignore[index]

    with pytest.raises(UsageError, match="immutable"):
        validate_manifest([job], Config())


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda job: job.update(schema_version=99), "unsupported schema_version"),
        (lambda job: job.update(operation="delete"), "operation"),
        (lambda job: job.pop("source"), "missing field"),
    ],
)
def test_unsupported_or_incomplete_v2_records_are_rejected(
    tmp_path: Path, change, match: str
) -> None:
    archive = tmp_path / "input.zip"
    archive.write_bytes(b"zip")
    job = v2_job(archive.resolve(), (tmp_path / "out").resolve())
    change(job)

    with pytest.raises(UsageError, match=match):
        validate_manifest([job], Config())


def test_v2_destination_collision_is_rejected_before_execution(tmp_path: Path) -> None:
    one = tmp_path / "one.zip"
    two = tmp_path / "two.zip"
    one.write_bytes(b"1")
    two.write_bytes(b"2")
    destination = (tmp_path / "same").resolve()

    with pytest.raises(UsageError, match="output collision"):
        validate_manifest(
            [
                v2_job(one.resolve(), destination, plan_index=0),
                v2_job(two.resolve(), destination, plan_index=1),
            ],
            Config(),
        )


def test_v2_io_budget_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "input.zip"
    archive.write_bytes(b"zip")
    job = v2_job(archive.resolve(), (tmp_path / "out").resolve())
    job["scheduling"]["io_tokens"] = 2  # type: ignore[index]
    job["integrity"] = calculate_integrity(job)

    with pytest.raises(UsageError, match="I/O slots"):
        validate_manifest([job], Config(io_slots=1))

    preflight = validate_manifest([job], Config(io_slots=1), enforce_io_budget=False)
    assert preflight[0]["scheduling"]["io_tokens"] == 2
