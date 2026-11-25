"""Quét một khoảng của ổ, chép file nhận ra được ra thư mục lưu và ghi báo cáo CSV."""

from __future__ import annotations

import csv
import errno
import json
import os
import shutil
import struct
import time
from dataclasses import dataclass
from typing import Callable

from .formats import GROUP_LABELS, GROUP_OF, GROUPS, MFT_MAGIC, Found, align_up, aligned_hits, find_headers
from .source import GB, SECTOR, Source, Stopped

CHUNK = 8 << 20
STATE_FILE = "tien_do.json"
REPORT_FILE = "bao_cao.csv"
MFT_FILE = "mft_records.bin"
REPORT_COLUMNS = ["file", "loai", "vi_tri_byte", "kich_thuoc", "ngay", "trang_thai"]
WHOLE, PARTIAL, FAILED = "tron ven", "khong tron ven", "khong ghi duoc"

ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL, ERROR_FILE_TOO_LARGE = 39, 112, 223


class OutOfSpace(Exception):
    """Ổ lưu sắp đầy."""


class OutputError(Exception):
    """Không ghi được vào thư mục lưu."""


@dataclass
class Progress:
    position: int
    origin: int
    end: int
    speed: float
    remaining: float
    counts: dict[str, int]
    saved: int
    saved_bytes: int
    partial: int
    bad_bytes: int

    @property
    def share(self) -> float:
        return (self.position - self.origin) / max(self.end - self.origin, 1)


