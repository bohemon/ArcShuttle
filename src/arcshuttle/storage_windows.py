"""Read-only, best-effort Windows storage endpoint detection."""

from __future__ import annotations

import ctypes
import os
import struct
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Protocol

from .storage import StorageClass, StorageObservation


class DriveType(IntEnum):
    """Values returned by ``GetDriveTypeW``."""

    UNKNOWN = 0
    NO_ROOT_DIR = 1
    REMOVABLE = 2
    FIXED = 3
    REMOTE = 4
    CDROM = 5
    RAMDISK = 6


class StorageBusType(IntEnum):
    """Relevant values from the Windows ``STORAGE_BUS_TYPE`` enumeration."""

    UNKNOWN = 0
    VIRTUAL = 14
    FILE_BACKED_VIRTUAL = 15
    SPACES = 16
    NVME = 17


@dataclass(frozen=True, slots=True)
class WindowsDeviceIdentity:
    """The physical device identity returned for a volume handle."""

    device_type: int
    device_number: int

    @property
    def key(self) -> str:
        return f"windows:device:{self.device_type}:{self.device_number}"


class WindowsNativeApi(Protocol):
    """Mockable boundary around the read-only Win32 calls used by the detector."""

    def volume_path_name(self, path: str) -> str: ...

    def drive_type(self, volume_root: str) -> int: ...

    def volume_name(self, volume_root: str) -> str: ...

    def open_volume(self, volume_name: str) -> AbstractContextManager[int]: ...

    def device_identity(self, handle: int) -> WindowsDeviceIdentity: ...

    def bus_type(self, handle: int) -> int: ...

    def incurs_seek_penalty(self, handle: int) -> bool: ...


_IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
_IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
_STORAGE_DEVICE_PROPERTY = 0
_STORAGE_DEVICE_SEEK_PENALTY_PROPERTY = 7
_PROPERTY_STANDARD_QUERY = 0
_ERROR_INSUFFICIENT_BUFFER = 122
_MAX_DESCRIPTOR_SIZE = 64 * 1024


def _parse_device_identity(data: bytes) -> WindowsDeviceIdentity:
    if len(data) < 12:
        raise ValueError("IOCTL_STORAGE_GET_DEVICE_NUMBER returned a short response")
    device_type, device_number, _partition_number = struct.unpack_from("<III", data)
    return WindowsDeviceIdentity(device_type, device_number)


def _parse_descriptor_size(data: bytes) -> int:
    if len(data) < 8:
        raise ValueError("storage property header is incomplete")
    _version, size = struct.unpack_from("<II", data)
    if size < 8 or size > _MAX_DESCRIPTOR_SIZE:
        raise ValueError(f"storage property descriptor size is invalid: {size}")
    return size


def _parse_bus_type(data: bytes) -> int:
    if len(data) < 32:
        raise ValueError("storage device descriptor is incomplete")
    size = _parse_descriptor_size(data)
    if size < 32 or len(data) < size:
        raise ValueError("storage device descriptor is truncated")
    return struct.unpack_from("<I", data, 28)[0]


def _parse_seek_penalty(data: bytes) -> bool:
    if len(data) < 9:
        raise ValueError("seek-penalty descriptor is incomplete")
    size = _parse_descriptor_size(data)
    if size < 9 or len(data) < size:
        raise ValueError("seek-penalty descriptor is truncated")
    value = data[8]
    if value not in (0, 1):
        raise ValueError("seek-penalty descriptor contains an invalid Boolean")
    return bool(value)


