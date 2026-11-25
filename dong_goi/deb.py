"""Tạo gói .deb và .tar.gz cho Linux bằng Python thuần (không cần dpkg)."""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
import time

INSTALL_DIR = "opt/khoiphucfile"
DEPENDS = ("libc6 (>= 2.28), libgl1, libegl1, libxkbcommon0, libxkbcommon-x11-0, libdbus-1-3, libfontconfig1, "
           "libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-image0, libxcb-render-util0, libxcb-shape0, "
           "util-linux, pkexec | policykit-1")


class Tree:
    """Nội dung gói: đường dẫn -> (dữ liệu hoặc file nguồn hoặc đích liên kết, quyền)."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[object, int]] = {}
        self.links: dict[str, str] = {}

    def add_file(self, path: str, source: str, mode: int = 0o644) -> None:
        self.files[path] = (source, mode)

    def add_text(self, path: str, text: str, mode: int = 0o644) -> None:
        self.files[path] = (text.encode("utf-8"), mode)

    def add_link(self, path: str, target: str) -> None:
        self.links[path] = target

    def add_folder(self, path: str, folder: str, executables: set[str]) -> None:
        for current, names, files in os.walk(folder):
            inside = os.path.relpath(current, folder).replace(os.sep, "/")
            base = path if inside == "." else f"{path}/{inside}"
            for name in [*names, *files]:
                full = os.path.join(current, name)
                if os.path.islink(full):
                    self.add_link(f"{base}/{name}", os.readlink(full))
                elif name in files:
                    relative = os.path.relpath(full, folder).replace(os.sep, "/")
                    self.add_file(f"{base}/{name}", full, 0o755 if relative in executables else 0o644)

    def write(self, archive: tarfile.TarFile, prefix: str) -> None:
        made: set[str] = set()

        def parents(path: str) -> None:
            parts = path.split("/")[:-1]
            for count in range(1, len(parts) + 1):
                folder = "/".join(parts[:count])
                if folder and folder not in made:
                    made.add(folder)
                    info = self._info(prefix + folder, 0o755)
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)

        for path in sorted([*self.files, *self.links]):
            parents(path)
            if path in self.links:
                info = self._info(prefix + path, 0o777)
                info.type, info.linkname = tarfile.SYMTYPE, self.links[path]
                archive.addfile(info)
                continue
            source, mode = self.files[path]
            info = self._info(prefix + path, mode)
            data = source if isinstance(source, bytes) else read(source)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

    @staticmethod
    def _info(name: str, mode: int) -> tarfile.TarInfo:
        info = tarfile.TarInfo(name)
        info.mode, info.mtime, info.uname, info.gname = mode, int(time.time()), "root", "root"
        return info

    def installed_kilobytes(self) -> int:
        total = sum(len(source) if isinstance(source, bytes) else os.path.getsize(source)
                    for source, _ in self.files.values())
        return total // 1024 + 1

    def md5sums(self) -> str:
        return "".join(f"{hashlib.md5(source if isinstance(source, bytes) else read(source)).hexdigest()}  {path}\n"
                       for path, (source, _) in sorted(self.files.items()))


def read(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def app_tree(dist: str, here: str, icon: str) -> Tree:
    """Cây thư mục cài đặt: dùng chung cho .deb và install.sh."""
    tree = Tree()
    tree.add_folder(INSTALL_DIR, dist, {"khoiphucfile", "khoiphuc"})
    tree.add_file("usr/share/applications/khoiphucfile.desktop", os.path.join(here, "linux", "khoiphucfile.desktop"))
    tree.add_file("usr/share/polkit-1/actions/vn.vinbs.khoiphucfile.policy",
                  os.path.join(here, "linux", "vn.vinbs.khoiphucfile.policy"))
    tree.add_file("usr/share/icons/hicolor/256x256/apps/khoiphucfile.png", icon)
    tree.add_link("usr/bin/khoiphucfile", "/opt/khoiphucfile/khoiphucfile")
    tree.add_link("usr/bin/khoiphuc", "/opt/khoiphucfile/khoiphuc")
    return tree


def tar_gz(write) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.GNU_FORMAT, compresslevel=9) as archive:
        write(archive)
    return buffer.getvalue()


def build_deb(tree: Tree, target: str, version: str, architecture: str, maintainer: str) -> None:
    control = Tree()
    control.add_text("control", (
        f"Package: khoiphucfile\nVersion: {version}\nSection: utils\nPriority: optional\n"
        f"Architecture: {architecture}\nMaintainer: {maintainer}\nInstalled-Size: {tree.installed_kilobytes()}\n"
        f"Depends: {DEPENDS}\nDescription: Khôi Phục File - cứu file từ ổ đĩa\n"
        " Cứu ảnh, video, âm thanh và tài liệu từ ổ đĩa đã xoá, format hoặc bị ghi đè.\n"
        " Chỉ đọc ổ nguồn, không gửi dữ liệu ra ngoài.\n"))
    control.add_text("md5sums", tree.md5sums())
    members = (("debian-binary", b"2.0\n"),
               ("control.tar.gz", tar_gz(lambda archive: control.write(archive, "./"))),
               ("data.tar.gz", tar_gz(lambda archive: tree.write(archive, "./"))))
    with open(target, "wb") as out:
        out.write(b"!<arch>\n")
        for name, data in members:
            out.write(f"{name:<16}{int(time.time()):<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n".encode("ascii"))
            out.write(data + (b"\n" if len(data) % 2 else b""))


def build_tar(dist: str, here: str, icon: str, target: str, folder: str) -> None:
    """Bản nén cho mọi bản phân phối: chạy thẳng, hoặc cài bằng install.sh."""
    tree = Tree()
    tree.add_folder("khoiphucfile", dist, {"khoiphucfile", "khoiphuc"})
    for name, mode in (("install.sh", 0o755), ("uninstall.sh", 0o755), ("khoiphucfile.desktop", 0o644),
                       ("vn.vinbs.khoiphucfile.policy", 0o644)):
        tree.add_file(name, os.path.join(here, "linux", name), mode)
    tree.add_file("khoiphucfile.png", icon)
    with open(target, "wb") as out:
        out.write(tar_gz(lambda archive: tree.write(archive, folder + "/")))
