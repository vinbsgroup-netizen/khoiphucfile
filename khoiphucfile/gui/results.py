"""Danh sách file cứu được: lọc, sắp xếp, ảnh thu nhỏ và xem trước."""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListView, QPushButton, QSplitter, QStackedWidget, QTableView,
                               QVBoxLayout, QWidget)

from ..formats import GROUP_OF, GROUPS
from ..scanner import FAILED, PARTIAL, WHOLE
from . import theme
from .common import NEVER_OPEN, button, human_size, label, number, open_file, reveal
from .options_page import GROUP_TITLES
from .thumbs import PREVIEWABLE, ThumbLoader, extension_tile

FILE, EXT, OFFSET, SIZE, DATE, STATUS = range(6)
STATUS_TEXT = {WHOLE: "Trọn vẹn", PARTIAL: "Không trọn vẹn", FAILED: "Không ghi được"}
COLUMNS = ("Tên file", "Loại", "Kích thước", "Ngày", "Trạng thái")
THUMB = 128


def show_date(text: str) -> str:
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return text


class FileModel(QAbstractTableModel):
    SORT_KEYS = (lambda row: os.path.basename(row[FILE]), lambda row: row[EXT], lambda row: row[SIZE],
                 lambda row: row[DATE], lambda row: row[STATUS])

    def __init__(self, thumbs: ThumbLoader, parent=None):
        super().__init__(parent)
        self.thumbs = thumbs
        self.tiles: dict[tuple, QPixmap] = {}
        self.thumbnails = False
        self.out_dir = ""
        self.all: list[list] = []
        self.view: list[list] = []
        self.group = ""
        self.status = ""
        self.needle = ""
        self.order: tuple[int, Qt.SortOrder] | None = None
        self.waiting_rows: dict[str, int] = {}
        thumbs.ready.connect(self._thumb_ready)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.view)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.TextAlignmentRole and orientation == Qt.Horizontal:
            return int((Qt.AlignRight if section == 2 else Qt.AlignLeft) | Qt.AlignVCenter)
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.view):
            return None
        row = self.view[index.row()]
        column = index.column()
        if role == Qt.DisplayRole:
            return (os.path.basename(row[FILE]), row[EXT], human_size(row[SIZE]), show_date(row[DATE]),
                    STATUS_TEXT.get(row[STATUS], row[STATUS]))[column]
        if role == Qt.TextAlignmentRole and column == 2:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            return row[FILE]
        if role == Qt.DecorationRole and column == 0 and self.thumbnails:
            return self._thumbnail(index.row(), row)
        return None

    def path_of(self, row: list) -> str:
        return os.path.join(self.out_dir, row[FILE])

    def _thumbnail(self, at: int, row: list):
        if row[EXT] in PREVIEWABLE and row[STATUS] != FAILED:
            path = self.path_of(row)
            pixmap = self.thumbs.get(path)
            if pixmap is None:
                self.waiting_rows[path] = at
            elif not pixmap.isNull():
                return pixmap
        return self._tile(row[EXT])

    def _tile(self, extension: str) -> QPixmap:
        colors = theme.current()
        key = (extension, colors.accent_soft)
        if key not in self.tiles:
            self.tiles[key] = extension_tile(extension, THUMB, colors.accent_soft, colors.accent)
        return self.tiles[key]

    def _thumb_ready(self, path: str) -> None:
        at = self.waiting_rows.pop(path, None)
        if at is not None and at < len(self.view):
            index = self.index(at, 0)
            self.dataChanged.emit(index, index, [Qt.DecorationRole])

    def matches(self, row: list) -> bool:
        return ((not self.group or GROUP_OF.get(row[EXT], "khac") == self.group)
                and (not self.status or row[STATUS] == self.status)
                and (not self.needle or self.needle in row[FILE].lower()))

    def load(self, out_dir: str, rows: list[list]) -> None:
        self.out_dir = out_dir
        self.all = list(rows)
        self.refilter()

    def refilter(self, group: str | None = None, status: str | None = None, needle: str | None = None) -> None:
        self.beginResetModel()
        self.group = self.group if group is None else group
        self.status = self.status if status is None else status
        self.needle = self.needle if needle is None else needle.lower()
        self.waiting_rows.clear()
        self.view = [row for row in self.all if self.matches(row)]
        self._sort_view()
        self.endResetModel()

    def append(self, rows: list[list]) -> None:
        self.all.extend(rows)
        shown = [row for row in rows if self.matches(row)]
        if shown:
            first = len(self.view)
            self.beginInsertRows(QModelIndex(), first, first + len(shown) - 1)
            self.view.extend(shown)
            self.endInsertRows()

    def sort(self, column, order=Qt.AscendingOrder) -> None:
        self.layoutAboutToBeChanged.emit()
        kept = self.persistentIndexList()
        rows = [self.view[index.row()] for index in kept]
        self.order = (column, order) if column >= 0 else None
        self.waiting_rows.clear()
        self._sort_view()
        places = {id(row): at for at, row in enumerate(self.view)} if kept else {}
        self.changePersistentIndexList(kept, [self.index(places[id(row)], index.column())
                                              for row, index in zip(rows, kept)])
        self.layoutChanged.emit()

    def _sort_view(self) -> None:
        if self.order:
            column, order = self.order
            self.view.sort(key=self.SORT_KEYS[column], reverse=order == Qt.DescendingOrder)


