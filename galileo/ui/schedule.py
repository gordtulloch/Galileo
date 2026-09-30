# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Schedule screen (SCHED-110 … SCHED-160): the per-Pier visual timeline.

A thin Qt view over ``galileo.scheduler.ObservatoryScheduler``'s job queue —
the only UI onto it; the earlier Planning > Scheduler table screen
(``galileo.ui.scheduler``, priority-order table, Edit… dialog, altitude-
trajectory chart) was removed once this screen existed (user's call — that
editing/charting capability has no replacement here, see ``docs/SDD.md``
Section 4.9b's "Reopened gap" note). This screen adds *placement* (when, and
for how long) and *outcome* (completed/error, with a log) on top of the
queue. See ``docs/SDD.md`` Section 4.9c.

A session lands on this timeline via its own Schedule control (SES-200,
``galileo.ui.sessions``) or its new Run control (SCHED-150); a standalone
pier-level operation (Open Dome, Close Dome, Dome Sync, Park Scope, Unpark
Scope) is dragged in from this screen's own side palette. Both are the same
``SchedulerJob`` underneath (``kind`` distinguishes them) and both render as
one block on the timeline, scaled to ``duration_minutes``.

Execution — actually opening the dome, actually running a session's blocks —
is not implemented here, same scope boundary ``galileo.ui.sessions`` and
``galileo.scheduler`` (SDD 4.9b) already draw: this screen only places jobs
on the clock and displays whatever ``run_state``/``run_log`` a (future)
execution engine has recorded against them.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_BLOCK_ROLE = Qt.ItemDataRole.UserRole
_PIXELS_PER_HOUR = 48
_ROW_HEIGHT = 46
_AXIS_HEIGHT = 22
_MAX_DAYS_BACK = 7

# Display label for each pier-level operation, in the order the palette shows
# them (PSD/user-facing wording) — distinct from the underlying action-block's
# own ``label`` (galileo.ui.sessions), which the Sessions screen's palette
# uses instead; both map to the same block *class*, just different copy.
_PIER_OP_LABELS: dict[str, str] = {
    "DomeOpenBlock": "Open Dome",
    "DomeCloseBlock": "Close Dome",
    "UnparkMountBlock": "Unpark Scope",
    "ParkMountBlock": "Park Scope",
    "DomeSyncBlock": "Dome Sync",
}
_PIER_OP_DEFAULT_MINUTES = 15.0


def _pier_op_classes() -> list[type]:
    from galileo.ui.sessions import (
        DomeCloseBlock,
        DomeOpenBlock,
        DomeSyncBlock,
        ParkMountBlock,
        UnparkMountBlock,
    )
    return [DomeOpenBlock, DomeCloseBlock, UnparkMountBlock, ParkMountBlock, DomeSyncBlock]


# --- Time helpers ------------------------------------------------------------
#
# Every SchedulerJob timeline field is stored as a UTC ISO string (naive
# strings are treated as UTC, matching _AltitudeChart's own convention in
# galileo.ui.app_window._widgets); the timeline itself is drawn in local
# wall-clock time, since that's what an observer at the keyboard plans around.

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
    """Read-only execution log viewer (SCHED-140) for one timeline entry."""

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


def _job_color(job: Any, window: Any = None) -> QColor:
    """Reuses the Sessions screen's own colour-by-block-type identity
    (``galileo.ui.sessions._block_color``) so a pier operation looks the same
    on both screens; a session job gets a fixed identity of its own."""
    from galileo.ui.sessions import _block_color
    kind_name = job.pier_op_kind if job.kind == "pier_op" else "SessionJob"
    return _block_color(kind_name, window)


