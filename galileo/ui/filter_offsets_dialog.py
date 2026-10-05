# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Filter Offsets dialog (EQP-FW-020, FOC-060), opened from the Focus screen's
Filter Offsets button.

One row per filter the connected filter wheel reports: a Primary checkbox
(exactly one filter at a time — the offset baseline), a Select checkbox
(which filters Start measures this run), four Measurement columns and a
Result column. Start moves the wheel to the first checked filter, runs four
autofocus sweeps there, averages their best-focus positions, then does the
same for every other checked filter in turn; each non-Primary filter's
Result is the Primary filter's average minus its own — the focuser move
``apply_filter_offset`` (``galileo.autofocus.AutofocusService``) applies on a
later filter change to maintain focus without a full autofocus run.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_COLUMNS = ["Filter", "Primary", "Select", "M1", "M2", "M3", "M4", "Result"]
_COL_FILTER, _COL_PRIMARY, _COL_SELECT, _COL_M1 = 0, 1, 2, 3
_COL_RESULT = len(_COLUMNS) - 1
_NUM_RUNS = 4


def _centered_checkbox() -> tuple[QWidget, QCheckBox]:
    cell = QWidget()
    layout = QHBoxLayout(cell)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    box = QCheckBox()
    layout.addWidget(box)
    return cell, box


