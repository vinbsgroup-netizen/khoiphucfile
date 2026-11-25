"""Luồng chạy phiên quét, báo tiến độ về giao diện."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal

from ..scanner import load_report
from ..session import WRITE_ERROR, Options, Outcome, Refused, Session


class ScanThread(QThread):
    opened = Signal(object, list)
    progress = Signal(object)
    rows = Signal(list)
    refused = Signal(str)
    ended = Signal(object)

    def __init__(self, options: Options, parent=None):
        super().__init__(parent)
        self.options = options
        self.session: Session | None = None
        self.stopping = False

    def stop(self) -> None:
        self.stopping = True
        if self.session:
            self.session.cancel()

    def run(self) -> None:
        try:
            session = self.session = Session(self.options)
            if self.stopping:
                session.cancel()
            # Đọc báo cáo cũ trước khi quét: đọc sau sẽ lẫn cả những dòng vừa ghi thêm.
            self.opened.emit(session, load_report(session.out_dir) if session.resumed else [])
            outcome = session.run(self.progress.emit, self.rows.emit, interval=0.3)
        except Refused as error:
            self.refused.emit(str(error))
            return
        except Exception as error:
            traceback.print_exc()
            if self.session is None:
                self.refused.emit(f"Không bắt đầu được: {error!r}")
                return
            outcome = Outcome(WRITE_ERROR, f"Lỗi không lường trước: {error!r}. Tiến độ gần nhất đã được giữ lại.")
        self.ended.emit(outcome)
