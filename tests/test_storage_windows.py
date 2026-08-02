from __future__ import annotations

import os
import struct
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path

import pytest

from arcshuttle.storage import StorageClass
from arcshuttle.storage_windows import (
    CtypesWindowsNativeApi,
    DriveType,
    StorageBusType,
    WindowsDeviceIdentity,
    WindowsStorageDetector,
    _parse_bus_type,
    _parse_device_identity,
    _parse_seek_penalty,
)


class FakeNativeApi:
    def __init__(
        self,
        *,
        volume_root: str = "C:\\",
        drive_type: int = DriveType.FIXED,
        volume_name: str = "\\\\?\\Volume{test}\\",
        identity: WindowsDeviceIdentity | None = None,
        bus_type: int = 11,
        seek_penalty: bool = False,
        fail_at: str | None = None,
    ) -> None:
        self.volume_root = volume_root
        self.drive_type_value = drive_type
        self.volume_name_value = volume_name
        self.identity = WindowsDeviceIdentity(7, 3) if identity is None else identity
        self.bus_type_value = bus_type
        self.seek_penalty_value = seek_penalty
        self.fail_at = fail_at
        self.resolved_path: str | None = None
        self.opened = 0
        self.closed = 0

    def _maybe_fail(self, action: str) -> None:
        if self.fail_at == action:
            if action == "malformed":
                raise ValueError("malformed native response")
            error = OSError(5, "access denied")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error

    def volume_path_name(self, path: str) -> str:
        self._maybe_fail("volume_path")
        self.resolved_path = path
        return self.volume_root

    def drive_type(self, volume_root: str) -> int:
        assert volume_root == self.volume_root
        self._maybe_fail("drive_type")
        return self.drive_type_value

    def volume_name(self, volume_root: str) -> str:
        assert volume_root == self.volume_root
        self._maybe_fail("volume_name")
        return self.volume_name_value

    @contextmanager
    def open_volume(self, volume_name: str) -> Iterator[int]:
        assert volume_name == self.volume_name_value
        self._maybe_fail("open")
        self.opened += 1
        try:
            yield 42
        finally:
            self.closed += 1

    def device_identity(self, handle: int) -> WindowsDeviceIdentity:
        assert handle == 42
        self._maybe_fail("identity")
        return self.identity

    def bus_type(self, handle: int) -> int:
        assert handle == 42
        if self.fail_at == "malformed":
            self._maybe_fail("malformed")
        self._maybe_fail("bus")
        return self.bus_type_value

    def incurs_seek_penalty(self, handle: int) -> bool:
        assert handle == 42
        self._maybe_fail("seek")
        return self.seek_penalty_value


class FakeKernel32:
    def __init__(self) -> None:
        self.closed: list[int] = []

    @staticmethod
    def CreateFileW(*_args: object) -> int:
        return 73

    def CloseHandle(self, handle: int) -> bool:
        self.closed.append(handle)
        return True


def detector_for(native: FakeNativeApi, existing: Path) -> WindowsStorageDetector:
    return WindowsStorageDetector(native, lexists=lambda path: path == existing)


def test_nvme_bus_is_classified_with_physical_device_key(tmp_path: Path) -> None:
    native = FakeNativeApi(bus_type=StorageBusType.NVME)

    result = detector_for(native, tmp_path)(tmp_path)

    assert result.device_key == "windows:device:7:3"
    assert result.storage_class is StorageClass.NVME
    assert "NVMe" in result.reason
    assert native.opened == native.closed == 1


@pytest.mark.parametrize(
    ("seek_penalty", "expected"),
    [(True, StorageClass.HDD), (False, StorageClass.SSD)],
)
def test_seek_penalty_distinguishes_hdd_and_non_nvme_ssd(
    tmp_path: Path, seek_penalty: bool, expected: StorageClass
) -> None:
    native = FakeNativeApi(seek_penalty=seek_penalty)

    result = detector_for(native, tmp_path)(tmp_path)

    assert result.storage_class is expected
    assert native.opened == native.closed == 1


