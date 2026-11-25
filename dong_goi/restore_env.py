"""Bản đóng gói trên Linux tự đặt LD_LIBRARY_PATH; trả lại như cũ để lsblk, pkexec, xdg-open không nạp nhầm thư viện."""

import os
import sys

if sys.platform.startswith("linux"):
    original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is not None:
        os.environ["LD_LIBRARY_PATH"] = original
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)
