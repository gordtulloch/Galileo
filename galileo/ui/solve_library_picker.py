# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Library frame chooser behind the Solve screen's Load & Slew (PLT-070)."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from galileo.ui.theme import ThemeManager

SHOWN_MAX = 500
_COLUMNS = ("Object", "Date", "Filter", "Exposure", "Telescope", "File")
_KEYS = ("object", "date", "filter", "exposure", "telescope", "name")        # the frame field behind each column
_DATE_COLUMN = _KEYS.index("date")


def _sort_key(text: str) -> tuple:
    """Case-blind, with runs of digits compared as numbers: M 2 before M 31, and 30 s before 120 s."""
    parts = re.split(r"(\d+(?:\.\d+)?)", text.casefold())
    return tuple(float(part) if i % 2 else part for i, part in enumerate(parts))


class _SortedItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        return _sort_key(self.text()) < _sort_key(other.text())


def library_light_frames(text: str = "", limit: int = SHOWN_MAX) -> list[dict[str, str]]:
    """Library light frames, newest first (only these have stars to solve). *text* narrows them by object, file name,
    filter, telescope or date. Soft-deleted frames are left out."""
    from galileo.library.models.base import db
    from galileo.library.models.fits_file import fitsFile

    db.connect(reuse_if_open=True)
    where = fitsFile.fitsFileType.contains("LIGHT") & (
        (fitsFile.fitsFileSoftDelete == False) | fitsFile.fitsFileSoftDelete.is_null())
    for word in text.split():
        where &= (fitsFile.fitsFileObject.contains(word) | fitsFile.fitsFileName.contains(word)
                  | fitsFile.fitsFileFilter.contains(word) | fitsFile.fitsFileTelescop.contains(word)
                  | fitsFile.fitsFileDate.cast("TEXT").contains(word))
    rows = (fitsFile.select().where(where)
            .order_by(fitsFile.fitsFileDate.desc(), fitsFile.fitsFileId.desc()).limit(limit))
    return [{"id": r.fitsFileId, "name": Path(r.fitsFileName or "").name, "object": r.fitsFileObject or "",
             "date": str(r.fitsFileDate or ""), "filter": r.fitsFileFilter or "",
             "exposure": str(r.fitsFileExpTime or ""), "telescope": r.fitsFileTelescop or ""} for r in rows]


class LibraryFrameDialog(QDialog):
    """Pick one Library light frame. After ``exec()`` is accepted, :meth:`selected` is that frame."""

    def __init__(self, parent: QWidget | None = None, theme: ThemeManager | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Load & Slew from the Library")
        self.resize(820, 480)
        self._frames: list[dict[str, str]] = []

        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by object, file name, filter, telescope or date")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        # The selected frame is drawn in inverse video: the theme's text colour behind its background colour, which
        # also holds in the night-vision theme.
        colors = (theme or ThemeManager()).palette()
        self.table.setStyleSheet(
            f"QTableWidget::item:selected {{ background: {colors['text']}; color: {colors['bg']}; }}")
        header.setSortIndicator(_DATE_COLUMN, Qt.SortOrder.DescendingOrder)       # newest first until a header is clicked
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table, 1)

        self.status = QLabel()
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.load_button = buttons.addButton("Load && Slew", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.search.textChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.cellDoubleClicked.connect(lambda *_: self.accept())
        self.refresh()

    def refresh(self) -> None:
        self._frames = library_light_frames(self.search.text())
        self.table.clearSelection()
        self.table.setSortingEnabled(False)               # or rows would move while they are being filled
        self.table.setRowCount(len(self._frames))
        for row, frame in enumerate(self._frames):
            for column, key in enumerate(_KEYS):
                item = _SortedItem(frame[key])
                item.setData(Qt.ItemDataRole.UserRole, row)      # which frame, wherever sorting puts it
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)                # re-sorts by the column last chosen
        if not self._frames:
            self.status.setText("No light frames match." if self.search.text() else "The Library has no light frames.")
        elif len(self._frames) >= SHOWN_MAX:
            self.status.setText(f"Showing the newest {SHOWN_MAX}; search to narrow the list.")
        else:
            self.status.setText(f"{len(self._frames)} frame(s)")
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.load_button.setEnabled(self.selected() is not None)

    def selected(self) -> dict[str, str] | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._frames[self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)]

    def accept(self) -> None:
        if self.selected() is not None:
            super().accept()
