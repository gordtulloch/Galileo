# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Scheduler screen (SCHED-010 … SCHED-100): the per-Pier job queue.

A job only ever enters the queue via a session's Schedule control (SES-200) — this
screen is a view onto, and a manager for, that queue: reorder, remove, edit a job's
priority/constraints/startup/completion conditions, and see its projected altitude
trajectory (SCHED-080). It does not create jobs directly, matching the one-way
Sessions -> Scheduler submission path the SRS specifies.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, ClassVar

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_STARTUP_LABELS = {"StartImmediate": "Immediate", "StartAtCulmination": "At culmination", "StartAtTime": "At time"}
_COMPLETION_LABELS = {"RunOnce": "Run once", "RepeatNTimes": "Repeat N times", "RepeatIndefinitely": "Repeat indefinitely"}


def _startup_summary(condition: Any) -> str:
    name = type(condition).__name__
    if name == "StartAtTime":
        return f"At {getattr(condition, 'time_utc', '?')}"
    return _STARTUP_LABELS.get(name, name)


def _completion_summary(condition: Any) -> str:
    name = type(condition).__name__
    if name == "RepeatNTimes":
        return f"Repeat {getattr(condition, 'n', '?')}x"
    return _COMPLETION_LABELS.get(name, name)


class _AltitudeChart(QWidget):
    """A small, self-painted altitude-over-time line (SCHED-080) — one line, one
    axis pair; deliberately simpler than the Guiding page's drift graph since
    there's only one series to show. Also reused, at a smaller fixed size, by
    the Sky Atlas page's per-result cards (SKY-030) — the same widget, not a
    second copy of this paint code."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 220)
        self.times: list = []
        self.altitudes: list = []

    def set_data(self, times: list, altitudes: list) -> None:
        self.times, self.altitudes = times, altitudes
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1a1a1a"))
        fg = QColor("#cccccc")
        font = QFont(painter.font())
        font.setPointSizeF(8.0)
        painter.setFont(font)

        plot = QRectF(40, 8, self.width() - 56, self.height() - 32)
        if plot.width() < 20 or plot.height() < 20 or not self.altitudes:
            painter.setPen(fg)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No trajectory data")
            painter.end()
            return

        y_min, y_max = -20.0, 90.0
        painter.setPen(fg)
        for alt in (0, 30, 60, 90):
            y = plot.bottom() - (alt - y_min) / (y_max - y_min) * plot.height()
            pen = QPen(QColor(90, 90, 90))
            pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(fg)
            painter.drawText(QRectF(0, y - 8, plot.left() - 4, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{alt}°")

        n = len(self.altitudes)
        points = [
            QPointF(plot.left() + i / max(n - 1, 1) * plot.width(),
                     plot.bottom() - (alt - y_min) / (y_max - y_min) * plot.height())
            for i, alt in enumerate(self.altitudes)
        ]
        painter.setPen(QPen(QColor("#4da6ff"), 2))
        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)

        # Time-axis ticks — a handful of "HH:MM" labels (UTC, matching this
        # app's convention everywhere else times are shown) evenly spaced
        # along the bottom, in the margin already reserved below the plot.
        if self.times and n > 1:
            num_ticks = min(4, n)
            tick_indices = sorted({round(i * (n - 1) / (num_ticks - 1)) for i in range(num_ticks)})
            painter.setPen(fg)
            for idx in tick_indices:
                x = plot.left() + idx / (n - 1) * plot.width()
                try:
                    label = datetime.datetime.fromisoformat(self.times[idx]).strftime("%H:%M")
                except (ValueError, IndexError):
                    continue
                painter.drawLine(QPointF(x, plot.bottom()), QPointF(x, plot.bottom() + 3))
                painter.drawText(QRectF(x - 22, plot.bottom() + 4, 44, 14), Qt.AlignmentFlag.AlignCenter, label)

        painter.end()


class _EditJobDialog(QDialog):
    """Priority, constraints, and startup/completion conditions for one job (SCHED-020/030/040/050)."""

    def __init__(self, job: Any, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit Job: {job.name}")
        self._job = job
        form = QFormLayout(self)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(1, 999)
        self.priority_spin.setValue(job.priority)
        self.priority_spin.setToolTip("Lower runs first.")
        form.addRow("Priority", self.priority_spin)

        self.min_alt_spin = QDoubleSpinBox()
        self.min_alt_spin.setRange(0.0, 90.0)
        self.min_alt_spin.setValue(job.constraints.min_altitude_deg)
        form.addRow("Min. altitude (°)", self.min_alt_spin)

        self.min_moon_spin = QDoubleSpinBox()
        self.min_moon_spin.setRange(0.0, 180.0)
        self.min_moon_spin.setValue(job.constraints.min_moon_separation_deg)
        form.addRow("Min. Moon separation (°)", self.min_moon_spin)

        self.twilight_combo = QComboBox()
        self.twilight_combo.addItems(["civil", "nautical", "astronomical"])
        self.twilight_combo.setCurrentText(job.constraints.twilight_restriction)
        form.addRow("Twilight restriction", self.twilight_combo)

        self.horizon_check = QComboBox()
        self.horizon_check.addItems(["Respect horizon obstructions", "Ignore horizon obstructions"])
        self.horizon_check.setCurrentIndex(0 if job.constraints.respect_horizon else 1)
        form.addRow("", self.horizon_check)

        self.startup_combo = QComboBox()
        self.startup_combo.addItems(["Immediate", "At culmination", "At time"])
        self.startup_combo.setCurrentIndex(
            {"StartImmediate": 0, "StartAtCulmination": 1, "StartAtTime": 2}.get(
                type(job.startup_condition).__name__, 0))
        form.addRow("Start", self.startup_combo)

        self.completion_combo = QComboBox()
        self.completion_combo.addItems(["Run once", "Repeat N times", "Repeat indefinitely"])
        self.completion_combo.setCurrentIndex(
            {"RunOnce": 0, "RepeatNTimes": 1, "RepeatIndefinitely": 2}.get(
                type(job.completion_condition).__name__, 0))
        form.addRow("Completion", self.completion_combo)

        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 999)
        self.repeat_spin.setValue(getattr(job.completion_condition, "n", 1))
        form.addRow("Repeat count", self.repeat_spin)

        self.total_spin = QSpinBox()
        self.total_spin.setRange(0, 100000)
        self.total_spin.setValue(job.total_required)
        self.total_spin.setToolTip("Frames required for this job to complete (SCHED-090).")
        form.addRow("Frames required", self.total_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self) -> None:
        from galileo.scheduler import (
            JobConstraints,
            RepeatIndefinitely,
            RepeatNTimes,
            RunOnce,
            StartAtCulmination,
            StartAtTime,
            StartImmediate,
        )
        job = self._job
        job.priority = self.priority_spin.value()
        job.constraints = JobConstraints(
            min_altitude_deg=self.min_alt_spin.value(),
            min_moon_separation_deg=self.min_moon_spin.value(),
            twilight_restriction=self.twilight_combo.currentText(),
            respect_horizon=self.horizon_check.currentIndex() == 0,
        )
        job.startup_condition = [StartImmediate(), StartAtCulmination(), StartAtTime(time_utc="")][
            self.startup_combo.currentIndex()]
        job.completion_condition = [RunOnce(), RepeatNTimes(n=self.repeat_spin.value()), RepeatIndefinitely()][
            self.completion_combo.currentIndex()]
        job.total_required = self.total_spin.value()


class SchedulerPageWidget(QWidget):
    """Planning > Scheduler (SCHED-010 … SCHED-100). Shares its ``ObservatoryScheduler``
    instances with Planning > Sessions via ``AppWindow._scheduler_for_pier``."""

    _COLUMNS: ClassVar[list[str]] = ["Priority", "Name", "Target", "State", "Progress", "Start", "Completion"]

    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("SchedulerPage")
        self._window = window
        self._build()
        self.reload()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        title = QLabel("Scheduler")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        hint = QLabel("Jobs are added from Planning > Sessions' Schedule control. "
                       "A job completing its required frames is removed here and its session is deleted there.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        self._status = QLabel("")
        self._status.setObjectName("StatusHint")
        outer.addWidget(self._status)

        self._table = QTableWidget(0, len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        self._up_btn = QPushButton("Move Up")
        self._up_btn.clicked.connect(lambda: self._move_selected(-1))
        self._down_btn = QPushButton("Move Down")
        self._down_btn.clicked.connect(lambda: self._move_selected(1))
        self._edit_btn = QPushButton("Edit…")
        self._edit_btn.clicked.connect(self._edit_selected)
        self._trajectory_btn = QPushButton("Show Trajectory…")
        self._trajectory_btn.clicked.connect(self._show_trajectory)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._remove_selected)
        for btn in (self._up_btn, self._down_btn, self._edit_btn, self._trajectory_btn, self._remove_btn):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        outer.addLayout(buttons)

        self._table.itemSelectionChanged.connect(self._update_button_states)
        self._update_button_states()

    # --- Pier / scheduler plumbing ------------------------------------------

    def _active_pier_name(self) -> str | None:
        pier = getattr(self._window, "_current_pier", None)
        return getattr(pier, "name", None)

    def _scheduler(self):
        get_scheduler = getattr(self._window, "_scheduler_for_pier", None)
        if get_scheduler is not None:
            return get_scheduler(self._active_pier_name())
        if not hasattr(self, "_local_scheduler"):
            from galileo.scheduler import ObservatoryScheduler
            self._local_scheduler = ObservatoryScheduler()
        return self._local_scheduler

    def _selected_job(self):
        rows = self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        if not rows:
            return None
        item = self._table.item(rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    # --- Refresh --------------------------------------------------------------

    def reload(self) -> None:
        """Show the active Pier's own job queue (mirrors SES-100's per-Pier scoping),
        reaping any job that has completed first (SCHED-050)."""
        scheduler = self._scheduler()
        scheduler.reap_completed_jobs()
        jobs = scheduler.jobs
        self._table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            state = "Active" if job is scheduler.active_job else "Pending"
            progress = (f"{job.frames_captured}/{job.total_required}" if job.total_required
                        else str(job.frames_captured))
            values = [str(job.priority), job.name, f"{job.target_ra:.2f}, {job.target_dec:.2f}",
                      state, progress, _startup_summary(job.startup_condition),
                      _completion_summary(job.completion_condition)]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, job)
                self._table.setItem(row, col, cell)
        pier_name = self._active_pier_name()
        if pier_name is None:
            self._status.setText("Create a Pier to see its job queue.")
        else:
            self._status.setText(f"{len(jobs)} job(s) for {pier_name}.")
        self._update_button_states()

    def _update_button_states(self) -> None:
        job = self._selected_job()
        for btn in (self._up_btn, self._down_btn, self._edit_btn, self._trajectory_btn, self._remove_btn):
            btn.setEnabled(job is not None)

    # --- Actions ----------------------------------------------------------------

    def _move_selected(self, delta: int) -> None:
        scheduler = self._scheduler()
        job = self._selected_job()
        if job is None:
            return
        index = scheduler.jobs.index(job)
        new_index = min(max(index + delta, 0), len(scheduler.jobs) - 1)
        if new_index != index:
            scheduler.move_job(job, new_index)
        self.reload()

    def _edit_selected(self) -> None:
        job = self._selected_job()
        if job is None:
            return
        dialog = _EditJobDialog(job, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply()
            self._scheduler().save()
        self.reload()

    def _show_trajectory(self) -> None:
        job = self._selected_job()
        if job is None:
            return
        scheduler = self._scheduler()
        observatory = getattr(self._window, "_current_observatory", None)
        if observatory is not None and getattr(observatory, "latitude", None) is not None:
            from galileo.planning.visibility import ObservingLocation
            scheduler.set_location(ObservingLocation(
                name=getattr(observatory, "name", ""),
                latitude=observatory.latitude, longitude=observatory.longitude,
            ))
        chart_data = scheduler.get_job_trajectory_chart(job)
        if not chart_data.get("altitudes"):
            QMessageBox.information(self, "Trajectory", "No trajectory available — set the Observatory's location first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Trajectory: {job.name}")
        layout = QVBoxLayout(dialog)
        chart = _AltitudeChart(dialog)
        chart.set_data(chart_data["times"], chart_data["altitudes"])
        layout.addWidget(chart)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _remove_selected(self) -> None:
        job = self._selected_job()
        if job is None:
            return
        reply = QMessageBox.question(
            self, "Remove Job", f"Remove {job.name!r} from the queue? Its session becomes editable again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        region = job.sequence
        if region is not None and hasattr(region, "deschedule"):
            region.deschedule()
        else:
            self._scheduler().remove_job(job)
        self.reload()
