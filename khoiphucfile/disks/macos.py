"""Ổ đĩa trên macOS: /dev/rdiskN qua diskutil; xin quyền mở ổ bằng authopen của hệ thống."""

from __future__ import annotations

import os
import plistlib
import re
import struct
import subprocess

from .common import AccessDenied, Disk, DiskNotFound

DKIOCGETBLOCKSIZE = 0x40046418
DKIOCGETBLOCKCOUNT = 0x40086419
AUTHOPEN = "/usr/libexec/authopen"


def diskutil(*arguments: str) -> dict:
    try:
        done = subprocess.run(["/usr/sbin/diskutil", *arguments], capture_output=True, timeout=60)
        return plistlib.loads(done.stdout) if done.stdout else {}
    except (OSError, ValueError, plistlib.InvalidFileException, subprocess.TimeoutExpired):
        return {}


def device_path(disk_id: str) -> str:
    return f"/dev/r{disk_id}"


def parse_spec(spec: str) -> str | None:
    match = re.fullmatch(r"(?:/dev/)?r?(disk\d+(?:s\d+)*)", spec)
    return match.group(1) if match else None


def whole_disk(disk_id: str) -> str:
    return re.match(r"disk\d+", disk_id).group(0)


def list_disks() -> list[Disk]:
    layout = diskutil("list", "-plist")
    mounts: dict[str, list[str]] = {}
    for entry in layout.get("AllDisksAndPartitions") or []:
        volumes = [*(entry.get("Partitions") or []), *(entry.get("APFSVolumes") or []), entry]
        points = [volume["MountPoint"] for volume in volumes if volume.get("MountPoint")]
        owners = {whole_disk(store["DeviceIdentifier"]) for store in entry.get("APFSPhysicalStores") or []}
        for owner in owners or {entry["DeviceIdentifier"]}:
            mounts.setdefault(owner, []).extend(points)
    disks = []
    for disk_id in layout.get("WholeDisks") or []:
        info = diskutil("info", "-plist", disk_id)
        bus = info.get("BusProtocol") or ""
        size = info.get("Size") or info.get("TotalSize") or 0
        if not size or (info.get("VirtualOrPhysical") == "Virtual" and bus != "Disk Image"):
            continue
        points = mounts.get(disk_id, [])
        disks.append(Disk(disk_id, device_path(disk_id), size, info.get("MediaName") or "", bus, points,
                          system="/" in points))
    return disks


def model_of(disk_id: str) -> str:
    return diskutil("info", "-plist", whole_disk(disk_id)).get("MediaName") or ""


def base_disks(disk_id: str) -> set[str]:
    """Đĩa chứa một phân vùng; với APFS gồm cả đĩa vật lý nằm dưới container."""
    whole = whole_disk(disk_id)
    found = {whole}
    for entry in diskutil("list", "-plist").get("AllDisksAndPartitions") or []:
        if entry.get("DeviceIdentifier") == whole:
            found |= {whole_disk(store["DeviceIdentifier"]) for store in entry.get("APFSPhysicalStores") or []}
    return found


def disks_of_path(path: str) -> set[str] | None:
    try:
        done = subprocess.run(["/bin/df", "-P", path], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = done.stdout.strip().splitlines()
    if done.returncode or len(lines) < 2:
        return None
    match = re.match(r"/dev/(disk\d+(?:s\d+)*)\s", lines[-1])
    if match:
        return base_disks(match.group(1))
    return set() if lines[-1].startswith("//") else None


def device_size(fd: int) -> int:
    import fcntl

    block = struct.unpack("I", fcntl.ioctl(fd, DKIOCGETBLOCKSIZE, bytes(4)))[0]
    count = struct.unpack("Q", fcntl.ioctl(fd, DKIOCGETBLOCKCOUNT, bytes(8)))[0]
    return block * count


def open_device(path: str):
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        raise DiskNotFound(f"Không thấy {path}. Ổ đã bị rút ra?") from None
    except PermissionError:
        from .fdpass import open_through

        fd = open_through([AUTHOPEN, "-stdoutpipe", "-o", str(os.O_RDONLY), path],
                          f"Không được cấp quyền đọc {path}. Nếu đã nhập đúng mật khẩu, hãy bật quyền Full Disk Access "
                          "cho ứng dụng trong System Settings › Privacy & Security rồi thử lại.")
    fileobj = os.fdopen(fd, "rb", buffering=0)
    try:
        return fileobj, device_size(fd)
    except OSError:
        fileobj.close()
        raise AccessDenied(f"Không đọc được dung lượng của {path}.") from None
