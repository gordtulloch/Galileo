# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Schedule screen (SCHED-110 … SCHED-160): the per-Pier calendar view over
``galileo.scheduler.ObservatoryScheduler``'s job queue — the only UI onto it;
the earlier Planning > Scheduler table screen (``galileo.ui.scheduler``,
priority-order table, Edit… dialog, altitude-trajectory chart) was removed
once this screen existed (user's call — that editing/charting capability has
no replacement here, see ``docs/SDD.md`` Section 4.9b's "Reopened gap" note).
This screen adds *placement* (when, and for how long) and *outcome*
(completed/error, with a log) on top of the queue. See ``docs/SDD.md``
Section 4.9c.

The screen is a multi-day calendar grid: one column per observing night, a
shared hour axis running down the left from dusk at the top to dawn at the
bottom (so the night itself sits centered in the column, not split across the
midnight-crossing top/bottom edges a plain calendar-day column would have),
each column shaded by that night's own sunlight/twilight/darkness (from
``galileo.planning.visibility``) when an Observatory location is configured,
plus that night's Moon phase. A session lands on this grid via its own
Schedule control (SES-200, ``galileo.ui.sessions``) or its Run control
(SCHED-150); a standalone pier-level operation (Open Dome, Close Dome, Dome
Sync, Park Scope, Unpark Scope) is added via "Add Pier Operation" on the
grid's own right-click menu — there is no side palette of block *types* to
drag from any more (removed, user's call: a drag source for creating new
pier-op entries competed with the calendar's own day/time layout without
adding capability). A job that already exists but has no start time yet
("Unscheduled", below the grid) is itself a small draggable block, though —
dragging one of those onto the grid is how it gets a start time in the first
place, same as dragging a positioned block to move it. Both a session and a
pier operation are the same ``SchedulerJob`` underneath (``kind``
distinguishes them) and both render as one block, positioned by start time
and sized to ``duration_minutes``.

