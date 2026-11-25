r"""Giao diện dòng lệnh.

    khoiphuc disks
    khoiphuc scan HM160HI --out D:\KhoiPhuc --start-gb 9.6

Chạy lại đúng lệnh đó thì quét tiếp từ chỗ dừng; thêm --restart để quét lại.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__, developer, disks
from .formats import parse_types
from .scanner import MFT_FILE, REPORT_FILE, Progress, human_time, summarize
from .session import DONE, FULL, LOST, STOPPED, WRITE_ERROR, Options, Refused, Session
from .source import GB, MB

EXIT_CODES = {DONE: 0, STOPPED: 130, FULL: 3, LOST: 4, WRITE_ERROR: 5}


def list_disks() -> int:
    found = disks.list_disks()
    if not found:
        hint = " Mở cmd bằng quyền Administrator rồi chạy lại." if sys.platform == "win32" else ""
        print(f"Không đọc được đĩa nào.{hint}")
        return 1
    for disk in found:
        mounts = ", ".join(disk.mounts) or "không gắn ổ nào"
        print(f"  {disk.label}: {disk.model or '?'} | {disk.size / GB:.1f} GB | {disk.bus or '?'} | {mounts}"
              f"{' | đĩa hệ thống' if disk.system else ''}")
    return 0


class ProgressLine:
    """In tiến độ: một dòng tự cập nhật khi chạy trong cửa sổ lệnh, mỗi phút một dòng khi ghi ra file."""

    def __init__(self) -> None:
        self.live = sys.stdout.isatty()
        self.interval = 2 if self.live else 60

    def __call__(self, progress: Progress) -> None:
        line = (f"{progress.share:6.1%} | {progress.position / GB:6.1f}/{progress.end / GB:.1f} GB"
                f" | {progress.speed / MB:5.1f} MB/s | còn ~{human_time(progress.remaining)}"
                f" | {summarize(progress.counts)}")
        if progress.bad_bytes:
            line += f" | lỗi đọc {progress.bad_bytes / MB:.1f} MB"
        if self.live:
            sys.stdout.write("\r" + line.ljust(110))
            sys.stdout.flush()
        else:
            print(line)


def scan_command(args: argparse.Namespace) -> int:
    try:
        session = Session(Options(args.source, args.out, int(args.start_gb * GB),
                                  int(args.end_gb * GB) if args.end_gb else None, parse_types(args.types),
                                  int(args.min_kb * 1024), args.dry_run, args.restart))
    except (Refused, ValueError) as error:
        print(error)
        return 2
    if session.warning and not args.dry_run:
        print(f"Cảnh báo: {session.warning}")
    if session.resumed:
        print(f"Tiếp tục lần quét trước từ {session.start / GB:.2f} GB (thêm --restart để quét lại từ đầu).")
    print(f"Nguồn: {session.path} {session.model} ({session.src.size / GB:.1f} GB) — chỉ đọc")
    print(f"Quét {session.start / GB:.2f} → {session.end / GB:.2f} GB, lưu vào {session.out_dir}"
          f"{' (chạy thử, không ghi)' if args.dry_run else ''}")

    line = ProgressLine()
    outcome = session.run(line, interval=line.interval)
    scanner = session.scanner
    print(f"\n{outcome.message}")
    if outcome.kind != DONE and not args.dry_run:
        print("Chạy lại đúng lệnh này để quét tiếp.")
    if scanner.partial:
        print(f"  {scanner.partial} ảnh không trọn vẹn (file bị phân mảnh) nằm trong các thư mục *_khong_tron_ven.")
    if scanner.failed:
        print(f"  {scanner.failed} file quá lớn so với ổ lưu (FAT32 chỉ chứa file dưới 4 GB), "
              "xem cột trang_thai trong báo cáo.")
    if scanner.mft:
        saved_to = "" if args.dry_run else f", đã lưu vào {MFT_FILE}"
        print(f"  Gặp {scanner.mft} bản ghi bảng tên file NTFS (MFT){saved_to}.")
    if session.src.bad_bytes:
        print(f"  {session.src.bad_bytes / MB:.1f} MB đọc lỗi (sector hỏng), được thay bằng số 0.")
    if not args.dry_run:
        print(f"  Danh sách file: {os.path.join(session.out_dir, REPORT_FILE)}")
    return EXIT_CODES[outcome.kind]


def about() -> int:
    print("\n".join(developer.about_lines()))
    for name in (developer.TERMS, developer.RULES):
        print("\n" + developer.read_document(name))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="khoiphuc",
                                     description="Khôi phục file bằng cách quét thô ổ đĩa (chỉ đọc ổ nguồn).")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True, metavar="{disks,scan,about}")
    sub.add_parser("disks", help="liệt kê đĩa vật lý")
    scan = sub.add_parser("scan", help="quét và chép file ra thư mục trên ổ khác")
    scan.add_argument("source",
                      help="mã đĩa (2, sdb, disk4), tên model (vd HM160HI), đường dẫn thiết bị hoặc file ảnh đĩa")
    scan.add_argument("--out", required=True, help="thư mục lưu, phải nằm trên ổ khác")
    scan.add_argument("--start-gb", type=float, default=0.0, help="bắt đầu quét từ GB thứ mấy")
    scan.add_argument("--end-gb", type=float, help="dừng ở GB thứ mấy (mặc định hết ổ)")
    scan.add_argument("--types", default="all", help="nhóm anh,video,amthanh,tailieu,khac hoặc đuôi jpg,mp4,...")
    scan.add_argument("--min-kb", type=float, default=0, help="bỏ file nhỏ hơn số KB này")
    scan.add_argument("--restart", action="store_true", help="bỏ tiến độ cũ, quét lại từ đầu")
    scan.add_argument("--dry-run", action="store_true", help="chỉ đếm, không ghi file")
    sub.add_parser("about", help="nhà phát triển, điều khoản và nội quy sử dụng")
    helper = sub.add_parser("open-device")
    helper.add_argument("path")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.command == "disks":
        return list_disks()
    if args.command == "about":
        return about()
    if args.command == "open-device":
        from .disks.open_device import send_device

        try:
            return send_device(args.path)
        except OSError as error:
            print(error, file=sys.stderr)
            return 1
    return scan_command(args)


if __name__ == "__main__":
    sys.exit(main())
