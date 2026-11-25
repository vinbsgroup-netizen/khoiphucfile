"""Giữ máy không tự ngủ trong lúc quét (một lần quét có thể kéo dài nhiều giờ)."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


@contextlib.contextmanager
def keep_awake():
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        try:
            yield
        finally:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        return

    command = inhibitor_command()
    helper = None
    if shutil.which(command[0]):
        with contextlib.suppress(OSError):
            helper = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
    try:
        yield
    finally:
        if helper:
            helper.terminate()
            helper.wait()


def inhibitor_command() -> list[str]:
    """Lệnh chặn ngủ tự kết thúc cùng ứng dụng, kể cả khi ứng dụng bị tắt đột ngột."""
    pid = str(os.getpid())
    if sys.platform == "darwin":
        return ["caffeinate", "-i", "-w", pid]
    return ["systemd-inhibit", "--what=idle:sleep", "--who=Khoi Phuc File", "--why=Dang quet o dia",
            "tail", f"--pid={pid}", "-f", "/dev/null"]
