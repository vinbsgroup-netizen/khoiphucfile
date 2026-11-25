"""Ổ đĩa trên Linux: /dev/sdX qua lsblk/findmnt; không phải root thì xin quyền mở ổ bằng pkexec."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys

from .common import AccessDenied, Disk, DiskNotFound

NO_LOCAL_DISK = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "tmpfs", "ramfs", "fuse.sshfs", "fuse.rclone", "9p", "virtiofs"}
HIDDEN = ("loop", "ram", "zram", "sr", "fd")
BUSES = {"usb": "USB", "sata": "SATA", "nvme": "NVMe", "mmc": "SD", "ata": "ATA", "sas": "SAS"}
BTRFS_ROOT = "/sys/fs/btrfs"


def run_json(command: list[str]) -> dict:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=30, env={**os.environ, "LC_ALL": "C"})
        return json.loads(done.stdout) if done.stdout.strip() else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def device_path(disk_id: str) -> str:
    return f"/dev/{disk_id}"


def parse_spec(spec: str) -> str | None:
    path = os.path.realpath(spec if spec.startswith("/dev/") else f"/dev/{spec}")
    try:
        is_block = stat.S_ISBLK(os.stat(path).st_mode)
    except (OSError, ValueError):
        return None
    return path.removeprefix("/dev/") if is_block else None


def collect_mounts(node: dict) -> list[str]:
    points = [node["mountpoint"]] if node.get("mountpoint") else []
    for child in node.get("children") or []:
        points += collect_mounts(child)
    return points


def list_disks() -> list[Disk]:
    tree = run_json(["lsblk", "-J", "-b", "-o", "NAME,KNAME,PATH,SIZE,MODEL,VENDOR,TRAN,TYPE,MOUNTPOINT"])
    disks = []
    for node in tree.get("blockdevices") or []:
        size = int(node.get("size") or 0)
        if node.get("type") != "disk" or not size or node["kname"].startswith(HIDDEN):
            continue
        model = " ".join(part.strip() for part in (node.get("vendor"), node.get("model")) if part and part.strip())
        transport = node.get("tran") or ""
        mounts = collect_mounts(node)
        disks.append(Disk(node["kname"], node.get("path") or device_path(node["kname"]), size, model,
                          BUSES.get(transport, transport), [point for point in mounts if not point.startswith("[")],
                          system="/" in mounts))
    return disks


def model_of(disk_id: str) -> str:
    return next((disk.model for disk in list_disks() if disk.id == disk_id), "")


def base_disks(disk_id: str) -> set[str]:
    """Các đĩa vật lý nằm dưới một thiết bị (phân vùng, LVM, LUKS, RAID)."""
    tree = run_json(["lsblk", "-J", "-s", "-o", "KNAME,TYPE", device_path(disk_id)])
    found: set[str] = set()

    def walk(node: dict) -> None:
        parents = node.get("children") or []
        for parent in parents:
            walk(parent)
        if not parents:
            found.add(node["kname"])

    for node in tree.get("blockdevices") or []:
        walk(node)
    return found or {disk_id}


def btrfs_members(device: str) -> list[str]:
    try:
        for volume in os.listdir(BTRFS_ROOT):
            folder = os.path.join(BTRFS_ROOT, volume, "devices")
            members = os.listdir(folder) if os.path.isdir(folder) else []
            if device in members:
                return members
    except OSError:
        pass
    return [device]


def disks_of_path(path: str) -> set[str] | None:
    systems = run_json(["findmnt", "-J", "-T", path, "-o", "SOURCE,FSTYPE"]).get("filesystems") or []
    if not systems:
        return None
    source, kind = re.sub(r"\[.*\]$", "", systems[0].get("source") or ""), systems[0].get("fstype") or ""
    if source.startswith("/dev/"):
        device = os.path.realpath(source).removeprefix("/dev/")
        members = btrfs_members(device) if kind == "btrfs" else [device]
        return set().union(*(base_disks(member) for member in members))
    return set() if kind in NO_LOCAL_DISK else None


def helper_command(path: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [os.path.join(os.path.dirname(os.path.realpath(sys.executable)), "khoiphuc"), "open-device", path]
    from . import open_device as helper

    return [sys.executable, "-I", os.path.abspath(helper.__file__), path]


def open_device(path: str):
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        raise DiskNotFound(f"Không thấy {path}. Ổ đã bị rút ra?") from None
    except PermissionError:
        from .fdpass import open_through

        fd = open_through(["pkexec", *helper_command(path)],
                          f"Không được cấp quyền đọc {path}. "
                          f"Có thể chạy trong terminal: sudo khoiphuc scan {path} --out THU_MUC")
    fileobj = os.fdopen(fd, "rb", buffering=0)
    size = os.lseek(fd, 0, os.SEEK_END)
    os.lseek(fd, 0, os.SEEK_SET)
    if not size:
        fileobj.close()
        raise AccessDenied(f"{path} không có dung lượng (khe thẻ trống?).")
    return fileobj, size
