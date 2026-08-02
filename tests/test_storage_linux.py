from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from arcshuttle.storage import StorageClass
from arcshuttle.storage_linux import LinuxStorageDetector


@dataclass(frozen=True)
class FakeStat:
    st_dev: int


class FakeLinuxMetadata:
    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        self.mountinfo = self.root / "proc" / "self" / "mountinfo"
        self.stats: dict[Path, int | BaseException] = {}
        self.device_numbers: dict[int, tuple[int, int]] = {}
        self.text: dict[Path, str | BaseException] = {}
        self.links: dict[Path, Path | BaseException] = {}
        self.directories: dict[Path, list[Path] | BaseException] = {}

    def detector(self) -> LinuxStorageDetector:
        return LinuxStorageDetector(
            sysfs_root=self.root / "sys",
            mountinfo_path=self.mountinfo,
            stat_path=self.stat_path,
            read_text=self.read_text,
            list_directory=self.list_directory,
            resolve_path=self.resolve_path,
            device_numbers=self.decode_device,
        )

    def endpoint(self, path: Path, major: int, minor: int) -> None:
        encoded = len(self.device_numbers) + 1
        self.stats[path.absolute()] = encoded
        self.device_numbers[encoded] = (major, minor)

    def block_device(self, major: int, minor: int, relative_node: str) -> Path:
        node = self.root / "sys" / "devices" / relative_node
        self.links[self.root / "sys" / "dev" / "block" / f"{major}:{minor}"] = node
        return node

    def rotational(self, node: Path, value: str) -> None:
        self.text[node / "queue" / "rotational"] = value

    def slaves(self, node: Path, **targets: Path | BaseException) -> None:
        directory = node / "slaves"
        entries = []
        for name, target in targets.items():
            entry = directory / name
            entries.append(entry)
            self.links[entry] = target
        self.directories[directory] = entries

    def stat_path(self, path: Path) -> FakeStat:
        value = self.stats.get(path.absolute(), FileNotFoundError(path))
        if isinstance(value, BaseException):
            raise value
        return FakeStat(value)

    def decode_device(self, device: int) -> tuple[int, int]:
        return self.device_numbers[device]

    def read_text(self, path: Path) -> str:
        value = self.text.get(path, FileNotFoundError(path))
        if isinstance(value, BaseException):
            raise value
        return value

    def resolve_path(self, path: Path) -> Path:
        value = self.links.get(path, FileNotFoundError(path))
        if isinstance(value, BaseException):
            raise value
        return value

    def list_directory(self, path: Path) -> list[Path]:
        value = self.directories.get(path, FileNotFoundError(path))
        if isinstance(value, BaseException):
            raise value
        return value


@pytest.mark.parametrize(
    ("node_name", "rotational", "expected"),
    [
        ("pci/block/sda", "1", StorageClass.HDD),
        ("pci/block/sdb", "0", StorageClass.SSD),
        ("pci/nvme/nvme0/nvme0n1", "0", StorageClass.NVME),
    ],
)
def test_classifies_direct_block_devices(
    tmp_path: Path, node_name: str, rotational: str, expected: StorageClass
) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    endpoint = tmp_path / "endpoint"
    fake.endpoint(endpoint, 8, 0)
    node = fake.block_device(8, 0, node_name)
    fake.rotational(node, rotational)

    observation = fake.detector()(endpoint)

    assert observation.device_key == "linux:8:0"
    assert observation.storage_class is expected
    assert "rotational=" in observation.reason


def test_nvme_transport_metadata_is_used_when_names_are_generic(tmp_path: Path) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    endpoint = tmp_path / "endpoint"
    fake.endpoint(endpoint, 259, 0)
    node = fake.block_device(259, 0, "pci/block/disk0")
    fake.rotational(node, "0")
    fake.text[node / "device" / "transport"] = "nvme\n"

    assert fake.detector()(endpoint).storage_class is StorageClass.NVME


def test_partition_inherits_parent_queue_metadata(tmp_path: Path) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    endpoint = tmp_path / "partition"
    fake.endpoint(endpoint, 8, 1)
    partition = fake.block_device(8, 1, "pci/block/sda/sda1")
    fake.rotational(partition.parent, "0")

    observation = fake.detector()(endpoint)

    assert observation.storage_class is StorageClass.SSD
    assert str(partition.parent) in observation.reason


def test_stacked_device_uses_most_conservative_backing_class(tmp_path: Path) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    endpoint = tmp_path / "mapped"
    fake.endpoint(endpoint, 253, 0)
    mapped = fake.block_device(253, 0, "virtual/block/dm-0")
    hdd = fake.root / "sys" / "devices" / "pci" / "block" / "sda"
    nvme = fake.root / "sys" / "devices" / "pci" / "nvme" / "nvme0n1"
    fake.rotational(hdd, "1")
    fake.rotational(nvme, "0")
    fake.slaves(mapped, sda=hdd, nvme0n1=nvme)

    observation = fake.detector()(endpoint)

    assert observation.storage_class is StorageClass.HDD
    assert "backing classes hdd, nvme" in observation.reason
    assert "selected conservative class hdd" in observation.reason


