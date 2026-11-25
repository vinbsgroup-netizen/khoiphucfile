"""Đóng gói ứng dụng cho hệ điều hành đang chạy, kết quả nằm trong ban_phat_hanh/.

    python -m pip install -r dong_goi/requirements.txt
    python dong_goi/build.py

Windows: .msi và .zip chạy thẳng   macOS: .dmg   Linux: .deb và .tar.gz   Mọi hệ: .whl (cài bằng pip/pipx)
PyInstaller không đóng gói chéo được: muốn bản macOS phải chạy trên máy Mac, muốn bản Linux phải chạy trên Linux.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "ban_phat_hanh")
WORK = os.path.join(ROOT, ".build")
DIST = os.path.join(WORK, "dist")
APP = os.path.join(DIST, "KhoiPhucFile")
sys.path[:0] = [ROOT, HERE]

from khoiphucfile import APP_NAME, __version__  # noqa: E402
from khoiphucfile.developer import DEVELOPER, EMAIL  # noqa: E402

PNG = os.path.join(HERE, "icons", "khoiphucfile.png")
ICO = os.path.join(HERE, "icons", "khoiphucfile.ico")


def run(*command: str, **options) -> None:
    print(">", " ".join(command), flush=True)
    subprocess.run(command, check=True, **options)


def machine() -> str:
    return {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower(),
                                                                                      platform.machine().lower())


def target(suffix: str) -> str:
    path = os.path.join(OUT, f"KhoiPhucFile-{__version__}-{suffix}")
    if os.path.exists(path):
        os.remove(path)
    return path


def freeze() -> None:
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
        "--distpath", DIST, "--workpath", os.path.join(WORK, "work"), os.path.join(HERE, "khoiphucfile.spec"))


def binaries() -> tuple[str, str]:
    """(chương trình giao diện, chương trình dòng lệnh) vừa đóng gói."""
    if sys.platform == "win32":
        return os.path.join(APP, "KhoiPhucFile.exe"), os.path.join(APP, "khoiphuc.exe")
    if sys.platform == "darwin":
        inside = os.path.join(DIST, "KhoiPhucFile.app", "Contents", "MacOS")
        return os.path.join(inside, "KhoiPhucFile"), os.path.join(inside, "khoiphuc")
    return os.path.join(APP, "khoiphucfile"), os.path.join(APP, "khoiphuc")


def smoke_test() -> None:
    """Chạy thử bản đóng gói: dòng lệnh phải cứu đúng một file, giao diện phải mở và đóng êm."""
    from tests.test_khoiphuc import png_bytes

    gui, cli = binaries()
    environment = {**os.environ, "PYTHONUTF8": "1"}
    with tempfile.TemporaryDirectory() as folder:
        image, saved = os.path.join(folder, "thu.img"), os.path.join(folder, "ra")
        with open(image, "wb") as out:
            out.write(bytes(1 << 20) + png_bytes() + bytes(1 << 20))
        run(cli, "scan", image, "--out", saved, env=environment)
        expected = os.path.join(saved, "anh", "png", "khong_ro_ngay", f"s{(1 << 20) // 512}.png")
        with open(expected, "rb") as handle:
            assert handle.read() == png_bytes(), "file cứu được sai nội dung"
    run(cli, "about", env=environment, stdout=subprocess.DEVNULL)
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        environment["QT_QPA_PLATFORM"] = "offscreen"
    try:
        run(gui, "--smoke-test", env=environment, timeout=90)
    except OSError as error:
        if getattr(error, "winerror", None) != 740:
            raise
        print("Bỏ qua chạy thử giao diện: cần mở cửa sổ lệnh bằng quyền Administrator.")


def zip_folder(folder: str, path: str, top: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for current, _, files in os.walk(folder):
            for name in files:
                full = os.path.join(current, name)
                archive.write(full, os.path.join(top, os.path.relpath(full, folder)))


def package_windows() -> None:
    import msi

    msi.build(APP, target(f"windows-{machine()}.msi"), APP_NAME, __version__, DEVELOPER, EMAIL, ICO)
    zip_folder(APP, target(f"windows-{machine()}-khong-can-cai.zip"), "KhoiPhucFile")


def package_macos() -> None:
    stage = os.path.join(WORK, "dmg")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    run("cp", "-R", os.path.join(DIST, "KhoiPhucFile.app"), stage)
    os.symlink("/Applications", os.path.join(stage, "Applications"))
    run("hdiutil", "create", "-volname", "Khoi Phuc File", "-srcfolder", stage, "-ov", "-format", "UDZO",
        target(f"macos-{machine()}.dmg"))


def package_linux() -> None:
    import deb

    architecture = {"x64": "amd64"}.get(machine(), machine())
    deb.build_deb(deb.app_tree(APP, HERE, PNG), target(f"linux-{architecture}.deb"), __version__, architecture,
                  f"{DEVELOPER} <{EMAIL}>")
    folder = f"KhoiPhucFile-{__version__}-linux-{machine()}"
    deb.build_tar(APP, HERE, PNG, target(f"linux-{machine()}.tar.gz"), folder)


def package_wheel() -> None:
    run(sys.executable, "-m", "build", "--wheel", "--outdir", OUT, ROOT, stdout=subprocess.DEVNULL)
    shutil.rmtree(os.path.join(ROOT, "build"), ignore_errors=True)
    shutil.rmtree(os.path.join(ROOT, "khoiphucfile.egg-info"), ignore_errors=True)


def checksums() -> None:
    lines = []
    for name in sorted(os.listdir(OUT)):
        if name != "SHA256SUMS.txt":
            with open(os.path.join(OUT, name), "rb") as handle:
                lines.append(f"{hashlib.sha256(handle.read()).hexdigest()}  {name}")
            print(f"{os.path.getsize(os.path.join(OUT, name)) / 1e6:8.1f} MB  {name}")
    with open(os.path.join(OUT, "SHA256SUMS.txt"), "w", encoding="utf-8", newline="\n") as out:
        out.write("\n".join(lines) + "\n")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    freeze()
    smoke_test()
    {"win32": package_windows, "darwin": package_macos}.get(sys.platform, package_linux)()
    package_wheel()
    checksums()


if __name__ == "__main__":
    main()
