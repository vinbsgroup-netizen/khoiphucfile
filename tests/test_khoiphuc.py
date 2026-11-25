import csv
import io
import json
import os
import random
import struct
import sys
import tempfile
import unittest
import wave
import zipfile
import zlib
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khoiphucfile import cli, disks, formats, scanner, session, source  # noqa: E402

SECTOR = source.SECTOR


def jpeg_bytes(original="2019:05:12 14:33:21", progressive=False, entropy_size=3000, seed=3):
    """JPEG đúng cấu trúc: EXIF có ảnh thu nhỏ bên trong, SOF0, DHT, SOS, dữ liệu nén có FF00 và RST."""
    rng = random.Random(seed)
    ifd0_at, exif_at, text_at = 8, 38, 56
    tiff = b"II*\0" + struct.pack("<I", ifd0_at)
    tiff += struct.pack("<H", 2) + struct.pack("<HHII", 0x0132, 2, 20, text_at)
    tiff += struct.pack("<HHII", 0x8769, 4, 1, exif_at) + struct.pack("<I", 0)
    tiff += struct.pack("<H", 1) + struct.pack("<HHII", 0x9003, 2, 20, text_at + 20) + struct.pack("<I", 0)
    tiff += b"2000:01:01 00:00:00\0" + original.encode() + b"\0"
    thumbnail = b"\xff\xd8\xff\xdb\x00\x04\x01\x02\xff\xd9"
    app1 = b"Exif\0\0" + tiff + thumbnail

    def segment(marker, payload):
        return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload

    def entropy():
        data = bytearray()
        while len(data) < entropy_size:
            byte = rng.randrange(256)
            data.append(byte)
            if byte == 0xFF:
                data.append(0x00)
        return bytes(data) + b"\xff\xd0" + bytes(rng.randrange(255) for _ in range(40))

    out = b"\xff\xd8" + segment(0xE1, app1) + segment(0xDB, b"\x00" + bytes(range(64)))
    out += segment(0xC0, b"\x08\x00\x10\x00\x10\x03" + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01")
    out += segment(0xC4, b"\x00" + bytes(16) + b"")
    scan = segment(0xDA, b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00")
    out += scan + entropy()
    if progressive:
        out += segment(0xC4, b"\x10" + bytes(16)) + scan + entropy()
    return out + b"\xff\xd9"


def png_bytes(width=3, height=2):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
       b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")


def bmp_bytes(width=3, height=2):
    row = (width * 24 + 31) // 32 * 4
    pixels = bytes(row * height)
    size = 54 + len(pixels)
    return (b"BM" + struct.pack("<IHHI", size, 0, 0, 54)
            + struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0) + pixels)


def wav_bytes():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(bytes(range(256)) * 20)
    return buf.getvalue()


def box(kind, payload):
    return struct.pack(">I", 8 + len(payload)) + kind + payload


MP4_MOMENT = datetime(2020, 3, 4, 5, 6, 7, tzinfo=timezone.utc)


def mp4_bytes(brand=b"isom"):
    seconds = int((MP4_MOMENT - datetime(1904, 1, 1, tzinfo=timezone.utc)).total_seconds())
    mvhd = box(b"mvhd", b"\0\0\0\0" + struct.pack(">II", seconds, seconds) + bytes(88))
    return (box(b"ftyp", brand + b"\0\0\2\0" + b"isomiso2mp41") + box(b"moov", mvhd)
            + box(b"free", bytes(8)) + box(b"mdat", bytes(range(256)) * 30))


def docx_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr(zipfile.ZipInfo("[Content_Types].xml", (2018, 6, 7, 8, 9, 10)), "<Types/>" * 50)
        out.writestr("word/document.xml", "<w:document>xin chao</w:document>" * 100)
    return buf.getvalue()


def zip_with_aligned_png():
    """Zip có ảnh PNG lưu không nén, bắt đầu đúng byte 512 của file zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as out:
        out.writestr("a" * (SECTOR - 30), png_bytes(9, 9))
    data = buf.getvalue()
    assert data[SECTOR:SECTOR + 8] == b"\x89PNG\r\n\x1a\n"
    return data


PDF = (b"%PDF-1.4\n1 0 obj\n<< /CreationDate (D:20180102030405+07'00') >>\nendobj\ntrailer\n<<>>\n%%EOF\n"
       b"2 0 obj\n<<>>\nendobj\nxref\n0 1\ntrailer\n<<>>\nstartxref\n0\n%%EOF\n")


def ole_bytes(stream="WordDocument"):
    header = bytearray(512)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHHHH", header, 0x18, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<II", header, 0x2C, 1, 1)
    struct.pack_into("<IIII", header, 0x38, 4096, 0xFFFFFFFE, 0, 0xFFFFFFFE)
    struct.pack_into("<I", header, 0x48, 0)
    struct.pack_into("<109I", header, 0x4C, 0, *([0xFFFFFFFF] * 108))
    fat = [0xFFFFFFFD, 0xFFFFFFFE, 3, 0xFFFFFFFE] + [0xFFFFFFFF] * 124
    directory = bytearray(512)
    for at, name, kind, start, size in ((0, "Root Entry", 5, 0xFFFFFFFE, 0), (128, stream, 2, 2, 1000)):
        raw = name.encode("utf-16-le") + b"\0\0"
        directory[at:at + len(raw)] = raw
        struct.pack_into("<H", directory, at + 64, len(raw))
        directory[at + 66] = kind
        struct.pack_into("<II", directory, at + 116, start, size)
    return bytes(header) + struct.pack("<128I", *fat) + bytes(directory) + bytes(range(256)) * 4


def memory_source(data, tail=65536, seed=9):
    blob = data + random.Random(seed).randbytes(tail)
    return source.Source("memory", fileobj=io.BytesIO(blob), size=len(blob))


class MeasureTest(unittest.TestCase):
    def check(self, measure, data, ext):
        found = measure(memory_source(data), 0)
        self.assertIsNotNone(found, ext)
        self.assertEqual((found.size, found.ext, found.complete), (len(data), ext, True))
        return found

    def test_each_format_is_measured_to_its_last_byte(self):
        self.check(formats.measure_png, png_bytes(), "png")
        self.check(formats.measure_gif, GIF, "gif")
        self.check(formats.measure_bmp, bmp_bytes(), "bmp")
        self.check(formats.measure_riff, wav_bytes(), "wav")
        self.check(formats.measure_bmff, mp4_bytes(b"qt  "), "mov")
        self.check(formats.measure_bmff, mp4_bytes(b"3gp4"), "3gp")
        self.check(formats.measure_zip, docx_bytes(), "docx")
        self.check(formats.measure_ole, ole_bytes(), "doc")
        self.check(formats.measure_ole, ole_bytes("__substg1.0_0037001F"), "msg")

    def test_jpeg_ends_at_its_own_eoi_and_reads_the_original_date(self):
        found = self.check(formats.measure_jpeg, jpeg_bytes(), "jpg")
        self.assertEqual(found.taken, datetime(2019, 5, 12, 14, 33, 21))
        self.check(formats.measure_jpeg, jpeg_bytes(progressive=True), "jpg")

    def test_mp4_date_comes_from_mvhd_in_local_time(self):
        found = self.check(formats.measure_bmff, mp4_bytes(), "mp4")
        self.assertEqual(found.taken, MP4_MOMENT.astimezone().replace(tzinfo=None))

    def test_pdf_keeps_incremental_updates_and_reads_its_date(self):
        found = self.check(formats.measure_pdf, PDF, "pdf")
        self.assertEqual(found.taken, datetime(2018, 1, 2, 3, 4, 5))

    def test_zip_date_is_the_first_entry_time(self):
        found = self.check(formats.measure_zip, docx_bytes(), "docx")
        self.assertEqual(found.taken, datetime(2018, 6, 7, 8, 9, 10))

    def test_video_without_moov_is_not_taken(self):
        data = box(b"ftyp", b"isom\0\0\2\0isom") + box(b"mdat", bytes(500))
        self.assertIsNone(formats.measure_bmff(memory_source(data), 0))

    def test_random_bytes_are_not_files(self):
        src = memory_source(b"", tail=1 << 20, seed=11)
        for _, _, measure in formats.SIGNATURES:
            for at in range(0, 1 << 20, 4096):
                found = measure(src, at)
                self.assertIsNone(found, f"{measure.__name__} @ {at}")


class SourceTest(unittest.TestCase):
    def test_reads_across_cached_blocks_match_the_raw_bytes(self):
        data = random.Random(2).randbytes(100_000)
        src = source.Source("small", fileobj=io.BytesIO(data), size=len(data), unit=8192, cache_blocks=3)
        for offset, length in ((0, 10), (8000, 500), (8191, 1), (5000, 40_000), (99_990, 50), (0, 100_000)):
            self.assertEqual(src.read(offset, length), data[offset:offset + length], (offset, length))
        self.assertLessEqual(len(src.cache), 3)

    def test_unreadable_block_becomes_zeros_and_is_counted(self):
        data = bytearray(random.Random(1).randbytes(3 * source.BLOCK))

        class Flaky(io.BytesIO):
            def read(self, n=-1):
                at = self.tell()
                if at < source.BLOCK + 8192 and at + n > source.BLOCK:
                    raise OSError(23, "CRC")
                return super().read(n)

        src = source.Source("flaky", fileobj=Flaky(bytes(data)), size=len(data))
        block = src.read(source.BLOCK, source.BLOCK)
        self.assertEqual(block[:8192], bytes(8192))
        self.assertEqual(block[8192:], bytes(data[source.BLOCK + 8192:2 * source.BLOCK]))
        self.assertEqual(src.bad_bytes, 8192)


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        self.image = os.path.join(self.tmp.name, "disk.img")

    def build(self, parts, size=24 << 20):
        blob = bytearray(random.Random(5).randbytes(size))
        for at, data in parts:
            blob[at:at + len(data)] = data
        with open(self.image, "wb") as handle:
            handle.write(blob)
        return parts

    def scan(self, *extra):
        with redirect_stdout(io.StringIO()) as printed:
            code = cli.main(["scan", self.image, "--out", self.out, *extra])
        return code, printed.getvalue()

    def report(self):
        with open(os.path.join(self.out, scanner.REPORT_FILE), encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    def saved(self, row):
        with open(os.path.join(self.out, row["file"]), "rb") as handle:
            return handle.read()

    def test_carves_every_file_with_exact_bytes_and_dated_names(self):
        parts = self.build([
            (1 * SECTOR * 100, jpeg_bytes()),
            (3 << 20, png_bytes()),
            ((5 << 20) + SECTOR * 7, mp4_bytes()),
            (7 << 20, docx_bytes()),
            ((9 << 20) + SECTOR, PDF),
            (11 << 20, ole_bytes("__substg1.0_0037001F")),
            ((13 << 20) - SECTOR, wav_bytes()),
            (15 << 20, GIF),
            (17 << 20, bmp_bytes()),
        ])
        code, _ = self.scan()
        self.assertEqual(code, 0)
        rows = sorted(self.report(), key=lambda row: int(row["vi_tri_byte"]))
        self.assertEqual([int(row["vi_tri_byte"]) for row in rows], [at for at, _ in parts])
        for row, (_, data) in zip(rows, parts):
            self.assertEqual(self.saved(row), data, row["file"])
        self.assertEqual(rows[0]["file"], os.path.join("anh", "jpg", "2019", f"2019-05-12_14-33-21_s100.jpg"))
        self.assertEqual(rows[3]["file"], os.path.join("tailieu", "docx", "2018", f"2018-06-07_08-09-10_s{(7 << 20) // SECTOR}.docx"))
        self.assertEqual(rows[5]["file"], os.path.join("tailieu", "msg", "khong_ro_ngay", f"s{(11 << 20) // SECTOR}.msg"))

    def test_broken_jpeg_keeps_its_top_part_and_the_next_photo_is_whole(self):
        first, second = jpeg_bytes(entropy_size=20000), jpeg_bytes("2021:01:02 03:04:05", seed=4)
        cut = 8 * SECTOR
        self.build([(1 << 20, first[:cut + 100]), ((1 << 20) + cut, second), ((1 << 20) + cut + len(second) + 64, bytes(8192))])
        self.scan()
        rows = sorted(self.report(), key=lambda row: int(row["vi_tri_byte"]))
        self.assertEqual([row["trang_thai"] for row in rows], ["khong tron ven", "tron ven"])
        self.assertTrue(rows[0]["file"].startswith(os.path.join("anh", "jpg_khong_tron_ven")))
        self.assertEqual(self.saved(rows[0]), first[:cut])
        self.assertEqual(self.saved(rows[1]), second)

    def test_headers_inside_a_carved_file_are_not_carved_again(self):
        data = zip_with_aligned_png()
        self.build([(2 << 20, data)])
        self.scan()
        self.assertEqual([row["loai"] for row in self.report()], ["zip"])

    def test_type_filter_skips_unwanted_files_but_still_jumps_over_them(self):
        self.build([(1 << 20, zip_with_aligned_png()), (4 << 20, jpeg_bytes())])
        self.scan("--types", "anh")
        self.assertEqual([row["loai"] for row in self.report()], ["jpg"])

    def test_interrupted_scan_resumes_where_it_stopped(self):
        parts = self.build([(1 << 20, jpeg_bytes()), (20 << 20, png_bytes())])
        original = scanner.Scanner.keep
        calls = {"n": 0}

        def keep_then_stop(self_, at, found):
            original(self_, at, found)
            calls["n"] += 1
            if calls["n"] == 1:
                raise KeyboardInterrupt

        with mock.patch.object(scanner.Scanner, "keep", keep_then_stop):
            code, _ = self.scan()
        self.assertEqual(code, 130)
        with open(os.path.join(self.out, scanner.STATE_FILE), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["position"], 0)
        code, printed = self.scan("--start-gb", "5")
        self.assertEqual(code, 0)
        self.assertIn("Tiếp tục", printed)
        offsets = sorted(int(row["vi_tri_byte"]) for row in self.report())
        self.assertEqual(offsets, [at for at, _ in parts])
        code, printed = self.scan()
        self.assertIn("Đã lưu 2 file", printed)

    def test_stops_before_filling_the_output_drive(self):
        self.build([(1 << 20, jpeg_bytes())])
        usage = mock.Mock(free=source.GB)
        with mock.patch.object(scanner.shutil, "disk_usage", return_value=usage):
            code, printed = self.scan()
        self.assertEqual(code, 3)
        self.assertIn("sắp đầy", printed)
        self.assertEqual(self.report(), [])

    def test_dry_run_writes_nothing(self):
        self.build([(1 << 20, jpeg_bytes())])
        code, printed = self.scan("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("ảnh 1", printed)
        self.assertFalse(os.path.exists(self.out))

    def test_ntfs_file_records_are_kept_for_later(self):
        record = b"FILE0" + bytes(1019)
        self.build([(3 << 20, record)])
        _, printed = self.scan()
        self.assertIn("1 bản ghi", printed)
        with open(os.path.join(self.out, scanner.MFT_FILE), "rb") as handle:
            saved = handle.read()
        self.assertEqual(struct.unpack_from("<Q", saved)[0], 3 << 20)
        self.assertEqual(saved[8:], record)

    def test_refuses_to_write_onto_the_disk_being_scanned(self):
        with mock.patch.object(disks, "resolve", return_value=("/dev/sdb", "sdb")),                 mock.patch.object(disks.backend, "disks_of_path", return_value={"sda", "sdb"}),                 mock.patch.object(disks.backend, "base_disks", return_value={"sdb"}),                 redirect_stdout(io.StringIO()) as printed:
            code = cli.main(["scan", "sdb", "--out", self.out])
        self.assertEqual(code, 2)
        self.assertIn("chính đĩa đang quét", printed.getvalue())


class TypesTest(unittest.TestCase):
    def test_groups_and_extensions(self):
        self.assertEqual(formats.parse_types("video,pdf"), set(formats.GROUPS["video"]) | {"pdf"})
        self.assertEqual(formats.parse_types("all"), set(formats.GROUP_OF))
        with self.assertRaises(ValueError):
            formats.parse_types("anh,exe")


if __name__ == "__main__":
    unittest.main()
