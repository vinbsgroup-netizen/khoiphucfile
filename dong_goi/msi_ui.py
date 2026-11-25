"""Trình cài đặt có cửa sổ cho bộ .msi: điều khoản, tiến độ, hoàn tất, sửa/gỡ, báo lỗi."""

from __future__ import annotations

import re

import msilib
from msilib import Dialog, add_data

W, H = 420, 290
BANNER = 56
VISIBLE, ENABLED, SUNKEN = 1, 2, 4
MODAL, MINIMIZE = 2, 4
PLAIN = 0x30000 | VISIBLE | ENABLED  # chữ trong suốt, không coi & là phím tắt
SHIELD = 0x800000
RUN_DETACHED = 34 + 192  # chạy lệnh từ thư mục INSTALLDIR, không chờ


def markdown_to_rtf(*documents: str) -> str:
    """Đủ dùng cho điều khoản và nội quy: tiêu đề, đoạn, gạch đầu dòng, số thứ tự, **đậm**."""

    def encode(text: str) -> str:
        out = []
        for char in text:
            if char in "\\{}":
                out.append("\\" + char)
            elif ord(char) < 128:
                out.append(char)
            else:
                out.append(f"\\u{ord(char) if ord(char) < 32768 else ord(char) - 65536}?")
        return "".join(out)

    def inline(text: str) -> str:
        text = re.sub(r"[`<>]", "", text)
        return "".join(f"{{\\b {encode(part)}}}" if at % 2 else encode(part) for at, part in enumerate(text.split("**")))

    body = []
    for number, document in enumerate(documents):
        if number:
            body.append("\\pard\\par")
        for line in document.splitlines():
            heading = re.match(r"(#+)\s+(.*)", line)
            bullet = re.match(r"(?:-|(\d+)\.)\s+(.*)", line)
            if heading:
                size = 26 if len(heading.group(1)) == 1 else 20
                body.append(f"\\pard\\sb140\\sa60{{\\b\\fs{size} {inline(heading.group(2))}}}\\par")
            elif bullet:
                mark = f"{bullet.group(1)}." if bullet.group(1) else "\\bullet"
                body.append(f"\\pard\\fi-240\\li360\\sa30 {mark}\\tab {inline(bullet.group(2))}\\par")
            elif line.strip():
                body.append(f"\\pard\\sa60 {inline(line)}\\par")
    return "{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl{\\f0 Segoe UI;}}\\fs17\n" + "\n".join(body) + "\n}"