Execution — actually opening the dome, actually running a session's blocks —
is not implemented here, same scope boundary ``galileo.ui.sessions`` and
``galileo.scheduler`` (SDD 4.9b) already draw: this screen only places jobs
on the calendar and displays whatever ``run_state``/``run_log`` a (future)
execution engine has recorded against them.
"""

from __future__ import annotations

from galileo.ui.qt_helpers import take_widget
import datetime
import logging
from typing import Any

from PySide6.QtCore import QDate, QPoint, Qt
from PySide6.QtWidgets import (
    QCalendarWidget,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from galileo.ui.schedule_dialogs import (  # noqa: F401  (re-exported: these used to live in this module)
    _EditJobDialog,
    _EditTimeDialog,
    _LogDialog,
    _TrajectoryDialog,
    _format_utc,
    _now_utc,
    _parse_utc,
)
from galileo.ui.schedule_canvas import (  # noqa: F401  (re-exported: these used to live in this module)
    _AXIS_WIDTH,
    _BLOCK_MARGIN,
    _CalendarCanvas,
    _DEFAULT_WINDOW_END_HOUR,
    _DEFAULT_WINDOW_START_HOUR,
    _HEADER_HEIGHT,
    _MIN_BLOCK_HEIGHT,
    _MIN_COLUMN_WIDTH,
    _MOON_PHASE_CACHE,
    _PIER_OP_LABELS,
    _SKY_DAY,
    _SKY_NIGHT,
    _SKY_TWILIGHT,
    _SUN_TRACK_CACHE,
    _ScheduleBlockWidget,
    _UnscheduledBlockWidget,
    _WINDOW_PADDING_HOURS,
    _almanac_band_color,
    _cached_moon_phase,
    _cached_sun_track,
    _crossing_hour,
    _darkest_evening_hour,
    _job_color,
    _local_midnight,
    _night_column_and_hour,
    _night_window_hours,
    _pier_op_classes,
    _shared_night_window,
    _sun_darkness_samples,
)

logger = logging.getLogger(__name__)

_PIXELS_PER_HOUR_STEPS = [16, 24, 32, 48, 64, 96]
_DEFAULT_PPH_INDEX = 2  # 32 px/hour
_MIN_DAYS = 1
_MAX_DAYS = 7
_DEFAULT_DAYS = 4
_MAX_DAYS_BACK = 7


_PIER_OP_DEFAULT_MINUTES = 15.0


# --- Time helpers ------------------------------------------------------------
#
# Every SchedulerJob timeline field is stored as a UTC ISO string (naive
# strings are treated as UTC, matching _AltitudeChart's own convention in
# galileo.ui.app_window._widgets); the calendar itself is drawn in local
# wall-clock time, since that's what an observer at the keyboard plans around.


def _current_location(window: Any) -> Any | None:
    """The active Pier's Observatory location, for the almanac shading —
    same convention as ``galileo.ui.app_window``'s other pages
    (``_planning_page.py``, ``_whats_up_page.py``): ``None`` when nothing is
    selected or it has no latitude/longitude configured yet."""
    obs = getattr(window, "_current_observatory", None)
    if obs is None:
        pier = getattr(window, "_current_pier", None)
        obs = getattr(pier, "observatory", None)
    if obs is None or getattr(obs, "latitude", None) is None or getattr(obs, "longitude", None) is None:
        return None
    from galileo.planning.visibility import ObservingLocation
    return ObservingLocation(
        name=getattr(obs, "name", ""), latitude=obs.latitude, longitude=obs.longitude,
        elevation_m=getattr(obs, "elevation_m", None) or 0.0,
        timezone=getattr(obs, "timezone", None) or "UTC",
    )


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
        self._pph_index = _DEFAULT_PPH_INDEX
        self._num_days_shown = _DEFAULT_DAYS
        self._dragging_job: Any = None
        self._shown_block_reason = ""
        self._build()
        self.reload()
        try:
            from galileo.ui.session_runner import get_session_controller
            get_session_controller(window).changed.connect(self._on_controller_changed)
        except Exception:               # a window without a session controller (tests, stubs)
            logger.debug("No session controller to follow", exc_info=True)

    def showEvent(self, event) -> None:
        """Re-read the shared scheduler whenever the page is shown: a session scheduled on
        Planning > Sessions adds a job while this page is hidden, and nothing else tells it."""
        super().showEvent(event)
        self.reload()

    def _on_controller_changed(self, *_args) -> None:
        """Refresh the status line when the safety block appears or clears (SCHED-060)."""
        if self._scheduler().safety_block_reason() != self._shown_block_reason:
            self.reload()

    # --- Layout -----------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        title = QLabel("Schedule")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        controls_bar = QHBoxLayout()
        self._zoom_out_btn = QPushButton("Zoom Out")
        self._zoom_out_btn.clicked.connect(self._zoom_out)
        controls_bar.addWidget(self._zoom_out_btn)
        self._zoom_in_btn = QPushButton("Zoom In")
        self._zoom_in_btn.clicked.connect(self._zoom_in)
        controls_bar.addWidget(self._zoom_in_btn)
        controls_bar.addSpacing(12)
        self._fewer_days_btn = QPushButton("Fewer Days")
        self._fewer_days_btn.clicked.connect(self._fewer_days)
        controls_bar.addWidget(self._fewer_days_btn)
        self._more_days_btn = QPushButton("More Days")
        self._more_days_btn.clicked.connect(self._more_days)
        controls_bar.addWidget(self._more_days_btn)
        controls_bar.addSpacing(12)
        self._almanac_check = QCheckBox("Show Almanac Shading")
        self._almanac_check.setChecked(True)
        self._almanac_check.toggled.connect(lambda _checked: self._canvas.refresh())
        controls_bar.addWidget(self._almanac_check)
        self._show_past_check = QCheckBox("Show Past Events")
        self._show_past_check.toggled.connect(lambda _checked: self._canvas.refresh())
        controls_bar.addWidget(self._show_past_check)
        controls_bar.addStretch(1)
        self._autoschedule_btn = QPushButton("Autoschedule")
        self._autoschedule_btn.clicked.connect(self._autoschedule)
        controls_bar.addWidget(self._autoschedule_btn)
        outer.addLayout(controls_bar)

        nav_bar = QHBoxLayout()
        self._back_btn = QPushButton("◀ Day")
        self._back_btn.clicked.connect(lambda: self._shift_day(-1))
        nav_bar.addWidget(self._back_btn)
        self._today_btn = QPushButton("Today")
        self._today_btn.clicked.connect(self._go_today)
        nav_bar.addWidget(self._today_btn)
        self._forward_btn = QPushButton("Day ▶")
        self._forward_btn.clicked.connect(lambda: self._shift_day(1))
        nav_bar.addWidget(self._forward_btn)
        self._subtitle = QLabel()
        self._subtitle.setObjectName("PageSubtitle")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_bar.addWidget(self._subtitle, 1)
        outer.addLayout(nav_bar)

        self._status = QLabel("")
        self._status.setObjectName("StatusHint")
        outer.addWidget(self._status)

        body = QHBoxLayout()
        outer.addLayout(body, 1)

        left = QVBoxLayout()
        self._mini_calendar = QCalendarWidget()
        self._mini_calendar.setGridVisible(True)
        self._mini_calendar.clicked.connect(self._on_calendar_clicked)
        left.addWidget(self._mini_calendar)

        unscheduled_label = QLabel("Unscheduled")
        unscheduled_label.setObjectName("PageSubtitle")
        left.addWidget(unscheduled_label)
        self._unscheduled_scroll = QScrollArea()
        self._unscheduled_scroll.setWidgetResizable(True)
        unscheduled_container = QWidget()
        self._unscheduled_layout = QVBoxLayout(unscheduled_container)
        self._unscheduled_layout.addStretch(1)
        self._unscheduled_scroll.setWidget(unscheduled_container)
        left.addWidget(self._unscheduled_scroll, 1)

        left_container = QWidget()
        left_container.setLayout(left)
        left_container.setMaximumWidth(240)
        body.addWidget(left_container)

        right = QVBoxLayout()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._canvas = _CalendarCanvas(self)
        self._scroll.setWidget(self._canvas)
        right.addWidget(self._scroll, 1)

        upcoming_label = QLabel("Upcoming Sessions")
        upcoming_label.setObjectName("PageSubtitle")
        right.addWidget(upcoming_label)
        self._upcoming_list = QPlainTextEdit()
        self._upcoming_list.setObjectName("upcoming_list")
        self._upcoming_list.setReadOnly(True)
        self._upcoming_list.setMaximumHeight(160)
        right.addWidget(self._upcoming_list)
        body.addLayout(right, 1)

        self._update_zoom_buttons()
        self._update_days_buttons()

    # --- Grid controls -------------------------------------------------------

    @property
    def pixels_per_hour(self) -> int:
        return _PIXELS_PER_HOUR_STEPS[self._pph_index]

    @property
    def num_days(self) -> int:
        return self._num_days_shown

    @property
    def show_almanac(self) -> bool:
        return self._almanac_check.isChecked()

    @property
    def show_past(self) -> bool:
        return self._show_past_check.isChecked()

    def current_location(self) -> Any | None:
        return _current_location(self.window_ref)

    def grid_viewport_width(self) -> int:
        return self._scroll.viewport().width()

    @property
    def dragging_job(self) -> Any:
        """The Unscheduled-tray job currently mid-drag onto the grid, or
        ``None`` — set by ``_UnscheduledBlockWidget`` for the duration of its
        ``QDrag.exec()`` and read by ``_CalendarCanvas.dropEvent``, the same
        role the old pier-op palette's ``currentItem()`` played."""
        return self._dragging_job

    def is_over_unscheduled(self, global_pos: QPoint) -> bool:
        """True if *global_pos* lies over the Unscheduled tray (a grid block
        dropped there is unscheduled)."""
        return self._unscheduled_scroll.rect().contains(self._unscheduled_scroll.mapFromGlobal(global_pos))

    def begin_job_drag(self, job: Any) -> None:
        self._dragging_job = job

    def end_job_drag(self) -> None:
        self._dragging_job = None

    def _zoom_out(self) -> None:
        self._pph_index = max(0, self._pph_index - 1)
        self._update_zoom_buttons()
        self._canvas.refresh()

    def _zoom_in(self) -> None:
        self._pph_index = min(len(_PIXELS_PER_HOUR_STEPS) - 1, self._pph_index + 1)
        self._update_zoom_buttons()
        self._canvas.refresh()

    def _update_zoom_buttons(self) -> None:
        self._zoom_out_btn.setEnabled(self._pph_index > 0)
        self._zoom_in_btn.setEnabled(self._pph_index < len(_PIXELS_PER_HOUR_STEPS) - 1)

    def _fewer_days(self) -> None:
        self._num_days_shown = max(_MIN_DAYS, self._num_days_shown - 1)
        self._update_days_buttons()
        self._canvas.refresh()

    def _more_days(self) -> None:
        self._num_days_shown = min(_MAX_DAYS, self._num_days_shown + 1)
        self._update_days_buttons()
        self._canvas.refresh()

    def _update_days_buttons(self) -> None:
        self._fewer_days_btn.setEnabled(self._num_days_shown > _MIN_DAYS)
        self._more_days_btn.setEnabled(self._num_days_shown < _MAX_DAYS)

    def _on_calendar_clicked(self, qdate: QDate) -> None:
        picked = datetime.date(qdate.year(), qdate.month(), qdate.day())
        today = _now_utc().astimezone().date()
        self._displayed_day_offset = max(-_MAX_DAYS_BACK, (picked - today).days)
        self.reload()

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

    def edit_job(self, job: Any) -> bool:
        """Open the job editor (SCHED-020/030/040/050); True if applied."""
        dialog = _EditJobDialog(job, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        dialog.apply()
        self.save_active_scheduler()
        self.reload()
        return True

    def show_trajectory(self, job: Any) -> None:
        """Show the job target's altitude-over-time chart (SCHED-080)."""
        scheduler = self._scheduler()
        location = self.current_location()
        if location is not None:
            scheduler.set_location(location)
        chart_data = scheduler.get_job_trajectory_chart(job)
        if not chart_data.get("altitudes"):
            QMessageBox.information(
                self, "Trajectory", "No trajectory available — set the Observatory's location first.")
            return
        _TrajectoryDialog(job, chart_data, self).exec()

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
        """SCHED-160: preview where ``galileo.autoschedule`` would put every
        unpositioned entry on the displayed night, and apply it on confirmation."""
        from galileo.autoschedule import AstropySkyModel, apply_plan, plan_autoschedule
        scheduler = self._scheduler()
        location = self.current_location()
        day_start = self.displayed_day_start_local()
        sky = AstropySkyModel(location) if location is not None else None
        plan = plan_autoschedule(
            scheduler, sky,
            (day_start + datetime.timedelta(hours=12)).astimezone(datetime.UTC),
            (day_start + datetime.timedelta(hours=36)).astimezone(datetime.UTC))
        if not plan.placements and not plan.unplaced:
            QMessageBox.information(self, "Autoschedule", "There are no unscheduled entries to place.")
            return
        night = day_start.strftime("%A, %B %d")
        if not plan.placements:
            QMessageBox.information(
                self, "Autoschedule", f"Nothing could be placed for the night of {night}:\n\n{plan.summary()}")
            return
        reply = QMessageBox.question(
            self, "Autoschedule", f"Place these entries on the night of {night}?\n\n{plan.summary()}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.Yes:
            apply_plan(scheduler, plan)
            self.reload()

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

    def unschedule_job(self, job: Any) -> None:
        """Take a timeline block off the grid. A session keeps its job and returns to the
        Unscheduled tray; a pier operation has nothing to return to, so it is deleted."""
        if job.kind != "session":
            self.remove_job(job)
            return
        job.scheduled_start_utc = None
        if getattr(job, "scheduled_end_utc", None):
            job.scheduled_end_utc = None
        self.save_active_scheduler()
        self.reload()

    def remove_job(self, job: Any) -> None:
        """Delete a job outright (Unscheduled tray's Delete, or a pier operation)."""
        reply = QMessageBox.question(
            self, "Delete", f"Delete {job.name!r} from the schedule?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if job.kind == "session" and job.sequence is not None and hasattr(job.sequence, "deschedule"):
            job.sequence.deschedule()
        else:
            self._scheduler().remove_job(job)
        self.reload()

    # --- Upcoming sessions ---------------------------------------------------

    @staticmethod
    def job_summary(job: Any) -> str:
        """One-line text summary of what *job* will do, starting with its target (a session's
        blocks in order, e.g. ``Slew To: M31 › Image: 10×300s Ha``); a pier operation is its label."""
        blocks = getattr(job.sequence, "blocks", None) if job.kind == "session" else None
        if not blocks:
            return job.name
        parts = [b.display_text for b in blocks]
        if not any(type(b).__name__ == "TargetBlock" for b in blocks):
            parts.insert(0, job.name)
        return " › ".join(parts)

    def upcoming_entries(self) -> list[tuple[datetime.datetime, Any]]:
        """Timed jobs that haven't finished yet, soonest first, as (local start, job)."""
        now = _now_utc()
        rows = []
        for job in self.timed_jobs():
            window = job.effective_window()
            if window is not None and window[1] >= now:
                rows.append((window[0], job))
        rows.sort(key=lambda r: r[0])
        return [(start.astimezone(), job) for start, job in rows]

    def _refresh_upcoming(self) -> None:
        entries = self.upcoming_entries()
        self._upcoming_list.setPlainText(
            "\n".join(f"{start.strftime('%a %b %d  %H:%M')}  —  {self.job_summary(job)}" for start, job in entries)
            or "No upcoming sessions scheduled.")

    # --- Refresh ---------------------------------------------------------------

    def reload(self) -> None:
        scheduler = self._scheduler()
        scheduler.reap_completed_jobs()
        day_start = self.displayed_day_start_local()
        self._mini_calendar.setSelectedDate(QDate(day_start.year, day_start.month, day_start.day))
        pier_name = self._active_pier_name()
        subject = pier_name or "Observatory"
        self._subtitle.setText(
            f"{subject} OPEN to CLOSE, starting the night of: {day_start.strftime('%A, %B %d, %Y')}")
        self._back_btn.setEnabled(self._displayed_day_offset > -_MAX_DAYS_BACK)
        self._canvas.refresh()
        self._refresh_upcoming()

        while self._unscheduled_layout.count() > 1:
            w = take_widget(self._unscheduled_layout)
            if w is not None:
                w.deleteLater()
        untimed = self.untimed_jobs()
        for job in untimed:
            self._unscheduled_layout.insertWidget(
                self._unscheduled_layout.count() - 1, _UnscheduledBlockWidget(job, self))

        if pier_name is None:
            self._status.setText("Create a Pier to see its schedule.")
        else:
            text = (f"{len(scheduler.jobs)} entr{'y' if len(scheduler.jobs) == 1 else 'ies'} for {pier_name} "
                    f"({len(untimed)} unscheduled).")
            blocked = scheduler.safety_block_reason()      # SCHED-060: why jobs are being held
            self._shown_block_reason = blocked
            if blocked:
                text += f"  BLOCKED — unsafe conditions: {blocked}. Jobs resume when conditions are safe."
            self._status.setText(text)