@pytest.mark.parametrize("volume_root", ["C:\\", "C:\\mounted-volume\\"])
def test_drive_letter_and_volume_mount_roots_are_resolved(tmp_path: Path, volume_root: str) -> None:
    native = FakeNativeApi(volume_root=volume_root)

    result = detector_for(native, tmp_path)(tmp_path)

    assert result.storage_class is StorageClass.SSD
    assert native.resolved_path == os.fspath(tmp_path)


def test_missing_destination_uses_nearest_existing_parent(tmp_path: Path) -> None:
    destination = tmp_path / "new" / "nested" / "archive.7z"
    native = FakeNativeApi()

    result = detector_for(native, tmp_path)(destination)

    assert result.storage_class is StorageClass.SSD
    assert native.resolved_path == os.fspath(tmp_path)


def test_volume_classification_is_cached_for_the_command(tmp_path: Path) -> None:
    native = FakeNativeApi(bus_type=StorageBusType.NVME)
    detector = detector_for(native, tmp_path)

    first = detector(tmp_path)
    second = detector(tmp_path / "new" / "archive.7z")

    assert first == second
    assert native.opened == native.closed == 1


@pytest.mark.parametrize(
    ("path", "expected_key"),
    [
        (r"\\server\share\archive.7z", "windows:unc:server/share"),
        (r"\\?\UNC\Server\Share\archive.7z", "windows:unc:server/share"),
    ],
)
def test_unc_paths_are_unknown_without_native_or_filesystem_queries(
    path: str, expected_key: str
) -> None:
    native = FakeNativeApi()
    probed = False

    def lexists(_path: Path) -> bool:
        nonlocal probed
        probed = True
        return True

    result = WindowsStorageDetector(native, lexists=lexists)(Path(path))

    assert result.device_key == expected_key
    assert result.storage_class is StorageClass.UNKNOWN
    assert "network" in result.reason
    assert probed is False
    assert native.opened == 0


def test_mapped_network_drive_is_unknown(tmp_path: Path) -> None:
    native = FakeNativeApi(volume_root="Z:\\", drive_type=DriveType.REMOTE)

    result = detector_for(native, tmp_path)(tmp_path)

    assert result.device_key == "windows:root:z:"
    assert result.storage_class is StorageClass.UNKNOWN
    assert "network" in result.reason
    assert native.opened == 0


def test_removable_local_device_uses_reported_seek_penalty(tmp_path: Path) -> None:
    native = FakeNativeApi(drive_type=DriveType.REMOVABLE, seek_penalty=False)

    result = detector_for(native, tmp_path)(tmp_path)

    assert result.storage_class is StorageClass.SSD
    assert "removable" in result.reason
    assert native.opened == native.closed == 1


@pytest.mark.parametrize("drive_type", [DriveType.UNKNOWN, DriveType.CDROM, DriveType.RAMDISK])
def test_unsupported_drive_types_are_unknown(tmp_path: Path, drive_type: DriveType) -> None:
    native = FakeNativeApi(drive_type=drive_type)

    result = detector_for(native, tmp_path)(tmp_path)

    assert result.storage_class is StorageClass.UNKNOWN
    assert drive_type.name.lower() in result.reason
    assert native.opened == 0


@pytest.mark.parametrize(
    "bus_type",
    [StorageBusType.VIRTUAL, StorageBusType.FILE_BACKED_VIRTUAL, StorageBusType.SPACES],
)
def test_virtual_and_stacked_bus_types_are_unknown_and_close_handle(
    tmp_path: Path, bus_type: StorageBusType
) -> None:
    native = FakeNativeApi(bus_type=bus_type)

    result = detector_for(native, tmp_path)(tmp_path)

    assert result.storage_class is StorageClass.UNKNOWN
    assert "unsupported" in result.reason
    assert native.opened == native.closed == 1


