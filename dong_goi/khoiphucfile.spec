# Cấu hình PyInstaller, dùng chung cho Windows, macOS và Linux. Chạy qua dong_goi/build.py.
import os
import sys

ROOT = os.path.dirname(SPECPATH)
sys.path.insert(0, ROOT)

from khoiphucfile import APP_NAME, __version__  # noqa: E402
from khoiphucfile.developer import COPYRIGHT, DEVELOPER  # noqa: E402

WINDOWS, MAC = sys.platform == "win32", sys.platform == "darwin"
DOCUMENTS = [(os.path.join(ROOT, "khoiphucfile", "van_ban", "*.md"), "khoiphucfile/van_ban")]
PICTURES = [(os.path.join(ROOT, "khoiphucfile", "gui", "*.png"), "khoiphucfile/gui")]
LICENSES = [(os.path.join(SPECPATH, "giay_phep", "*.txt"), "giay_phep")]
UNUSED = ["tkinter", "unittest", "pydoc", "doctest", "test", "lib2to3", "xmlrpc", "sqlite3", "PIL", "numpy",
          "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL"]
HOOKS = [os.path.join(SPECPATH, "restore_env.py")]

gui = Analysis([os.path.join(SPECPATH, "run_gui.py")], pathex=[ROOT], datas=DOCUMENTS + PICTURES + LICENSES,
               excludes=UNUSED, runtime_hooks=HOOKS)
cli = Analysis([os.path.join(SPECPATH, "run_cli.py")], pathex=[ROOT], datas=DOCUMENTS,
               excludes=UNUSED + ["PySide6", "shiboken6", "khoiphucfile.gui"], runtime_hooks=HOOKS)

# Không dùng tới: OpenGL phần mềm (20 MB), bản dịch Qt và các thư viện Qt ngoài Core/Gui/Widgets.
DROPPED = ("opengl32sw.dll", "qt6network", "qt6qml", "qt6quick", "qt6pdf", "qt6svg", "qt6virtualkeyboard", "qt6opengl")


def needed(entry):
    name = entry[0].replace("\\", "/").lower()
    base = os.path.basename(name)
    if "/translations/" in name:
        return False
    return not (WINDOWS and (base.startswith(DROPPED) or base in ("qpdf.dll", "qsvg.dll", "qsvgicon.dll")
                             or "/networkinformation/" in name or "/tls/" in name))


gui.binaries = [entry for entry in gui.binaries if needed(entry)]
gui.datas = [entry for entry in gui.datas if needed(entry)]


def version_resource(description, filename):
    if not WINDOWS:
        return None
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)

    numbers = tuple(int(part) for part in __version__.split(".")) + (0,)
    strings = {"CompanyName": DEVELOPER, "FileDescription": description, "FileVersion": __version__,
               "LegalCopyright": COPYRIGHT, "OriginalFilename": filename, "ProductName": APP_NAME,
               "ProductVersion": __version__}
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[StringFileInfo([StringTable("042a04b0", [StringStruct(key, value) for key, value in strings.items()])]),
              VarFileInfo([VarStruct("Translation", [0x042A, 1200])])])


ICON = os.path.join(SPECPATH, "icons", "khoiphucfile.icns" if MAC else "khoiphucfile.ico")
GUI_NAME = "KhoiPhucFile" if WINDOWS or MAC else "khoiphucfile"

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name=GUI_NAME, console=False, icon=ICON,
              upx=False, uac_admin=WINDOWS, version=version_resource(APP_NAME, "KhoiPhucFile.exe"))
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="khoiphuc", console=True, icon=ICON,
              upx=False, version=version_resource(APP_NAME + " (dòng lệnh)", "khoiphuc.exe"))
collected = COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas, upx=False, name="KhoiPhucFile")

if MAC:
    BUNDLE(collected, name="KhoiPhucFile.app", icon=ICON, bundle_identifier="vn.vinbs.khoiphucfile", version=__version__,
           info_plist={"CFBundleDisplayName": APP_NAME, "CFBundleName": APP_NAME, "CFBundleShortVersionString": __version__,
                       # Gói có thêm chương trình dòng lệnh nên PyInstaller tưởng ứng dụng chạy ngầm; ghi rõ là có cửa sổ.
                       "CFBundleExecutable": GUI_NAME, "LSBackgroundOnly": False,
                       "NSHumanReadableCopyright": COPYRIGHT, "NSHighResolutionCapable": True,
                       "LSMinimumSystemVersion": "12.0", "CFBundleDevelopmentRegion": "vi",
                       "NSRemovableVolumesUsageDescription": "Để đọc ổ đĩa cần cứu dữ liệu và lưu file cứu được.",
                       "NSDesktopFolderUsageDescription": "Để lưu file cứu được vào thư mục bạn chọn.",
                       "NSDocumentsFolderUsageDescription": "Để lưu file cứu được vào thư mục bạn chọn.",
                       "NSDownloadsFolderUsageDescription": "Để lưu file cứu được vào thư mục bạn chọn."})
