"""Giới thiệu, điều khoản, nội quy và hộp thoại đồng ý khi mở ứng dụng lần đầu."""

from __future__ import annotations

import html
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, developer
from .common import button, label, settings

ABOUT, TERMS, RULES, THIRD_PARTY = range(4)
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")


def document_view(name: str) -> QTextBrowser:
    view = QTextBrowser()
    view.setOpenExternalLinks(True)
    view.setMarkdown(developer.read_document(name))
    view.document().setDocumentMargin(14)
    return view


def about_view() -> QWidget:
    picture = QLabel()
    picture.setPixmap(QIcon(ICON).pixmap(128, 128))
    rows = "".join(f"<tr><td style='padding: 3px 18px 3px 0'>{title}</td><td style='padding: 3px 0'><b>{contact_link(title, value)}</b></td></tr>"
                   for title, value in developer.contacts())
    details = QLabel(f"<table cellspacing='0'>{rows}</table>")
    details.setTextInteractionFlags(Qt.TextBrowserInteraction)
    details.setOpenExternalLinks(True)

    text = QVBoxLayout()
    text.addWidget(label(APP_NAME, "title"))
    text.addWidget(label(f"Phiên bản {__version__}", "muted"))
    text.addSpacing(10)
    text.addWidget(details)
    text.addSpacing(10)
    text.addWidget(label("Cứu ảnh, video, âm thanh và tài liệu từ ổ đĩa đã xoá, format hoặc bị ghi đè. "
                         "Ứng dụng chỉ đọc ổ nguồn và không gửi dữ liệu ra ngoài máy bạn.", wrap=True))
    text.addSpacing(10)
    text.addWidget(label(f"{developer.COPYRIGHT}. Sử dụng miễn phí theo Điều khoản sử dụng.", "muted", wrap=True))
    text.addStretch(1)

    page = QWidget()
    layout = QHBoxLayout(page)
    layout.setContentsMargins(22, 22, 22, 22)
    layout.setSpacing(24)
    layout.addWidget(picture, 0, Qt.AlignTop)
    layout.addLayout(text, 1)
    return page


def contact_link(title: str, value: str) -> str:
    shown = html.escape(value)
    if title == "Email":
        return f"<a href='mailto:{shown}'>{shown}</a>"
    if title == "Website":
        return f"<a href='{shown}'>{shown}</a>"
    return shown


class InfoDialog(QDialog):
    def __init__(self, page: int = ABOUT, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.resize(760, 600)
        tabs = QTabWidget()
        tabs.addTab(about_view(), "Giới thiệu")
        tabs.addTab(document_view(developer.TERMS), "Điều khoản sử dụng")
        tabs.addTab(document_view(developer.RULES), "Nội quy sử dụng")
        tabs.addTab(document_view(developer.THIRD_PARTY), "Thành phần bên thứ ba")
        tabs.setCurrentIndex(page)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(button("Đóng", self.accept))
        layout = QVBoxLayout(self)
        layout.addWidget(tabs, 1)
        layout.addLayout(bottom)


class AcceptDialog(QDialog):
    """Hiện khi mở ứng dụng lần đầu hoặc khi văn bản thay đổi."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.resize(760, 640)
        tabs = QTabWidget()
        tabs.addTab(document_view(developer.TERMS), "Điều khoản sử dụng")
        tabs.addTab(document_view(developer.RULES), "Nội quy sử dụng")
        self.agree = QCheckBox("Tôi đã đọc và đồng ý với Điều khoản sử dụng và Nội quy sử dụng")
        self.ok = button("Bắt đầu sử dụng", self.accept, "primary")
        self.ok.setEnabled(False)
        self.agree.toggled.connect(self.ok.setEnabled)
        bottom = QHBoxLayout()
        bottom.addWidget(self.agree, 1)
        bottom.addWidget(button("Không đồng ý, thoát", self.reject))
        bottom.addWidget(self.ok)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(label("Trước khi bắt đầu", "title"))
        layout.addWidget(label(f"{APP_NAME} do {developer.DEVELOPER} phát triển, dùng miễn phí. "
                               "Vui lòng đọc điều khoản và nội quy dưới đây.", "muted", wrap=True))
        layout.addWidget(tabs, 1)
        layout.addLayout(bottom)


def ensure_accepted() -> bool:
    store = settings()
    if store.value("terms_accepted", "") == developer.TERMS_VERSION:
        return True
    if AcceptDialog().exec() != QDialog.Accepted:
        return False
    store.setValue("terms_accepted", developer.TERMS_VERSION)
    store.sync()
    return True