class Preview(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "card")
        self.setMinimumWidth(240)
        self.thumbs = ThumbLoader(900, capacity=12, max_waiting=2, parent=self)
        self.thumbs.ready.connect(self._ready)
        self.path = ""
        self.pixmap = QPixmap()
        self.picture = QLabel(alignment=Qt.AlignCenter)
        self.picture.setMinimumSize(1, 160)
        self.name = label("", "section", wrap=True)
        self.name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.details = label("", "muted", wrap=True)
        self.open_button = button("Mở file", lambda: open_file(self.path))
        self.reveal_button = button("Mở thư mục chứa", lambda: reveal(self.path))
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.reveal_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(self.picture, 1)
        layout.addWidget(self.name)
        layout.addWidget(self.details)
        layout.addLayout(buttons)
        self.show_row(None, "")

    def show_row(self, row: list | None, path: str) -> None:
        self.path = path
        self.pixmap = QPixmap()
        self.picture.setPixmap(QPixmap())
        written = row is not None and row[STATUS] != FAILED
        self.open_button.setEnabled(written and row[EXT] not in NEVER_OPEN)
        self.reveal_button.setEnabled(written)
        if row is None:
            self.name.setText("")
            self.details.setText("")
            self.picture.setText("Chọn một file để xem trước")
            return
        self.name.setText(os.path.basename(path))
        lines = [f"{human_size(row[SIZE])}, {STATUS_TEXT.get(row[STATUS], row[STATUS]).lower()}"]
        if row[DATE]:
            lines.append(f"Ngày trong file: {show_date(row[DATE])}")
        lines.append(f"Vị trí trên ổ: byte {number(row[OFFSET])}")
        self.details.setText("\n".join(lines))
        if not written:
            self.picture.setText("File quá lớn so với ổ lưu nên chưa được chép ra")
        elif row[EXT] in PREVIEWABLE:
            self.picture.setText("Đang đọc ảnh…")
            if self.thumbs.get(path) is not None:
                self._ready(path)
        else:
            self.picture.setText("Không có xem trước cho loại file này")

    def _ready(self, path: str) -> None:
        if path != self.path:
            return
        pixmap = self.thumbs.get(path)
        if pixmap is None or pixmap.isNull():
            self.picture.setText("Không đọc được ảnh này" if os.path.exists(path) else "File không còn trong thư mục lưu")
            return
        self.pixmap = pixmap
        self._fit()

    def _fit(self) -> None:
        if not self.pixmap.isNull():
            self.picture.setPixmap(self.pixmap.scaled(self.picture.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()


class ResultsView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.thumbs = ThumbLoader(THUMB, square=True, parent=self)
        self.model = FileModel(self.thumbs, self)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 56), (2, 88), (3, 130), (4, 110)):
            self.table.setColumnWidth(column, width)
        header.setSortIndicator(-1, Qt.AscendingOrder)
        self.table.setSortingEnabled(True)

        self.grid = QListView()
        self.grid.setModel(self.model)
        self.grid.setSelectionModel(self.table.selectionModel())
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setLayoutMode(QListView.Batched)
        self.grid.setBatchSize(1000)
        self.grid.setUniformItemSizes(True)
        self.grid.setIconSize(QSize(THUMB, THUMB))
        self.grid.setGridSize(QSize(THUMB + 30, THUMB + 40))
        self.grid.setTextElideMode(Qt.ElideMiddle)

        self.views = QStackedWidget()
        self.views.addWidget(self.table)
        self.views.addWidget(self.grid)
        self.preview = Preview()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.views)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([660, 300])
        splitter.setChildrenCollapsible(False)

        self.group = QComboBox()
        self.group.addItem("Mọi loại", "")
        for group in GROUPS:
            self.group.addItem(GROUP_TITLES[group], group)
        self.status = QComboBox()
        self.status.addItem("Mọi trạng thái", "")
        for value, text in STATUS_TEXT.items():
            self.status.addItem(text, value)
        self.search = QLineEdit()
        self.search.setObjectName("field")
        self.search.setPlaceholderText("Tìm theo tên, ngày hoặc đuôi file")
        self.search.setClearButtonEnabled(True)
        self.search_timer = QTimer(self, singleShot=True, interval=250)
        self.count = label("", "muted")
        self.list_button = self._toggle("Danh sách", 0)
        self.grid_button = self._toggle("Ảnh thu nhỏ", 1)
        toggles = QButtonGroup(self)
        toggles.addButton(self.list_button)
        toggles.addButton(self.grid_button)
        self.list_button.setChecked(True)

        self.group.currentIndexChanged.connect(self._filter)
        self.status.currentIndexChanged.connect(self._filter)
        self.search.textChanged.connect(lambda _: self.search_timer.start())
        self.search_timer.timeout.connect(self._filter)
        self.table.selectionModel().currentRowChanged.connect(lambda current, _: self._show(current))
        self.model.modelReset.connect(lambda: self._show(QModelIndex()))
        for view in (self.table, self.grid):
            view.activated.connect(self._activate)

        filters = QHBoxLayout()
        filters.addWidget(self.group)
        filters.addWidget(self.status)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.count)
        filters.addWidget(self.list_button)
        filters.addWidget(self.grid_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(filters)
        layout.addWidget(splitter, 1)

    def _toggle(self, text: str, page: int) -> QPushButton:
        widget = QPushButton(text)
        widget.setCheckable(True)
        widget.setProperty("role", "toggle")
        widget.toggled.connect(lambda on: self._switch(page) if on else None)
        return widget

    def _switch(self, page: int) -> None:
        self.model.thumbnails = page == 1
        self.views.setCurrentIndex(page)
        current = self.table.currentIndex()
        if current.isValid():
            (self.grid if page else self.table).scrollTo(current)

    def load(self, out_dir: str, rows: list[list]) -> None:
        self.thumbs.clear()
        self.preview.thumbs.clear()
        self.model.load(out_dir, rows)
        self._update_count()

    def append(self, rows: list[list]) -> None:
        self.model.append(rows)
        self._update_count()

    def shutdown(self) -> None:
        self.thumbs.shutdown()
        self.preview.thumbs.shutdown()

    def _filter(self) -> None:
        self.model.refilter(self.group.currentData(), self.status.currentData(), self.search.text().strip())
        self._update_count()

    def _update_count(self) -> None:
        shown, total = len(self.model.view), len(self.model.all)
        self.count.setText(f"{number(total)} file" if shown == total else f"{number(shown)} / {number(total)} file")

    def _show(self, index) -> None:
        if not index.isValid():
            self.preview.show_row(None, "")
            return
        row = self.model.view[index.row()]
        self.preview.show_row(row, self.model.path_of(row))

    def _activate(self, index) -> None:
        row = self.model.view[index.row()]
        if row[STATUS] != FAILED:
            open_file(self.model.path_of(row))
