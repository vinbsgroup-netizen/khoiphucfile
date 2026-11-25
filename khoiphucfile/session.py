"""Một lần quét trọn vẹn: kiểm tra an toàn, mở ổ, chạy tiếp từ chỗ dừng và lưu tiến độ.

Dùng chung cho dòng lệnh và giao diện.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from . import disks
from .formats import GROUP_OF
from .power import keep_awake
from .scanner import STATE_FILE, OutOfSpace, OutputError, Progress, Scanner, load_state, save_state
from .source import GB, SECTOR, Source, SourceLost, Stopped

DONE, STOPPED, FULL, LOST, WRITE_ERROR = "xong", "dung", "day", "mat_o", "loi_ghi"


class Refused(Exception):
    """Không thể bắt đầu quét; nội dung lỗi viết sẵn cho người dùng đọc."""


@dataclass
class Options:
    source: str
    out_dir: str
    start: int = 0
    end: int | None = None
    types: set[str] = field(default_factory=lambda: set(GROUP_OF))
    min_size: int = 0
    dry_run: bool = False
    restart: bool = False


@dataclass
class Outcome:
    kind: str
    message: str


def state_path(out_dir: str) -> str:
    return os.path.join(out_dir, STATE_FILE)


def output_problem(out_dir: str, disk_id: str | None) -> tuple[bool, str]:
    """(có bị chặn không, lời nhắn) cho thư mục lưu; lời nhắn rỗng nghĩa là ổn."""
    if disk_id is None:
        return False, ""
    same = disks.output_on_disk(out_dir, disk_id)
    if same:
        return True, "Thư mục lưu nằm trên chính đĩa đang quét. Chọn ổ khác để không ghi đè dữ liệu cần cứu."
    if same is None:
        return False, "Không kiểm tra được thư mục lưu nằm trên đĩa nào; hãy chắc chắn nó KHÁC đĩa đang quét."
    return False, ""


class Session:
    def __init__(self, options: Options):
        self.options = options
        self.out_dir = os.path.abspath(options.out_dir)
        try:
            self.path, self.disk_id = disks.resolve(options.source)
        except disks.DiskNotFound as error:
            raise Refused(str(error)) from None
        blocked, self.warning = output_problem(self.out_dir, self.disk_id)
        if blocked:
            raise Refused(self.warning)
        try:
            self.src: Source = disks.open_source(self.path, self.disk_id)
        except (disks.AccessDenied, disks.DiskNotFound) as error:
            raise Refused(str(error)) from None
        except OSError as error:
            raise Refused(f"Không mở được {self.path}: {error.strerror or error}") from None
        try:
            self._prepare()
        except BaseException:
            self.src.close()
            raise

    def _prepare(self) -> None:
        options = self.options
        self.model = disks.model_of(self.disk_id)
        state = None if options.restart or options.dry_run else load_state(state_path(self.out_dir))
        if state:
            other_model = state.get("model") and self.model and state["model"] != self.model
            if state.get("source_size") != self.src.size or other_model:
                raise Refused("Thư mục lưu đang chứa tiến độ của một đĩa khác. "
                              "Chọn thư mục khác hoặc quét lại từ đầu (--restart).")
            self.origin, self.start, self.end = state["start"], state["position"], state["end"]
            self.wanted, self.min_size = set(state["types"]), state["min_size"]
        else:
            self.origin = self.start = options.start // SECTOR * SECTOR
            self.end = min(self.src.size, options.end) if options.end else self.src.size
            self.wanted, self.min_size = set(options.types), options.min_size
            if self.start >= self.end:
                raise Refused(f"Khoảng quét rỗng: bắt đầu ở {self.start / GB:.2f} GB "
                              f"nhưng kết thúc ở {self.end / GB:.2f} GB.")
        self.resumed = state is not None
        self.scanner = Scanner(self.src, self.out_dir, self.wanted, self.min_size, options.dry_run)
        if state:
            self.scanner.restore(state)

    def cancel(self) -> None:
        self.src.cancel()

    def checkpoint(self) -> None:
        if self.options.dry_run:
            return
        try:
            save_state(state_path(self.out_dir), {
                "source": self.path, "source_size": self.src.size, "model": self.model, "start": self.origin,
                "end": self.end, "position": self.scanner.position, "types": sorted(self.wanted),
                "min_size": self.min_size, "updated": datetime.now().isoformat(timespec="seconds"),
                **self.scanner.committed})
        except OSError as error:
            raise OutputError(str(error)) from None

    def run(self, on_progress: Callable[[Progress], None] | None = None,
            on_rows: Callable[[list[list]], None] | None = None, interval: float = 0.5) -> Outcome:
        scanner = self.scanner
        scanner.on_rows = on_rows
        scanner.position = self.start
        try:
            if not self.options.dry_run:
                os.makedirs(self.out_dir, exist_ok=True)
            scanner.open_report(fresh=not self.resumed)
        except OSError as error:
            self.src.close()
            return Outcome(WRITE_ERROR, f"Không ghi được vào thư mục lưu: {error}")
        try:
            outcome = self._scan(on_progress, interval)
            self.checkpoint()
        except OutputError as error:
            outcome = Outcome(WRITE_ERROR, f"Không lưu được tiến độ vào thư mục lưu: {error}")
        finally:
            scanner.close()
            self.src.close()
        return outcome

    def _scan(self, on_progress: Callable[[Progress], None] | None, interval: float) -> Outcome:
        scanner = self.scanner
        try:
            with keep_awake():
                scanner.run(self.start, self.end, self.checkpoint, origin=self.origin,
                            on_progress=on_progress, interval=interval)
        except (KeyboardInterrupt, Stopped):
            return Outcome(STOPPED, f"Đã dừng ở {scanner.position / GB:.2f} GB. Có thể quét tiếp từ chỗ này.")
        except OutOfSpace:
            return Outcome(FULL, f"Ổ lưu sắp đầy, dừng ở {scanner.position / GB:.2f} GB. "
                                 "Giải phóng chỗ trống rồi quét tiếp.")
        except SourceLost:
            return Outcome(LOST, f"Mất kết nối với ổ đang quét ở {scanner.position / GB:.2f} GB. "
                                 "Cắm lại ổ rồi quét tiếp.")
        except OutputError as error:
            return Outcome(WRITE_ERROR, f"Không ghi được vào thư mục lưu, dừng ở {scanner.position / GB:.2f} GB: {error}")
        return Outcome(DONE, f"Xong. Đã lưu {scanner.saved} file ({scanner.saved_bytes / GB:.2f} GB): {scanner.summary()}.")