@pytest.mark.parametrize(
    ("fail_at", "expected_key", "opened"),
    [
        ("volume_path", "windows:path:", 0),
        ("drive_type", "windows:path:", 0),
        ("volume_name", "windows:root:c:", 0),
        ("open", "windows:volume:\\\\?\\volume{test}", 0),
        ("identity", "windows:volume:\\\\?\\volume{test}", 1),
        ("bus", "windows:volume:\\\\?\\volume{test}", 1),
        ("seek", "windows:volume:\\\\?\\volume{test}", 1),
        ("malformed", "windows:volume:\\\\?\\volume{test}", 1),
    ],
)
def test_native_failures_return_unknown_and_close_any_open_handle(
    tmp_path: Path, fail_at: str, expected_key: str, opened: int
) -> None:
    native = FakeNativeApi(fail_at=fail_at)

    result = detector_for(native, tmp_path)(tmp_path)

    assert result.device_key.startswith(expected_key)
    assert result.storage_class is StorageClass.UNKNOWN
    assert "failed" in result.reason
    assert native.opened == opened
    assert native.closed == opened


def test_inaccessible_missing_path_is_unknown_without_native_calls(tmp_path: Path) -> None:
    native = FakeNativeApi()

    result = WindowsStorageDetector(native, lexists=lambda _path: False)(tmp_path / "missing")

    assert result.storage_class is StorageClass.UNKNOWN
    assert "no existing parent" in result.reason
    assert native.resolved_path is None


def test_detection_does_not_write_diagnostics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = detector_for(FakeNativeApi(fail_at="open"), tmp_path)(tmp_path)

    assert result.storage_class is StorageClass.UNKNOWN
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize("raise_inside", [False, True])
def test_ctypes_volume_handle_closes_on_success_and_failure(raise_inside: bool) -> None:
    kernel32 = FakeKernel32()
    native = object.__new__(CtypesWindowsNativeApi)
    native._kernel32 = kernel32  # type: ignore[attr-defined]

    expectation = pytest.raises(RuntimeError) if raise_inside else nullcontext()
    with expectation, native.open_volume("\\\\?\\Volume{test}\\") as handle:
        assert handle == 73
        if raise_inside:
            raise RuntimeError("fixture failure")

    assert kernel32.closed == [73]


@pytest.mark.skipif(os.name == "nt", reason="non-Windows import fallback")
def test_default_detector_is_importable_without_windows_apis(tmp_path: Path) -> None:
    result = WindowsStorageDetector(lexists=lambda _path: True)(tmp_path)

    assert result.storage_class is StorageClass.UNKNOWN
    assert "loading Windows APIs failed" in result.reason


def test_device_identity_parser_rejects_short_response() -> None:
    with pytest.raises(ValueError, match="short response"):
        _parse_device_identity(b"\0" * 11)


def test_device_identity_parser_ignores_partition_number() -> None:
    identity = _parse_device_identity(struct.pack("<III", 7, 9, 4))

    assert identity == WindowsDeviceIdentity(7, 9)
    assert identity.key == "windows:device:7:9"


@pytest.mark.parametrize(
    "response",
    [
        b"\0" * 7,
        struct.pack("<II", 36, 7),
        struct.pack("<II", 36, 70_000),
        struct.pack("<II", 36, 36) + b"\0" * 23,
    ],
)
def test_bus_descriptor_parser_rejects_malformed_responses(response: bytes) -> None:
    with pytest.raises(ValueError):
        _parse_bus_type(response)


def test_bus_descriptor_parser_reads_nvme() -> None:
    response = bytearray(36)
    struct.pack_into("<II", response, 0, 36, 36)
    struct.pack_into("<I", response, 28, StorageBusType.NVME)

    assert _parse_bus_type(response) == StorageBusType.NVME


@pytest.mark.parametrize(
    "response",
    [
        b"\0" * 8,
        struct.pack("<II", 12, 12) + b"\x02\0\0\0",
        struct.pack("<II", 12, 12) + b"\x01",
    ],
)
def test_seek_penalty_parser_rejects_malformed_responses(response: bytes) -> None:
    with pytest.raises(ValueError):
        _parse_seek_penalty(response)


@pytest.mark.parametrize(("raw", "expected"), [(0, False), (1, True)])
def test_seek_penalty_parser_reads_windows_boolean(raw: int, expected: bool) -> None:
    response = struct.pack("<II", 12, 12) + bytes([raw, 0, 0, 0])

    assert _parse_seek_penalty(response) is expected
