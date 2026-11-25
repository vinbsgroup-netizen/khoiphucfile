"""Thông tin nhà phát triển và các văn bản kèm ứng dụng. Dòng để trống sẽ không hiện ra."""

from __future__ import annotations

import os

from . import APP_NAME, __version__

DEVELOPER = "VINBS"
EMAIL = "vinbsgroup@gmail.com"
WEBSITE = ""
PHONE = ""
ADDRESS = ""
COPYRIGHT = "© 2026 VINBS"

# Đổi khi sửa điều khoản hoặc nội quy; người dùng sẽ được hỏi đồng ý lại.
TERMS_VERSION = "2026-11-25"

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "van_ban")
TERMS, RULES, THIRD_PARTY = "dieu_khoan_su_dung.md", "noi_quy_su_dung.md", "thanh_phan_ben_thu_ba.md"


def read_document(name: str) -> str:
    with open(os.path.join(FOLDER, name), encoding="utf-8") as handle:
        return handle.read()


def contacts() -> list[tuple[str, str]]:
    rows = (("Nhà phát triển", DEVELOPER), ("Email", EMAIL), ("Website", WEBSITE),
            ("Điện thoại", PHONE), ("Địa chỉ", ADDRESS))
    return [(title, value) for title, value in rows if value]


def about_lines() -> list[str]:
    return [f"{APP_NAME} {__version__}", *(f"{title}: {value}" for title, value in contacts()), COPYRIGHT]
