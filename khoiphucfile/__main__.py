"""Không có tham số thì mở giao diện, có tham số thì chạy dòng lệnh."""

import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] != "--smoke-test":
        from khoiphucfile.cli import main as run
    else:
        from khoiphucfile.gui.app import main as run
    return run()


if __name__ == "__main__":
    sys.exit(main())
