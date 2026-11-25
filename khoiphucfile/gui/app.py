"""Khởi động giao diện."""

from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import QLocale, QStandardPaths, QTimer, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import APP_ID, APP_NAME, __version__
from . import about, theme
from .window import MainWindow


class Vietnamese(QTranslator):
    """Qt không có sẵn bản tiếng Việt; dịch những chữ mà người dùng gặp trong hộp thoại và menu chuột phải."""

    WORDS = {"Yes": "Có", "No": "Không", "OK": "Đồng ý", "Cancel": "Huỷ", "Close": "Đóng", "Open": "Mở", "Save": "Lưu",
             "Choose": "Chọn", "Undo": "Hoàn tác", "Redo": "Làm lại", "Cut": "Cắt", "Copy": "Sao chép", "Paste": "Dán",
             "Delete": "Xoá", "Select All": "Chọn tất cả", "Copy Link Location": "Sao chép liên kết",
             "Directory:": "Thư mục:", "File name:": "Tên file:", "Files of type:": "Loại file:", "Look in:": "Nơi tìm:",
             "Step up": "Tăng", "Step down": "Giảm"}

    def isEmpty(self) -> bool:
        return False

    def translate(self, context, text, disambiguation=None, n=-1):
        return self.WORDS.get((text or "").replace("&", ""), "")


def log_path() -> str:
    folder = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "loi.txt")


def report_crash(kind, error, trace) -> None:
    text = "".join(traceback.format_exception(kind, error, trace))
    if sys.stderr:
        sys.stderr.write(text)
    try:
        with open(log_path(), "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
        where = f"\n\nChi tiết: {log_path()}"
    except OSError:
        where = ""
    QMessageBox.critical(None, APP_NAME, f"Có lỗi ngoài dự kiến: {error}{where}")


def build_app(arguments: list[str]) -> QApplication:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = QApplication(arguments)
    app.setApplicationName(APP_ID)
    app.setOrganizationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Vietnamese))
    app.installTranslator(Vietnamese(app))
    app.setWindowIcon(QIcon(about.ICON))
    theme.apply(app)
    app.styleHints().colorSchemeChanged.connect(lambda _: theme.apply(app))
    return app


def main() -> int:
    smoke_test = "--smoke-test" in sys.argv
    app = build_app(sys.argv)
    if not smoke_test:
        sys.excepthook = report_crash
        if not about.ensure_accepted():
            return 0
    window = MainWindow()
    window.show()
    if smoke_test:
        QTimer.singleShot(2500, window.close)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