class _ScheduleBlockWidget(QFrame):
    """One SchedulerJob's block on the timeline (SCHED-110): sized to its
    duration, coloured by kind, bordered by outcome (SCHED-140), draggable
    along the time axis, right-click to edit its time or view its log."""

    def __init__(self, job: Any, canvas: _TimelineCanvas, window: Any = None, parent=None) -> None:
        super().__init__(parent)
        self.job = job
        self._canvas = canvas
        self._window = window
        self.setFrameShape(QFrame.Shape.Box)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 4, 2)
        self._label = QLabel(job.name)
        self._label.setWordWrap(False)
        layout.addWidget(self._label, 1)
        self._log_btn = QPushButton("Log")
        self._log_btn.setFixedWidth(40)
        self._log_btn.clicked.connect(lambda: _LogDialog(self.job, self).exec())
        layout.addWidget(self._log_btn)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.apply_style()
        self._drag_origin: QPoint | None = None
        self._drag_start_x = 0

    def apply_style(self) -> None:
        color = _job_color(self.job, self._window)
        border = {"completed": "#2e9e3f", "error": "#cc3333"}.get(self.job.run_state, "#555555")
        border_width = 2 if self.job.run_state in ("completed", "error") else 1
        self.setStyleSheet(
            f"_ScheduleBlockWidget {{ background-color: {color.name()}; "
            f"border: {border_width}px solid {border}; border-radius: 4px; }}"
        )
        self._label.setText(self.job.name)

    def _on_context_menu(self, pos) -> None:
        menu = QMenu(self)
        set_time = menu.addAction("Set Time…")
        remove = menu.addAction("Remove from Schedule")
        action = menu.exec(self.mapToGlobal(pos))
        if action is set_time:
            dialog = _EditTimeDialog(self.job, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                dialog.apply()
                self._canvas.commit_and_refresh()
        elif action is remove:
            self._canvas.remove_job(self.job)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_start_x = self.x()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is not None:
            dx = event.globalPosition().toPoint().x() - self._drag_origin.x()
            new_x = max(0, self._drag_start_x + dx)
            self.move(new_x, self.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_origin is not None:
            self._drag_origin = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._canvas.reposition_from_pixels(self.job, self.x())
        super().mouseReleaseEvent(event)


class _TimelineCanvas(QWidget):
    """The day's axis plus every job's block (SCHED-110) for the active Pier,
    and the drop target for the pier-operation palette."""

    def __init__(self, page: SchedulePageWidget, parent=None) -> None:
        super().__init__(parent)
        self._page = page
        self.setAcceptDrops(True)
        self.setMinimumWidth(int(24 * _PIXELS_PER_HOUR))
        self._blocks: list[_ScheduleBlockWidget] = []

    def day_start_local(self) -> datetime.datetime:
        return self._page.displayed_day_start_local()

    def refresh(self) -> None:
        for widget in self._blocks:
            widget.deleteLater()
        self._blocks = []
        day_start = self.day_start_local()
        day_end = day_start + datetime.timedelta(days=1)
        rows: list[float] = []  # each row's rightmost occupied x, in hours
        placed = []
        for job in self._page.timed_jobs():
            window = job.effective_window()
            if window is None:
                continue
            start_local = window[0].astimezone()
            end_local = window[1].astimezone()
            if end_local <= day_start or start_local >= day_end:
                continue
            start_hour = max(0.0, (start_local - day_start).total_seconds() / 3600.0)
            end_hour = min(24.0, (end_local - day_start).total_seconds() / 3600.0)
            row = next((i for i, right in enumerate(rows) if start_hour >= right), None)
            if row is None:
                row = len(rows)
                rows.append(end_hour)
            else:
                rows[row] = end_hour
            placed.append((job, start_hour, end_hour, row))

        for job, start_hour, end_hour, row in placed:
            widget = _ScheduleBlockWidget(job, self, self._page.window_ref, self)
            x = int(start_hour * _PIXELS_PER_HOUR)
            width = max(24, int((end_hour - start_hour) * _PIXELS_PER_HOUR))
            y = _AXIS_HEIGHT + row * _ROW_HEIGHT
            widget.setGeometry(x, y, width, _ROW_HEIGHT - 4)
            widget.show()
            self._blocks.append(widget)

        height = _AXIS_HEIGHT + max(1, len(rows)) * _ROW_HEIGHT + 8
        self.setMinimumHeight(height)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(120, 120, 120))
        painter.setPen(pen)
        for hour in range(25):
            x = hour * _PIXELS_PER_HOUR
            painter.drawLine(x, 0, x, self.height())
            if hour % 2 == 0 and hour < 24:
                painter.drawText(x + 2, _AXIS_HEIGHT - 6, f"{hour:02d}:00")
        painter.end()

    def reposition_from_pixels(self, job: Any, x: int) -> None:
        hour = max(0.0, min(23.98, x / _PIXELS_PER_HOUR))
        new_start = self.day_start_local() + datetime.timedelta(hours=hour)
        duration = job.duration_minutes or job.DEFAULT_DURATION_MINUTES
        job.scheduled_start_utc = _format_utc(new_start.astimezone(datetime.UTC))
        if job.scheduled_end_utc:
            job.scheduled_end_utc = _format_utc((new_start + datetime.timedelta(minutes=duration)).astimezone(datetime.UTC))
        self.commit_and_refresh()

    def commit_and_refresh(self) -> None:
        self._page.save_active_scheduler()
        self.refresh()

    def remove_job(self, job: Any) -> None:
        self._page.remove_job(job)

    def dragEnterEvent(self, event) -> None:
        if event.source() is self._page.palette:
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.source() is self._page.palette:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if event.source() is not self._page.palette:
            return
        item = self._page.palette.currentItem()
        if item is None:
            return
        block_cls, label = item.data(_BLOCK_ROLE)
        hour = max(0.0, min(23.98, event.position().x() / _PIXELS_PER_HOUR))
        start = self.day_start_local() + datetime.timedelta(hours=hour)
        self._page.add_pier_operation(block_cls, label, start)
        event.acceptProposedAction()


def _build_pier_op_palette(window: Any, parent=None) -> QListWidget:
    from galileo.ui.sessions import _block_item_widget
    palette = QListWidget(parent)
    palette.setObjectName("SchedulePalette")
    palette.setDragEnabled(True)
    palette.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
    palette.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    palette.setMaximumWidth(180)
    palette.setToolTip("Drag a pier-level operation onto the timeline to schedule it.")
    for cls in _pier_op_classes():
        label = _PIER_OP_LABELS.get(cls.__name__, cls.label)
        item = QListWidgetItem(label)
        item.setData(_BLOCK_ROLE, (cls, label))
        palette.addItem(item)
        widget = _block_item_widget(label, cls.__name__, window)
        item.setSizeHint(widget.sizeHint())
        palette.setItemWidget(item, widget)
    return palette


class _UnscheduledRow(QFrame):
    """One not-yet-positioned job (SCHED-120), listed below the timeline
    rather than guessed onto it."""

    def __init__(self, job: Any, page: SchedulePageWidget, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self)
        layout.addWidget(QLabel(job.name), 1)
        set_time_btn = QPushButton("Set Time…")
        set_time_btn.clicked.connect(self._set_time)
        layout.addWidget(set_time_btn)
        log_btn = QPushButton("Log")
        log_btn.clicked.connect(lambda: _LogDialog(job, self).exec())
        layout.addWidget(log_btn)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda: page.remove_job(job))
        layout.addWidget(remove_btn)
        self._job = job
        self._page = page

    def _set_time(self) -> None:
        dialog = _EditTimeDialog(self._job, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply()
            self._page.save_active_scheduler()
            self._page.reload()


class SchedulePageWidget(QWidget):
    """Planning > Schedule (SCHED-110 … SCHED-160). Constructed once by
    ``AppWindow._build_schedule_page`` and kept in sync with the active Pier
    via ``reload()``, following the same convention every other per-Pier page
    uses."""

    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("SchedulePage")
        self.window_ref = window
        self._displayed_day_offset = 0  # days from today, clamped to [-_MAX_DAYS_BACK, +inf)
        self._build()
        self.reload()

    # --- Layout -----------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        title = QLabel("Schedule")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        top_bar = QHBoxLayout()
        self._back_btn = QPushButton("◀ Day")
        self._back_btn.clicked.connect(lambda: self._shift_day(-1))
        top_bar.addWidget(self._back_btn)
        self._today_btn = QPushButton("Today")
        self._today_btn.clicked.connect(self._go_today)
        top_bar.addWidget(self._today_btn)
        self._forward_btn = QPushButton("Day ▶")
        self._forward_btn.clicked.connect(lambda: self._shift_day(1))
        top_bar.addWidget(self._forward_btn)
        self._day_label = QLabel()
        self._day_label.setObjectName("PageSubtitle")
        top_bar.addWidget(self._day_label)
        top_bar.addStretch(1)
        self._autoschedule_btn = QPushButton("Autoschedule")
        self._autoschedule_btn.clicked.connect(self._autoschedule)
        top_bar.addWidget(self._autoschedule_btn)
        outer.addLayout(top_bar)

        self._status = QLabel("")
        self._status.setObjectName("StatusHint")
        outer.addWidget(self._status)

        body = QHBoxLayout()
        outer.addLayout(body, 1)

        left = QVBoxLayout()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._canvas = _TimelineCanvas(self)
        self._scroll.setWidget(self._canvas)
        left.addWidget(self._scroll, 2)

        unscheduled_label = QLabel("Unscheduled")
        unscheduled_label.setObjectName("PageSubtitle")
        left.addWidget(unscheduled_label)
        self._unscheduled_scroll = QScrollArea()
        self._unscheduled_scroll.setWidgetResizable(True)
        self._unscheduled_scroll.setMaximumHeight(160)
        unscheduled_container = QWidget()
        self._unscheduled_layout = QVBoxLayout(unscheduled_container)
        self._unscheduled_layout.addStretch(1)
        self._unscheduled_scroll.setWidget(unscheduled_container)
        left.addWidget(self._unscheduled_scroll, 1)

        body.addLayout(left, 1)

        self.palette = _build_pier_op_palette(self.window_ref, self)
        body.addWidget(self.palette)

    # --- Pier / scheduler plumbing -----------------------------------------

    def _active_pier_name(self) -> str | None:
        pier = getattr(self.window_ref, "_current_pier", None)
        return getattr(pier, "name", None)

    def _scheduler(self):
        get_scheduler = getattr(self.window_ref, "_scheduler_for_pier", None)
        if get_scheduler is not None:
            return get_scheduler(self._active_pier_name())
        if not hasattr(self, "_local_scheduler"):
            from galileo.scheduler import ObservatoryScheduler
            self._local_scheduler = ObservatoryScheduler()
        return self._local_scheduler

    def save_active_scheduler(self) -> None:
        self._scheduler().save()

    # --- Day window ----------------------------------------------------------

    def displayed_day_start_local(self) -> datetime.datetime:
        today = _now_utc().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        return today + datetime.timedelta(days=self._displayed_day_offset)

    def _shift_day(self, delta: int) -> None:
        self._displayed_day_offset = max(-_MAX_DAYS_BACK, self._displayed_day_offset + delta)
        self.reload()

    def _go_today(self) -> None:
        self._displayed_day_offset = 0
        self.reload()

    def _autoschedule(self) -> None:
        """SCHED-160 (P3): the control exists; automatic placement logic is
        deferred, same as SCHED-070's replanning — see SDD 4.9c."""
        QMessageBox.information(self, "Autoschedule", "Automatic scheduling isn't implemented yet.")

    # --- Jobs ----------------------------------------------------------------

    def timed_jobs(self) -> list[Any]:
        return [j for j in self._scheduler().jobs if j.scheduled_start_utc]

    def untimed_jobs(self) -> list[Any]:
        return [j for j in self._scheduler().jobs if not j.scheduled_start_utc]

    def add_pier_operation(self, block_cls: type, label: str, start_local: datetime.datetime) -> None:
        scheduler = self._scheduler()
        job = scheduler.add_pier_operation(block_cls.__name__, label, self._active_pier_name() or "")
        job.scheduled_start_utc = _format_utc(start_local.astimezone(datetime.UTC))
        job.duration_minutes = _PIER_OP_DEFAULT_MINUTES
        scheduler.save()
        self.reload()

    def remove_job(self, job: Any) -> None:
        reply = QMessageBox.question(
            self, "Remove from Schedule", f"Remove {job.name!r} from the schedule?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if job.kind == "session" and job.sequence is not None and hasattr(job.sequence, "deschedule"):
            job.sequence.deschedule()
        else:
            self._scheduler().remove_job(job)
        self.reload()

    # --- Refresh ---------------------------------------------------------------

    def reload(self) -> None:
        scheduler = self._scheduler()
        scheduler.reap_completed_jobs()
        day_start = self.displayed_day_start_local()
        self._day_label.setText(day_start.strftime("%A, %Y-%m-%d"))
        self._back_btn.setEnabled(self._displayed_day_offset > -_MAX_DAYS_BACK)
        self._canvas.refresh()

        while self._unscheduled_layout.count() > 1:
            item = self._unscheduled_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        untimed = self.untimed_jobs()
        for job in untimed:
            self._unscheduled_layout.insertWidget(self._unscheduled_layout.count() - 1, _UnscheduledRow(job, self))

        pier_name = self._active_pier_name()
        if pier_name is None:
            self._status.setText("Create a Pier to see its schedule.")
        else:
            self._status.setText(
                f"{len(scheduler.jobs)} entr{'y' if len(scheduler.jobs) == 1 else 'ies'} for {pier_name} "
                f"({len(untimed)} unscheduled).")
