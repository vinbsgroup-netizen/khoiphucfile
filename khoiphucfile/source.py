"""Đọc thô ổ đĩa hoặc file ảnh đĩa: chỉ đọc, có cache, chịu được vùng đọc lỗi."""

from __future__ import annotations

import os
from collections import OrderedDict

SECTOR = 512
ALIGN = 4096
BLOCK = 1 << 20
READ_UNIT = 32 << 20
MB = 1 << 20
GB = 1_000_000_000


class Stopped(Exception):
    """Người dùng bấm dừng."""


class SourceLost(Exception):
    """Ổ nguồn không còn đọc được nữa (rút dây, mất điện, ổ chết hẳn)."""


class Source:
    """Đọc theo khối 32 MB; vùng lỗi trả về số 0 và được đếm vào bad_bytes.

    Ổ USB tốn phí cố định cho mỗi lần đọc: khối 1 MB chỉ được ~6 MB/s, khối 32 MB ~28 MB/s.
    """

    RETRY_STEPS = (1 << 20, 64 << 10, ALIGN)

    def __init__(self, path: str, fileobj=None, size: int | None = None,
                 unit: int = READ_UNIT, cache_blocks: int = 8):
        self.path = path
        self.file = fileobj if fileobj is not None else open(path, "rb", buffering=0)
        self.size = size if size is not None else os.fstat(self.file.fileno()).st_size
        self.unit = unit
        self.cache: OrderedDict[int, bytes] = OrderedDict()
        self.cache_blocks = cache_blocks
        self.bad_bytes = 0
        self.cancelled = False
        self._last_good: int | None = None

    def close(self) -> None:
        self.file.close()

    def cancel(self) -> None:
        """Gọi được từ luồng khác; lần đọc kế tiếp sẽ ném Stopped."""
        self.cancelled = True

    def read(self, offset: int, length: int) -> bytes:
        end = min(offset + length, self.size)
        if offset < 0 or offset >= end:
            return b""
        pieces = []
        pos = offset
        while pos < end:
            index = pos // self.unit
            base = index * self.unit
            block = self._block(index)
            piece = block[pos - base:min(len(block), end - base)]
            if not piece:
                break
            pieces.append(piece)
            pos += len(piece)
        return pieces[0] if len(pieces) == 1 else b"".join(pieces)

    def copy_to(self, offset: int, size: int, path: str) -> None:
        with open(path, "wb") as out:
            pos, end = offset, offset + size
            while pos < end:
                n = min(BLOCK - pos % BLOCK, end - pos)
                out.write(self.read(pos, n))
                pos += n

    def _block(self, index: int) -> bytes:
        block = self.cache.get(index)
        if block is not None:
            self.cache.move_to_end(index)
            return block
        start = index * self.unit
        end = min(start + self.unit, self.size)
        bad_before = self.bad_bytes
        block = self._fill(start, end, self.RETRY_STEPS)
        if self.bad_bytes - bad_before == end - start and not self._alive():
            self.bad_bytes = bad_before
            raise SourceLost(self.path)
        self.cache[index] = block
        if len(self.cache) > self.cache_blocks:
            self.cache.popitem(last=False)
        return block

    def _fill(self, start: int, end: int, steps: tuple[int, ...]) -> bytes:
        """Đọc [start, end); đoạn lỗi được chia nhỏ dần, tới 4 KB vẫn lỗi thì thay bằng số 0."""
        if self.cancelled:
            raise Stopped
        try:
            return self._read_exact(start, end)
        except OSError:
            while steps and steps[0] >= end - start:
                steps = steps[1:]
            if not steps:
                self.bad_bytes += end - start
                return bytes(end - start)
            step = steps[0]
            return b"".join(self._fill(at, min(at + step, end), steps[1:]) for at in range(start, end, step))

    def _read_exact(self, start: int, end: int) -> bytes:
        """Đọc đủ [start, end). Linux trả về thiếu khi gặp sector hỏng nên phải đọc tiếp cho tới khi báo lỗi."""
        pieces = []
        pos = start
        self.file.seek(start)
        while pos < end:
            piece = self.file.read(end - pos)
            if not piece:
                raise OSError("đọc thiếu")
            pieces.append(piece)
            pos += len(piece)
        self._last_good = start
        return pieces[0] if len(pieces) == 1 else b"".join(pieces)

    def _alive(self) -> bool:
        """Cả khối 32 MB đều lỗi: do vùng hỏng hay do ổ đã bị rút? Thử lại một chỗ từng đọc được."""
        if self.path.startswith("/dev/") and not os.path.exists(self.path):
            return False
        for at in {0, self._last_good or 0}:
            try:
                self.file.seek(at)
                if self.file.read(min(ALIGN, self.size - at)):
                    return True
            except OSError:
                continue
        return False
