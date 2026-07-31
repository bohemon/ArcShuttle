from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from arcshuttle.config import Config
from arcshuttle.inspect import Inspection
from arcshuttle.manifest import calculate_integrity, make_plan, validate_manifest
from arcshuttle.multipart import MultipartInfo
from arcshuttle.sevenzip import InspectionResult
from arcshuttle.util import UsageError


def no_inspection(path: Path, timeout: float) -> InspectionResult:
    raise AssertionError("small known archive should not be inspected")


def plan_one(path: Path, **config_changes: object) -> tuple[dict[str, object], Config]:
    config = replace(Config(), inspect_threshold=10_000, small_threshold=10_000, **config_changes)
    result = make_plan([MultipartInfo(path, False)], config, no_inspection)
    assert result.errors == []
    return result.jobs[0], config


def test_json_lines_round_trip_and_validation(tmp_path: Path) -> None:
    archive = tmp_path / "日本語.zip"
    archive.write_bytes(b"zip")
    job, config = plan_one(archive)

    round_trip = json.loads(json.dumps(job, ensure_ascii=False))

    assert validate_manifest([round_trip], config)[0]["path"] == str(archive.resolve())


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

    result = make_plan(
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

    result = make_plan(
        [MultipartInfo(archive, False)],
        config,
        lambda path, timeout: InspectionResult(Inspection(format="7z"), "timeout", True),
    )

    assert result.jobs[0]["scheduling"]["profile"] == "heavy-serial"
    assert result.jobs[0]["scheduling"]["classification_reason"] == "inspection-failed"
