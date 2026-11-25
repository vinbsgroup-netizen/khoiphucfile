"""Bước 3: theo dõi tiến độ quét và xem file cứu được."""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMessageBox, QProgressBar, QVBoxLayout, QWidget

from .. import disks
from ..formats import GROUPS
from ..scanner import Progress, load_report, load_state
from ..session import DONE, FULL, LOST, STOPPED, Options, Outcome, state_path
from ..source import GB, MB
from .common import Banner, button, decimal, human_duration, human_size, label, number, open_folder, run_async
from .options_page import GROUP_TITLES
from .results import ResultsView
from .scan_thread import ScanThread


def explain(outcome: Outcome, scanner) -> str:
    place = f"{decimal(scanner.position / GB)} GB"
    return {
        DONE: f"Đã cứu {number(scanner.saved)} file ({human_size(scanner.saved_bytes)}).",
        STOPPED: f"Đã dừng ở {place}. Bấm Quét tiếp để chạy tiếp từ chỗ này.",
        FULL: f"Ổ lưu sắp đầy nên dừng ở {place}. Giải phóng chỗ trống rồi bấm Quét tiếp.",
        LOST: f"Mất kết nối với ổ đang quét ở {place}. Cắm lại ổ, đợi vài giây rồi bấm Quét tiếp.",
    }.get(outcome.kind, outcome.message)


