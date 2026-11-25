"""Vài thứ dùng chung giữa các trang của giao diện."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QSettings, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from .. import APP_ID
from ..source import GB

NEVER_OPEN = {"jar", "apk", "ole"}


@dataclass
class Choice:
    """Nguồn người dùng đã chọn: một ổ đĩa, hoặc một file ảnh đĩa (disk_id là None)."""

    spec: str
    disk_id: str | None
    title: str
    size: int
    model: str = ""


def settings() -> QSettings:
    return QSettings(QSettings.IniFormat, QSettings.UserScope, APP_ID, APP_ID)


def decimal(value: float, places: int = 1) -> str:
    return f"{value:.{places}f}".replace(".", ",")


def human_size(size: float) -> str:
    for unit, scale in (("GB", GB), ("MB", 1_000_000), ("KB", 1_000)):
        if size >= scale:
            return f"{decimal(size / scale)} {unit}"
    return f"{int(size)} B"


def human_duration(seconds: float) -> str:
    minutes = int(max(seconds, 0) // 60)
    if minutes < 1:
        return "dưới 1 phút"
    return f"khoảng {minutes // 60} giờ {minutes % 60} phút" if minutes >= 60 else f"khoảng {minutes} phút"


def number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def free_bytes(folder: str) -> int | None:
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return None


def label(text: str = "", role: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def button(text: str, on_click: Callable[[], None], role: str = "") -> QPushButton:
    widget = QPushButton(text)
    if role:
        widget.setProperty("role", role)
    widget.clicked.connect(lambda _checked=False: on_click())
    return widget


class Banner(QFrame):
    """Dải thông báo màu; ẩn khi không có gì để nói."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.text = label(wrap=True)
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(12, 9, 12, 9)
        self.layout_.addWidget(self.text, 1)
        self.setVisible(False)

    def show_message(self, kind: str, text: str) -> None:
        self.setProperty("banner", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        for child in (self.text,):
            child.style().unpolish(child)
            child.style().polish(child)
        self.text.setText(text)
        self.setVisible(bool(text))

    def add_button(self, widget: QPushButton) -> None:
        self.layout_.addWidget(widget)


class _Task(QRunnable):
    def __init__(self, work: Callable[[], object], bridge: "_Bridge"):
        super().__init__()
        self.work, self.bridge = work, bridge

    def run(self) -> None:
        try:
            result = self.work()
        except Exception as error:
            result = error
        try:
            self.bridge.done.emit(result)
        except RuntimeError:
            pass


class _Bridge(QObject):
    done = Signal(object)


def run_async(owner: QObject, work: Callable[[], object], then: Callable[[object], None]) -> None:
    """Chạy work ở luồng phụ rồi gọi then(kết quả hoặc Exception) ở luồng giao diện."""
    bridge = _Bridge(owner)

    def finish(result: object) -> None:
        bridge.deleteLater()
        then(result)

    bridge.done.connect(finish)
    QThreadPool.globalInstance().start(_Task(work, bridge))


def open_file(path: str) -> None:
    """Mở bằng ứng dụng mặc định. Trên Windows đi qua explorer để file cứu được không chạy với quyền Administrator."""
    if os.path.splitext(path)[1].lstrip(".").lower() in NEVER_OPEN:
        reveal(path)
    elif sys.platform == "win32":
        subprocess.Popen(["explorer.exe", os.path.normpath(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def reveal(path: str) -> None:
    if sys.platform == "win32":
        subprocess.Popen(f'explorer.exe /select,"{os.path.normpath(path)}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))


def open_folder(path: str) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer.exe", os.path.normpath(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
