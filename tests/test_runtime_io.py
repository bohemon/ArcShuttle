from __future__ import annotations

from pathlib import Path

import pytest

from arcshuttle.cli import _prepare_runtime_jobs
from arcshuttle.config import Config, resolve_config
from arcshuttle.manifest import calculate_integrity
from arcshuttle.operations.create import make_create_plan
from arcshuttle.storage import StorageClass, StorageObservation
from arcshuttle.util import UsageError


class RecordingDetector:
    def __init__(self, classify=None) -> None:
        self.paths: list[Path] = []
        self.classify = classify or (lambda _path: StorageClass.NVME)

    def __call__(self, path: Path) -> StorageObservation:
        self.paths.append(path)
        storage_class = self.classify(path)
        return StorageObservation(f"fixture:{path}", storage_class, "fixture")


def planned_job(tmp_path: Path, config: Config) -> dict[str, object]:
    source = tmp_path / "source.dat"
    source.write_bytes(b"source")
    planning = make_create_plan([source], config)
    assert planning.errors == []
    return planning.jobs[0]


def automatic_config(tmp_path: Path, **values: object) -> Config:
    return resolve_config(
        {"max_processes": 8, "output_dir": tmp_path / "out", **values}, environ={}
    )


def test_runtime_auto_resolution_uses_validated_source_and_destination_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = automatic_config(tmp_path)
    job = planned_job(tmp_path, config)
    detector = RecordingDetector()

    jobs, effective = _prepare_runtime_jobs(
        [job], config, program_name="arcshuttle", detector=detector
    )

    assert effective.io_slots == 4
    assert jobs[0]["job_id"] == job["job_id"]
    assert detector.paths == [
        Path(job["source"]["path"]),  # type: ignore[index]
        Path(job["destination"]["path"]),  # type: ignore[index]
    ]
    assert "arcshuttle: I/O auto: io_slots=4" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("values", "expected_slots"),
    [
        ({"io_slots": 3}, 3),
        ({"storage_profile": "hdd"}, 1),
        ({"storage_profile": "ssd"}, 2),
        ({"storage_profile": "nvme"}, 4),
    ],
)
def test_explicit_io_configuration_bypasses_detection(
    tmp_path: Path,
    values: dict[str, object],
    expected_slots: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = automatic_config(tmp_path, **values)
    job = planned_job(tmp_path, config)

    def forbidden(_path: Path) -> StorageObservation:
        raise AssertionError("explicit configuration must not invoke detection")

    _, effective = _prepare_runtime_jobs(
        [job], config, program_name="arcshuttle", detector=forbidden
    )

    assert effective.io_slots == expected_slots
    assert "I/O auto" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("storage_class", "expected_slots"),
    [
        (StorageClass.HDD, 1),
        (StorageClass.SSD, 2),
        (StorageClass.NVME, 4),
        (StorageClass.UNKNOWN, 2),
    ],
)
def test_runtime_auto_resolution_maps_storage_classes(
    tmp_path: Path, storage_class: StorageClass, expected_slots: int
) -> None:
    config = automatic_config(tmp_path)
    job = planned_job(tmp_path, config)

    _, effective = _prepare_runtime_jobs(
        [job],
        config,
        program_name="arcshuttle",
        detector=RecordingDetector(lambda _path: storage_class),
    )

    assert effective.io_slots == expected_slots


def test_mixed_endpoints_use_the_lowest_capacity(tmp_path: Path) -> None:
    config = automatic_config(tmp_path)
    job = planned_job(tmp_path, config)
    destination = Path(job["destination"]["path"])  # type: ignore[index]
    detector = RecordingDetector(
        lambda path: StorageClass.HDD if path == destination else StorageClass.NVME
    )

    _, effective = _prepare_runtime_jobs(
        [job], config, program_name="arcshuttle", detector=detector
    )

    assert effective.io_slots == 1


def test_detector_failure_uses_the_two_slot_fallback(tmp_path: Path) -> None:
    config = automatic_config(tmp_path)
    job = planned_job(tmp_path, config)

    def denied(_path: Path) -> StorageObservation:
        raise PermissionError("fixture")

    _, effective = _prepare_runtime_jobs([job], config, program_name="arcshuttle", detector=denied)

    assert effective.io_slots == 2


def test_quiet_suppresses_auto_resolution_diagnostic(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = automatic_config(tmp_path, quiet=True)
    job = planned_job(tmp_path, config)

    _prepare_runtime_jobs([job], config, program_name="arcshuttle", detector=RecordingDetector())

    assert capsys.readouterr().err == ""


def test_invalid_manifest_is_rejected_before_detection(tmp_path: Path) -> None:
    config = automatic_config(tmp_path)
    detector = RecordingDetector()

    with pytest.raises(UsageError, match="missing field"):
        _prepare_runtime_jobs(
            [{"schema_version": 2, "record_type": "job"}],
            config,
            program_name="arcshuttle",
            detector=detector,
        )

    assert detector.paths == []


def test_io_budget_is_enforced_after_nvme_resolution(tmp_path: Path) -> None:
    config = automatic_config(tmp_path, max_processes=4)
    job = planned_job(tmp_path, config)
    job["scheduling"]["io_tokens"] = 3  # type: ignore[index]
    job["integrity"] = calculate_integrity(job)

    jobs, effective = _prepare_runtime_jobs(
        [job], config, program_name="arcshuttle", detector=RecordingDetector()
    )

    assert effective.io_slots == 4
    assert jobs[0]["scheduling"]["io_tokens"] == 3