class ScanPage(QWidget):
    running_changed = Signal(bool)
    refused = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.thread: ScanThread | None = None
        self.options: Options | None = None
        self.out_dir = ""

        self.title = label("", "title")
        self.subtitle = label("", "muted", wrap=True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.status = label("", "", wrap=True)
        self.banner = Banner()
        self.stop_button = button("Dừng", self.stop)
        self.resume_button = button("Quét tiếp", self._resume, "primary")
        self.folder_button = button("Mở thư mục lưu", lambda: open_folder(self.out_dir))
        self.tiles = {group: label("0", "number") for group in GROUPS}
        self.results = ResultsView()

        heading = QHBoxLayout()
        heading_text = QVBoxLayout()
        heading_text.addWidget(self.title)
        heading_text.addWidget(self.subtitle)
        heading.addLayout(heading_text, 1)
        for widget in (self.folder_button, self.stop_button, self.resume_button):
            heading.addWidget(widget)
        tiles = QHBoxLayout()
        for group, value in self.tiles.items():
            card = QFrame()
            card.setProperty("role", "card")
            inside = QVBoxLayout(card)
            inside.setContentsMargins(14, 8, 14, 8)
            inside.setSpacing(0)
            inside.addWidget(value)
            inside.addWidget(label(GROUP_TITLES[group], "muted"))
            tiles.addWidget(card, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        layout.addLayout(heading)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addWidget(self.banner)
        layout.addLayout(tiles)
        layout.addWidget(self.results, 1)
        self._buttons(running=False, can_resume=False)

    def is_running(self) -> bool:
        return self.thread is not None

    def start(self, options: Options) -> None:
        self.options = options
        self.out_dir = options.out_dir
        self.title.setText("Đang mở ổ…")
        self.subtitle.setText(f"Lưu vào {options.out_dir}")
        self.status.setText("Nếu hệ điều hành hỏi mật khẩu, hãy nhập để cho phép đọc ổ đĩa.")
        self.banner.show_message("info", "")
        self.bar.setRange(0, 0)
        thread = self.thread = ScanThread(options, self)
        thread.opened.connect(self._opened)
        thread.progress.connect(self._progress)
        thread.rows.connect(self.results.append)
        thread.refused.connect(self._refused)
        thread.ended.connect(self._ended)
        thread.finished.connect(thread.deleteLater)
        self._buttons(running=True, can_resume=False)
        self.running_changed.emit(True)
        thread.start()

    def show_results(self, out_dir: str) -> bool:
        """Mở lại kết quả của một lần quét trước; False khi thư mục không có báo cáo."""
        rows = load_report(out_dir)
        state = load_state(state_path(out_dir))
        if not rows and not state:
            return False
        state = state or {}
        self.out_dir, self.options = out_dir, None
        self.title.setText("Kết quả đã quét")
        self.subtitle.setText(out_dir)
        self.banner.show_message("info", "")
        self.bar.setRange(0, 1000)
        unfinished = bool(state) and state["position"] < state["end"]
        if state:
            share = (state["position"] - state["start"]) / max(state["end"] - state["start"], 1)
            self.bar.setValue(int(share * 1000))
            place = f"mới quét {share:.0%}" if unfinished else "đã quét xong"
            self.status.setText(f"{state.get('model') or state.get('source', '')}: {place}, "
                                f"{number(state.get('saved', len(rows)))} file, {human_size(state.get('saved_bytes', 0))}.")
            self._counts(state.get("counts", {}))
        else:
            self.bar.setValue(1000)
            self.status.setText(f"{number(len(rows))} file.")
            self._counts({})
        self.results.load(out_dir, rows)
        self._buttons(running=False, can_resume=unfinished)
        return True

    def stop(self) -> None:
        if self.thread:
            self.stop_button.setEnabled(False)
            self.stop_button.setText("Đang dừng…")
            self.thread.stop()

    def wait(self, milliseconds: int) -> bool:
        return self.thread is None or self.thread.wait(milliseconds)

    def _buttons(self, running: bool, can_resume: bool) -> None:
        self.stop_button.setVisible(running)
        self.stop_button.setEnabled(running)
        self.stop_button.setText("Dừng")
        self.resume_button.setVisible(can_resume)
        self.resume_button.setEnabled(True)
        self.folder_button.setEnabled(bool(self.out_dir) and os.path.isdir(self.out_dir))

    def _counts(self, counts: dict) -> None:
        for group, tile in self.tiles.items():
            tile.setText(number(counts.get(group, 0)))

    def _opened(self, session, earlier_rows: list) -> None:
        self.title.setText("Đang quét")
        self.subtitle.setText(f"{session.model or os.path.basename(session.path)} → {session.out_dir}")
        self.status.setText("Đang đọc những phần đầu tiên…")
        self.bar.setRange(0, 1000)
        self.banner.show_message("warn", session.warning)
        self.results.load(session.out_dir, earlier_rows)
        self._counts(session.scanner.committed["counts"])
        self.folder_button.setEnabled(True)

    def _progress(self, progress: Progress) -> None:
        self.bar.setValue(int(progress.share * 1000))
        parts = [f"{decimal(progress.share * 100)}%", f"{decimal(progress.position / GB)} / {decimal(progress.end / GB)} GB",
                 f"{progress.speed / MB:.0f} MB/s"]
        if progress.position < progress.end:
            parts.append(f"còn {human_duration(progress.remaining)}")
        parts.append(f"đã cứu {number(progress.saved)} file ({human_size(progress.saved_bytes)})")
        if progress.bad_bytes:
            parts.append(f"lỗi đọc {human_size(progress.bad_bytes)}")
        self.status.setText("  ·  ".join(parts))
        self._counts(progress.counts)

    def _finish(self) -> None:
        self.thread.wait(5000)
        self.thread = None
        self.running_changed.emit(False)

    def _refused(self, message: str) -> None:
        self._finish()
        self.bar.setRange(0, 1000)
        self._buttons(running=False, can_resume=False)
        self.refused.emit(message)

    def _ended(self, outcome: Outcome) -> None:
        scanner = self.thread.session.scanner
        self._finish()
        self.title.setText({DONE: "Đã quét xong", STOPPED: "Đã dừng"}.get(outcome.kind, "Quét bị gián đoạn"))
        notes = [explain(outcome, scanner)]
        if scanner.partial:
            notes.append(f"{number(scanner.partial)} ảnh không trọn vẹn vì nằm rời rạc trên ổ, chỉ cứu được phần đầu.")
        if scanner.failed:
            notes.append(f"{number(scanner.failed)} file quá lớn so với ổ lưu (ổ FAT32 chỉ chứa file dưới 4 GB).")
        if scanner.src.bad_bytes:
            notes.append(f"{human_size(scanner.src.bad_bytes)} không đọc được do sector hỏng.")
        self.banner.show_message({DONE: "ok", STOPPED: "info"}.get(outcome.kind, "error"), "\n".join(notes))
        self._counts(scanner.committed["counts"])
        self._buttons(running=False, can_resume=outcome.kind != DONE)

    def _resume(self) -> None:
        state = load_state(state_path(self.out_dir))
        if not state:
            self.banner.show_message("error", "Không thấy file tiến độ trong thư mục lưu.")
            return
        self.resume_button.setEnabled(False)

        def locate():
            if not state["source"].startswith(("\\\\.\\", "/dev/")):
                return state["source"] if os.path.isfile(state["source"]) else None
            disk = disks.find_again(state["source"], state.get("model", ""), state["source_size"])
            return disk.path if disk else None

        def begin(path):
            self.resume_button.setEnabled(True)
            if isinstance(path, str):
                self.start(Options(path, self.out_dir))
            else:
                name = state.get("model") or state["source"]
                self.banner.show_message("warn", f"Không thấy {name} ({human_size(state['source_size'])}). "
                                                 "Cắm lại ổ rồi bấm Quét tiếp.")

        run_async(self, locate, begin)

    def confirm_stop(self) -> bool:
        answer = QMessageBox.question(self, "Đang quét", "Dừng quét và thoát? Lần sau có thể quét tiếp từ chỗ này.")
        return answer == QMessageBox.Yes
