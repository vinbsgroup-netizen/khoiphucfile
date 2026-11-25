"""Bước 1: chọn ổ đĩa (hoặc file ảnh đĩa) cần cứu dữ liệu."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QStyle, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .. import disks
from .common import Banner, Choice, button, human_size, label, run_async

DISK_ROLE = Qt.UserRole


class SourcePage(QWidget):
    chosen = Signal(object)
    results_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Ổ đĩa", "Dung lượng", "Kết nối", "Đang gắn tại"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemActivated.connect(lambda *_: self._continue())

        self.banner = Banner()
        self.admin_button = button("Mở lại với quyền quản trị", self._relaunch)
        self.banner.add_button(self.admin_button)
        self.admin_button.setVisible(False)
        self.refresh_button = button("Làm mới", self.refresh)
        self.next_button = button("Tiếp tục", self._continue, "primary")
        self.next_button.setEnabled(False)

        bottom = QHBoxLayout()
        bottom.addWidget(self.refresh_button)
        bottom.addWidget(button("Dùng file ảnh đĩa…", self._pick_image))
        bottom.addWidget(button("Xem kết quả đã quét…", self._pick_results))
        bottom.addStretch(1)
        bottom.addWidget(self.next_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        layout.addWidget(label("Chọn ổ cần cứu dữ liệu", "title"))
        layout.addWidget(label("Ứng dụng chỉ đọc ổ này, không ghi gì vào đó. Đừng chép thêm hay format lại ổ trước khi cứu xong.",
                               "muted", wrap=True))
        layout.addWidget(self.banner)
        layout.addWidget(self.tree, 1)
        layout.addLayout(bottom)

    def refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Đang tìm ổ…")
        run_async(self, disks.list_disks, self._show)

    def _show(self, found: object) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Làm mới")
        kept = self._selected()
        self.tree.clear()
        if isinstance(found, Exception):
            self.banner.show_message("error", f"Không liệt kê được ổ đĩa: {found}")
            return
        icon = self.style().standardIcon(QStyle.SP_DriveHDIcon)
        for disk in found:
            name = f"{disk.label}: {disk.model}" if disk.model else disk.label
            mounts = ", ".join(disk.mounts[:3]) + ("…" if len(disk.mounts) > 3 else "")
            item = QTreeWidgetItem([name, human_size(disk.size), disk.bus,
                                    mounts + (" (đĩa hệ thống)" if disk.system else "")])
            item.setIcon(0, icon)
            item.setToolTip(0, disk.path)
            item.setToolTip(3, "\n".join(disk.mounts))
            item.setData(0, DISK_ROLE, disk)
            self.tree.addTopLevelItem(item)
            if kept and kept.path == disk.path:
                self.tree.setCurrentItem(item)
        self._explain(found)

    def _explain(self, found: list) -> None:
        needs_admin = sys.platform == "win32" and not disks.backend.is_admin()
        self.admin_button.setVisible(needs_admin)
        if needs_admin:
            self.banner.show_message("warn", "Windows chỉ cho đọc thô ổ đĩa khi ứng dụng chạy bằng quyền quản trị.")
        elif not found:
            self.banner.show_message("warn", "Không thấy ổ nào. Cắm ổ rồi bấm Làm mới.")
        else:
            self.banner.show_message("info", "")

    def _selected(self):
        item = self.tree.currentItem()
        return item.data(0, DISK_ROLE) if item and item.isSelected() else None

    def _selection_changed(self) -> None:
        self.next_button.setEnabled(self._selected() is not None)

    def _continue(self) -> None:
        disk = self._selected()
        if disk:
            self.chosen.emit(Choice(disk.path, disk.id, f"{disk.label}: {disk.model or disk.path}", disk.size, disk.model))

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file ảnh đĩa", "",
                                              "Ảnh đĩa (*.img *.dd *.raw *.bin *.iso *.001);;Mọi file (*)")
        if path:
            self.chosen.emit(Choice(path, None, f"File ảnh đĩa: {os.path.basename(path)}", os.path.getsize(path)))

    def _pick_results(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục đã lưu kết quả quét")
        if folder:
            self.results_requested.emit(folder)

    def _relaunch(self) -> None:
        arguments = [] if getattr(sys, "frozen", False) else ["-m", "khoiphucfile"]
        if disks.backend.relaunch_as_admin(arguments):
            self.window().close()
