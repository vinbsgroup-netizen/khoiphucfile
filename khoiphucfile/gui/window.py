"""Cửa sổ chính: ba bước ở cột trái, nội dung từng bước ở bên phải."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, developer
from . import about
from .common import Choice, button, label
from .options_page import OptionsPage
from .scan_page import ScanPage
from .source_page import SourcePage

SOURCE, OPTIONS, SCAN = range(3)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setMinimumSize(880, 620)
        self.source_page = SourcePage()
        self.options_page = OptionsPage()
        self.scan_page = ScanPage()
        self.stack = QStackedWidget()
        for page in (self.source_page, self.options_page, self.scan_page):
            self.stack.addWidget(page)

        logo = QLabel()
        logo.setPixmap(QIcon(about.ICON).pixmap(48, 48))
        name = QLabel(APP_NAME)
        name.setObjectName("brand")
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand_text.addWidget(name)
        brand_text.addWidget(label(developer.DEVELOPER, "muted"))
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.addWidget(logo)
        brand.addLayout(brand_text, 1)
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(212)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(14, 22, 14, 16)
        rail_layout.setSpacing(4)
        rail_layout.addLayout(brand)
        rail_layout.addSpacing(18)
        self.steps: list[QPushButton] = []
        group = QButtonGroup(self)
        for at, text in enumerate(("1.  Chọn ổ", "2.  Nơi lưu và loại file", "3.  Quét và kết quả")):
            step = QPushButton(text)
            step.setProperty("role", "step")
            step.setCheckable(True)
            step.clicked.connect(lambda _checked=False, page=at: self.go(page))
            group.addButton(step)
            self.steps.append(step)
            rail_layout.addWidget(step)
        rail_layout.addStretch(1)
        for text, page in (("Giới thiệu", about.ABOUT), ("Điều khoản sử dụng", about.TERMS),
                           ("Nội quy sử dụng", about.RULES)):
            link = button(text, lambda page=page: about.InfoDialog(page, self).exec(), "link")
            link.setCursor(Qt.PointingHandCursor)
            rail_layout.addWidget(link)
        version = label(f"Phiên bản {__version__}", "muted")
        version.setContentsMargins(12, 6, 0, 0)
        rail_layout.addWidget(version)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(rail)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.has_choice = self.has_results = False
        self.source_page.chosen.connect(self._chosen)
        self.source_page.results_requested.connect(self.open_results)
        self.options_page.back.connect(lambda: self.go(SOURCE))
        self.options_page.start.connect(self._start)
        self.options_page.results_requested.connect(self.open_results)
        self.scan_page.running_changed.connect(lambda _: self._update_steps())
        self.scan_page.refused.connect(self._refused)
        self.go(SOURCE)
        QTimer.singleShot(0, self.source_page.refresh)

    def go(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        self._update_steps()

    def _update_steps(self) -> None:
        current, running = self.stack.currentIndex(), self.scan_page.is_running()
        allowed = (not running, not running and self.has_choice, self.has_results or running)
        for at, step in enumerate(self.steps):
            step.setEnabled(allowed[at] or at == current)
            step.setChecked(at == current)

    def _chosen(self, choice: Choice) -> None:
        self.has_choice = True
        self.options_page.set_choice(choice)
        self.go(OPTIONS)

    def _start(self, options) -> None:
        self.has_results = True
        self.scan_page.start(options)
        self.go(SCAN)

    def open_results(self, folder: str) -> None:
        if not self.scan_page.show_results(folder):
            QMessageBox.information(self, APP_NAME, "Thư mục này không có kết quả quét (không thấy bao_cao.csv).")
            return
        self.has_results = True
        self.go(SCAN)

    def _refused(self, message: str) -> None:
        self.has_results = False
        self.go(OPTIONS if self.has_choice else SOURCE)
        QMessageBox.warning(self, "Không bắt đầu quét được", message)

    def closeEvent(self, event) -> None:
        if self.scan_page.is_running():
            if not self.scan_page.confirm_stop():
                event.ignore()
                return
            self.scan_page.stop()
            if not self.scan_page.wait(60_000):
                # Ổ hỏng có thể treo một lệnh đọc rất lâu; tiến độ gần nhất đã được lưu nên thoát hẳn được.
                os._exit(0)
        self.scan_page.results.shutdown()
        event.accept()