class FilterOffsetsDialog(QDialog):
    """Measures each selected filter's focus offset relative to the Pier's
    Primary filter. ESC, the title bar's X and the Close button are all
    refused while a run is in progress — mirrors ``_FlatsDialog``, since a
    background worker thread here is likewise still updating this dialog's
    own widgets through connected signals."""

    _measured = Signal(int, int, object)       # (row, column, value-or-None)
    _filter_started = Signal(int, str)         # (row, filter_name)
    _finished = Signal()
    _failed = Signal(str)

    def __init__(self, focus_page) -> None:
        super().__init__(focus_page._window._window)
        self._focus_page = focus_page
        self.running = False
        self._stop_requested = False
        self._service = None
        self.setWindowTitle("Filter Offsets")
        self.setMinimumWidth(640)
        self._build()
        self._measured.connect(self._on_measured)
        self._filter_started.connect(self._on_filter_started)
        self._finished.connect(self._on_finished)
        self._failed.connect(self._on_failed)
        self._reload()

    def reject(self) -> None:
        if self.running:
            return
        super().reject()

    # --- Layout ---------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_FILTER, QHeaderView.ResizeMode.Stretch)
        for column in range(_COL_PRIMARY, len(_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        outer.addWidget(self.table)

        self.status_label = QLabel(
            "Check Primary for the baseline filter, Select for every filter to measure, then Start."
        )
        self.status_label.setObjectName("StatusHint")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        button_row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("AccentButton")
        self.start_btn.clicked.connect(self._start)
        button_row.addWidget(self.start_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        button_row.addWidget(self.stop_btn)
        button_row.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        button_row.addWidget(self.buttons)
        outer.addLayout(button_row)

    # --- Row population ---------------------------------------------------

    def _reload(self) -> None:
        """One row per filter the connected wheel reports, seeded from this
        Pier's saved offset state, if any."""
        wheel = self._focus_page._filter_wheel()
        names = [str(n) for n in (getattr(wheel, "filter_names", None) or [])]
        from galileo.observatory import get_filter_offsets
        saved = {o.filter_name: o for o in get_filter_offsets(self._focus_page._window._current_pier)}

        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            offset = saved.get(name)

            item = QTableWidgetItem(name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, _COL_FILTER, item)

            primary_cell, primary_box = _centered_checkbox()
            primary_box.setChecked(bool(offset and offset.is_primary))
            primary_box.toggled.connect(lambda checked, r=row: self._on_primary_toggled(r, checked))
            self.table.setCellWidget(row, _COL_PRIMARY, primary_cell)

            select_cell, _select_box = _centered_checkbox()
            self.table.setCellWidget(row, _COL_SELECT, select_cell)

            measurements = offset.measurements if offset is not None else (None, None, None, None)
            for i, value in enumerate(measurements):
                self._set_cell_text(row, _COL_M1 + i, value)
            self._set_cell_text(row, _COL_RESULT, offset.offset_steps if offset is not None else None, signed=True)

    def _set_cell_text(self, row: int, column: int, value: int | None, signed: bool = False) -> None:
        text = "—" if value is None else (f"{value:+d}" if signed else str(value))
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, column, item)

    def _primary_box(self, row: int) -> QCheckBox:
        return self.table.cellWidget(row, _COL_PRIMARY).findChild(QCheckBox)

    def _select_box(self, row: int) -> QCheckBox:
        return self.table.cellWidget(row, _COL_SELECT).findChild(QCheckBox)

    def _on_primary_toggled(self, row: int, checked: bool) -> None:
        """Exactly one filter can be Primary — the offset calculation needs
        one unambiguous baseline. Checking one here unchecks every other
        row and persists immediately, matching this app's other per-Pier
        settings (no separate Save button)."""
        if checked:
            for other in range(self.table.rowCount()):
                if other != row:
                    box = self._primary_box(other)
                    box.blockSignals(True)
                    box.setChecked(False)
                    box.blockSignals(False)
        pier = self._focus_page._window._current_pier
        if pier is None:
            return
        filter_name = self.table.item(row, _COL_FILTER).text()
        from galileo.autofocus import FilterOffset
        from galileo.observatory import get_filter_offsets, save_filter_offset
        existing = next((o for o in get_filter_offsets(pier) if o.filter_name == filter_name), None)
        save_filter_offset(pier, FilterOffset(
            filter_name=filter_name, is_primary=checked,
            measurements=existing.measurements if existing is not None else (None, None, None, None),
            offset_steps=existing.offset_steps if existing is not None else None,
        ))

    # --- Running -----------------------------------------------------------

    def _set_running(self, running: bool) -> None:
        self.running = running
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setEnabled(not running)
        for row in range(self.table.rowCount()):
            self._primary_box(row).setEnabled(not running)
            self._select_box(row).setEnabled(not running)

    def _start(self) -> None:
        focus_page = self._focus_page
        pier = focus_page._window._current_pier
        if pier is None:
            QMessageBox.information(self, "No Pier selected", "Select (or create) an Observatory and Pier first.")
            return
        camera, focuser, wheel = focus_page._camera(), focus_page._focuser(), focus_page._filter_wheel()
        missing = [n for n, d in (("camera", camera), ("focuser", focuser), ("filter wheel", wheel)) if d is None]
        if missing:
            QMessageBox.information(
                self, "Equipment not connected",
                f"Connect a {' and a '.join(missing)} on the Equipment pages first.",
            )
            return
        rows = [row for row in range(self.table.rowCount()) if self._select_box(row).isChecked()]
        if not rows:
            QMessageBox.information(self, "Nothing selected", 'Check "Select" for at least one filter to measure.')
            return

        self._stop_requested = False
        self._set_running(True)
        self.status_label.setText("Starting…")
        threading.Thread(
            target=self._worker, args=(camera, focuser, wheel, pier, rows),
            name="filter-offsets", daemon=True,
        ).start()

    def _stop(self) -> None:
        self._stop_requested = True
        if self._service is not None:
            self._service.cancel()
        self.status_label.setText("Stopping after the current focus run…")

    def _worker(self, camera, focuser, wheel, pier, rows: list[int]) -> None:
        import asyncio

        from galileo.autofocus import AutofocusService, FilterOffset
        from galileo.observatory import get_autofocus_params, get_primary_filter, save_filter_offset

        params = get_autofocus_params(pier)
        names = [str(n) for n in (getattr(wheel, "filter_names", None) or [])]
        selection = [(row, self.table.item(row, _COL_FILTER).text(), self._primary_box(row).isChecked())
                     for row in rows]

        # The Primary filter's average, used as every other filter's baseline: measured this
        # run if it's one of the checked rows, else whatever was saved from an earlier run.
        primary_avg = None
        primary_in_selection = next((name for _, name, is_primary in selection if is_primary), None)
        if primary_in_selection is None:
            existing_primary = get_primary_filter(pier)
            if existing_primary is not None:
                primary_avg = existing_primary.average_position

        try:
            for row, filter_name, is_primary in selection:
                if self._stop_requested:
                    break
                self._filter_started.emit(row, filter_name)
                if filter_name in names:
                    index = names.index(filter_name)
                    if getattr(wheel, "position", None) != index:
                        asyncio.run(wheel.move_to(index))

                measurements: list[int | None] = []
                for _run in range(_NUM_RUNS):
                    if self._stop_requested:
                        break
                    service = AutofocusService(
                        camera=camera, focuser=focuser, exposure_s=params.exposure_s,
                        backlash_compensation=params.backlash_compensation, pier_key=self._focus_page._pier_key(),
                    )
                    self._service = service
                    result = asyncio.run(service.run(step_size=params.step_size, num_points=params.num_points))
                    self._service = None
                    value = result.best_position if result.success else None
                    measurements.append(value)
                    self._measured.emit(row, _COL_M1 + len(measurements) - 1, value)
                measurements += [None] * (_NUM_RUNS - len(measurements))

                average = FilterOffset(filter_name, measurements=tuple(measurements)).average_position
                if is_primary:
                    primary_avg = average
                    offset_steps = 0 if average is not None else None
                elif average is not None and primary_avg is not None:
                    offset_steps = primary_avg - average
                else:
                    offset_steps = None

                save_filter_offset(pier, FilterOffset(
                    filter_name=filter_name, is_primary=is_primary,
                    measurements=tuple(measurements), offset_steps=offset_steps,
                ))
                self._measured.emit(row, _COL_RESULT, offset_steps)
        except Exception as exc:
            logger.exception("Filter Offsets run failed")
            self._failed.emit(str(exc))
            return
        self._finished.emit()

    # --- Worker-thread signal handlers (UI thread) --------------------------

    def _on_measured(self, row: int, column: int, value) -> None:
        self._set_cell_text(row, column, value, signed=(column == _COL_RESULT))

    def _on_filter_started(self, row: int, filter_name: str) -> None:
        self.status_label.setText(f"Measuring {filter_name} — {_NUM_RUNS} focus runs…")

    def _on_finished(self) -> None:
        self._set_running(False)
        self.status_label.setText("Stopped." if self._stop_requested else "Done.")

    def _on_failed(self, message: str) -> None:
        self._set_running(False)
        self.status_label.setText(f"Failed: {message}")
