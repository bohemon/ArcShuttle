"""Read-only Linux storage endpoint classification.

The detector deliberately avoids subprocesses and active probes.  Its filesystem
operations are injectable so the behavior can be tested without depending on the
host's block devices or mount layout.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from arcshuttle.storage import StorageClass, StorageObservation, storage_class_capacity


class _StatResult(Protocol):
    st_dev: int


StatPath = Callable[[Path], _StatResult]
ReadText = Callable[[Path], str]
ListDirectory = Callable[[Path], Iterable[Path]]
ResolvePath = Callable[[Path], Path]
DeviceNumbers = Callable[[int], tuple[int, int]]


_NVME_COMPONENT = re.compile(r"^nvme\d+(?:n\d+)?(?:p\d+)?$")
_NETWORK_FILESYSTEMS = frozenset(
    {
        "9p",
        "afs",
        "ceph",
        "cifs",
        "davfs",
        "davfs2",
        "fuse.glusterfs",
        "fuse.rclone",
        "fuse.sshfs",
        "glusterfs",
        "lustre",
        "ncpfs",
        "nfs",
        "nfs4",
        "smb3",
        "sshfs",
    }
)


def _stat_path(path: Path) -> _StatResult:
    return path.stat()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _list_directory(path: Path) -> Iterable[Path]:
    return path.iterdir()


def _resolve_path(path: Path) -> Path:
    return path.resolve(strict=True)


def _device_numbers(device: int) -> tuple[int, int]:
    return os.major(device), os.minor(device)


@dataclass(frozen=True, slots=True)
class _NodeClassification:
    storage_class: StorageClass
    reason: str


@dataclass(slots=True)
class LinuxStorageDetector:
    """Classify Linux paths from mount and sysfs metadata without modifying storage."""

    sysfs_root: Path = Path("/sys")
    mountinfo_path: Path = Path("/proc/self/mountinfo")
    stat_path: StatPath = field(default=_stat_path, repr=False)
    read_text: ReadText = field(default=_read_text, repr=False)
    list_directory: ListDirectory = field(default=_list_directory, repr=False)
    resolve_path: ResolvePath = field(default=_resolve_path, repr=False)
    device_numbers: DeviceNumbers = field(default=_device_numbers, repr=False)
    _device_cache: dict[str, StorageObservation] = field(
        default_factory=dict, init=False, repr=False
    )

    def __call__(self, path: Path) -> StorageObservation:
        """Return a best-effort observation for *path* or its nearest existing parent."""

        requested = path.absolute()
        existing_path, device, error = self._nearest_existing_device(requested)
        if existing_path is None or device is None:
            return StorageObservation(
                f"linux:path:{requested}",
                StorageClass.UNKNOWN,
                error or "no existing path was available for storage detection",
            )

        try:
            major, minor = self.device_numbers(device)
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            return StorageObservation(
                f"linux:device:{device}",
                StorageClass.UNKNOWN,
                f"could not decode st_dev for {existing_path}: {exc}",
            )

        device_id = f"{major}:{minor}"
        device_key = f"linux:{device_id}"
        cached = self._device_cache.get(device_key)
        if cached is not None:
            return cached
        filesystem = self._filesystem_type(device_id)
        if filesystem is not None and self._is_network_filesystem(filesystem):
            observation = StorageObservation(
                device_key,
                StorageClass.UNKNOWN,
                f"{existing_path} uses network filesystem {filesystem}",
            )
            self._device_cache[device_key] = observation
            return observation

        device_link = self.sysfs_root / "dev" / "block" / device_id
        node, link_error = self._resolve_sysfs_path(device_link)
        if node is None:
            observation = StorageObservation(
                device_key,
                StorageClass.UNKNOWN,
                f"sysfs metadata for {device_id} is unavailable: {link_error}",
            )
            self._device_cache[device_key] = observation
            return observation

        classification = self._classify_node(node, frozenset())
        observation = StorageObservation(
            device_key, classification.storage_class, classification.reason
        )
        self._device_cache[device_key] = observation
        return observation

    def _nearest_existing_device(self, path: Path) -> tuple[Path | None, int | None, str | None]:
        candidate = path
        while True:
            try:
                return candidate, self.stat_path(candidate).st_dev, None
            except (FileNotFoundError, NotADirectoryError):
                parent = candidate.parent
                if parent == candidate:
                    return None, None, f"neither {path} nor any parent could be inspected"
                candidate = parent
            except (OSError, ValueError) as exc:
                return None, None, f"could not inspect {candidate}: {exc}"

    def _filesystem_type(self, device_id: str) -> str | None:
        try:
            content = self.read_text(self.mountinfo_path)
        except (OSError, UnicodeError):
            return None

        for line in content.splitlines():
            before, separator, after = line.partition(" - ")
            if not separator:
                continue
            fields = before.split()
            details = after.split()
            if len(fields) >= 3 and details and fields[2] == device_id:
                return details[0].lower()
        return None

    @staticmethod
    def _is_network_filesystem(filesystem: str) -> bool:
        return filesystem in _NETWORK_FILESYSTEMS or filesystem.startswith("fuse.sshfs")

    def _resolve_sysfs_path(self, path: Path) -> tuple[Path | None, str | None]:
        try:
            resolved = self.resolve_path(path).absolute()
        except (OSError, RuntimeError, ValueError) as exc:
            return None, str(exc)

        root = self.sysfs_root.absolute()
        if not resolved.is_relative_to(root):
            return None, f"resolved path {resolved} escapes sysfs root {root}"
        return resolved, None

    def _classify_node(self, node: Path, ancestors: frozenset[Path]) -> _NodeClassification:
        if node in ancestors:
            return _NodeClassification(
                StorageClass.UNKNOWN, f"cycle detected in the sysfs graph at {node}"
            )

        rotational, owner, metadata_errors = self._rotational_metadata(node)
        if rotational is not None and owner is not None:
            if rotational == 1:
                return _NodeClassification(StorageClass.HDD, f"{owner} reports queue/rotational=1")
            if self._is_nvme(node, owner):
                return _NodeClassification(
                    StorageClass.NVME,
                    f"{owner} reports queue/rotational=0 and has NVMe identity",
                )
            return _NodeClassification(
                StorageClass.SSD, f"{owner} reports queue/rotational=0 without NVMe identity"
            )

        child_results: list[_NodeClassification] = []
        graph_errors = list(metadata_errors)
        slaves_path = node / "slaves"
        try:
            slave_links = sorted(self.list_directory(slaves_path), key=lambda item: item.name)
        except (OSError, RuntimeError, ValueError) as exc:
            graph_errors.append(f"could not inspect {slaves_path}: {exc}")
            slave_links = []

        next_ancestors = ancestors | {node}
        for slave_link in slave_links:
            slave, link_error = self._resolve_sysfs_path(slave_link)
            if slave is None:
                child_results.append(
                    _NodeClassification(
                        StorageClass.UNKNOWN,
                        f"could not resolve backing device {slave_link}: {link_error}",
                    )
                )
                continue
            child_results.append(self._classify_node(slave, next_ancestors))

        if child_results:
            return self._combine_backing_devices(node, child_results)

        detail = "; ".join(graph_errors) if graph_errors else "no usable queue or slave metadata"
        return _NodeClassification(
            StorageClass.UNKNOWN, f"could not classify sysfs device {node}: {detail}"
        )

    def _rotational_metadata(self, node: Path) -> tuple[int | None, Path | None, tuple[str, ...]]:
        errors: list[str] = []
        for owner in (node, node.parent):
            metadata_path = owner / "queue" / "rotational"
            try:
                value = self.read_text(metadata_path).strip()
            except FileNotFoundError:
                continue
            except (OSError, UnicodeError) as exc:
                errors.append(f"could not read {metadata_path}: {exc}")
                continue
            if value in {"0", "1"}:
                return int(value), owner, tuple(errors)
            errors.append(f"{metadata_path} contains invalid value {value!r}")
        return None, None, tuple(errors)

    def _is_nvme(self, node: Path, queue_owner: Path) -> bool:
        for candidate in (node, queue_owner):
            if any(_NVME_COMPONENT.fullmatch(part) for part in candidate.parts):
                return True
            transport_path = candidate / "device" / "transport"
            try:
                transport = self.read_text(transport_path).strip().lower()
            except (OSError, UnicodeError):
                continue
            if transport == "nvme" or transport.startswith("nvme-"):
                return True
        return False

    @staticmethod
    def _combine_backing_devices(
        node: Path, results: list[_NodeClassification]
    ) -> _NodeClassification:
        classes = {result.storage_class for result in results}
        capacity = min(storage_class_capacity(item) for item in classes)
        candidates = [item for item in classes if storage_class_capacity(item) == capacity]
        storage_class = (
            StorageClass.UNKNOWN if StorageClass.UNKNOWN in candidates else min(candidates)
        )
        names = ", ".join(sorted(item.value for item in classes))
        details = "; ".join(result.reason for result in results)
        return _NodeClassification(
            storage_class,
            f"{node} uses backing classes {names}; selected conservative class "
            f"{storage_class.value} ({details})",
        )
