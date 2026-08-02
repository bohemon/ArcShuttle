"""Platform-neutral storage classification and automatic I/O-slot policy."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .util import path_key


class StorageClass(StrEnum):
    """Coarse storage classes used for conservative scheduler capacity decisions."""

    HDD = "hdd"
    SSD = "ssd"
    NVME = "nvme"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class StorageObservation:
    """One path's platform-independent storage identity and classification."""

    device_key: str
    storage_class: StorageClass
    reason: str


class StorageDetector(Protocol):
    """Callable boundary implemented by platform-specific endpoint detectors."""

    def __call__(self, path: Path) -> StorageObservation: ...


@dataclass(frozen=True, slots=True)
class IoSlotResolution:
    """The deterministic result of aggregating detected storage endpoints."""

    slots: int
    observations: tuple[StorageObservation, ...]
    used_fallback: bool
    reason: str


_CLASS_CAPACITY = {
    StorageClass.HDD: 1,
    StorageClass.SSD: 2,
    StorageClass.NVME: 4,
    StorageClass.UNKNOWN: 2,
}


def storage_class_capacity(storage_class: StorageClass) -> int:
    """Return the global slot capacity assigned to a detected storage class."""

    return _CLASS_CAPACITY[storage_class]


def _more_conservative(
    candidate: StorageObservation, current: StorageObservation
) -> StorageObservation:
    candidate_capacity = storage_class_capacity(candidate.storage_class)
    current_capacity = storage_class_capacity(current.storage_class)
    if candidate_capacity < current_capacity:
        return candidate
    if candidate_capacity == current_capacity and candidate.storage_class is StorageClass.UNKNOWN:
        return candidate
    return current


def resolve_auto_io_slots(
    observations: Iterable[StorageObservation], *, max_processes: int
) -> IoSlotResolution:
    """Deduplicate endpoints and derive the conservative global automatic I/O budget."""

    if max_processes < 1:
        raise ValueError("max_processes must be positive")

    by_device: dict[str, StorageObservation] = {}
    for observation in observations:
        if not observation.device_key:
            raise ValueError("storage observation device_key must be non-empty")
        current = by_device.get(observation.device_key)
        by_device[observation.device_key] = (
            observation if current is None else _more_conservative(observation, current)
        )

    unique = tuple(by_device.values())
    if not unique:
        slots = min(2, max_processes)
        return IoSlotResolution(
            slots,
            unique,
            True,
            "no storage endpoints were available; using the conservative fallback",
        )

    capacity = min(storage_class_capacity(item.storage_class) for item in unique)
    slots = min(capacity, max_processes)
    unknown_count = sum(item.storage_class is StorageClass.UNKNOWN for item in unique)
    classes = ", ".join(sorted({item.storage_class.value for item in unique}))
    if unknown_count:
        reason = (
            f"detected storage classes: {classes}; {unknown_count} endpoint(s) were unknown, "
            "using the conservative fallback capacity"
        )
    else:
        reason = f"detected storage classes: {classes}; using the lowest endpoint capacity"
    if slots < capacity:
        reason += f", capped by max_processes={max_processes}"
    return IoSlotResolution(slots, unique, bool(unknown_count), reason)


def default_storage_detector() -> StorageDetector:
    """Return the native detector for the current supported platform."""

    if sys.platform == "win32":
        from .storage_windows import WindowsStorageDetector

        return WindowsStorageDetector()
    if sys.platform.startswith("linux"):
        from .storage_linux import LinuxStorageDetector

        return LinuxStorageDetector()

    platform = sys.platform

    def unsupported(path: Path) -> StorageObservation:
        return StorageObservation(
            f"unsupported:{platform}:{path_key(path)}",
            StorageClass.UNKNOWN,
            f"storage detection is unsupported on platform {platform}",
        )

    return unsupported


def observe_storage_paths(
    paths: Iterable[Path], detector: StorageDetector
) -> tuple[StorageObservation, ...]:
    """Detect unique paths while converting detector failures into unknown observations."""

    observations: list[StorageObservation] = []
    seen: set[str] = set()
    for path in paths:
        key = path_key(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            observation = detector(path)
        except Exception as exc:  # Detection is advisory and must never prevent execution.
            observation = StorageObservation(
                f"error:path:{key}",
                StorageClass.UNKNOWN,
                f"storage detection failed with {type(exc).__name__}",
            )
        observations.append(observation)
    return tuple(observations)
