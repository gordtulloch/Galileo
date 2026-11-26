# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Library > Masters: view the master calibration frames, recreate one or delete one (LIB-240)."""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from galileo.library.config import load_config as load_library_config
from galileo.library.core import master_actions
from galileo.library.models import Masters
from galileo.ui.library._worker import run_in_worker

logger = logging.getLogger(__name__)

TYPE_LABELS = {"bias": "Bias", "dark": "Dark", "flat": "Flat", "flatdark": "Flat-dark"}
COLUMNS = ["Type", "Created", "Telescope", "Camera", "Filter", "Exposure (s)", "Binning", "Temp (°C)",
           "Gain", "Offset", "Frames", "File"]


def _values(master: Masters) -> list[str]:
    binning = f"{master.binning_x}x{master.binning_y}" if master.binning_x and master.binning_y else ""
    created = master.creation_date.strftime("%Y-%m-%d %H:%M") if master.creation_date else ""
    name = os.path.basename(master.master_path)
    if not os.path.exists(master.master_path):
        name += " (missing)"
    cells = [TYPE_LABELS.get(master.master_type, master.master_type), created, master.telescope,
             master.instrument, master.filter_name, master.exposure_time, binning, master.ccd_temp,
             master.gain, master.offset, master.file_count or None, name]
    return ["" if c is None else str(c) for c in cells]


class MastersWidget(QWidget):
    """A table of masters with View, Recreate and Delete for the selected one."""

    masters_changed = Signal()
    _progress = Signal(int, str)       # emitted from the stacking thread, delivered on the UI thread

    def __init__(self) -> None:
        super().__init__()
        self._busy = False
        self._build_ui()
        self._progress.connect(self._show_progress)
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("Master Frames")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        layout.addWidget(title)

        top = QHBoxLayout()
        top.addWidget(QLabel("Type"))
        self.type_combo = QComboBox()
        self.type_combo.addItem("All types", None)
        for value, label in TYPE_LABELS.items():
            self.type_combo.addItem(label, value)
        self.type_combo.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.type_combo)
        top.addStretch(1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        layout.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(COLUMNS)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.view())
        layout.addWidget(self.tree, 1)

        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        self.details_label.setTextFormat(Qt.TextFormat.PlainText)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        buttons = QHBoxLayout()
        self.status_label = QLabel()
        self.view_button = QPushButton("View")
        self.view_button.clicked.connect(self.view)
        self.recreate_button = QPushButton("Recreate")
        self.recreate_button.clicked.connect(self.recreate)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete)
        buttons.addWidget(self.status_label, 1)
        buttons.addWidget(self.view_button)
        buttons.addWidget(self.recreate_button)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)

    def showEvent(self, event) -> None:
        if not self._busy:
            self.refresh()       # the Calibration and Sessions screens also make masters
        super().showEvent(event)

    def refresh(self, *_) -> None:
        selected = self.selected_id()
        wanted = self.type_combo.currentData()
        try:
            masters = [m for m in master_actions.list_masters() if wanted is None or m.master_type == wanted]
        except Exception:
            logger.exception("Could not read the masters")
            self.status_label.setText("Could not read the masters; see the log.")
            return
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for master in masters:
            item = QTreeWidgetItem(_values(master))
            item.setData(0, Qt.ItemDataRole.UserRole, master.id)
            self.tree.addTopLevelItem(item)
        self.tree.setSortingEnabled(True)
        for column in range(len(COLUMNS) - 1):
            self.tree.resizeColumnToContents(column)
        if selected is not None:
            self.select(selected)
        if not self._busy:
            self.status_label.setText(f"{len(masters)} master(s)")
        self._selection_changed()

    def select(self, master_id: int) -> None:
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == master_id:
                self.tree.setCurrentItem(item)
                return

    def selected_id(self) -> int | None:
        items = self.tree.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _selected(self) -> Masters | None:
        master_id = self.selected_id()
        return None if master_id is None else Masters.get_or_none(Masters.id == master_id)

    def _selection_changed(self) -> None:
        master = self._selected()
        blocker = None
        if master is None:
            self.details_label.setText("Select a master to see its details.")
        else:
            blocker = master_actions.recreate_blocker(master)
            lines = [f"File: {master.master_path}",
                     f"Source session: {master.source_session_id or 'none (imported)'}"]
            if master.source_session_id:
                present, catalogued = master_actions.source_frames(master)
                lines.append(f"Source frames on disk: {len(present)} of {catalogued}")
            if blocker:
                lines.append(blocker)
            self.details_label.setText("\n".join(lines))
        idle = master is not None and not self._busy
        self.view_button.setEnabled(master is not None and os.path.exists(master.master_path))
        self.recreate_button.setEnabled(idle and blocker is None)
        self.delete_button.setEnabled(idle)

    def view(self) -> None:
        """Open the selected master in the external FITS viewer."""
        master = self._selected()
        if master is None:
            return
        if not os.path.exists(master.master_path):
            QMessageBox.warning(self, "File Not Found", f"Master file not found:\n{master.master_path}")
            return
        try:
            from galileo.ui.library.viewer import open_fits_file
            open_fits_file(master.master_path,
                           load_library_config().get("DEFAULT", "fits_viewer_path", fallback=None))
        except Exception as exc:
            logger.exception("Could not open the master")
            QMessageBox.critical(self, "Error", f"Failed to open the master:\n{exc}")

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(
            self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def recreate(self) -> None:
        master = self._selected()
        if master is None or self._busy:
            return
        present, catalogued = master_actions.source_frames(master)
        text = (f"Stack this {TYPE_LABELS.get(master.master_type, master.master_type)} master again from "
                f"{len(present)} source frames? The current file is replaced.")
        if len(present) < catalogued:
            text += f"\n\n{catalogued - len(present)} of the catalogued frames are no longer on disk."
        if not self._confirm("Recreate master", text):
            return
        master_id = master.id
        self._set_busy(True)
        self.status_label.setText("Recreating...")

        def progress(value, total, message) -> None:
            self._progress.emit(int(value * 100 / total) if total else 0, message)

        run_in_worker(self, lambda: master_actions.recreate_master(master_id, progress),
                      lambda _result: self._recreated(master_id), self._recreate_failed)

    def _show_progress(self, percent: int, message: str) -> None:
        if self._busy:
            self.progress_bar.setValue(percent)
            self.status_label.setText(message)

    def _recreated(self, master_id: int) -> None:
        self._set_busy(False)
        self.refresh()
        self.select(master_id)
        self.status_label.setText("Master recreated")
        self.masters_changed.emit()

    def _recreate_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.refresh()
        self.status_label.setText("Recreation failed")
        QMessageBox.warning(self, "Recreate master", str(error))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(busy)
        self.tree.setEnabled(not busy)
        self.type_combo.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self._selection_changed()

    def delete(self) -> None:
        master = self._selected()
        if master is None or self._busy:
            return
        if not self._confirm("Delete master",
                             f"Permanently delete this master and its file?\n\n{master.master_path}\n\n"
                             "The frames it was built from are not changed."):
            return
        try:
            master_actions.delete_master(master.id)
        except Exception as exc:
            logger.exception("Could not delete the master")
            QMessageBox.warning(self, "Delete master", str(exc))
            return
        self.refresh()
        self.status_label.setText("Master deleted")
        self.masters_changed.emit()
