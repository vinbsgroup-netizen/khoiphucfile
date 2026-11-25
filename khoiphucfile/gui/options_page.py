"""Bước 2: chọn loại file, nơi lưu và khoảng quét."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QLineEdit, QMessageBox, QPushButton, QRadioButton, QSpinBox, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import disks
from ..formats import GROUPS
from ..scanner import load_state
from ..session import Options, output_problem, state_path
from ..source import GB
from .common import Banner, Choice, button, free_bytes, human_size, label, run_async, settings

GROUP_TITLES = {"anh": "Ảnh", "video": "Video", "amthanh": "Âm thanh", "tailieu": "Tài liệu", "khac": "File nén và khác"}


class TypesTree(QTreeWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderHidden(True)
        self.setColumnCount(2)
        self.setColumnWidth(0, 190)
        for group, extensions in GROUPS.items():
            parent = QTreeWidgetItem([GROUP_TITLES[group], ", ".join(extensions)])
            parent.setFlags(parent.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            for extension in extensions:
                child = QTreeWidgetItem([extension])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked)
                parent.addChild(child)
            self.addTopLevelItem(parent)
        self.itemChanged.connect(lambda *_: self.changed.emit())

    def _children(self):
        for i in range(self.topLevelItemCount()):
            parent = self.topLevelItem(i)
            for j in range(parent.childCount()):
                yield parent.child(j)

    def selected(self) -> set[str]:
        return {child.text(0) for child in self._children() if child.checkState(0) == Qt.Checked}

    def select(self, extensions: set[str]) -> None:
        for child in self._children():
            child.setCheckState(0, Qt.Checked if child.text(0) in extensions else Qt.Unchecked)


class OptionsPage(QWidget):
    back = Signal()
    start = Signal(object)
    results_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.choice: Choice | None = None
        self.blocked = True
        self.state: dict | None = None
        self.check_number = 0

        self.source_label = label("", "muted", wrap=True)
        self.out = QLineEdit()
        self.out.setObjectName("field")
        self.out.setPlaceholderText("Thư mục nằm trên ổ khác với ổ đang cứu")
        self.out_status = Banner()
        self.timer = QTimer(self, singleShot=True, interval=350)
        self.timer.timeout.connect(self._check_output)
        self.out.textChanged.connect(self._output_changed)

        self.resume_banner = Banner()
        self.resume = QRadioButton("Quét tiếp từ chỗ dừng")
        self.fresh = QRadioButton("Quét lại từ đầu")
        choices = QButtonGroup(self)
        for radio in (self.resume, self.fresh):
            choices.addButton(radio)
            radio.toggled.connect(self._update_controls)
        self.view_button = button("Xem kết quả", lambda: self.results_requested.emit(self.out_dir()))
        self.resume_row = QWidget()
        resume_layout = QHBoxLayout(self.resume_row)
        resume_layout.setContentsMargins(0, 0, 0, 0)
        resume_layout.addWidget(self.resume)
        resume_layout.addWidget(self.fresh)
        resume_layout.addStretch(1)
        resume_layout.addWidget(self.view_button)

        self.types = TypesTree()
        self.types.changed.connect(self._update_controls)

        self.advanced_button = QPushButton("Tuỳ chọn nâng cao ▸")
        self.advanced_button.setCheckable(True)
        self.advanced_button.toggled.connect(self._toggle_advanced)
        self.advanced = QWidget()
        self.start_gb, self.end_gb = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.start_gb, self.end_gb):
            spin.setDecimals(2)
            spin.setSuffix(" GB")
            spin.valueChanged.connect(self._update_controls)
        self.start_gb.setSpecialValueText("Đầu ổ")
        self.end_gb.setSpecialValueText("Hết ổ")
        self.min_kb = QSpinBox()
        self.min_kb.setSpecialValueText("Không bỏ file nào")
        self.min_kb.setRange(0, 1_000_000)
        self.min_kb.setSuffix(" KB")
        for spin in (self.start_gb, self.end_gb, self.min_kb):
            spin.setFixedWidth(170)
        fields = QGridLayout(self.advanced)
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setHorizontalSpacing(16)
        fields.setColumnStretch(3, 1)
        for column, (text, spin) in enumerate((("Bắt đầu quét từ", self.start_gb), ("Dừng ở", self.end_gb),
                                               ("Bỏ file nhỏ hơn", self.min_kb))):
            fields.addWidget(label(text, "muted"), 0, column)
            fields.addWidget(spin, 1, column)
        self.advanced.setVisible(False)

        self.start_button = button("Bắt đầu quét", self._start, "primary")

        out_row = QHBoxLayout()
        out_row.addWidget(self.out, 1)
        out_row.addWidget(button("Chọn…", self._pick_folder))
        advanced_row = QHBoxLayout()
        advanced_row.addWidget(self.advanced_button)
        advanced_row.addStretch(1)
        bottom = QHBoxLayout()
        bottom.addWidget(button("Quay lại", self.back.emit))
        bottom.addStretch(1)
        bottom.addWidget(self.start_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        layout.addWidget(label("Lưu ở đâu, tìm những gì", "title"))
        layout.addWidget(self.source_label)
        layout.addWidget(label("Nơi lưu file cứu được", "section"))
        layout.addLayout(out_row)
        layout.addWidget(self.out_status)
        layout.addWidget(self.resume_banner)
        layout.addWidget(self.resume_row)
        layout.addWidget(label("Loại file cần tìm", "section"))
        layout.addWidget(self.types, 1)
        layout.addLayout(advanced_row)
        layout.addWidget(self.advanced)
        layout.addLayout(bottom)

    def set_choice(self, choice: Choice) -> None:
        self.choice = choice
        self.source_label.setText(f"Ổ nguồn: {choice.title} ({human_size(choice.size)}), chỉ đọc.")
        for spin in (self.start_gb, self.end_gb):
            spin.setRange(0, choice.size / GB)
            spin.setValue(0)
        store = settings()
        remembered = store.value("out_dir", "")
        self.out.setText(remembered or suggest_folder(choice.disk_id))
        types = store.value("types", "")
        if types:
            self.types.select(set(str(types).split(",")))
        self._check_output()

    def out_dir(self) -> str:
        text = self.out.text().strip()
        return os.path.abspath(os.path.expanduser(text)) if text else ""

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu file cứu được",
                                                  disks.existing_parent(self.out_dir()) if self.out_dir() else "")
        if folder:
            self.out.setText(os.path.normpath(folder))

    def _toggle_advanced(self, shown: bool) -> None:
        self.advanced.setVisible(shown)
        self.advanced_button.setText("Tuỳ chọn nâng cao ▾" if shown else "Tuỳ chọn nâng cao ▸")

    def _output_changed(self) -> None:
        self.check_number += 1  # bỏ kết quả kiểm tra thư mục cũ đang trên đường về
        self.blocked = True
        self.state = None
        self._update_controls()
        self.timer.start()

    def _check_output(self) -> None:
        self.timer.stop()
        self.check_number += 1
        ticket, folder, choice = self.check_number, self.out_dir(), self.choice
        if not folder or choice is None:
            self.state = None
            self.out_status.show_message("info", "")
            self._show_state()
            return

        def work():
            parent = disks.existing_parent(folder)
            blocked, message = output_problem(folder, choice.disk_id)
            writable = os.path.isdir(parent) and os.access(parent, os.W_OK)
            return blocked, message, writable, free_bytes(parent), load_state(state_path(folder))

        def show(result):
            if ticket != self.check_number:
                return
            if isinstance(result, Exception):
                self.out_status.show_message("error", f"Không kiểm tra được thư mục này: {result}")
                return
            blocked, message, writable, free, state = result
            if blocked:
                self.out_status.show_message("error", message)
            elif not writable:
                blocked = True
                self.out_status.show_message("error", "Không ghi được vào thư mục này. Chọn thư mục khác.")
            elif message:
                self.out_status.show_message("warn", message)
            elif free is not None:
                kind = "warn" if free < 10 * GB else "ok"
                self.out_status.show_message(kind, f"Còn trống {human_size(free)} trên ổ lưu.")
            else:
                self.out_status.show_message("info", "")
            self.blocked = blocked
            self.state = state
            self._show_state()

        run_async(self, work, show)

    def _show_state(self) -> None:
        state, choice = self.state, self.choice
        self.resume_row.setVisible(bool(state))
        if not state or choice is None:
            self.resume_banner.show_message("info", "")
            self._update_controls()
            return
        same = state.get("source_size") == choice.size and (
            not state.get("model") or not choice.model or state["model"] == choice.model)
        finished = state.get("position", 0) >= state.get("end", 1)
        share = (state.get("position", 0) - state.get("start", 0)) / max(state.get("end", 1) - state.get("start", 0), 1)
        if not same:
            self.resume_banner.show_message("warn", "Thư mục này đang chứa kết quả quét của một ổ khác. "
                                                    "Nên chọn thư mục khác; quét lại từ đầu sẽ thay danh sách cũ.")
        elif finished:
            self.resume_banner.show_message("info", "Thư mục này đã có kết quả quét xong của ổ này.")
        else:
            self.resume_banner.show_message("info", f"Thư mục này có lần quét đang dở ({share:.0%}) của ổ này.")
        self.resume.setEnabled(same and not finished)
        (self.resume if same and not finished else self.fresh).setChecked(True)
        self._update_controls()

    def resuming(self) -> bool:
        return bool(self.state) and self.resume.isEnabled() and self.resume.isChecked()

    def _update_controls(self) -> None:
        resuming = self.resuming()
        for widget in (self.types, self.advanced):
            widget.setEnabled(not resuming)
        range_ok = resuming or not self.end_gb.value() or self.start_gb.value() < self.end_gb.value()
        ready = not self.blocked and bool(self.out_dir()) and range_ok and (resuming or bool(self.types.selected()))
        self.start_button.setEnabled(ready)
        self.start_button.setText("Quét tiếp" if resuming else "Bắt đầu quét")

    def _start(self) -> None:
        restart = bool(self.state) and not self.resuming()
        if restart:
            answer = QMessageBox.question(self, "Quét lại từ đầu", "Danh sách và tiến độ cũ trong thư mục này sẽ bị thay. "
                                          "Các file đã cứu trước đó vẫn còn. Quét lại từ đầu?")
            if answer != QMessageBox.Yes:
                return
        types = self.types.selected()
        store = settings()
        store.setValue("out_dir", self.out_dir())
        store.setValue("types", ",".join(sorted(types)))
        self.start.emit(Options(self.choice.spec, self.out_dir(), int(self.start_gb.value() * GB),
                                int(self.end_gb.value() * GB) or None, types,
                                self.min_kb.value() * 1024, restart=restart))


def suggest_folder(disk_id: str | None) -> str:
    """Windows: ổ còn trống nhiều nhất, không nằm trên đĩa đang cứu; nơi khác: thư mục nhà."""
    if sys.platform != "win32":
        return os.path.join(os.path.expanduser("~"), "KhoiPhuc")
    holders = {f"{letter}:\\": disks.backend.disks_of_path(f"{letter}:\\") for letter in disks.backend.drive_letters()}
    # Ổ mạng không có đĩa vật lý; bỏ qua vì hỏi dung lượng ổ mạng mất kết nối có thể treo cửa sổ.
    local = [root for root, found in holders.items() if found and disk_id not in found]
    best = max(local, key=lambda root: free_bytes(root) or 0, default="")
    return os.path.join(best, "KhoiPhuc") if best else ""
