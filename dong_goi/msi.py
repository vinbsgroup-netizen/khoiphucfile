"""Tạo bộ cài Windows (.msi) bằng msilib có sẵn trong Python 3.10-3.12, không cần công cụ ngoài."""

from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile
import uuid
import warnings
from ctypes import wintypes

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import msilib
    import msilib.schema
    import msilib.sequence

UPGRADE_CODE = "{8B0C6A0E-6E6B-4C0B-9E7E-5C1B7D0F3A52}"
INSTALLED_EXE = "%ProgramFiles%\\{developer}\\{folder}\\KhoiPhucFile.exe"
UTF8 = 65001
INCLUSIVE_MAX = 0x200


def force_utf8(path: str) -> None:
    """MSI mặc định lưu chữ theo bảng mã của máy; ép UTF-8 để tên tiếng Việt đúng trên mọi máy."""
    msi = ctypes.WinDLL("msi")
    msi.MsiOpenDatabaseW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG)]
    msi.MsiDatabaseImportW.argtypes = [wintypes.ULONG, wintypes.LPCWSTR, wintypes.LPCWSTR]
    for function in (msi.MsiDatabaseCommit, msi.MsiCloseHandle):
        function.argtypes = [wintypes.ULONG]
    handle = wintypes.ULONG()
    with tempfile.TemporaryDirectory() as folder:
        with open(os.path.join(folder, "codepage.idt"), "w", newline="") as out:
            out.write(f"\r\n\r\n{UTF8}\t_ForceCodepage\r\n")
        check(msi.MsiOpenDatabaseW(path, ctypes.c_void_p(1), ctypes.byref(handle)))
        try:
            check(msi.MsiDatabaseImportW(handle, folder, "codepage.idt"))
            check(msi.MsiDatabaseCommit(handle))
        finally:
            msi.MsiCloseHandle(handle)


def check(code: int) -> None:
    if code:
        raise OSError(f"Windows Installer báo lỗi {code}")


def reorder(db, table: str, action: str, sequence: int) -> None:
    view = db.OpenView(f"UPDATE `{table}` SET `Sequence`={sequence} WHERE `Action`='{action}'")
    view.Execute(None)
    view.Close()


def set_property(db, name: str, value: str) -> None:
    view = db.OpenView("UPDATE `Property` SET `Value`=? WHERE `Property`=?")
    record = msilib.CreateRecord(2)
    record.SetString(1, value)
    record.SetString(2, name)
    view.Execute(record)
    view.Close()


def add_files(db, cab, folder, name: str, feature) -> None:
    """Thêm mọi file và thư mục con; mỗi thư mục là một component, khoá là chính thư mục đó.

    Không lấy file làm khoá: khi nâng cấp, Windows Installer so phiên bản của file khoá rồi bỏ qua cả component.
    """
    code = "{" + str(uuid.uuid5(uuid.UUID(UPGRADE_CODE.strip("{}")), name)).upper() + "}"
    entries = sorted(os.listdir(folder.absolute))
    files = [entry for entry in entries if os.path.isfile(os.path.join(folder.absolute, entry))]
    if files:
        folder.start_component("C_" + folder.logical, feature, 0, uuid=code)
        for entry in files:
            folder.add_file(entry)
    for entry in entries:
        if os.path.isdir(os.path.join(folder.absolute, entry)):
            child = msilib.Directory(db, cab, folder, entry, entry, f"{folder.make_short(entry)}|{entry}")
            add_files(db, cab, child, f"{name}/{entry}", feature)


def make_shortcut(path: str, target: str, description: str) -> None:
    """Tạo file .lnk; tên file phải không dấu vì WScript.Shell không ghi được tên Unicode."""
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);$s.TargetPath=$env:LNK_TARGET;"
              "$s.IconLocation=$env:LNK_TARGET+',0';$s.Description=$env:LNK_TEXT;$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True,
                   env={**os.environ, "LNK": path, "LNK_TARGET": target, "LNK_TEXT": description})


