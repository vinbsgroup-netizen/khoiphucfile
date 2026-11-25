r"""Ổ đĩa trên Windows: \\.\PhysicalDriveN qua DeviceIoControl, cần quyền Administrator."""

from __future__ import annotations

import os
import re
import struct
import subprocess
import sys

from .common import AccessDenied, Disk, DiskNotFound

IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000
GENERIC_READ = 0x80000000
BUS_TYPES = {1: "SCSI", 3: "ATA", 7: "USB", 8: "RAID", 10: "SAS", 11: "SATA", 12: "SD", 13: "MMC",
             14: "Ảo", 15: "Ảnh đĩa", 17: "NVMe"}


def device_query(path: str, code: int, inbuf: bytes = b"", access: int = 0, outsize: int = 4096) -> bytes | None:
    """Gọi DeviceIoControl trên ổ/đĩa; None khi không có quyền hoặc thiết bị không trả lời."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k32.DeviceIoControl.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.CreateFileW(path, access, 3, None, 3, 0, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        return None
    try:
        inb = ctypes.create_string_buffer(inbuf, len(inbuf)) if inbuf else None
        outb = ctypes.create_string_buffer(outsize)
        got = wintypes.DWORD(0)
        if not k32.DeviceIoControl(handle, code, inb, len(inbuf), outb, outsize, ctypes.byref(got), None):
            return None
        return outb.raw[:got.value]
    finally:
        k32.CloseHandle(handle)


def device_path(disk_id: str) -> str:
    return f"\\\\.\\PhysicalDrive{disk_id}"


def parse_spec(spec: str) -> str | None:
    if spec.isdigit():
        return str(int(spec))
    match = re.fullmatch(r"\\\\\.\\PhysicalDrive(\d+)", spec, re.IGNORECASE)
    return match.group(1) if match else None


def device_length(path: str) -> int | None:
    data = device_query(path, IOCTL_DISK_GET_LENGTH_INFO, access=GENERIC_READ)
    return struct.unpack_from("<q", data)[0] if data and len(data) >= 8 else None


def device_model(path: str) -> tuple[str, str]:
    data = device_query(path, IOCTL_STORAGE_QUERY_PROPERTY, struct.pack("<II4x", 0, 0))
    if not data or len(data) < 32:
        return "", ""
    fields = struct.unpack_from("<IIBBBBIIIII", data)
    vendor_at, product_at, bus = fields[6], fields[7], fields[10]

    def text(at: int) -> str:
        if not at or at >= len(data):
            return ""
        end = data.find(b"\0", at)
        return data[at:end if end >= 0 else len(data)].decode("ascii", "replace").strip()

    return " ".join(part for part in (text(vendor_at), text(product_at)) if part), BUS_TYPES.get(bus, str(bus))


def drive_letters() -> list[str]:
    import ctypes

    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [chr(65 + i) for i in range(26) if mask >> i & 1]


def volume_disks(letter: str) -> set[int]:
    data = device_query(f"\\\\.\\{letter}:", IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS)
    if not data or len(data) < 8:
        return set()
    count = struct.unpack_from("<I", data)[0]
    return {struct.unpack_from("<I", data, 8 + 24 * i)[0] for i in range(count) if 8 + 24 * i + 24 <= len(data)}


def list_disks() -> list[Disk]:
    holders = {letter: volume_disks(letter) for letter in drive_letters()}
    system_letter = os.environ.get("SystemDrive", "C:")[:1].upper()
    disks = []
    for number in range(32):
        path = device_path(str(number))
        size = device_length(path)
        if size is None:
            continue
        model, bus = device_model(path)
        letters = [letter for letter, numbers in holders.items() if number in numbers]
        disks.append(Disk(str(number), path, size, model, bus, [f"{letter}:" for letter in letters],
                          system=system_letter in letters))
    return disks


def model_of(disk_id: str) -> str:
    return device_model(device_path(disk_id))[0]


def open_device(path: str):
    try:
        fileobj = open(path, "rb", buffering=0)
    except FileNotFoundError:
        raise DiskNotFound(f"Không thấy {path}. Ổ đã bị rút ra?") from None
    except PermissionError:
        raise AccessDenied("Không mở được đĩa: cần chạy bằng quyền Administrator.") from None
    size = device_length(path)
    if size is None:
        fileobj.close()
        raise AccessDenied("Không đọc được dung lượng đĩa: cần chạy bằng quyền Administrator.")
    return fileobj, size


def base_disks(disk_id: str) -> set[str]:
    return {disk_id}


def disks_of_path(path: str) -> set[str] | None:
    drive = os.path.splitdrive(path)[0]
    if drive.startswith("\\\\") and not drive.startswith(("\\\\?\\", "\\\\.\\")):
        return set()
    letter = drive[:1].upper()
    disks = volume_disks(letter) if letter.isalpha() else set()
    return {str(number) for number in disks} or None


def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def relaunch_as_admin(arguments: list[str]) -> bool:
    """Mở lại ứng dụng qua hộp thoại UAC; False khi người dùng từ chối."""
    import ctypes

    parameters = subprocess.list2cmdline(arguments)
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, parameters, os.getcwd(), 1) > 32
