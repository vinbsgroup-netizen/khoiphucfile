"""Nhận ra và đo độ dài từng định dạng file theo cấu trúc bên trong của nó.

Mỗi hàm measure_* nhận vị trí đầu file trên ổ và trả về Found, hoặc None khi
không phải file đúng định dạng.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from .source import BLOCK, MB, SECTOR, Source

MAX_IMAGE = 128 * MB
MAX_DOCUMENT = 1024 * MB
MAX_VIDEO = 16 * 1024 * MB
MAX_SEARCH = 256 * MB

GROUPS = {
    "anh": ("jpg", "png", "gif", "bmp", "webp", "heic", "avif"),
    "video": ("mp4", "mov", "m4v", "3gp", "avi"),
    "amthanh": ("wav", "m4a"),
    "tailieu": ("pdf", "doc", "xls", "ppt", "msg", "vsd", "docx", "xlsx", "pptx", "odt", "ods", "odp", "epub"),
    "khac": ("zip", "jar", "apk", "ole"),
}
GROUP_OF = {ext: group for group, exts in GROUPS.items() for ext in exts}
GROUP_LABELS = {"anh": "ảnh", "video": "video", "amthanh": "âm thanh", "tailieu": "tài liệu", "khac": "khác"}


@dataclass
class Found:
    """Một file nhận ra được: độ dài, đuôi, đã trọn vẹn chưa và ngày đọc được trong file."""

    size: int
    ext: str
    complete: bool = True
    taken: datetime | None = None
    skip: bool = True


def align_up(value: int, unit: int = SECTOR) -> int:
    return value + (-value) % unit


def printable(raw: bytes) -> bool:
    return all(32 <= c < 127 for c in raw)


def plausible(stamp: datetime | None) -> datetime | None:
    if stamp is None or not 1990 <= stamp.year <= 2100:
        return None
    return stamp


# ---------------------------------------------------------------- JPEG

JPEG_MARKER = re.compile(rb"\xff+([^\x00\xff\xd0-\xd7])")
ZERO_RUN = b"\0" * 4096
JPEG_FRAMES = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
JPEG_SEGMENTS = JPEG_FRAMES | {0xC4, 0xCC, 0xDA, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF, 0xFE} | set(range(0xE0, 0xF0))


def parse_stamp(raw: bytes, layout: str = "%Y:%m:%d %H:%M:%S") -> datetime | None:
    try:
        return plausible(datetime.strptime(raw.decode("ascii"), layout))
    except (UnicodeDecodeError, ValueError):
        return None


def read_ifd(tiff: bytes, at: int, order: str) -> dict[int, tuple[int, int, int]]:
    count = struct.unpack_from(order + "H", tiff, at)[0]
    tags = {}
    for i in range(min(count, 512)):
        tag, kind, n, value = struct.unpack_from(order + "HHII", tiff, at + 2 + 12 * i)
        tags[tag] = (kind, n, value)
    return tags


def exif_date(app1: bytes) -> datetime | None:
    """DateTimeOriginal, rồi DateTimeDigitized, rồi DateTime trong khối EXIF."""
    if not app1.startswith(b"Exif\0\0"):
        return None
    tiff = app1[6:]
    try:
        order = {b"II": "<", b"MM": ">"}[tiff[:2]]
        tags = read_ifd(tiff, struct.unpack_from(order + "I", tiff, 4)[0], order)
        candidates = []
        if 0x8769 in tags:
            exif = read_ifd(tiff, tags[0x8769][2], order)
            candidates += [exif.get(0x9003), exif.get(0x9004)]
        candidates.append(tags.get(0x0132))
    except (KeyError, struct.error):
        return None
    for tag in candidates:
        if tag and tag[0] == 2 and tag[1] >= 19:
            stamp = parse_stamp(tiff[tag[2]:tag[2] + 19])
            if stamp:
                return stamp
    return None


def next_jpeg_marker(src: Source, pos: int, limit: int) -> int | None:
    """Marker kế tiếp sau dữ liệu nén; một dải 4 KB toàn số 0 cũng coi là hết ảnh (file bị đứt)."""
    while pos < limit:
        window = src.read(pos, min(BLOCK, limit - pos) + len(ZERO_RUN))
        if len(window) < 2:
            return None
        match = JPEG_MARKER.search(window)
        zeros = window.find(ZERO_RUN)
        if zeros >= 0 and (match is None or zeros < match.start()):
            return pos + zeros
        if match:
            return pos + match.start(1) - 1
        pos += max(len(window) - len(ZERO_RUN), 1)
    return None


def measure_jpeg(src: Source, off: int) -> Found | None:
    limit = off + MAX_IMAGE
    pos = off + 2
    taken = None
    seen_frame = seen_scan = False
    while pos < limit:
        head = src.read(pos, 4)
        if len(head) < 2 or head[0] != 0xFF:
            break
        marker = head[1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker == 0xD9:
            return Found(pos + 2 - off, "jpg", True, taken) if seen_scan else None
        if marker not in JPEG_SEGMENTS or len(head) < 4:
            break
        length = struct.unpack_from(">H", head, 2)[0]
        if length < 2:
            break
        if marker == 0xE1 and taken is None:
            taken = exif_date(src.read(pos + 4, length - 2))
        seen_frame = seen_frame or marker in JPEG_FRAMES
        pos += 2 + length
        if marker == 0xDA:
            if not seen_frame:
                return None
            seen_scan = True
            marker_at = next_jpeg_marker(src, pos, limit)
            if marker_at is None:
                break
            pos = marker_at
    if seen_scan:
        return Found(pos - off, "jpg", False, taken, skip=False)
    return None


# ---------------------------------------------------------------- other images

def measure_png(src: Source, off: int) -> Found | None:
    pos, limit, first = off + 8, off + MAX_IMAGE, True
    while pos < limit:
        head = src.read(pos, 8)
        if len(head) < 8:
            return None
        length, kind = struct.unpack(">I4s", head)
        if not kind.isalpha() or length > MAX_IMAGE or (first and kind != b"IHDR"):
            return None
        first = False
        pos += 12 + length
        if kind == b"IEND":
            return Found(pos - off, "png")
    return None


def skip_gif_blocks(src: Source, pos: int, limit: int) -> int | None:
    while pos < limit:
        size = src.read(pos, 1)
        if not size:
            return None
        pos += 1 + size[0]
        if size[0] == 0:
            return pos
    return None


def measure_gif(src: Source, off: int) -> Found | None:
    head = src.read(off, 13)
    if len(head) < 13 or head[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height, flags = struct.unpack_from("<HHB", head, 6)
    if not width or not height:
        return None
    pos, limit, frames = off + 13, off + MAX_IMAGE, 0
    if flags & 0x80:
        pos += 3 << ((flags & 7) + 1)
    while pos is not None and pos < limit:
        kind = src.read(pos, 1)
        if kind == b";":
            return Found(pos + 1 - off, "gif") if frames else None
        if kind == b"!":
            pos = skip_gif_blocks(src, pos + 2, limit)
        elif kind == b",":
            desc = src.read(pos, 10)
            if len(desc) < 10:
                return None
            pos += 10
            if desc[9] & 0x80:
                pos += 3 << ((desc[9] & 7) + 1)
            pos = skip_gif_blocks(src, pos + 1, limit)
            frames += 1
        else:
            return None
    return None


def measure_bmp(src: Source, off: int) -> Found | None:
    head = src.read(off, 54)
    if len(head) < 54:
        return None
    size, reserved, data_at, dib = struct.unpack_from("<IIII", head, 2)
    if reserved or dib not in (40, 52, 56, 108, 124):
        return None
    width, height, planes, bpp, compression = struct.unpack_from("<iiHHI", head, 18)
    if planes != 1 or bpp not in (1, 4, 8, 16, 24, 32) or not 0 < width <= 30000 or not 0 < abs(height) <= 30000:
        return None
    if not 14 + dib <= data_at < size <= MAX_IMAGE:
        return None
    if compression in (0, 3):
        expected = data_at + (width * bpp + 31) // 32 * 4 * abs(height)
        if not expected <= size <= expected + 4:
            return None
        return Found(size, "bmp")
    if compression in (1, 2):
        return Found(size, "bmp", skip=False)
    return None


# ---------------------------------------------------------------- RIFF / ISO media

RIFF_KINDS = {b"AVI ": "avi", b"WAVE": "wav", b"WEBP": "webp"}


def walk_riff(src: Source, pos: int, end: int) -> bool:
    for _ in range(100_000):
        if pos >= end:
            return pos <= end + 1
        head = src.read(pos, 8)
        if len(head) < 8 or not printable(head[:4]):
            return False
        size = struct.unpack_from("<I", head, 4)[0]
        pos += 8 + size + (size & 1)
    return False


def measure_riff(src: Source, off: int) -> Found | None:
    head = src.read(off, 12)
    if len(head) < 12:
        return None
    size, form = struct.unpack_from("<I4s", head, 4)
    ext = RIFF_KINDS.get(form)
    if not ext or size < 12 or not walk_riff(src, off + 12, off + 8 + size):
        return None
    end = off + 8 + size + (size & 1)
    while form == b"AVI ":
        more = src.read(end, 12)
        if len(more) < 12 or more[:4] != b"RIFF" or more[8:12] != b"AVIX":
            break
        extra = struct.unpack_from("<I", more, 4)[0]
        if not walk_riff(src, end + 12, end + 8 + extra):
            break
        end += 8 + extra + (extra & 1)
    if end - off > MAX_VIDEO:
        return None
    return Found(end - off, ext)


BMFF_KNOWN = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"uuid", b"meta", b"pdin", b"moof",
              b"mfra", b"styp", b"sidx", b"prft", b"pnot", b"junk", b"udta", b"PICT", b"emsg", b"ssix"}
HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"}


def bmff_ext(brand: bytes) -> str:
    if brand == b"qt  ":
        return "mov"
    if brand.startswith(b"3g"):
        return "3gp"
    if brand in HEIF_BRANDS:
        return "heic"
    if brand in (b"avif", b"avis"):
        return "avif"
    if brand in (b"M4A ", b"M4B "):
        return "m4a"
    if brand == b"M4V ":
        return "m4v"
    return "mp4"


def mac_date(seconds: int) -> datetime | None:
    if not seconds:
        return None
    try:
        moment = datetime(1904, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
        return plausible(moment.astimezone().replace(tzinfo=None))
    except (OverflowError, ValueError, OSError):
        return None


def mvhd_date(src: Source, moov_at: int, moov_size: int) -> datetime | None:
    data = src.read(moov_at + 8, min(moov_size - 8, 4096))
    at = 0
    try:
        while at + 8 <= len(data):
            size, kind = struct.unpack_from(">I4s", data, at)
            if kind == b"mvhd":
                if data[at + 8] == 1:
                    return mac_date(struct.unpack_from(">Q", data, at + 12)[0])
                return mac_date(struct.unpack_from(">I", data, at + 12)[0])
            if size < 8:
                return None
            at += size
    except (struct.error, IndexError):
        return None
    return None


def measure_bmff(src: Source, off: int) -> Found | None:
    head = src.read(off, 12)
    if len(head) < 12:
        return None
    if not 16 <= struct.unpack_from(">I", head)[0] <= 1024 or not printable(head[8:12]):
        return None
    ext = bmff_ext(head[8:12])
    pos, end, limit = off, off, off + MAX_VIDEO
    seen: set[bytes] = set()
    taken = None
    while pos < limit:
        box = src.read(pos, 16)
        if len(box) < 8:
            break
        size, kind = struct.unpack_from(">I4s", box)
        if not printable(kind):
            break
        if size == 1:
            if len(box) < 16:
                break
            size = struct.unpack_from(">Q", box, 8)[0]
            if size < 16:
                break
        elif size < 8:
            break
        if pos + size > limit:
            break
        if kind == b"moov" and taken is None:
            taken = mvhd_date(src, pos, size)
        pos += size
        if kind in BMFF_KNOWN:
            seen.add(kind)
            end = pos
    need = {b"meta"} if ext in ("heic", "avif") else {b"moov", b"mdat"}
    if b"ftyp" not in seen or not need <= seen:
        return None
    return Found(end - off, ext, True, taken)


# ---------------------------------------------------------------- documents

PDF_MORE = re.compile(rb"\s*(\d+\s+\d+\s+obj|xref|startxref)")
PDF_DATE = re.compile(rb"/CreationDate\s*\(D:(\d{8})(\d{6})?")


def measure_pdf(src: Source, off: int) -> Found | None:
    head = src.read(off, 65536)
    if not re.match(rb"%PDF-\d\.\d", head):
        return None
    taken = None
    stamp = PDF_DATE.search(head)
    if stamp:
        taken = parse_stamp(stamp.group(1) + (stamp.group(2) or b"000000"), "%Y%m%d%H%M%S")
    pos, limit = off, off + MAX_SEARCH
    while pos < limit:
        window = src.read(pos, BLOCK + 5)
        if len(window) < 6:
            return None
        at = window.find(b"%%EOF")
        if at < 0:
            pos += len(window) - 5
            continue
        end = pos + at + 5
        tail = src.read(end, 2)
        if tail.startswith(b"\r\n"):
            end += 2
        elif tail[:1] in (b"\r", b"\n"):
            end += 1
        if PDF_MORE.match(src.read(end, 64)):
            pos = end
            continue
        return Found(end - off, "pdf", True, taken, skip=False)
    return None


def dos_date(day: int, clock: int) -> datetime | None:
    try:
        stamp = datetime(1980 + (day >> 9), (day >> 5) & 15, day & 31,
                         clock >> 11, (clock >> 5) & 63, min((clock & 31) * 2, 59))
    except ValueError:
        return None
    return plausible(stamp) if stamp.year > 1980 else None


def zip_end(src: Source, off: int, eocd: int) -> int | None:
    rec = src.read(eocd, 22)
    if len(rec) < 22:
        return None
    this_disk, cd_disk, n_here, n_total, cd_size, cd_offset, comment = struct.unpack_from("<HHHHIIH", rec, 4)
    if 0xFFFFFFFF in (cd_size, cd_offset) or n_total == 0xFFFF:
        locator = src.read(eocd - 20, 20)
        if len(locator) < 20 or locator[:4] != b"PK\x06\x07":
            return None
        z64 = struct.unpack_from("<Q", locator, 8)[0]
        record = src.read(off + z64, 56)
        if len(record) < 56 or record[:4] != b"PK\x06\x06":
            return None
        cd_size, cd_offset = struct.unpack_from("<QQ", record, 40)
        if cd_offset + cd_size != z64:
            return None
    elif this_disk or cd_disk or n_here != n_total or cd_offset + cd_size != eocd - off:
        return None
    if n_total and src.read(off + cd_offset, 4) != b"PK\x01\x02":
        return None
    return eocd + 22 + comment


def zip_kind(src: Source, off: int, end: int, first_name: bytes, first_data: int) -> str:
    names = src.read(max(off, end - 4 * MB), min(end - off, 4 * MB))
    if b"word/document" in names:
        return "docx"
    if b"xl/workbook" in names:
        return "xlsx"
    if b"ppt/presentation" in names:
        return "pptx"
    if first_name == b"mimetype":
        mime = src.read(first_data, 64)
        for needle, ext in ((b"opendocument.text", "odt"), (b"opendocument.spreadsheet", "ods"),
                            (b"opendocument.presentation", "odp"), (b"epub+zip", "epub")):
            if needle in mime:
                return ext
    if b"AndroidManifest.xml" in names:
        return "apk"
    if b"META-INF/MANIFEST.MF" in names:
        return "jar"
    return "zip"


def measure_zip(src: Source, off: int) -> Found | None:
    head = src.read(off, 30)
    if len(head) < 30:
        return None
    version, _, method, clock, day = struct.unpack_from("<HHHHH", head, 4)
    name_len, extra_len = struct.unpack_from("<HH", head, 26)
    if version > 100 or method not in (0, 1, 6, 8, 9, 12, 14, 93, 95, 98, 99) or not 0 < name_len <= 1024:
        return None
    first_name = src.read(off + 30, name_len)
    pos, limit = off, off + MAX_SEARCH
    while pos < limit:
        window = src.read(pos, BLOCK + 22)
        at = window.find(b"PK\x05\x06")
        while at >= 0:
            end = zip_end(src, off, pos + at)
            if end:
                kind = zip_kind(src, off, end, first_name, off + 30 + name_len + extra_len)
                return Found(end - off, kind, True, dos_date(day, clock))
            at = window.find(b"PK\x05\x06", at + 1)
        if len(window) < BLOCK + 22:
            return None
        pos += BLOCK
    return None


OLE_FREE, OLE_FAT = 0xFFFFFFFF, 0xFFFFFFFD
OLE_LAST_REGULAR = 0xFFFFFFFA


def ole_kind(src: Source, off: int, sector: int, fat: list[int], first_dir: int) -> str:
    names: list[str] = []
    sid, hops = first_dir, 0
    while sid < len(fat) and hops < 64:
        block = src.read(off + (sid + 1) * sector, sector)
        for at in range(0, len(block) - 127, 128):
            n = struct.unpack_from("<H", block, at + 64)[0]
            if 2 <= n <= 64:
                names.append(block[at:at + n - 2].decode("utf-16-le", "replace"))
        sid, hops = fat[sid], hops + 1
    if "WordDocument" in names:
        return "doc"
    if "Workbook" in names or "Book" in names:
        return "xls"
    if "PowerPoint Document" in names:
        return "ppt"
    if any(name.startswith(("__substg1.0_", "__properties_version1.0")) for name in names):
        return "msg"
    if "VisioDocument" in names:
        return "vsd"
    return "ole"


def measure_ole(src: Source, off: int) -> Found | None:
    head = src.read(off, 512)
    if len(head) < 512:
        return None
    major, order, shift = struct.unpack_from("<HHH", head, 0x1A)
    if order != 0xFFFE or (major, shift) not in ((3, 9), (4, 12)):
        return None
    sector = 1 << shift
    per = sector // 4
    n_fat, first_dir = struct.unpack_from("<II", head, 0x2C)
    first_difat, n_difat = struct.unpack_from("<II", head, 0x44)
    if not 0 < n_fat <= MAX_DOCUMENT // (sector * per) + 1:
        return None
    fat_ids = [sid for sid in struct.unpack_from("<109I", head, 0x4C) if sid < OLE_LAST_REGULAR]
    sid = first_difat
    for _ in range(min(n_difat, 4096)):
        if sid >= OLE_LAST_REGULAR:
            break
        block = src.read(off + (sid + 1) * sector, sector)
        if len(block) < sector:
            return None
        ids = struct.unpack(f"<{per}I", block)
        fat_ids += [x for x in ids[:-1] if x < OLE_LAST_REGULAR]
        sid = ids[-1]
    if len(fat_ids) < n_fat:
        return None
    fat_ids = fat_ids[:n_fat]
    fat: list[int] = []
    for fid in fat_ids:
        if (fid + 2) * sector > MAX_DOCUMENT:
            return None
        block = src.read(off + (fid + 1) * sector, sector)
        if len(block) < sector:
            return None
        fat.extend(struct.unpack(f"<{per}I", block))
    if any(fat[fid] != OLE_FAT for fid in fat_ids if fid < len(fat)) or max(fat_ids) >= len(fat):
        return None
    used = max((i for i, value in enumerate(fat) if value != OLE_FREE), default=-1)
    if used < first_dir:
        return None
    return Found((used + 2) * sector, ole_kind(src, off, sector, fat, first_dir))


# ---------------------------------------------------------------- scanning

SIGNATURES: tuple[tuple[int, bytes, Callable[[Source, int], Found | None]], ...] = (
    (0, b"\xff\xd8\xff", measure_jpeg),
    (0, b"\x89PNG\r\n\x1a\n", measure_png),
    (0, b"GIF8", measure_gif),
    (0, b"BM", measure_bmp),
    (0, b"RIFF", measure_riff),
    (4, b"ftyp", measure_bmff),
    (0, b"%PDF-", measure_pdf),
    (0, b"PK\x03\x04", measure_zip),
    (0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", measure_ole),
)
MFT_MAGIC = b"FILE0"


def aligned_hits(buf: bytes, magic: bytes, shift: int, span: int) -> list[int]:
    """Vị trí (tính từ đầu buf) mà magic nằm ở đúng đầu sector, trong khoảng [0, span)."""
    hits = []
    at = buf.find(magic, shift)
    while at >= 0:
        start = at - shift
        if start >= span:
            break
        if start % SECTOR == 0:
            hits.append(start)
        at = buf.find(magic, (start // SECTOR + 1) * SECTOR + shift)
    return hits


def find_headers(buf: bytes, base: int, stop: int) -> list[tuple[int, Callable[[Source, int], Found | None]]]:
    found = [(base + start, measure)
             for shift, magic, measure in SIGNATURES
             for start in aligned_hits(buf, magic, shift, stop - base)]
    found.sort(key=lambda hit: hit[0])
    return found


def parse_types(text: str) -> set[str]:
    if text.strip().lower() in ("", "all", "tatca"):
        return set(GROUP_OF)
    wanted: set[str] = set()
    for item in text.lower().replace(" ", "").split(","):
        if item in GROUPS:
            wanted |= set(GROUPS[item])
        elif item in GROUP_OF:
            wanted.add(item)
        elif item:
            raise ValueError(f"Không biết loại '{item}'. Dùng nhóm {', '.join(GROUPS)} hoặc đuôi như jpg, mp4.")
    return wanted
