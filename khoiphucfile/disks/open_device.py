"""Chạy bằng quyền root: mở một ổ đĩa CHỈ ĐỌC rồi trao descriptor cho tiến trình cha qua stdout.

File này đứng một mình (không import gì của ứng dụng) để phần chạy quyền root càng nhỏ càng tốt.
"""

import os
import socket
import stat
import sys


def send_device(path: str, out_fd: int = 1) -> int:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        if not stat.S_ISBLK(os.fstat(fd).st_mode):
            print(f"{path} không phải ổ đĩa", file=sys.stderr)
            return 2
        os.set_blocking(fd, True)
        with socket.socket(fileno=os.dup(out_fd)) as channel:
            socket.send_fds(channel, [b"1"], [fd])
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("cần đúng một đường dẫn ổ đĩa")
    try:
        sys.exit(send_device(sys.argv[1]))
    except OSError as problem:
        sys.exit(str(problem))
