"""Phần khác nhau giữa các hệ điều hành và các sự cố khi đọc/ghi ổ thật."""

import csv
import errno
import io
import os
import plistlib
import random
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khoiphucfile import cli, disks, formats, scanner, session, source  # noqa: E402
from khoiphucfile.disks import linux, macos, open_device, windows  # noqa: E402
from tests.test_khoiphuc import box, jpeg_bytes, png_bytes  # noqa: E402

MB = source.MB


class DeviceFile(io.BytesIO):
    """Ổ đĩa giả: vùng bad đọc là lỗi; kiểu Linux thì lần đọc trước đó trả về thiếu tới sát vùng hỏng."""

    def __init__(self, data, bad=range(0), unplug_after=None):
        super().__init__(data)
        self.bad = bad
        self.unplug_after = unplug_after
        self.reads = 0

    def read(self, n=-1):
        self.reads += 1
        if self.unplug_after is not None and self.reads > self.unplug_after:
            raise OSError(errno.EIO, "I/O error")
        at = self.tell()
        if self.bad and at < self.bad.stop and at + n > self.bad.start:
            if at >= self.bad.start:
                raise OSError(errno.EIO, "I/O error")
            return super().read(self.bad.start - at)
        return super().read(n)


class ReadTest(unittest.TestCase):
    def test_short_reads_before_a_bad_sector_lose_only_that_sector(self):
        data = random.Random(1).randbytes(3 * MB)
        bad = range(MB + 8192, MB + 12288)
        src = source.Source("linux", fileobj=DeviceFile(data, bad), size=len(data))
        expected = data[:bad.start] + bytes(4096) + data[bad.stop:]
        self.assertEqual(src.read(0, len(data)), expected)
        self.assertEqual(src.bad_bytes, 4096)

    def test_a_dead_area_is_zeroed_while_the_rest_of_the_disk_still_answers(self):
        unit = 256 << 10
        data = random.Random(2).randbytes(4 * unit)
        src = source.Source("area", fileobj=DeviceFile(data, range(unit, 2 * unit)), size=len(data), unit=unit)
        self.assertEqual(src.read(0, len(data)), data[:unit] + bytes(unit) + data[2 * unit:])
        self.assertEqual(src.bad_bytes, unit)

    def test_a_disk_that_stops_answering_is_reported_as_lost(self):
        unit = 256 << 10
        data = random.Random(3).randbytes(4 * unit)
        src = source.Source("gone", fileobj=DeviceFile(data, unplug_after=1), size=len(data), unit=unit)
        src.read(0, unit)
        with self.assertRaises(source.SourceLost):
            src.read(unit, unit)
        self.assertEqual(src.bad_bytes, 0)

    def test_cancel_stops_at_the_next_read(self):
        src = source.Source("cancel", fileobj=io.BytesIO(bytes(MB)), size=MB)
        src.cancel()
        with self.assertRaises(source.Stopped):
            src.read(0, 10)


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        self.parts = [(MB, jpeg_bytes()), (40 * MB, png_bytes()), (70 * MB, jpeg_bytes("2021:01:02 03:04:05", seed=4))]
        blob = bytearray(80 * MB)
        for at, data in self.parts:
            blob[at:at + len(data)] = data
        self.blob = bytes(blob)

    def open(self, model="USB DISK", size=None, **device):
        src = source.Source("ổ giả", fileobj=DeviceFile(self.blob, **device), size=size or len(self.blob))
        for target, value in (("resolve", ("ổ giả", "9")), ("output_on_disk", False), ("open_source", src),
                              ("model_of", model)):
            patch = mock.patch.object(disks, target, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        return session.Session(session.Options("9", self.out))

    def offsets(self):
        return sorted(row[2] for row in scanner.load_report(self.out))

    def test_unplugging_keeps_the_place_and_the_scan_finishes_after_replugging(self):
        outcome = self.open(unplug_after=1).run()
        self.assertEqual(outcome.kind, session.LOST)
        self.assertEqual(self.offsets(), [MB])
        resumed = self.open()
        self.assertTrue(resumed.resumed)
        self.assertEqual(resumed.run().kind, session.DONE)
        self.assertEqual(self.offsets(), [at for at, _ in self.parts])

    def test_stop_from_another_thread_then_resume(self):
        first = self.open()
        outcome = first.run(on_rows=lambda rows: first.cancel())
        self.assertEqual(outcome.kind, session.STOPPED)
        live = []
        second = self.open()
        self.assertEqual(second.run(on_rows=live.extend).kind, session.DONE)
        self.assertEqual(self.offsets(), [at for at, _ in self.parts])
        self.assertEqual([row[2] for row in live], [at for at, _ in self.parts[1:]])

    def test_progress_reaches_the_end(self):
        seen = []
        self.open().run(on_progress=seen.append, interval=0)
        self.assertEqual(seen[-1].share, 1.0)
        self.assertEqual(seen[-1].counts["anh"], 3)
        self.assertEqual(sorted(item.position for item in seen), [item.position for item in seen])

    def test_another_disk_with_the_same_size_cannot_continue_the_old_scan(self):
        self.open(unplug_after=1).run()
        with self.assertRaises(session.Refused):
            self.open(model="DISK KHAC")

    def test_interrupted_copy_leaves_no_half_file(self):
        current = self.open()
        original = source.Source.copy_to

        def copy_then_cancel(src, offset, size, path):
            original(src, offset, size // 2, path)
            raise source.Stopped

        with mock.patch.object(source.Source, "copy_to", copy_then_cancel):
            self.assertEqual(current.run().kind, session.STOPPED)
        left = [name for _, _, names in os.walk(self.out) for name in names]
        self.assertEqual(sorted(left), sorted([scanner.REPORT_FILE, scanner.STATE_FILE]))

    def test_file_too_big_for_the_output_drive_is_skipped_and_listed(self):
        current = self.open()
        original = source.Source.copy_to

        def fat32(src, offset, size, path):
            if offset == MB:
                raise OSError(errno.ENOSPC, "No space left on device")
            original(src, offset, size, path)

        with mock.patch.object(source.Source, "copy_to", fat32), \
                mock.patch.object(scanner.shutil, "disk_usage", return_value=mock.Mock(free=100 * source.GB)):
            self.assertEqual(current.run().kind, session.DONE)
        statuses = {row[2]: row[5] for row in scanner.load_report(self.out)}
        self.assertEqual(statuses, {MB: scanner.FAILED, 40 * MB: scanner.WHOLE, 70 * MB: scanner.WHOLE})
        self.assertEqual((current.scanner.saved, current.scanner.failed), (2, 1))

    def test_losing_the_output_drive_stops_instead_of_crashing(self):
        current = self.open()
        with mock.patch.object(source.Source, "copy_to", side_effect=OSError(errno.ENODEV, "gone")):
            self.assertEqual(current.run().kind, session.WRITE_ERROR)

    def test_a_parser_crash_on_damaged_data_skips_that_file_only(self):
        def broken(src, off):
            raise struct.error("unpack requires a buffer")

        with mock.patch.object(scanner, "find_headers", lambda buf, base, stop: [
                (at, broken if at == MB else measure) for at, measure in formats.find_headers(buf, base, stop)]):
            self.assertEqual(self.open().run().kind, session.DONE)
        self.assertEqual(self.offsets(), [40 * MB, 70 * MB])

    def test_empty_range_is_refused(self):
        self.open()
        with self.assertRaises(session.Refused):
            session.Session(session.Options("9", self.out, start=200 * MB))


class ReportTest(unittest.TestCase):
    def test_report_rows_come_back_typed_and_a_torn_last_line_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, scanner.REPORT_FILE), "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(scanner.REPORT_COLUMNS)
                writer.writerow(["anh\\jpg\\2019\\a.jpg", "jpg", 512, 100, "2019-05-12 14:33:21", "tron ven"])
                handle.write("anh\\jpg\\2019\\b.jpg,jpg,10")
            rows = scanner.load_report(folder)
        self.assertEqual(rows, [[os.path.join("anh", "jpg", "2019", "a.jpg"), "jpg", 512, 100,
                                 "2019-05-12 14:33:21", "tron ven"]])

    def test_missing_report_is_empty(self):
        self.assertEqual(scanner.load_report(os.path.join(tempfile.gettempdir(), "khong-co-thu-muc-nay")), [])


LSBLK = {"blockdevices": [
    {"name": "loop0", "kname": "loop0", "path": "/dev/loop0", "size": 4096, "model": None, "vendor": None,
     "tran": None, "type": "loop", "mountpoint": "/snap/core"},
    {"name": "sda", "kname": "sda", "path": "/dev/sda", "size": "160041885696", "model": "HM160HI ",
     "vendor": "SAMSUNG ", "tran": "usb", "type": "disk", "mountpoint": None, "children": [
         {"name": "sda1", "kname": "sda1", "path": "/dev/sda1", "size": 1, "type": "part", "mountpoint": "/media/usb"}]},
    {"name": "sr0", "kname": "sr0", "path": "/dev/sr0", "size": 1073741312, "type": "rom", "mountpoint": None},
    {"name": "zram0", "kname": "zram0", "path": "/dev/zram0", "size": 8589934592, "type": "disk", "mountpoint": "[SWAP]"},
    {"name": "nvme0n1", "kname": "nvme0n1", "path": "/dev/nvme0n1", "size": 512110190592, "model": "SSD", "vendor": None,
     "tran": "nvme", "type": "disk", "mountpoint": None, "children": [
         {"name": "nvme0n1p2", "kname": "nvme0n1p2", "type": "part", "mountpoint": None, "children": [
             {"name": "root", "kname": "dm-0", "type": "crypt", "mountpoint": "/"}]}]},
]}
LSBLK_UP = {
    "/dev/dm-0": {"blockdevices": [{"kname": "dm-0", "type": "crypt", "children": [
        {"kname": "nvme0n1p2", "type": "part", "children": [{"kname": "nvme0n1", "type": "disk"}]}]}]},
    "/dev/sda": {"blockdevices": [{"kname": "sda", "type": "disk"}]},
    "/dev/sda1": {"blockdevices": [{"kname": "sda1", "type": "part", "children": [{"kname": "sda", "type": "disk"}]}]},
    "/dev/md0": {"blockdevices": [{"kname": "md0", "type": "raid1", "children": [
        {"kname": "sdb", "type": "disk"}, {"kname": "sdc", "type": "disk"}]}]},
}


class LinuxTest(unittest.TestCase):
    def setUp(self):
        self.mounted = {"filesystems": []}

        def run_json(command):
            if command[0] == "findmnt":
                return self.mounted
            return LSBLK_UP.get(command[-1], {}) if "-s" in command else LSBLK

        for target, replacement in (("run_json", run_json),):
            patch = mock.patch.object(linux, target, replacement)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(linux.os.path, "realpath", lambda path: {"/dev/mapper/root": "/dev/dm-0"}.get(path, path))
        patch.start()
        self.addCleanup(patch.stop)

    def test_lists_real_disks_with_their_mounts(self):
        found = linux.list_disks()
        self.assertEqual([(d.id, d.size, d.model, d.bus, d.mounts, d.system) for d in found], [
            ("sda", 160041885696, "SAMSUNG HM160HI", "USB", ["/media/usb"], False),
            ("nvme0n1", 512110190592, "SSD", "NVMe", ["/"], True)])

    def test_output_folder_is_traced_through_encryption_and_raid(self):
        self.mounted = {"filesystems": [{"source": "/dev/mapper/root[/home]", "fstype": "btrfs"}]}
        self.assertEqual(linux.disks_of_path("/home/a"), {"nvme0n1"})
        self.mounted = {"filesystems": [{"source": "/dev/md0", "fstype": "ext4"}]}
        self.assertEqual(linux.disks_of_path("/data"), {"sdb", "sdc"})

    def test_network_and_unknown_filesystems(self):
        self.mounted = {"filesystems": [{"source": "nas:/share", "fstype": "nfs4"}]}
        self.assertEqual(linux.disks_of_path("/mnt/nas"), set())
        self.mounted = {"filesystems": [{"source": "tank/data", "fstype": "zfs"}]}
        self.assertIsNone(linux.disks_of_path("/tank"))
        self.mounted = {}
        self.assertIsNone(linux.disks_of_path("/x"))

    def test_saving_onto_a_partition_of_the_scanned_disk_is_refused(self):
        self.mounted = {"filesystems": [{"source": "/dev/sda1", "fstype": "exfat"}]}
        with mock.patch.object(disks, "backend", linux):
            self.assertTrue(disks.output_on_disk(tempfile.gettempdir(), "sda"))
            self.assertFalse(disks.output_on_disk(tempfile.gettempdir(), "nvme0n1"))


MAC_LIST = {"WholeDisks": ["disk0", "disk3", "disk4", "disk5"], "AllDisksAndPartitions": [
    {"DeviceIdentifier": "disk0", "Partitions": [{"DeviceIdentifier": "disk0s1"}, {"DeviceIdentifier": "disk0s2"}]},
    {"DeviceIdentifier": "disk3", "APFSPhysicalStores": [{"DeviceIdentifier": "disk0s2"}],
     "APFSVolumes": [{"DeviceIdentifier": "disk3s1", "MountPoint": "/System/Volumes/Data"},
                     {"DeviceIdentifier": "disk3s3", "MountPoint": "/"}]},
    {"DeviceIdentifier": "disk4", "Partitions": [{"DeviceIdentifier": "disk4s1", "MountPoint": "/Volumes/USB"}]},
    {"DeviceIdentifier": "disk5", "Partitions": [], "MountPoint": "/Volumes/Anh"}]}
MAC_INFO = {
    "disk0": {"Size": 500277790720, "MediaName": "APPLE SSD", "BusProtocol": "Apple Fabric", "VirtualOrPhysical": "Physical"},
    "disk3": {"Size": 494384795648, "MediaName": "", "BusProtocol": "Apple Fabric", "VirtualOrPhysical": "Virtual"},
    "disk4": {"Size": 160041885696, "MediaName": "HM160HI", "BusProtocol": "USB", "VirtualOrPhysical": "Physical"},
    "disk5": {"Size": 104857600, "MediaName": "Disk Image", "BusProtocol": "Disk Image", "VirtualOrPhysical": "Virtual"},
}


class MacTest(unittest.TestCase):
    def setUp(self):
        def run(command, **_):
            if command[0] == "/bin/df":
                return mock.Mock(returncode=0, stdout=self.df)
            data = MAC_LIST if command[1] == "list" else MAC_INFO[command[-1]]
            return mock.Mock(stdout=plistlib.dumps(data))

        patch = mock.patch.object(macos.subprocess, "run", run)
        patch.start()
        self.addCleanup(patch.stop)

    def test_lists_physical_disks_and_images_but_not_apfs_containers(self):
        self.assertEqual([(d.id, d.path, d.model, d.bus, d.mounts, d.system) for d in macos.list_disks()], [
            ("disk0", "/dev/rdisk0", "APPLE SSD", "Apple Fabric", ["/System/Volumes/Data", "/"], True),
            ("disk4", "/dev/rdisk4", "HM160HI", "USB", ["/Volumes/USB"], False),
            ("disk5", "/dev/rdisk5", "Disk Image", "Disk Image", ["/Volumes/Anh"], False)])

    def test_output_on_an_apfs_volume_is_traced_to_the_physical_disk(self):
        self.df = ("Filesystem 512-blocks Used Available Capacity Mounted on\n"
                   "/dev/disk3s1 965595304 1 1 1% /System/Volumes/Data\n")
        self.assertEqual(macos.disks_of_path("/Users/a"), {"disk0", "disk3"})
        self.df = "Filesystem 512-blocks Used Available Capacity Mounted on\n//a@nas/share 1 1 1 1% /Volumes/share\n"
        self.assertEqual(macos.disks_of_path("/Volumes/share"), set())

    def test_accepts_every_spelling_of_a_disk(self):
        for spec in ("disk4", "rdisk4", "/dev/disk4", "/dev/rdisk4"):
            self.assertEqual(macos.parse_spec(spec), "disk4")
        self.assertEqual(macos.base_disks("disk4s1"), {"disk4"})
        self.assertIsNone(macos.parse_spec("HM160HI"))


class WindowsTest(unittest.TestCase):
    def test_accepts_numbers_and_device_paths(self):
        self.assertEqual(windows.parse_spec("2"), "2")
        self.assertEqual(windows.parse_spec(r"\\.\physicaldrive11"), "11")
        self.assertIsNone(windows.parse_spec("HM160HI"))

    @unittest.skipUnless(sys.platform == "win32", "chỉ chạy trên Windows")
    def test_the_system_drive_maps_to_a_physical_disk(self):
        holders = windows.disks_of_path(os.environ["SystemDrive"] + "\\")
        self.assertTrue(holders and all(number.isdigit() for number in holders))
        self.assertEqual(windows.disks_of_path(r"\\server\share\folder"), set())


class FindAgainTest(unittest.TestCase):
    def test_replugged_disk_is_found_under_its_new_number(self):
        found = [disks.Disk("0", "p0", 500, "SSD"), disks.Disk("3", "p3", 160, "HM160HI"), disks.Disk("4", "p4", 160, "KHAC")]
        with mock.patch.object(disks, "list_disks", return_value=found):
            self.assertEqual(disks.find_again("p2", "HM160HI", 160).id, "3")
            self.assertIsNone(disks.find_again("p2", "HM160HI", 161))
            self.assertEqual(disks.find_again("p4", "", 160).id, "4")
            self.assertIsNone(disks.find_again("p9", "", 160))


@unittest.skipUnless(hasattr(socket, "send_fds") and hasattr(socket, "AF_UNIX"), "cần Unix socket")
class FdPassTest(unittest.TestCase):
    SEND = ("import os,socket,sys;fd=os.open(sys.argv[1],os.O_RDONLY);"
            "socket.send_fds(socket.socket(fileno=os.dup(1)),[b'1'],[fd])")

    def test_descriptor_opened_by_the_helper_is_usable_here(self):
        from khoiphucfile.disks.fdpass import open_through

        with tempfile.NamedTemporaryFile() as handle:
            handle.write(b"du lieu")
            handle.flush()
            fd = open_through([sys.executable, "-c", self.SEND, handle.name], "bị từ chối")
            with os.fdopen(fd, "rb") as received:
                self.assertEqual(received.read(), b"du lieu")

    def test_a_refused_helper_explains_why(self):
        from khoiphucfile.disks.fdpass import open_through

        with self.assertRaises(disks.AccessDenied) as caught:
            open_through([sys.executable, "-c", "import sys; sys.exit('Not authorized')"], "bị từ chối")
        self.assertIn("Not authorized", str(caught.exception))
        with self.assertRaises(disks.AccessDenied):
            open_through(["/khong/co/lenh/nay"], "bị từ chối")

    def test_helper_hands_over_block_devices_only(self):
        with tempfile.NamedTemporaryFile() as handle:
            done = subprocess.run([sys.executable, "-I", open_device.__file__, handle.name], capture_output=True)
            self.assertEqual(done.returncode, 2)
            self.assertTrue(stat.S_ISREG(os.stat(handle.name).st_mode))


class CliTest(unittest.TestCase):
    def test_unknown_type_and_unknown_disk_are_explained(self):
        for arguments in (["scan", "x.img", "--out", "o", "--types", "exe"], ["scan", "khong-co-dia-nay", "--out", "o"]):
            with redirect_stdout(io.StringIO()) as printed, mock.patch.object(disks, "list_disks", return_value=[]):
                self.assertEqual(cli.main(arguments), 2)
            self.assertIn("Không", printed.getvalue())

    def test_video_box_walk_survives_a_truncated_image(self):
        data = box(b"ftyp", b"isom\0\0\2\0isom")[:14]
        src = source.Source("cụt", fileobj=io.BytesIO(data), size=len(data))
        self.assertIsNone(formats.measure_bmff(src, 0))


if __name__ == "__main__":
    unittest.main()
