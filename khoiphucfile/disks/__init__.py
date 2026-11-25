"""Liệt kê và mở ổ đĩa vật lý trên Windows, macOS và Linux (chỉ đọc)."""

from __future__ import annotations

import os
import sys

from ..source import Source
from .common import AccessDenied, Disk, DiskNotFound

if sys.platform == "win32":
    from . import windows as backend
elif sys.platform == "darwin":
    from . import macos as backend
else:
    from . import linux as backend

__all__ = ["AccessDenied", "Disk", "DiskNotFound", "backend", "find_again", "list_disks", "model_of",
           "open_source", "output_on_disk", "resolve"]


def list_disks() -> list[Disk]:
    return backend.list_disks()


def resolve(spec: str) -> tuple[str, str | None]:
    """Đổi điều người dùng gõ thành (đường dẫn, mã đĩa); mã đĩa là None khi nguồn là file ảnh đĩa.

    Nhận mã đĩa (2, sdb, disk4), đường dẫn thiết bị, file ảnh đĩa hoặc một đoạn tên model (vd HM160HI).
    """
    disk_id = backend.parse_spec(spec)
    if disk_id is not None:
        return backend.device_path(disk_id), disk_id
    if os.path.isfile(spec):
        return os.path.abspath(spec), None
    hits = [disk for disk in list_disks() if spec.lower() in disk.model.lower()]
    if len(hits) != 1:
        raise DiskNotFound(f"Không xác định được đĩa '{spec}' ({len(hits)} đĩa khớp). "
                           "Xem danh sách bằng lệnh: khoiphuc disks")
    return hits[0].path, hits[0].id


def open_source(path: str, disk_id: str | None) -> Source:
    if disk_id is None:
        return Source(path)
    fileobj, size = backend.open_device(path)
    return Source(path, fileobj=fileobj, size=size)


def model_of(disk_id: str | None) -> str:
    return "" if disk_id is None else backend.model_of(disk_id)


def output_on_disk(out_dir: str, disk_id: str) -> bool | None:
    """Thư mục lưu có nằm trên chính đĩa đang quét không; None khi không xác định được."""
    holders = backend.disks_of_path(existing_parent(out_dir))
    if holders is None:
        return None
    return bool(holders & backend.base_disks(disk_id))


def find_again(path: str, model: str, size: int) -> Disk | None:
    """Tìm lại đĩa của lần quét trước: số đĩa có thể đổi sau khi cắm lại nên so model và dung lượng."""
    hits = [disk for disk in list_disks() if disk.size == size and (not model or disk.model == model)]
    if len(hits) > 1:
        hits = [disk for disk in hits if disk.path == path]
    return hits[0] if len(hits) == 1 else None


def existing_parent(path: str) -> str:
    path = os.path.realpath(path)
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path
