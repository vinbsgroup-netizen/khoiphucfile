"""Từ icons/nguon.png (1024x1024, nền trong suốt) xuất ra png, ico (Windows) và icns (macOS).

Muốn đổi biểu tượng: thay icons/nguon.png rồi chạy lại file này.
"""

import os
import struct
import sys

from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPolygonF

HERE = os.path.dirname(os.path.abspath(__file__))
ICONS = os.path.join(HERE, "icons")
GUI = os.path.join(os.path.dirname(HERE), "khoiphucfile", "gui")
MAC_SCALE = 0.82


def draw(size: int, scale: float = 1.0) -> QImage:
    source = QImage(os.path.join(ICONS, "nguon.png")).convertToFormat(QImage.Format_ARGB32_Premultiplied)
    inner = round(size * scale)
    while source.width() >= inner * 2:
        source = source.scaled(source.width() // 2, source.height() // 2, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    picture = source.scaled(inner, inner, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.drawImage((size - inner) // 2, (size - inner) // 2, picture)
    painter.end()
    return image


def png(size: int, scale: float = 1.0) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    draw(size, scale).save(buffer, "PNG")
    return bytes(buffer.data())


def draw_mark(kind: str, color: str, size: int = 64) -> QImage:
    """Dấu chọn cho ô đánh dấu: check (đã chọn) hoặc dash (chọn một phần)."""
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 16, size / 16)
    painter.setPen(QPen(QColor(color), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    points = [QPointF(4, 8.4), QPointF(7, 11.2), QPointF(12, 5)] if kind == "check" else [QPointF(4.5, 8), QPointF(11.5, 8)]
    painter.drawPolyline(QPolygonF(points))
    painter.end()
    return image


def write_ico(path: str) -> None:
    images = [(size, png(size)) for size in (16, 24, 32, 48, 64, 128, 256)]
    offset = 6 + 16 * len(images)
    directory, body = b"", b""
    for size, data in images:
        directory += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset + len(body))
        body += data
    with open(path, "wb") as out:
        out.write(struct.pack("<HHH", 0, 1, len(images)) + directory + body)


def write_icns(path: str) -> None:
    """Biểu tượng macOS chừa lề quanh hình theo chuẩn của Apple."""
    kinds = ((b"icp4", 16), (b"icp5", 32), (b"icp6", 64), (b"ic07", 128), (b"ic08", 256), (b"ic09", 512),
             (b"ic10", 1024), (b"ic11", 32), (b"ic12", 64), (b"ic13", 256), (b"ic14", 512))
    body = b""
    for kind, size in kinds:
        data = png(size, MAC_SCALE)
        body += kind + struct.pack(">I", len(data) + 8) + data
    with open(path, "wb") as out:
        out.write(b"icns" + struct.pack(">I", len(body) + 8) + body)


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
    write_ico(os.path.join(ICONS, "khoiphucfile.ico"))
    write_icns(os.path.join(ICONS, "khoiphucfile.icns"))
    for target in (os.path.join(ICONS, "khoiphucfile.png"), os.path.join(GUI, "icon.png")):
        with open(target, "wb") as out:
            out.write(png(256))
    for theme, color in (("light", "#FFFFFF"), ("dark", "#04162E")):
        for kind in ("check", "dash"):
            draw_mark(kind, color).save(os.path.join(GUI, f"{kind}_{theme}.png"))
    app.quit()


if __name__ == "__main__":
    main()
