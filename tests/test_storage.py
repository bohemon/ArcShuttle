from __future__ import annotations

from pathlib import Path

import pytest

from arcshuttle.storage import (
    StorageClass,
    StorageDetector,
    StorageObservation,
    resolve_auto_io_slots,
    storage_class_capacity,
)


@pytest.mark.parametrize(
    ("storage_class", "expected"),
    [
        (StorageClass.HDD, 1),
        (StorageClass.SSD, 2),
        (StorageClass.NVME, 4),
        (StorageClass.UNKNOWN, 2),
    ],
)
def test_storage_class_capacity(storage_class: StorageClass, expected: int) -> None:
    assert storage_class_capacity(storage_class) == expected


def test_auto_slots_use_the_lowest_unique_device_capacity() -> None:
    observations = [
        StorageObservation("nvme:0", StorageClass.NVME, "source"),
        StorageObservation("nvme:0", StorageClass.NVME, "destination on same device"),
        StorageObservation("disk:1", StorageClass.HDD, "external destination"),
    ]

    resolution = resolve_auto_io_slots(observations, max_processes=8)

    assert resolution.slots == 1
    assert [item.device_key for item in resolution.observations] == ["nvme:0", "disk:1"]
    assert resolution.used_fallback is False


def test_duplicate_device_keeps_the_more_conservative_observation() -> None:
    resolution = resolve_auto_io_slots(
        [
            StorageObservation("device", StorageClass.NVME, "first result"),
            StorageObservation("device", StorageClass.UNKNOWN, "ambiguous stacked device"),
        ],
        max_processes=8,
    )

    assert resolution.slots == 2
    assert resolution.observations[0].storage_class is StorageClass.UNKNOWN
    assert resolution.used_fallback is True
    assert "unknown" in resolution.reason


def test_auto_slots_are_capped_by_max_processes() -> None:
    resolution = resolve_auto_io_slots(
        [StorageObservation("nvme:0", StorageClass.NVME, "NVMe bus")],
        max_processes=3,
    )

    assert resolution.slots == 3
    assert "capped by max_processes=3" in resolution.reason


def test_no_observations_use_the_conservative_fallback() -> None:
    resolution = resolve_auto_io_slots([], max_processes=1)

    assert resolution.slots == 1
    assert resolution.observations == ()
    assert resolution.used_fallback is True


@pytest.mark.parametrize("max_processes", [0, -1])
def test_auto_slots_require_a_positive_process_budget(max_processes: int) -> None:
    with pytest.raises(ValueError, match="max_processes"):
        resolve_auto_io_slots([], max_processes=max_processes)


def test_observations_require_a_stable_device_key() -> None:
    with pytest.raises(ValueError, match="device_key"):
        resolve_auto_io_slots(
            [StorageObservation("", StorageClass.UNKNOWN, "missing key")], max_processes=2
        )


def test_detector_protocol_accepts_a_callable() -> None:
    def detector(path: Path) -> StorageObservation:
        return StorageObservation(f"test:{path.drive}", StorageClass.SSD, "fixture")

    typed_detector: StorageDetector = detector
    assert typed_detector(Path("/tmp")).storage_class is StorageClass.SSD
