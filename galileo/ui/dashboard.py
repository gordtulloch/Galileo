# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Observatory dashboard screen (OBS-060): every Pier's state at a glance.

One row per Pier of the selected Observatory showing its equipment, sequence and
scheduler state (``Observatory.get_dashboard``), in addition to the focused
single-Pier screens. Double-click a row, or press **Open Pier**, to make that
Pier the working one.

The screen refreshes itself every couple of seconds while it is on screen. Reading
the Piers and their queued jobs touches the database, so that is done on a worker
thread; the UI thread only snapshots in-memory state beforehand and fills the
table afterwards, and it never starts a second collection while one is running.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from types import SimpleNamespace
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_MS = 2000
COLUMNS = ("Pier", "Equipment", "Sequence", "Scheduler")


def queue_from_database(pier_name: str) -> Any:
    """A read-only stand-in for a Pier's persisted job queue (just names and run states),
    for a Pier whose scheduler has not been loaded into memory yet."""
    from galileo.library.models.scheduler import SchedulerJobRecord
    rows = SchedulerJobRecord.select().where(SchedulerJobRecord.pier_name == pier_name)
    return SimpleNamespace(
        jobs=[SimpleNamespace(name=r.name, run_state=r.run_state or "pending") for r in rows],
        active_job=None,
    )


def collect_dashboard(
    observatory_name: str,
    pier_records: list,
    *,
    selected_key: Any = None,
    selected_connected: bool = False,
    runs: dict | None = None,
    schedulers: dict | None = None,
    queue_loader: Callable[[str], Any] = queue_from_database,
    is_connected: Callable[[Any], bool] | None = None,
) -> list[dict]:
    """Build the dashboard rows for *pier_records* via ``Observatory.get_dashboard`` (OBS-060).

    *runs* is ``{pier_key: (state, session name)}`` from the session controller; *schedulers*
    maps a Pier name to its in-memory scheduler (others are read from the database with
    *queue_loader*). A Pier's equipment is *connected* when it is the selected Pier and
    *selected_connected*, or when *is_connected* says that Pier has a live device (the Equipment
    pages keep each Pier's connections across a Pier switch, OBS-140); without *is_connected*
    every other Pier reports disconnected. Each row gains ``selected``."""
    from galileo.current_object import pier_key
    from galileo.observatory import Observatory, Pier

    runs, schedulers = runs or {}, schedulers or {}
    observatory = Observatory(observatory_name)
    keys = {}
    for record in pier_records:
        pier = Pier(record.name)
        key = pier_key(record)
        keys[record.name] = key
        if (key == selected_key and selected_connected) or (is_connected is not None and is_connected(record)):
            pier.device_pool = SimpleNamespace()          # truthy: live devices
        if key in runs:
            pier.sequence_runner = SimpleNamespace(state=runs[key][0])
        scheduler = schedulers.get(record.name)
        if scheduler is None:
            try:
                scheduler = queue_loader(record.name)
            except Exception:
                logger.exception("Could not read the job queue of Pier %r", record.name)
        pier.scheduler = scheduler
        observatory.add_pier(pier)
    rows = observatory.get_dashboard()
    for row in rows:
        row["selected"] = keys[row["pier_name"]] == selected_key
        row["sequence_state"] = str(getattr(row["sequence_state"], "value", row["sequence_state"]))
    return rows


def describe_scheduler(row: dict) -> str:
    """The Scheduler cell: the running job, the queue depth, or idle."""
    if row["scheduler_state"] == "running":
        more = f" (+{row['queued_jobs']} queued)" if row["queued_jobs"] else ""
        return f"running: {row['active_job']}{more}"
    if row["scheduler_state"] == "queued":
        return f"{row['queued_jobs']} queued"
    return "idle"


class DashboardPage(QWidget):
    """The multi-Pier status dashboard (OBS-060)."""

    _collected = Signal(object)         # rows from the worker thread, delivered on the UI thread

    def __init__(self, window: Any) -> None:
        super().__init__()
        self.setObjectName("DashboardPage")
        self._app = window
        self._busy = False
        self._rows: list[dict] = []

        layout = QVBoxLayout(self)
        title = QLabel("Observatory Dashboard")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        self._subtitle = QLabel()
        layout.addWidget(self._subtitle)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(list(COLUMNS))
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.cellDoubleClicked.connect(lambda row, _col: self.open_pier(row))
        layout.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        self._open_btn = QPushButton("Open Pier")
        self._open_btn.clicked.connect(lambda: self.open_pier(self._table.currentRow()))
        buttons.addWidget(self._open_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._collected.connect(self._show)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._render([])

    # --- Refresh ---------------------------------------------------------------

    def _tick(self) -> None:
        if self.isVisible():             # nothing to refresh while another screen is showing
            self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload()

    def reload(self) -> None:
        """Start a background collection unless one is already running."""
        if self._busy:
            return
        app = self._app
        observatory = getattr(app, "_current_observatory", None)
        if observatory is None:
            self._render([])
            return
        from galileo.current_object import pier_key
        selected = getattr(app, "_current_pier", None)
        controller = getattr(app, "__dict__", {}).get("_session_controller")
        try:
            connected = bool(selected is not None and app._pier_is_connected())
        except Exception:
            connected = False
        args = {
            "selected_key": pier_key(selected),
            "selected_connected": connected,
            "runs": controller.run_snapshot() if controller is not None else {},
            "schedulers": dict(getattr(app, "_schedulers", {}) or {}),
            "is_connected": getattr(app, "_pier_has_connected_devices", None),
        }
        self._busy = True
        threading.Thread(target=self._collect, args=(observatory, args), daemon=True,
                         name="dashboard-collect").start()

    def _collect(self, observatory: Any, args: dict) -> None:
        """Worker thread: read the Piers and queues, then hand the rows to the UI thread."""
        try:
            from galileo.observatory import list_piers
            rows = collect_dashboard(observatory.name, list_piers(observatory), **args)
        except Exception:
            logger.exception("Could not collect the Observatory dashboard")
            rows = None
        with contextlib.suppress(RuntimeError):      # the page was destroyed while collecting
            self._collected.emit(rows)

    def _show(self, rows: list[dict] | None) -> None:
        self._busy = False
        if rows is not None:
            self._render(rows)

    # --- Display -----------------------------------------------------------------

    def _render(self, rows: list[dict]) -> None:
        self._rows = rows
        observatory = getattr(self._app, "_current_observatory", None)
        if observatory is None:
            self._subtitle.setText("No Observatory selected.")
        else:
            self._subtitle.setText(f"{observatory.name} — {len(rows)} Pier{'s' if len(rows) != 1 else ''}")
        current = self._table.currentRow()
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            name = row["pier_name"] + (" (selected)" if row.get("selected") else "")
            cells = (name, row["equipment_state"], row["sequence_state"], describe_scheduler(row))
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(r, c, item)
        if 0 <= current < len(rows):
            self._table.selectRow(current)
        self._open_btn.setEnabled(bool(rows))

    def open_pier(self, row: int) -> None:
        """Make the Pier in table *row* the working Pier (the focused single-Pier view)."""
        if not 0 <= row < len(self._rows):
            return
        name = self._rows[row]["pier_name"]
        combo = getattr(self._app, "_pier_combo", None)
        if combo is None:
            return
        index = combo.findText(name)
        if index < 0:
            return
        combo.setCurrentIndex(index)
        self._app._on_pier_activated(index)
        self.reload()
