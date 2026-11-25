"""Phần chung cho lớp ổ đĩa của các hệ điều hành."""

from __future__ import annotations

from dataclasses import dataclass, field


class AccessDenied(Exception):
    """Không được phép đọc thô ổ đĩa; nội dung lỗi đã viết sẵn cho người dùng đọc."""


class DiskNotFound(Exception):
    """Không thấy đĩa được yêu cầu."""


@dataclass
class Disk:
    id: str
    path: str
    size: int
    model: str = ""
    bus: str = ""
    mounts: list[str] = field(default_factory=list)
    system: bool = False

    @property
    def label(self) -> str:
        return f"Đĩa {self.id}" if self.id.isdigit() else self.id
