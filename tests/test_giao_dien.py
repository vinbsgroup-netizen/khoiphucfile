"""Giao diện chạy ngầm (offscreen): quét, dừng, quét tiếp, lọc kết quả, điều khoản."""

import os
import random
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QDialog, QMessageBox
except ImportError:
    raise unittest.SkipTest("chưa cài PySide6")

from khoiphucfile import developer, disks, scanner, session  # noqa: E402
from khoiphucfile.gui import about, app as gui_app, options_page, scan_page  # noqa: E402
from khoiphucfile.gui.common import Choice, human_duration, human_size, open_file  # noqa: E402
from khoiphucfile.gui.window import OPTIONS, SCAN, MainWindow  # noqa: E402
from tests.test_khoiphuc import PDF, jpeg_bytes, mp4_bytes, png_bytes  # noqa: E402

MB = 1 << 20
APP = None


def setUpModule():
    global APP
    APP = gui_app.build_app(["test"])


class GuiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, self.tmp.name)
        patch = mock.patch.object(disks, "list_disks", return_value=[])
        patch.start()
        self.addCleanup(patch.stop)
        self.image = os.path.join(self.tmp.name, "usb.img")
        self.out = os.path.join(self.tmp.name, "ra")
        makers = (png_bytes, lambda: jpeg_bytes(seed=7), lambda: PDF, mp4_bytes)
        self.parts = [((i + 1) * 4 * MB, makers[i % 4]()) for i in range(20)]
        blob = bytearray(random.Random(4).randbytes(MB)) * 96
        for at, data in self.parts:
            blob[at:at + len(data)] = data
        with open(self.image, "wb") as handle:
            handle.write(blob)

    def wait(self, condition, seconds=60):
        end = time.monotonic() + seconds
        while not condition():
            APP.processEvents()
            time.sleep(0.005)
            self.assertLess(time.monotonic(), end, "hết giờ chờ")

    def open_window(self):
        window = MainWindow()
        window.show()
        self.addCleanup(window.close)
        return window

    def choose(self, window):
        window._chosen(Choice(self.image, None, "ảnh đĩa", os.path.getsize(self.image)))
        window.options_page.out.setText(self.out)
        self.wait(window.options_page.start_button.isEnabled)

    def offsets(self, window):
        return sorted(row[2] for row in window.scan_page.results.model.all)

    def test_scan_stop_resume_shows_every_file_once(self):
        window = self.open_window()
        self.choose(window)
        page = window.scan_page
        stop_early = page.results.append

        def append_then_stop(rows):
            stop_early(rows)
            page.stop()

        with mock.patch.object(page.results, "append", append_then_stop):
            window.options_page.start_button.click()
            self.wait(lambda: not page.is_running())
        self.assertEqual(window.stack.currentIndex(), SCAN)
        if page.title.text() == "Đã dừng":
            self.assertTrue(page.resume_button.isVisible())
            page.resume_button.click()
        self.wait(lambda: page.title.text() == "Đã quét xong")
        self.assertEqual(self.offsets(window), [at for at, _ in self.parts])
        self.assertEqual(sorted(row[2] for row in scanner.load_report(self.out)), [at for at, _ in self.parts])
        self.assertEqual(page.tiles["anh"].text(), "10")
        self.assertFalse(page.resume_button.isVisible())

    def test_filters_and_sorting(self):
        session.Session(session.Options(self.image, self.out)).run()
        window = self.open_window()
        window.open_results(self.out)
        view = window.scan_page.results
        self.assertEqual(len(view.model.view), 20)
        view.group.setCurrentIndex(view.group.findData("video"))
        self.assertEqual({row[1] for row in view.model.view}, {"mp4"})
        view.group.setCurrentIndex(0)
        view.search.setText("PDF")
        view._filter()
        self.assertEqual({row[1] for row in view.model.view}, {"pdf"})
        view.search.setText("")
        view._filter()
        view.table.sortByColumn(2, Qt.DescendingOrder)
        sizes = [row[3] for row in view.model.view]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        view.table.selectRow(0)
        self.assertEqual(view.preview.path, view.model.path_of(view.model.view[0]))
        view.grid_button.setChecked(True)
        APP.processEvents()

    def test_finished_folder_offers_results_and_restart(self):
        session.Session(session.Options(self.image, self.out)).run()
        window = self.open_window()
        self.choose(window)
        page = window.options_page
        self.assertTrue(page.resume_row.isVisible())
        self.assertFalse(page.resume.isEnabled())
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            page.start_button.click()
        self.assertEqual(window.stack.currentIndex(), OPTIONS)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            page.start_button.click()
        self.wait(lambda: window.scan_page.title.text() == "Đã quét xong")
        self.assertEqual(self.offsets(window), [at for at, _ in self.parts])

    def test_a_late_answer_about_the_previous_folder_is_ignored(self):
        window = self.open_window()
        window._chosen(Choice(self.image, None, "ảnh đĩa", os.path.getsize(self.image)))
        page = window.options_page
        page._check_output()
        page.out.setText(os.path.join(self.tmp.name, "khác"))
        page.timer.stop()
        end = time.monotonic() + 0.5
        while time.monotonic() < end:
            APP.processEvents()
        self.assertFalse(page.start_button.isEnabled())

    def test_output_on_the_source_disk_is_blocked(self):
        window = self.open_window()
        with mock.patch.object(disks, "output_on_disk", return_value=True):
            window._chosen(Choice("/dev/sdb", "sdb", "sdb", 100 * MB))
            window.options_page.out.setText(self.out)
            self.wait(lambda: window.options_page.out_status.property("banner") == "error")
        self.assertFalse(window.options_page.start_button.isEnabled())

    @unittest.skipUnless(sys.platform == "win32", "chỉ chạy trên Windows")
    def test_suggested_folder_avoids_the_source_disk_and_network_drives(self):
        holders = {"C": {"0"}, "E": {"2"}, "F": {"1"}, "Z": None}
        free = {"C:\\": 50, "E:\\": 900, "F:\\": 70}
        with mock.patch.object(disks.backend, "drive_letters", return_value=list(holders)),                 mock.patch.object(disks.backend, "disks_of_path", side_effect=lambda root: holders[root[0]]),                 mock.patch.object(options_page, "free_bytes", side_effect=lambda root: free[root]):
            self.assertEqual(options_page.suggest_folder("2"), "F:\KhoiPhuc")
            self.assertEqual(options_page.suggest_folder(None), "E:\KhoiPhuc")
        with mock.patch.object(disks.backend, "drive_letters", return_value=["C"]),                 mock.patch.object(disks.backend, "disks_of_path", return_value={"0"}):
            self.assertEqual(options_page.suggest_folder("0"), "")

    def test_refused_scan_returns_to_the_options(self):
        window = self.open_window()
        self.choose(window)
        os.remove(self.image)
        with mock.patch.object(QMessageBox, "warning") as warning:
            window.options_page.start_button.click()
            self.wait(lambda: warning.called)
        self.assertEqual(window.stack.currentIndex(), OPTIONS)
        self.assertFalse(window.scan_page.is_running())

    def test_folder_without_results_is_explained(self):
        window = self.open_window()
        with mock.patch.object(QMessageBox, "information") as shown:
            window.open_results(self.tmp.name)
        self.assertTrue(shown.called)

    def test_losing_the_disk_explains_how_to_continue(self):
        text = scan_page.explain(session.Outcome(session.LOST, ""), mock.Mock(position=5_000_000_000, saved=1, saved_bytes=1))
        self.assertIn("5,0 GB", text)
        self.assertIn("Cắm lại ổ", text)


class TermsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, self.tmp.name)

    def test_the_app_opens_only_after_agreeing_and_asks_again_when_terms_change(self):
        with mock.patch.object(about.AcceptDialog, "exec", return_value=QDialog.Rejected):
            self.assertFalse(about.ensure_accepted())
        with mock.patch.object(about.AcceptDialog, "exec", return_value=QDialog.Accepted) as asked:
            self.assertTrue(about.ensure_accepted())
            self.assertTrue(about.ensure_accepted())
            self.assertEqual(asked.call_count, 1)
            with mock.patch.object(developer, "TERMS_VERSION", "bản mới"):
                self.assertTrue(about.ensure_accepted())
            self.assertEqual(asked.call_count, 2)

    def test_agree_box_unlocks_the_button(self):
        dialog = about.AcceptDialog()
        self.assertFalse(dialog.ok.isEnabled())
        dialog.agree.setChecked(True)
        self.assertTrue(dialog.ok.isEnabled())

    def test_documents_name_the_developer_and_contact(self):
        for name in (developer.TERMS, developer.RULES):
            text = developer.read_document(name)
            self.assertIn(developer.DEVELOPER, text)
            self.assertIn(developer.EMAIL, text)
        self.assertIn(("Nhà phát triển", "VINBS"), developer.contacts())
        with mock.patch.object(developer, "WEBSITE", ""):
            self.assertNotIn("Website", dict(developer.contacts()))

    def test_standard_buttons_are_in_vietnamese(self):
        box = QMessageBox(QMessageBox.Question, "x", "y", QMessageBox.Yes | QMessageBox.No)
        self.assertEqual({button.text() for button in box.buttons()}, {"Có", "Không"})

    def test_numbers_read_naturally(self):
        self.assertEqual(human_size(1_500_000_000), "1,5 GB")
        self.assertEqual(human_duration(5400), "khoảng 1 giờ 30 phút")

    def test_recovered_programs_are_never_started(self):
        with mock.patch("khoiphucfile.gui.common.reveal") as revealed, \
                mock.patch("khoiphucfile.gui.common.subprocess.Popen") as started:
            open_file(os.path.join("x", "a.jar"))
        self.assertTrue(revealed.called)
        self.assertFalse(started.called)


if __name__ == "__main__":
    unittest.main()