def add_shortcut(db, cab, folder, shortcut: str, name: str, code_name: str, feature) -> None:
    """Cài lối tắt như một file thường: bảng Shortcut của MSI làm việc gỡ chậm tới gần một phút mỗi lối tắt."""
    code = "{" + str(uuid.uuid5(uuid.UUID(UPGRADE_CODE.strip("{}")), code_name)).upper() + "}"
    component, file_id = "C_" + folder.logical, "L_" + folder.logical
    msilib.add_data(db, "Component", [(component, code, folder.logical, 256, None, file_id)])
    msilib.add_data(db, "FeatureComponents", [(feature.id, component)])
    sequence, _ = cab.append(shortcut, name + ".lnk", file_id)
    msilib.add_data(db, "File", [(file_id, component, f"KHOIPH~1.LNK|{name}.lnk", os.path.getsize(shortcut),
                                  None, None, 512, sequence)])


def build(source: str, target: str, name: str, version: str, developer: str, contact: str, icon: str) -> None:
    ascii_name = "Khoi Phuc File"
    product = msilib.gen_uuid()
    msilib._directories.clear()  # msilib nhớ tên thư mục giữa các lần gọi và sẽ đổi INSTALLDIR thành INSTALLDIR1
    msilib.init_database(target, msilib.schema, ascii_name, product, version, developer).Close()
    force_utf8(target)
    db = msilib.OpenDatabase(target, msilib.MSIDBOPEN_DIRECT)
    msilib.add_tables(db, msilib.sequence)
    set_property(db, "ProductName", name)
    msilib.add_data(db, "Property", [
        ("UpgradeCode", UPGRADE_CODE), ("ALLUSERS", "1"), ("SecureCustomProperties", "OLDVERSION;NEWERVERSION"),
        ("REINSTALLMODE", "amus"),
        ("ARPPRODUCTICON", "AppIcon.ico"), ("ARPCONTACT", contact), ("ARPNOMODIFY", "1"),
        ("ARPCOMMENTS", "Cứu file từ ổ đĩa đã xoá, format hoặc bị ghi đè")])
    msilib.add_data(db, "Upgrade", [
        (UPGRADE_CODE, "0.0.1", version, None, INCLUSIVE_MAX, None, "OLDVERSION"),
        (UPGRADE_CODE, version, None, None, 2, None, "NEWERVERSION")])
    msilib.add_data(db, "LaunchCondition", [
        ("VersionNT64 AND VersionNT >= 603", f"{name} cần Windows 10 hoặc 11 bản 64-bit."),
        ("Installed OR NOT NEWERVERSION", f"Máy đã có phiên bản {name} mới hơn.")])
    # Gỡ bản cũ TRƯỚC khi chép bản mới, nếu không việc gỡ sẽ xoá luôn file vừa chép.
    reorder(db, "InstallExecuteSequence", "RemoveExistingProducts", 1410)
    # Dò phiên bản (200) phải xong rồi mới kiểm tra điều kiện, nếu không sẽ cài đè được bản cũ lên bản mới.
    for table in ("InstallExecuteSequence", "InstallUISequence"):
        reorder(db, table, "LaunchConditions", 250)
    msilib.add_data(db, "Icon", [("AppIcon.ico", msilib.Binary(icon))])

    feature = msilib.Feature(db, "Main", ascii_name, name, 1, directory="INSTALLDIR")
    feature.set_current()
    cab = msilib.CAB("khoiphucfile")
    root = msilib.Directory(db, cab, None, source, "TARGETDIR", "SourceDir")
    programs = msilib.Directory(db, cab, root, ".", "ProgramFiles64Folder", "PFiles")
    vendor = msilib.Directory(db, cab, programs, ".", "VENDORDIR", developer)
    install = msilib.Directory(db, cab, vendor, ".", "INSTALLDIR", f"KHOIPH~1|{ascii_name}")
    desktop = msilib.Directory(db, cab, root, ".", "DesktopFolder", "Desktop")
    menu = msilib.Directory(db, cab, root, ".", "ProgramMenuFolder", "Programs")
    add_files(db, cab, install, f"app {version}", feature)

    with tempfile.TemporaryDirectory() as scratch:
        shortcut = os.path.join(scratch, "khoiphucfile.lnk")
        make_shortcut(shortcut, INSTALLED_EXE.format(developer=developer, folder=ascii_name),
                      "Cứu file từ ổ đĩa đã xoá, format hoặc bị ghi đè")
        for folder in (desktop, menu):
            add_shortcut(db, cab, folder, shortcut, name, f"{folder.logical} {version}", feature)
        cab.commit(db)
    db.Commit()
    db.Close()