class CtypesWindowsNativeApi:
    """Minimal ctypes implementation of the native read-only query boundary."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows storage APIs are unavailable on this platform")

        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        self._kernel32 = kernel32
        self._wintypes = wintypes

        kernel32.GetVolumePathNameW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        kernel32.GetVolumePathNameW.restype = wintypes.BOOL
        kernel32.GetVolumeNameForVolumeMountPointW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        kernel32.GetVolumeNameForVolumeMountPointW.restype = wintypes.BOOL
        kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetDriveTypeW.restype = wintypes.UINT
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.DeviceIoControl.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        kernel32.DeviceIoControl.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

    @staticmethod
    def _raise_last_error() -> None:
        raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]

    def volume_path_name(self, path: str) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        if not self._kernel32.GetVolumePathNameW(path, buffer, len(buffer)):
            self._raise_last_error()
        return buffer.value

    def drive_type(self, volume_root: str) -> int:
        return int(self._kernel32.GetDriveTypeW(volume_root))

    def volume_name(self, volume_root: str) -> str:
        buffer = ctypes.create_unicode_buffer(1024)
        if not self._kernel32.GetVolumeNameForVolumeMountPointW(volume_root, buffer, len(buffer)):
            self._raise_last_error()
        return buffer.value

    @contextmanager
    def open_volume(self, volume_name: str) -> Iterator[int]:
        share_read_write_delete = 0x00000001 | 0x00000002 | 0x00000004
        open_existing = 3
        handle = self._kernel32.CreateFileW(
            volume_name.rstrip("\\"),
            0,
            share_read_write_delete,
            None,
            open_existing,
            0,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle in (None, invalid_handle):
            self._raise_last_error()
        try:
            yield int(handle)
        finally:
            if not self._kernel32.CloseHandle(handle):
                self._raise_last_error()

    def _device_io_control(
        self, handle: int, control_code: int, input_data: bytes, output_size: int
    ) -> bytes:
        input_buffer = ctypes.create_string_buffer(input_data) if input_data else None
        output_buffer = ctypes.create_string_buffer(output_size)
        returned = self._wintypes.DWORD()
        success = self._kernel32.DeviceIoControl(
            handle,
            control_code,
            input_buffer,
            len(input_data),
            output_buffer,
            output_size,
            ctypes.byref(returned),
            None,
        )
        if not success:
            self._raise_last_error()
        if returned.value > output_size:
            raise ValueError("DeviceIoControl reported more bytes than the output buffer")
        return output_buffer.raw[: returned.value]

    def _query_property(self, handle: int, property_id: int) -> bytes:
        query = struct.pack("<II4x", property_id, _PROPERTY_STANDARD_QUERY)
        try:
            header = self._device_io_control(handle, _IOCTL_STORAGE_QUERY_PROPERTY, query, 8)
        except OSError as exc:
            if getattr(exc, "winerror", None) != _ERROR_INSUFFICIENT_BUFFER:
                raise
            # Some storage drivers require the fixed part of the descriptor even for the
            # sizing request. The largest fixed descriptor used here is 36 bytes.
            header = self._device_io_control(handle, _IOCTL_STORAGE_QUERY_PROPERTY, query, 36)
        size = _parse_descriptor_size(header)
        return self._device_io_control(handle, _IOCTL_STORAGE_QUERY_PROPERTY, query, size)

    def device_identity(self, handle: int) -> WindowsDeviceIdentity:
        response = self._device_io_control(handle, _IOCTL_STORAGE_GET_DEVICE_NUMBER, b"", 12)
        return _parse_device_identity(response)

    def bus_type(self, handle: int) -> int:
        return _parse_bus_type(self._query_property(handle, _STORAGE_DEVICE_PROPERTY))

    def incurs_seek_penalty(self, handle: int) -> bool:
        return _parse_seek_penalty(
            self._query_property(handle, _STORAGE_DEVICE_SEEK_PENALTY_PROPERTY)
        )


_VIRTUAL_BUS_TYPES = {
    StorageBusType.VIRTUAL,
    StorageBusType.FILE_BACKED_VIRTUAL,
    StorageBusType.SPACES,
}


def _unc_share_key(path: Path) -> str | None:
    raw = str(path).replace("/", "\\")
    if raw.casefold().startswith("\\\\?\\unc\\"):
        parts = raw[8:].split("\\")
    elif raw.startswith("\\\\") and not raw.startswith(("\\\\?\\", "\\\\.\\")):
        parts = raw[2:].split("\\")
    else:
        return None
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return "windows:unc:unknown"
    return f"windows:unc:{parts[0].casefold()}/{parts[1].casefold()}"


def _nearest_existing_parent(path: Path, *, lexists: Callable[[Path], bool]) -> Path | None:
    try:
        candidate = path.expanduser()
    except (OSError, RuntimeError):
        return None
    while True:
        try:
            if lexists(candidate):
                return candidate
        except OSError:
            return None
        parent = candidate.parent
        if parent == candidate:
            return None
        candidate = parent


def _path_key(path: Path) -> str:
    try:
        normalized = os.path.abspath(os.fspath(path))
    except OSError:
        normalized = os.fspath(path)
    return f"windows:path:{os.path.normcase(normalized)}"


def _volume_key(volume_name: str) -> str:
    normalized = volume_name.rstrip("\\").casefold()
    return f"windows:volume:{normalized}"


def _error_reason(action: str, exc: Exception) -> str:
    winerror = getattr(exc, "winerror", None)
    suffix = f" (Windows error {winerror})" if winerror is not None else ""
    return f"{action} failed: {type(exc).__name__}{suffix}"


class WindowsStorageDetector:
    """Classify a Windows path without modifying it or requiring administrator access."""

    def __init__(
        self,
        native: WindowsNativeApi | None = None,
        *,
        lexists: Callable[[Path], bool] | None = None,
    ) -> None:
        self._native = native
        self._lexists = os.path.lexists if lexists is None else lexists

    def __call__(self, path: Path) -> StorageObservation:
        unc_key = _unc_share_key(path)
        if unc_key is not None:
            return StorageObservation(
                unc_key, StorageClass.UNKNOWN, "UNC paths are network storage"
            )

        existing = _nearest_existing_parent(path, lexists=self._lexists)
        fallback_key = _path_key(existing if existing is not None else path)
        if existing is None:
            return StorageObservation(
                fallback_key,
                StorageClass.UNKNOWN,
                "no existing parent was accessible for Windows storage detection",
            )

        try:
            native = self._native if self._native is not None else CtypesWindowsNativeApi()
        except Exception as exc:
            return StorageObservation(
                fallback_key, StorageClass.UNKNOWN, _error_reason("loading Windows APIs", exc)
            )

        try:
            volume_root = native.volume_path_name(os.fspath(existing))
            drive_type = DriveType(native.drive_type(volume_root))
        except Exception as exc:
            return StorageObservation(
                fallback_key, StorageClass.UNKNOWN, _error_reason("resolving the volume", exc)
            )

        normalized_root = volume_root.rstrip("\\").casefold()
        root_key = f"windows:root:{normalized_root}"
        if drive_type is DriveType.REMOTE:
            return StorageObservation(
                root_key, StorageClass.UNKNOWN, "the volume is network storage"
            )
        if drive_type not in {DriveType.FIXED, DriveType.REMOVABLE}:
            return StorageObservation(
                root_key,
                StorageClass.UNKNOWN,
                f"Windows drive type {drive_type.name.lower()} is unsupported",
            )

        try:
            volume_name = native.volume_name(volume_root)
        except Exception as exc:
            return StorageObservation(
                root_key, StorageClass.UNKNOWN, _error_reason("resolving the volume identity", exc)
            )
        volume_key = _volume_key(volume_name)

        try:
            with native.open_volume(volume_name) as handle:
                identity = native.device_identity(handle)
                bus_type = native.bus_type(handle)
                if bus_type == StorageBusType.NVME:
                    return StorageObservation(
                        identity.key, StorageClass.NVME, "Windows reports an NVMe storage bus"
                    )
                if bus_type in _VIRTUAL_BUS_TYPES:
                    bus_name = StorageBusType(bus_type).name.lower().replace("_", "-")
                    return StorageObservation(
                        identity.key,
                        StorageClass.UNKNOWN,
                        f"Windows reports an unsupported {bus_name} storage layout",
                    )
                seek_penalty = native.incurs_seek_penalty(handle)
        except Exception as exc:
            return StorageObservation(
                volume_key, StorageClass.UNKNOWN, _error_reason("querying storage metadata", exc)
            )

        removable = " removable" if drive_type is DriveType.REMOVABLE else ""
        if seek_penalty:
            return StorageObservation(
                identity.key,
                StorageClass.HDD,
                f"Windows reports that the{removable} device incurs seek penalty",
            )
        return StorageObservation(
            identity.key,
            StorageClass.SSD,
            f"Windows reports that the{removable} non-NVMe device has no seek penalty",
        )


def detect_windows_storage(path: Path) -> StorageObservation:
    """Detect a Windows endpoint using the default native adapter."""

    return WindowsStorageDetector()(path)