def human_time(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    return f"{seconds // 3600}g{seconds % 3600 // 60:02d}p"


def summarize(counts: dict[str, int]) -> str:
    parts = [f"{GROUP_LABELS[group]} {count}" for group, count in counts.items() if count]
    return " · ".join(parts) or "chưa có file"


class Scanner:
    def __init__(self, src: Source, out_dir: str, wanted: set[str], min_size: int = 0,
                 dry_run: bool = False, reserve: int = 2 * GB,
                 on_rows: Callable[[list[list]], None] | None = None):
        self.src = src
        self.out_dir = out_dir
        self.wanted = wanted
        self.min_size = min_size
        self.dry_run = dry_run
        self.reserve = reserve
        self.on_rows = on_rows
        self.counts = {group: 0 for group in GROUPS}
        self.saved = self.saved_bytes = self.partial = self.failed = self.mft = 0
        self.position = 0
        self.report = None
        self.report_file = None
        self.pending_rows: list[list] = []
        self.committed = self.snapshot()

    def restore(self, state: dict) -> None:
        self.counts.update(state.get("counts", {}))
        self.saved = state.get("saved", 0)
        self.saved_bytes = state.get("saved_bytes", 0)
        self.partial = state.get("partial", 0)
        self.failed = state.get("failed", 0)
        self.mft = state.get("mft", 0)
        self.src.bad_bytes = state.get("bad_bytes", 0)
        self.committed = self.snapshot()

    def snapshot(self) -> dict:
        return {"counts": dict(self.counts), "saved": self.saved, "saved_bytes": self.saved_bytes,
                "partial": self.partial, "failed": self.failed, "mft": self.mft, "bad_bytes": self.src.bad_bytes}

    def commit(self) -> None:
        """Ghi nhận các file của khối vừa quét xong; khối dở dang sẽ được quét lại khi chạy tiếp."""
        rows, self.pending_rows = self.pending_rows, []
        if self.report and rows:
            try:
                self.report.writerows(rows)
                self.report_file.flush()
            except OSError as error:
                raise OutputError(str(error)) from None
        self.committed = self.snapshot()
        if rows and self.on_rows:
            self.on_rows(rows)

    def open_report(self, fresh: bool) -> None:
        if self.dry_run:
            return
        path = os.path.join(self.out_dir, REPORT_FILE)
        new = fresh or not os.path.exists(path)
        self.report_file = open(path, "w" if new else "a", newline="", encoding="utf-8-sig" if new else "utf-8")
        self.report = csv.writer(self.report_file)
        if new:
            self.report.writerow(REPORT_COLUMNS)
            mft_path = os.path.join(self.out_dir, MFT_FILE)
            if os.path.exists(mft_path):
                os.remove(mft_path)

    def close(self) -> None:
        if self.report_file:
            self.report_file.close()
            self.report_file = None
            self.report = None

    def target(self, at: int, found: Found) -> str:
        group = GROUP_OF.get(found.ext, "khac")
        folder = os.path.join(self.out_dir, group, found.ext if found.complete else found.ext + "_khong_tron_ven")
        sector = at // SECTOR
        if found.taken:
            return os.path.join(folder, f"{found.taken:%Y}", f"{found.taken:%Y-%m-%d_%H-%M-%S}_s{sector}.{found.ext}")
        return os.path.join(folder, "khong_ro_ngay", f"s{sector}.{found.ext}")

    def free_space(self) -> int:
        try:
            return shutil.disk_usage(self.out_dir).free
        except OSError as error:
            raise OutputError(str(error)) from None

    def write(self, at: int, size: int, path: str) -> bool:
        """Chép ra path; False khi ổ lưu không chứa được file lớn như vậy (vd FAT32 quá 4 GB)."""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.src.copy_to(at, size, path)
            return True
        except BaseException as error:
            try:
                os.remove(path)
            except OSError:
                pass
            if not isinstance(error, OSError):
                raise
            code = getattr(error, "winerror", None)
            full = error.errno == errno.ENOSPC or code in (ERROR_DISK_FULL, ERROR_HANDLE_DISK_FULL)
            too_large = error.errno == errno.EFBIG or code == ERROR_FILE_TOO_LARGE
            if too_large or (full and self.free_space() >= size + self.reserve):
                return False
            if full:
                raise OutOfSpace(path) from None
            raise OutputError(str(error)) from None

    def keep(self, at: int, found: Found) -> None:
        if found.ext not in self.wanted or found.size < self.min_size:
            return
        path = self.target(at, found)
        if not self.dry_run:
            if self.free_space() < found.size + self.reserve:
                raise OutOfSpace(path)
            stored = self.write(at, found.size, path)
            status = FAILED if not stored else WHOLE if found.complete else PARTIAL
            self.pending_rows.append([os.path.relpath(path, self.out_dir), found.ext, at, found.size,
                                      f"{found.taken:%Y-%m-%d %H:%M:%S}" if found.taken else "", status])
            if not stored:
                self.failed += 1
                return
        self.counts[GROUP_OF.get(found.ext, "khac")] += 1
        self.saved += 1
        self.saved_bytes += found.size
        self.partial += 0 if found.complete else 1

    def keep_mft(self, at: int) -> None:
        self.mft += 1
        if not self.dry_run:
            record = struct.pack("<Q", at) + self.src.read(at, 1024).ljust(1024, b"\0")
            try:
                with open(os.path.join(self.out_dir, MFT_FILE), "ab") as out:
                    out.write(record)
            except OSError as error:
                raise OutputError(str(error)) from None

    def summary(self) -> str:
        return summarize(self.counts)

    def scan_chunk(self, pos: int, stop: int, skip_until: int) -> int:
        """Quét [pos, stop), trả về vị trí đã được phủ bởi các file trọn vẹn (có thể vượt quá stop)."""
        buf = self.src.read(pos, stop - pos + 16)
        for start_at in aligned_hits(buf, MFT_MAGIC, 0, stop - pos):
            self.keep_mft(pos + start_at)
        for at, measure in find_headers(buf, pos, stop):
            if at < skip_until:
                continue
            if self.src.cancelled:
                raise Stopped
            try:
                found = measure(self.src, at)
            except (struct.error, IndexError, ValueError, OverflowError):
                continue
            if found is None:
                continue
            self.keep(at, found)
            if found.complete and found.skip:
                skip_until = max(skip_until, align_up(at + found.size))
        return skip_until

    def run(self, start: int, end: int, checkpoint: Callable[[], None] | None = None, every: float = 30.0,
            origin: int | None = None, on_progress: Callable[[Progress], None] | None = None,
            interval: float = 0.5) -> None:
        """Quét [start, end); origin là điểm bắt đầu của cả lần quét (khi chạy tiếp) để tính phần trăm."""
        pos = start - start % SECTOR
        origin = start if origin is None else origin
        skip_until = pos
        began, began_at = time.monotonic(), pos
        last_check, last_shown = began, began - interval

        def show(done: int, now: float) -> None:
            speed = (done - began_at) / max(now - began, 1e-6)
            on_progress(Progress(done, origin, end, speed, (end - done) / max(speed, 1), dict(self.counts),
                                 self.saved, self.saved_bytes, self.partial, self.src.bad_bytes))

        while pos < end:
            self.position = pos
            self.commit()
            stop = min(pos + CHUNK, end)
            skip_until = self.scan_chunk(pos, stop, skip_until)
            pos = max(stop, skip_until)
            now = time.monotonic()
            if checkpoint and now - last_check >= every:
                self.position = min(pos, end)
                self.commit()
                checkpoint()
                last_check = now
            if on_progress and now - last_shown >= interval:
                show(min(pos, end), now)
                last_shown = now
        self.position = end
        self.commit()
        if on_progress:
            show(end, time.monotonic())


def load_state(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def save_state(path: str, state: dict) -> None:
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=1)
    os.replace(temp, path)


def load_report(out_dir: str) -> list[list]:
    """Các dòng trong bao_cao.csv, đúng thứ tự cột REPORT_COLUMNS; bỏ dòng hỏng (mất điện giữa chừng)."""
    rows = []
    try:
        with open(os.path.join(out_dir, REPORT_FILE), newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            for row in reader:
                if len(row) != len(REPORT_COLUMNS) or not row[2].isdigit() or not row[3].isdigit():
                    continue
                name = row[0] if os.sep == "\\" else row[0].replace("\\", os.sep)
                rows.append([name, row[1], int(row[2]), int(row[3]), row[4], row[5]])
    except (OSError, csv.Error, UnicodeDecodeError):
        pass
    return rows
