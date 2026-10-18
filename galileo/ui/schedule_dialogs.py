# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Schedule page's modal dialogs: edit a time slot, edit a job, view a job's log, view its trajectory."""

from __future__ import annotations

import datetime
from typing import Any
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QPlainTextEdit, QSpinBox, QVBoxLayout


def _parse_utc(text: str) -> datetime.datetime:
    from galileo.scheduler import _parse_utc as _scheduler_parse_utc
    return _scheduler_parse_utc(text)


def _format_utc(dt: datetime.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.astimezone(datetime.UTC).isoformat()


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class _EditTimeDialog(QDialog):
    """Right-click dialog (SCHED-120): optional start, optional end, and a
    duration used to size the block when only a start (or neither) is set."""

    def __init__(self, job: Any, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Schedule Time: {job.name}")
        self._job = job
        form = QFormLayout(self)

        now_local = _now_utc().astimezone()

        self.start_check = QCheckBox("Set start time")
        self.start_edit = QDateTimeEdit()
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        if job.scheduled_start_utc:
            self.start_check.setChecked(True)
            self.start_edit.setDateTime(_parse_utc(job.scheduled_start_utc).astimezone())
        else:
            self.start_edit.setDateTime(now_local)
            self.start_edit.setEnabled(False)
        self.start_check.toggled.connect(self.start_edit.setEnabled)
        form.addRow(self.start_check, self.start_edit)

        self.end_check = QCheckBox("Set end time")
        self.end_edit = QDateTimeEdit()
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        if job.scheduled_end_utc:
            self.end_check.setChecked(True)
            self.end_edit.setDateTime(_parse_utc(job.scheduled_end_utc).astimezone())
        else:
            self.end_edit.setDateTime(now_local + datetime.timedelta(hours=1))
            self.end_edit.setEnabled(False)
        self.end_check.toggled.connect(self.end_edit.setEnabled)
        form.addRow(self.end_check, self.end_edit)

        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(1.0, 1440.0)
        self.duration_spin.setSuffix(" min")
        self.duration_spin.setValue(job.duration_minutes or job.DEFAULT_DURATION_MINUTES)
        self.duration_spin.setToolTip("Used to size the block when no end time is set.")
        form.addRow("Duration", self.duration_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self) -> None:
        job = self._job
        job.scheduled_start_utc = _format_utc(self.start_edit.dateTime().toPython()) if self.start_check.isChecked() else None
        job.scheduled_end_utc = _format_utc(self.end_edit.dateTime().toPython()) if self.end_check.isChecked() else None
        job.duration_minutes = self.duration_spin.value()


class _LogDialog(QDialog):
    """Read-only execution log viewer (SCHED-140) for one calendar entry."""

    def __init__(self, job: Any, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Log: {job.name}")
        self.resize(480, 320)
        layout = QVBoxLayout(self)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(
            "\n".join(job.run_log) if job.run_log
            else "No log entries yet — execution isn't wired up for this build."
        )
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class _EditJobDialog(QDialog):
    """Priority, constraints, startup/completion conditions and frames
    required for one job (SCHED-020/030/040/050), ported from the removed
    Scheduler table screen."""

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

        self.horizon_combo = QComboBox()
        self.horizon_combo.addItems(["Respect horizon obstructions", "Ignore horizon obstructions"])
        self.horizon_combo.setCurrentIndex(0 if job.constraints.respect_horizon else 1)
        form.addRow("Horizon", self.horizon_combo)

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
            respect_horizon=self.horizon_combo.currentIndex() == 0,
        )
        startup = self.startup_combo.currentIndex()
        if startup == 2:
            # Keep an existing "At time" value; otherwise use the job's scheduled start.
            existing = job.startup_condition.time_utc if isinstance(job.startup_condition, StartAtTime) else ""
            job.startup_condition = StartAtTime(time_utc=existing or job.scheduled_start_utc or "")
        else:
            job.startup_condition = [StartImmediate(), StartAtCulmination()][startup]
        job.completion_condition = [RunOnce(), RepeatNTimes(n=self.repeat_spin.value()), RepeatIndefinitely()][
            self.completion_combo.currentIndex()]
        job.total_required = self.total_spin.value()


class _TrajectoryDialog(QDialog):
    """Altitude-over-time chart for one job's target (SCHED-080), using the
    shared ``_AltitudeChart`` widget."""

    def __init__(self, job: Any, chart_data: dict, parent=None) -> None:
        super().__init__(parent)
        from .app_window._widgets import _AltitudeChart
        self.setWindowTitle(f"Trajectory: {job.name}")
        self.resize(560, 320)
        layout = QVBoxLayout(self)
        self.chart = _AltitudeChart(self)
        self.chart.set_data(chart_data["times"], chart_data["altitudes"])
        layout.addWidget(self.chart)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
