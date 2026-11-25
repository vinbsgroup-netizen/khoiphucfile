"""Đọc ảnh thu nhỏ ở luồng phụ, có cache; chỉ làm những ảnh đang hiện trên màn hình."""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QObject, QRect, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap

PREVIEWABLE = {"jpg", "png", "gif", "bmp", "webp"}


def read_image(path: str, box: int) -> QImage:
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > box:
        reader.setScaledSize(size.scaled(QSize(box, box), Qt.KeepAspectRatio))
    return reader.read()


def on_square(pixmap: QPixmap, box: int) -> QPixmap:
    """Đặt ảnh vào giữa ô vuông để mọi ô trong lưới cao bằng nhau."""
    square = QPixmap(box, box)
    square.fill(Qt.transparent)
    painter = QPainter(square)
    painter.drawPixmap((box - pixmap.width()) // 2, (box - pixmap.height()) // 2, pixmap)
    painter.end()
    return square


def extension_tile(text: str, box: int, background: str, foreground: str) -> QPixmap:
    square = QPixmap(box, box)
    square.fill(Qt.transparent)
    painter = QPainter(square)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(background))
    tile = QRect(box // 6, box // 8, box * 2 // 3, box * 3 // 4)
    painter.drawRoundedRect(tile, 8, 8)
    font = painter.font()
    font.setPixelSize(box // 6)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(foreground))
    painter.drawText(tile, Qt.AlignCenter, text.upper())
    painter.end()
    return square


class _Job(QRunnable):
    def __init__(self, loader: "ThumbLoader"):
        super().__init__()
        self.loader = loader

    def run(self) -> None:
        path = self.loader.take()
        if path is not None:
            image = read_image(path, self.loader.box)
            try:
                self.loader.loaded.emit(path, image)
            except RuntimeError:
                pass


class ThumbLoader(QObject):
    """Ảnh được yêu cầu sau cùng đọc trước; cuộn nhanh thì các yêu cầu cũ bị bỏ."""

    loaded = Signal(str, QImage)
    ready = Signal(str)

    def __init__(self, box: int, capacity: int = 800, max_waiting: int = 120, square: bool = False, parent=None):
        super().__init__(parent)
        self.box = box
        self.square = square
        self.capacity = capacity
        self.max_waiting = max_waiting
        self.cache: OrderedDict[str, QPixmap] = OrderedDict()
        self.waiting: list[str] = []
        self.pending: set[str] = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.loaded.connect(self._store)

    def get(self, path: str) -> QPixmap | None:
        """QPixmap (rỗng khi ảnh hỏng), hoặc None khi còn đang đọc."""
        pixmap = self.cache.get(path)
        if pixmap is not None:
            self.cache.move_to_end(path)
            return pixmap
        if path not in self.pending:
            self.pending.add(path)
            self.waiting.append(path)
            while len(self.waiting) > self.max_waiting:
                self.pending.discard(self.waiting.pop(0))
            self.pool.start(_Job(self))
        return None

    def take(self) -> str | None:
        try:
            return self.waiting.pop()
        except IndexError:
            return None

    def clear(self) -> None:
        self.waiting.clear()
        self.pending.clear()
        self.cache.clear()

    def shutdown(self) -> None:
        self.waiting.clear()
        self.pool.clear()
        self.pool.waitForDone(3000)

    def _store(self, path: str, image: QImage) -> None:
        self.pending.discard(path)
        pixmap = QPixmap.fromImage(image)
        self.cache[path] = on_square(pixmap, self.box) if self.square and not image.isNull() else pixmap
        while len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
        self.ready.emit(path)