def add_ui(db, name: str, developer: str, license_rtf: str, banner: str) -> None:
    add_data(db, "Binary", [("Banner", msilib.Binary(banner))])
    add_data(db, "TextStyle", [("Normal", "Segoe UI", 9, None, 0), ("Title", "Segoe UI", 13, None, 1)])
    add_data(db, "Property", [("DefaultUIFont", "Normal"), ("ErrorDialog", "ErrorDlg"), ("LAUNCHAPP", "1")])
    add_data(db, "CheckBox", [("ACCEPTED", "1"), ("LAUNCHAPP", "1")])
    # Mở qua explorer để Windows hỏi quyền quản trị cho ứng dụng; gọi thẳng sẽ bị từ chối vì bộ cài không chạy quyền đó.
    add_data(db, "CustomAction", [("LaunchApp", RUN_DETACHED, "INSTALLDIR",
                                   "[WindowsFolder]explorer.exe \"[INSTALLDIR]KhoiPhucFile.exe\"")])
    add_data(db, "UIText", [("bytes", "byte"), ("KB", "KB"), ("MB", "MB"), ("GB", "GB")])
    add_data(db, "ActionText", [
        ("InstallValidate", "Đang kiểm tra", None), ("RemoveExistingProducts", "Đang gỡ phiên bản cũ", None),
        ("InstallFiles", "Đang chép file", None), ("RemoveFiles", "Đang xoá file", None),
        ("PublishProduct", "Đang ghi thông tin ứng dụng", None), ("Rollback", "Đang hoàn tác", None)])
    # Chỉ đóng hoặc mở ứng dụng thì không hiện trang "Đã huỷ".
    db.OpenView("UPDATE `InstallUISequence` SET `Condition`='NOT QUIETEXIT' WHERE `Action`='UserExit'").Execute(None)
    add_data(db, "InstallUISequence", [
        ("LicenseDlg", "NOT Installed", 1230), ("MaintenanceDlg", "Installed", 1240), ("ProgressDlg", None, 1280)])

    def page(dialog: str, first: str, default: str, cancel: str, attributes: int = VISIBLE | MODAL | MINIMIZE) -> Dialog:
        created = Dialog(db, dialog, 50, 50, W, H, attributes, f"Cài đặt {name}", first, default, cancel)
        created.bitmap("Banner", 0, 0, W, BANNER, "Banner")
        created.line("BottomLine", 0, H - 34, W, 0)
        return created

    def text(dialog: Dialog, control: str, y: int, height: int, value: str) -> None:
        dialog.text(control, 18, y, W - 36, height, PLAIN, value)

    def ask_before_cancelling(control) -> None:
        control.event("SpawnDialog", "CancelDlg")

    right, left, bottom, size = W - 78, W - 160, H - 26, (66, 18)

    licence = page("LicenseDlg", "Accept", "Install", "Cancel")
    text(licence, "Intro", BANNER + 8, 26,
         f"[ProductName] [ProductVersion] do {developer} phát triển, dùng miễn phí. Ứng dụng sẽ được cài vào:\r\n[INSTALLDIR]")
    licence.control("Terms", "ScrollableText", 18, BANNER + 40, W - 36, 120, VISIBLE | ENABLED | SUNKEN,
                    None, license_rtf, None, None)
    licence.checkbox("Accept", 18, H - 68, W - 36, 14, VISIBLE | ENABLED, "ACCEPTED",
                     "Tôi đồng ý với Điều khoản sử dụng và Nội quy sử dụng", "Install")
    install = licence.pushbutton("Install", left, bottom, *size, VISIBLE | ENABLED | SHIELD, "Cài đặt", "Cancel")
    install.condition("Disable", "NOT ACCEPTED")
    install.condition("Enable", "ACCEPTED = \"1\"")
    install.event("EndDialog", "Return", "ACCEPTED = \"1\"")
    ask_before_cancelling(licence.pushbutton("Cancel", right, bottom, *size, VISIBLE | ENABLED, "Huỷ", "Accept"))

    maintenance = page("MaintenanceDlg", "Open", "Open", "Close")
    text(maintenance, "Title", BANNER + 12, 18, "{\\Title}[ProductName] đã có trên máy này")
    text(maintenance, "Help", BANNER + 34, 30, "Mở ứng dụng từ biểu tượng trên màn hình Desktop hoặc menu Start, hoặc chọn bên dưới.")
    opener = maintenance.pushbutton("Open", 18, BANNER + 74, 140, 20, VISIBLE | ENABLED, "Mở [ProductName]", "Repair")
    opener.event("DoAction", "LaunchApp", "1", 1)
    opener.event("[QUIETEXIT]", "1", "1", 2)
    opener.event("EndDialog", "Exit", "1", 3)
    repair = maintenance.pushbutton("Repair", 18, BANNER + 102, 140, 20, VISIBLE | ENABLED | SHIELD, "Cài lại", "Remove")
    repair.event("ReinstallMode", "amus", "1", 1)
    repair.event("Reinstall", "ALL", "1", 2)
    repair.event("EndDialog", "Return", "1", 3)
    remove = maintenance.pushbutton("Remove", 18, BANNER + 130, 140, 20, VISIBLE | ENABLED | SHIELD, "Gỡ khỏi máy", "Close")
    remove.event("Remove", "ALL", "1", 1)
    remove.event("EndDialog", "Return", "1", 2)
    text(maintenance, "Keep", BANNER + 156, 16, "Gỡ ứng dụng không xoá các file bạn đã cứu.")
    close = maintenance.pushbutton("Close", right, bottom, *size, VISIBLE | ENABLED, "Đóng", "Open")
    close.event("[QUIETEXIT]", "1", "1", 1)
    close.event("EndDialog", "Exit", "1", 2)

    progress = page("ProgressDlg", "Cancel", "Cancel", "Cancel", VISIBLE | MINIMIZE)
    text(progress, "Title", BANNER + 24, 18, "{\\Title}Đang thực hiện, vui lòng đợi…")
    action = progress.text("Action", 18, BANNER + 56, W - 36, 14, PLAIN, " ")
    action.mapping("ActionText", "Text")
    bar = progress.control("Bar", "ProgressBar", 18, BANNER + 76, W - 36, 12, 0x10000 | VISIBLE, None, None, None, None)
    bar.mapping("SetProgress", "Progress")
    ask_before_cancelling(progress.pushbutton("Cancel", right, bottom, *size, VISIBLE | ENABLED, "Huỷ", None))

    done = page("ExitDialog", "Finish", "Finish", "Finish")
    title = done.text("Title", 18, BANNER + 24, W - 36, 18, PLAIN, "{\\Title}Đã cài xong [ProductName]")
    title.condition("Hide", "Installed OR REMOVE = \"ALL\"")
    other = done.text("TitleOther", 18, BANNER + 24, W - 36, 18, 0x30000 | ENABLED, "{\\Title}Đã thực hiện xong")
    other.condition("Show", "Installed OR REMOVE = \"ALL\"")
    where = done.text("Where", 18, BANNER + 52, W - 36, 30, PLAIN,
                      "Biểu tượng [ProductName] có trên màn hình Desktop và trong menu Start.")
    where.condition("Hide", "REMOVE = \"ALL\"")
    launch = done.checkbox("Launch", 18, BANNER + 90, W - 36, 14, VISIBLE | ENABLED, "LAUNCHAPP",
                           "Mở [ProductName] ngay", "Finish")
    launch.condition("Hide", "REMOVE = \"ALL\"")
    finish = done.pushbutton("Finish", right, bottom, *size, VISIBLE | ENABLED, "Hoàn tất", "Launch")
    finish.event("DoAction", "LaunchApp", "LAUNCHAPP = \"1\" AND NOT (REMOVE = \"ALL\")", 1)
    finish.event("EndDialog", "Return", "1", 2)

    for dialog, title_text, explanation in (
            ("UserExit", "Đã huỷ", "Máy của bạn chưa bị thay đổi. Có thể chạy lại bộ cài bất cứ lúc nào."),
            ("FatalError", "Chưa hoàn tất được",
             f"Máy của bạn chưa bị thay đổi. Hãy đóng {name} nếu đang mở rồi chạy lại bộ cài.")):
        failed = page(dialog, "Finish", "Finish", "Finish")
        text(failed, "Title", BANNER + 24, 18, "{\\Title}" + title_text)
        text(failed, "Why", BANNER + 52, 40, explanation)
        failed.pushbutton("Finish", right, bottom, *size, VISIBLE | ENABLED, "Đóng", "Finish").event("EndDialog", "Exit")

    confirm = Dialog(db, "CancelDlg", 50, 10, 240, 80, VISIBLE | MODAL, f"Cài đặt {name}", "No", "No", "No")
    confirm.text("Question", 16, 16, 208, 26, PLAIN, "Dừng và thoát?")
    confirm.pushbutton("Yes", 50, 52, *size, VISIBLE | ENABLED, "Thoát", "No").event("EndDialog", "Exit")
    confirm.pushbutton("No", 126, 52, *size, VISIBLE | ENABLED, "Làm tiếp", "Yes").event("EndDialog", "Return")

    # Windows Installer tự chọn nút nào hiện ra; tên các nút do nó quy định.
    error = Dialog(db, "ErrorDlg", 50, 10, 330, 110, 0x10000 | VISIBLE | MODAL, f"Cài đặt {name}", "ErrorText", None, None)
    error.text("ErrorText", 16, 12, 298, 56, PLAIN, "")
    for control, event, caption, at in (("N", "ErrorNo", "Không", 10), ("Y", "ErrorYes", "Có", 60), ("A", "ErrorAbort", "Dừng", 110),
                                        ("C", "ErrorCancel", "Huỷ", 160), ("I", "ErrorIgnore", "Bỏ qua", 210),
                                        ("O", "ErrorOk", "Đồng ý", 260), ("R", "ErrorRetry", "Thử lại", 260)):
        error.pushbutton(control, at, 82, 58, 18, VISIBLE | ENABLED, caption, None).event("EndDialog", event)

    busy = page("FilesInUse", "Retry", "Retry", "Exit", VISIBLE | MODAL | MINIMIZE | 0x10)
    text(busy, "Title", BANNER + 10, 18, "{\\Title}Cần đóng ứng dụng đang mở")
    text(busy, "Help", BANNER + 32, 26, "Các chương trình dưới đây đang dùng file cần thay. Đóng chúng rồi bấm Thử lại.")
    busy.control("List", "ListBox", 18, BANNER + 62, W - 36, 90, VISIBLE | ENABLED | SUNKEN, "FileInUseProcess",
                 None, None, None)
    busy.pushbutton("Exit", right, bottom, *size, VISIBLE | ENABLED, "Thoát", "Ignore").event("EndDialog", "Exit")
    busy.pushbutton("Ignore", left, bottom, *size, VISIBLE | ENABLED, "Bỏ qua", "Retry").event("EndDialog", "Ignore")
    busy.pushbutton("Retry", left - 82, bottom, *size, VISIBLE | ENABLED, "Thử lại", "Exit").event("EndDialog", "Retry")