def test_duplicate_paths_have_the_same_device_identity(tmp_path: Path) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    fake.endpoint(first, 8, 0)
    fake.endpoint(second, 8, 0)
    node = fake.block_device(8, 0, "pci/block/sda")
    fake.rotational(node, "1")

    first_result = fake.detector()(first)
    second_result = fake.detector()(second)

    assert first_result.device_key == second_result.device_key == "linux:8:0"


def test_device_classification_is_cached_for_the_command(tmp_path: Path) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    fake.endpoint(first, 8, 0)
    fake.endpoint(second, 8, 0)
    node = fake.block_device(8, 0, "pci/block/sda")
    fake.rotational(node, "1")
    detector = fake.detector()

    assert detector(first).storage_class is StorageClass.HDD
    fake.text[node / "queue" / "rotational"] = AssertionError("cache was not used")
    fake.links[fake.root / "sys" / "dev" / "block" / "8:0"] = AssertionError("cache was not used")

    assert detector(second).storage_class is StorageClass.HDD


def test_missing_destination_uses_nearest_existing_parent(tmp_path: Path) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    parent = tmp_path / "destination"
    missing = parent / "new" / "archive.7z"
    fake.endpoint(parent, 259, 0)
    node = fake.block_device(259, 0, "pci/nvme/nvme1/nvme1n1")
    fake.rotational(node, "0")

    observation = fake.detector()(missing)

    assert observation.storage_class is StorageClass.NVME
    assert observation.device_key == "linux:259:0"


def test_network_filesystem_is_unknown(tmp_path: Path) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    endpoint = tmp_path / "network"
    fake.endpoint(endpoint, 0, 42)
    fake.text[fake.mountinfo] = "30 20 0:42 / /mnt/share rw - nfs server:/share rw\n"

    observation = fake.detector()(endpoint)

    assert observation.storage_class is StorageClass.UNKNOWN
    assert "network filesystem nfs" in observation.reason


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("absent", "sysfs metadata"),
        ("outside", "escapes sysfs root"),
        ("malformed", "invalid value"),
        ("denied", "Permission denied"),
    ],
)
def test_unavailable_or_malformed_sysfs_is_unknown(tmp_path: Path, setup: str, reason: str) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    endpoint = tmp_path / setup
    fake.endpoint(endpoint, 8, 0)
    link = fake.root / "sys" / "dev" / "block" / "8:0"
    if setup == "outside":
        fake.links[link] = fake.root / "outside" / "sda"
    elif setup in {"malformed", "denied"}:
        node = fake.block_device(8, 0, "pci/block/sda")
        fake.text[node / "queue" / "rotational"] = (
            "sometimes" if setup == "malformed" else PermissionError("Permission denied")
        )

    observation = fake.detector()(endpoint)

    assert observation.storage_class is StorageClass.UNKNOWN
    assert reason in observation.reason


def test_broken_slave_link_is_unknown(tmp_path: Path) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    endpoint = tmp_path / "mapped"
    fake.endpoint(endpoint, 253, 0)
    mapped = fake.block_device(253, 0, "virtual/block/dm-0")
    fake.slaves(mapped, broken=FileNotFoundError("broken link"))

    observation = fake.detector()(endpoint)

    assert observation.storage_class is StorageClass.UNKNOWN
    assert "could not resolve backing device" in observation.reason


def test_stacked_device_cycle_is_unknown(tmp_path: Path) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    endpoint = tmp_path / "mapped"
    fake.endpoint(endpoint, 253, 0)
    first = fake.block_device(253, 0, "virtual/block/dm-0")
    second = fake.root / "sys" / "devices" / "virtual" / "block" / "dm-1"
    fake.slaves(first, dm1=second)
    fake.slaves(second, dm0=first)

    observation = fake.detector()(endpoint)

    assert observation.storage_class is StorageClass.UNKNOWN
    assert "cycle detected" in observation.reason


def test_stat_access_denial_returns_unknown_without_climbing_to_parent(tmp_path: Path) -> None:
    fake = FakeLinuxMetadata(tmp_path)
    endpoint = (tmp_path / "restricted").absolute()
    fake.stats[endpoint] = PermissionError("access denied")

    observation = fake.detector()(endpoint)

    assert observation.storage_class is StorageClass.UNKNOWN
    assert observation.device_key.startswith("linux:path:")
    assert "access denied" in observation.reason
