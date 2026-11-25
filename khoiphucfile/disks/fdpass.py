"""Nhận file descriptor do một tiến trình có quyền cao hơn mở hộ (pkexec, authopen)."""

from __future__ import annotations

import socket
import subprocess

from .common import AccessDenied


def open_through(command: list[str], denied_message: str) -> int:
    """Chạy command với stdout là một Unix socket và chờ nó gửi về descriptor của ổ đĩa."""
    ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with ours:
        try:
            with theirs:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=theirs, stderr=subprocess.PIPE)
        except OSError as error:
            raise AccessDenied(f"{denied_message} ({error})") from None
        received: list[int] = []
        while not received:
            data, fds, _, _ = socket.recv_fds(ours, 256, 1)
            received += fds
            if not data and not fds:
                break
    detail = process.communicate()[1].decode("utf-8", "replace").strip()
    if not received:
        last_line = detail.splitlines()[-1] if detail else ""
        raise AccessDenied(f"{denied_message} ({last_line})" if last_line else denied_message)
    return received[0]
