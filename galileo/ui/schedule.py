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

import datetime
import logging
import math
from typing import Any

from PySide6.QtCore import QDate, QMimeData, QPoint, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QDrag, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QCheckBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_AXIS_WIDTH = 56
_HEADER_HEIGHT = 40
_MIN_COLUMN_WIDTH = 170
_MIN_BLOCK_HEIGHT = 20
_BLOCK_MARGIN = 4
_PIXELS_PER_HOUR_STEPS = [16, 24, 32, 48, 64, 96]
_DEFAULT_PPH_INDEX = 2  # 32 px/hour
_MIN_DAYS = 1
_MAX_DAYS = 7
_DEFAULT_DAYS = 4
_MAX_DAYS_BACK = 7

# Fallback night window (local hours since that night's own midnight, so
# 31.0 means 07:00 the next calendar day) when no Observatory location is
# configured to compute the real dusk/dawn times — chosen to comfortably
# frame a typical mid-latitude observing night.
_DEFAULT_WINDOW_START_HOUR = 17.0
_DEFAULT_WINDOW_END_HOUR = 31.0
_WINDOW_PADDING_HOURS = 1.0

# Display label for each pier-level operation, in the order the "Add Pier
# Operation" context-menu shows them (PSD/user-facing wording) — distinct
# from the underlying action-block's own ``label`` (galileo.ui.sessions),
# which the Sessions screen's own palette uses instead; both map to the same
# block *class*, just different copy.
_PIER_OP_LABELS: dict[str, str] = {
    "DomeOpenBlock": "Open Dome",
    "DomeCloseBlock": "Close Dome",
    "UnparkMountBlock": "Unpark Scope",
    "ParkMountBlock": "Park Scope",
    "DomeSyncBlock": "Dome Sync",
}
_PIER_OP_DEFAULT_MINUTES = 15.0

# Sky-gradient endpoints for the almanac shading (pale daylight -> twilight ->
# night), independent of the active theme — a night-sky colour cue reads the
# same regardless of the app's own light/dark styling. Theme.RED (night
# vision, UI-011) is special-cased separately: every colour it produces must
# stay red-only, so it can't use this gradient at all.
_SKY_DAY = (0xCF, 0xE3, 0xF5)
_SKY_TWILIGHT = (0x5B, 0x6E, 0x8C)
_SKY_NIGHT = (0x10, 0x14, 0x20)

_SUN_TRACK_CACHE: dict[tuple, dict] = {}
_MOON_PHASE_CACHE: dict[str, dict | None] = {}


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
# galileo.ui.app_window._widgets); the calendar itself is drawn in local
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


def _local_midnight(day: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time()).astimezone()


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


def _cached_sun_track(location: Any, date_str: str) -> dict:
    key = (round(location.latitude, 3), round(location.longitude, 3), date_str)
    cached = _SUN_TRACK_CACHE.get(key)
    if cached is None:
        from galileo.planning.visibility import sun_altitude_track
        cached = sun_altitude_track(location, date_str, resolution_min=10)
        _SUN_TRACK_CACHE[key] = cached
    return cached


def _cached_moon_phase(date_str: str) -> dict | None:
    if date_str not in _MOON_PHASE_CACHE:
        from galileo.planning.visibility import moon_phase_info
        _MOON_PHASE_CACHE[date_str] = moon_phase_info(date_str)
    return _MOON_PHASE_CACHE[date_str]


def _almanac_band_color(darkness: float, theme_mgr: Any) -> QColor:
    """A sky colour for *darkness* (0.0 daylight .. 1.0 astronomically dark).
    Theme.RED stays red-only (UI-011); every other theme gets the same fixed
    day->twilight->night gradient regardless of light/dark mode, since it's a
    sky colour cue, not a surface tone."""
    from galileo.ui.theme import Theme
    if theme_mgr is not None and theme_mgr.current_theme == Theme.RED:
        r = int(90 - darkness * 72)
        return QColor(max(14, r), 0, 0)

    def lerp(a: int, b: int, t: float) -> int:
        return round(a + (b - a) * t)

    if darkness <= 0.5:
        t = darkness / 0.5
        c = tuple(lerp(_SKY_DAY[i], _SKY_TWILIGHT[i], t) for i in range(3))
    else:
        t = (darkness - 0.5) / 0.5
        c = tuple(lerp(_SKY_TWILIGHT[i], _SKY_NIGHT[i], t) for i in range(3))
    return QColor(*c)


def _crossing_hour(times_iso: list[str], altitudes: list[float], rising: bool) -> float | None:
    """The hour-of-day (local, 0-24) of the first (*rising*) or last
    (falling) Sun-altitude crossing of 0° across one calendar day's track —
    sunrise or sunset — interpolated between the straddling samples for a
    finer time than the track's own sampling resolution, the same technique
    ``galileo.planning.visibility.rise_transit_set`` already uses for its own
    horizon crossings. ``None`` if the Sun never crosses 0° that day (e.g.
    polar day/night)."""
    hits: list[float] = []
    for i in range(len(altitudes) - 1):
        a0, a1 = altitudes[i], altitudes[i + 1]
        crossed = (a0 < 0.0 <= a1) if rising else (a0 >= 0.0 > a1)
        if not crossed:
            continue
        t0 = datetime.datetime.fromisoformat(times_iso[i])
        t1 = datetime.datetime.fromisoformat(times_iso[i + 1])
        frac = 0.0 if a1 == a0 else max(0.0, min(1.0, -a0 / (a1 - a0)))
        hour0 = t0.hour + t0.minute / 60.0 + t0.second / 3600.0
        hits.append(hour0 + frac * (t1 - t0).total_seconds() / 3600.0)
    if not hits:
        return None
    return hits[0] if rising else hits[-1]


def _night_window_hours(location: Any, night_date: datetime.date) -> tuple[float, float] | None:
    """(sunset_hour, sunrise_hour) for the night starting on *night_date*'s
    evening, both in hours since *night_date*'s own local midnight — sunset
    in [0, 24), sunrise in [24, 48) since it falls the next calendar day.
    ``None`` when the Sun doesn't both set that evening and rise the next
    morning (e.g. high-latitude summer)."""
    evening = _cached_sun_track(location, night_date.isoformat())
    morning = _cached_sun_track(location, (night_date + datetime.timedelta(days=1)).isoformat())
    if not evening["times"] or not morning["times"]:
        return None
    sunset = _crossing_hour(evening["times"], evening["altitudes"], rising=False)
    sunrise = _crossing_hour(morning["times"], morning["altitudes"], rising=True)
    if sunset is None or sunrise is None:
        return None
    return sunset, sunrise + 24.0


def _shared_night_window(location: Any | None, column_dates: list[datetime.date]) -> tuple[float, float]:
    """The (start, end) local-hour range shared by every visible day column —
    top of the grid is dusk, bottom is dawn, so a night sits centered in its
    column rather than split across a plain calendar day's midnight-crossing
    top/bottom edges. The widest sunset-to-sunrise span among *column_dates*,
    padded, or a fixed default when there's no location or the Sun doesn't
    set/rise on any visible night."""
    if location is not None:
        starts: list[float] = []
        ends: list[float] = []
        for d in column_dates:
            window = _night_window_hours(location, d)
            if window is not None:
                starts.append(window[0])
                ends.append(window[1])
        if starts:
            return (
                max(0.0, min(starts) - _WINDOW_PADDING_HOURS),
                min(48.0, max(ends) + _WINDOW_PADDING_HOURS),
            )
    return _DEFAULT_WINDOW_START_HOUR, _DEFAULT_WINDOW_END_HOUR


def _night_column_and_hour(local_dt: datetime.datetime) -> tuple[datetime.date, float]:
    """Which night column *local_dt* belongs to, and its hour-offset since
    that night's own local midnight (0-48 scale): afternoon/evening (hour
    >= 12) belongs to *that* date's night; the small hours belong to the
    *previous* date's night (its early-morning tail) — a 2am job lands with
    the evening that led into it, not a following night that hasn't started."""
    hour = local_dt.hour + local_dt.minute / 60.0 + local_dt.second / 3600.0
    if hour >= 12.0:
        return local_dt.date(), hour
    return local_dt.date() - datetime.timedelta(days=1), hour + 24.0


def _sun_darkness_samples(
    location: Any, night_date: datetime.date, theme_mgr: Any, window_start: float, window_end: float,
) -> dict | None:
    """Per-sample (hour-offset, darkness, colour) across the shared night
    window for *night_date*'s own night — combining that date's evening track
    with the next date's morning track (a night spans two calendar dates),
    restricted to [*window_start*, *window_end*]. Darkness remaps the Sun's
    altitude so 0° (horizon) is 0.0 and -18° (astronomical twilight) or lower
    is 1.0, continuous rather than the discrete Daylight/Twilight/Night
    buckets ``galileo.planning.visibility.day_night_bands`` uses, since a
    smooth sky gradient reads better on a calendar block than hard edges."""
    evening = _cached_sun_track(location, night_date.isoformat())
    morning = _cached_sun_track(location, (night_date + datetime.timedelta(days=1)).isoformat())
    samples: list[tuple[float, float]] = []
    for track, day_offset in ((evening, 0.0), (morning, 24.0)):
        for t_iso, alt in zip(track["times"], track["altitudes"], strict=True):
            t = datetime.datetime.fromisoformat(t_iso)
            hour = day_offset + t.hour + t.minute / 60.0 + t.second / 3600.0
            if window_start - 0.01 <= hour <= window_end + 0.01:
                samples.append((hour, alt))
    if not samples:
        return None
    samples.sort(key=lambda s: s[0])
    span = max(0.01, window_end - window_start)
    hours = [h for h, _ in samples]
    darkness = [max(0.0, min(1.0, -alt / 18.0)) for _, alt in samples]
    stops = [
        (max(0.0, min(1.0, (h - window_start) / span)), _almanac_band_color(dk, theme_mgr))
        for h, dk in zip(hours, darkness, strict=True)
    ]
    return {"hours": hours, "darkness": darkness, "stops": stops}


def _darkest_evening_hour(sample: dict | None) -> float | None:
    """The midpoint hour-offset of the longest fully-dark stretch in *sample*
    (its window already spans dusk to dawn, so there's exactly one night to
    find) — where the Moon-phase label lands. ``None`` when the Sun never
    gets fully dark within the window (e.g. high-latitude summer)."""
    if not sample:
        return None
    best: tuple[float, float] | None = None
    run_start: float | None = None
    run_end: float | None = None
    for hour, dark in zip(sample["hours"], sample["darkness"], strict=True):
        if dark >= 0.9:
            if run_start is None:
                run_start = hour
            run_end = hour
        else:
            if run_start is not None and (best is None or (run_end - run_start) > (best[1] - best[0])):
                best = (run_start, run_end)
            run_start = None
    if run_start is not None and (best is None or (run_end - run_start) > (best[1] - best[0])):
        best = (run_start, run_end)
    return (best[0] + best[1]) / 2.0 if best else None


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


def _job_color(job: Any, window: Any = None) -> QColor:
    """Reuses the Sessions screen's own colour-by-block-type identity
    (``galileo.ui.sessions._block_color``) so a pier operation looks the same
    on both screens; a session job gets a fixed identity of its own."""
    from galileo.ui.sessions import _block_color
    kind_name = job.pier_op_kind if job.kind == "pier_op" else "SessionJob"
    return _block_color(kind_name, window)


class _ScheduleBlockWidget(QFrame):
    """One SchedulerJob's block on the calendar (SCHED-110): positioned by
    start time and sized to duration, coloured by kind, bordered by outcome
    (SCHED-140), draggable to another day/time, right-click to edit its time
    or view its log."""

    def __init__(self, job: Any, canvas: _CalendarCanvas, window: Any = None, parent=None) -> None:
        super().__init__(parent)
        self.job = job
        self._canvas = canvas
        self._window = window
        self.setFrameShape(QFrame.Shape.Box)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 3, 2)
        layout.setSpacing(2)
        self._label = QLabel(job.name)
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)
        self._log_btn = QPushButton("Log")
        self._log_btn.clicked.connect(lambda: _LogDialog(self.job, self).exec())
        layout.addWidget(self._log_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.apply_style()
        self._drag_origin: QPoint | None = None
        self._drag_start_pos = QPoint()

    def apply_style(self) -> None:
        color = _job_color(self.job, self._window)
        border = {"completed": "#2e9e3f", "error": "#cc3333"}.get(self.job.run_state, "#555555")
        border_width = 2 if self.job.run_state in ("completed", "error") else 1
        # Log only has something to show once a run has actually happened —
        # no execution engine writes to run_log until then (SCHED-140), so a
        # still-pending block skips the button rather than offering a dialog
        # that would only ever say "No log entries yet".
        self._log_btn.setVisible(self.job.run_state != "pending")
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
            self._drag_start_pos = self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is not None:
            delta = event.globalPosition().toPoint() - self._drag_origin
            new_pos = self._drag_start_pos + delta
            self.move(max(0, new_pos.x()), max(0, new_pos.y()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_origin is not None:
            self._drag_origin = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._canvas.reposition_from_pixels(self.job, self.x(), self.y())
        super().mouseReleaseEvent(event)


class _CalendarCanvas(QWidget):
    """The multi-day grid (SCHED-110): a shared hour axis, one column per
    visible calendar day (shaded by that day's own sunlight/twilight/
    darkness and Moon phase when an Observatory location is configured), and
    every job's block for the active Pier. Right-click on empty grid space to
    add a pier-level operation there; drop an Unscheduled block (dragged from
    below the grid, via ``SchedulePageWidget.dragging_job``) to give it a
    start time."""

    def __init__(self, page: SchedulePageWidget, parent=None) -> None:
        super().__init__(parent)
        self._page = page
        self._blocks: list[_ScheduleBlockWidget] = []
        self._column_dates: list[datetime.date] = []
        self._col_width = _MIN_COLUMN_WIDTH
        self._window_start = _DEFAULT_WINDOW_START_HOUR
        self._window_end = _DEFAULT_WINDOW_END_HOUR
        self._bands_cache: dict[datetime.date, dict] = {}
        self._moon_cache: dict[datetime.date, dict | None] = {}
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.setAcceptDrops(True)
        self.setMinimumWidth(_AXIS_WIDTH + _MIN_COLUMN_WIDTH)

    def day_start_local(self) -> datetime.datetime:
        return self._page.displayed_day_start_local()

    def refresh(self) -> None:
        for widget in self._blocks:
            widget.deleteLater()
        self._blocks = []

        num_days = self._page.num_days
        pph = self._page.pixels_per_hour
        day0 = self.day_start_local().date()
        self._column_dates = [day0 + datetime.timedelta(days=i) for i in range(num_days)]

        location = self._page.current_location()
        self._window_start, self._window_end = _shared_night_window(location, self._column_dates)

        available = max(_MIN_COLUMN_WIDTH, self._page.grid_viewport_width() - _AXIS_WIDTH)
        self._col_width = max(_MIN_COLUMN_WIDTH, available // num_days)

        total_width = _AXIS_WIDTH + self._col_width * num_days
        total_height = _HEADER_HEIGHT + int((self._window_end - self._window_start) * pph) + 8
        self.setMinimumSize(total_width, total_height)
        self.resize(total_width, total_height)

        theme_mgr = getattr(self._page.window_ref, "_theme", None)
        self._bands_cache = {}
        self._moon_cache = {}
        if self._page.show_almanac and location is not None:
            for d in self._column_dates:
                self._bands_cache[d] = _sun_darkness_samples(location, d, theme_mgr, self._window_start, self._window_end)
                self._moon_cache[d] = _cached_moon_phase(d.isoformat())

        now_local = _now_utc().astimezone()
        column_set = set(self._column_dates)
        placed_per_day: dict[datetime.date, list[tuple[Any, float, float]]] = {d: [] for d in self._column_dates}
        for job in self._page.timed_jobs():
            window = job.effective_window()
            if window is None:
                continue
            start_local = window[0].astimezone()
            end_local = window[1].astimezone()
            if not self._page.show_past and end_local < now_local:
                continue
            night_date, start_offset = _night_column_and_hour(start_local)
            if night_date not in column_set:
                continue
            # A job scheduled outside the shared dusk-to-dawn window (e.g. a
            # genuinely daytime task) still renders, pinned to whichever edge
            # of the window it's closest to, rather than vanishing from the
            # grid entirely — this screen is deliberately night-focused
            # (that's what it's for), not a general-purpose 24h calendar.
            start_offset = max(self._window_start, min(self._window_end, start_offset))
            duration_hours = max(0.0, (end_local - start_local).total_seconds() / 3600.0)
            end_offset = min(self._window_end, start_offset + duration_hours)
            placed_per_day[night_date].append((job, start_offset, max(start_offset, end_offset)))

        for col_index, d in enumerate(self._column_dates):
            entries = sorted(placed_per_day[d], key=lambda e: e[1])
            lane_right: list[float] = []
            lane_of: list[int] = []
            for _job, start_offset, end_offset in entries:
                lane = next((i for i, right in enumerate(lane_right) if start_offset >= right), None)
                if lane is None:
                    lane = len(lane_right)
                    lane_right.append(end_offset)
                else:
                    lane_right[lane] = end_offset
                lane_of.append(lane)
            lane_count = max(1, len(lane_right))
            lane_width = max(20, (self._col_width - 2 * _BLOCK_MARGIN) // lane_count)

            for (job, start_offset, end_offset), lane in zip(entries, lane_of, strict=True):
                widget = _ScheduleBlockWidget(job, self, self._page.window_ref, self)
                x = _AXIS_WIDTH + col_index * self._col_width + _BLOCK_MARGIN + lane * lane_width
                y = _HEADER_HEIGHT + int((start_offset - self._window_start) * pph)
                max_height = _HEADER_HEIGHT + int((self._window_end - self._window_start) * pph) - y
                height = max(_MIN_BLOCK_HEIGHT, min(max_height, int((end_offset - start_offset) * pph)))
                widget.setGeometry(x, y, max(20, lane_width - 2), height)
                widget.show()
                self._blocks.append(widget)

        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme_mgr = getattr(self._page.window_ref, "_theme", None)
        palette = theme_mgr.palette() if theme_mgr is not None else None
        pph = self._page.pixels_per_hour
        top = _HEADER_HEIGHT
        bottom = top + int((self._window_end - self._window_start) * pph)
        today = _now_utc().astimezone().date()
        border_color = QColor(palette["border"]) if palette else QColor(90, 90, 90)
        text_bright = QColor(palette["text_bright"]) if palette else QColor("white")

        for i, d in enumerate(self._column_dates):
            x = _AXIS_WIDTH + i * self._col_width
            column_rect = QRectF(x, top, self._col_width, bottom - top)
            sample = self._bands_cache.get(d)
            if sample is not None and sample["stops"]:
                gradient = QLinearGradient(0, top, 0, bottom)
                for frac, color in sample["stops"]:
                    gradient.setColorAt(max(0.0, min(1.0, frac)), color)
                painter.fillRect(column_rect, QBrush(gradient))
            elif palette is not None:
                painter.fillRect(column_rect, QColor(palette["surface"]))

            header_rect = QRectF(x, 0, self._col_width, _HEADER_HEIGHT)
            painter.fillRect(header_rect, QColor(palette["surface_alt"]) if palette else QColor("#333333"))
            if d == today:
                accent = theme_mgr.accent_color if theme_mgr is not None else "#12877b"
                painter.fillRect(QRectF(x, _HEADER_HEIGHT - 3, self._col_width, 3), QColor(accent))
            painter.setPen(text_bright)
            label = d.strftime("%A, %B %d, %Y") if self._col_width >= 210 else d.strftime("%a %b %d")
            painter.drawText(header_rect.adjusted(8, 0, -4, 0),
                              Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)

            moon = self._moon_cache.get(d)
            label_hour = _darkest_evening_hour(sample)
            if moon is not None and label_hour is not None:
                y = top + int((label_hour - self._window_start) * pph)
                painter.setPen(QColor("#f0f0f0"))
                text = f"{moon['name']} is up\n{moon['fraction'] * 100:.1f}% illuminated"
                painter.drawText(QRectF(x + 8, y, self._col_width - 16, 50),
                                  Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, text)

            painter.setPen(QPen(border_color))
            painter.drawLine(int(x), 0, int(x), bottom)

        grid_right = _AXIS_WIDTH + self._col_width * len(self._column_dates)
        painter.setPen(QPen(border_color))
        painter.drawLine(grid_right, 0, grid_right, bottom)

        for hour_mark in range(math.ceil(self._window_start), math.floor(self._window_end) + 1):
            y = top + int((hour_mark - self._window_start) * pph)
            painter.drawLine(0, y, grid_right, y)
            painter.drawText(4, y + 12, f"{hour_mark % 24:02d}:00")

        now_local = _now_utc().astimezone()
        now_night_date, now_offset = _night_column_and_hour(now_local)
        if self._window_start <= now_offset <= self._window_end and now_night_date in self._column_dates:
            i = self._column_dates.index(now_night_date)
            x = _AXIS_WIDTH + i * self._col_width
            y = top + int((now_offset - self._window_start) * pph)
            accent = theme_mgr.accent_color if theme_mgr is not None else "#e74c3c"
            painter.setPen(QPen(QColor(accent), 2))
            painter.drawLine(int(x), y, int(x + self._col_width), y)

        painter.end()

    def _column_and_hour_at(self, pos) -> tuple[int, float]:
        col_index = int((pos.x() - _AXIS_WIDTH) // self._col_width) if self._col_width else 0
        col_index = max(0, min(len(self._column_dates) - 1, col_index))
        pph = self._page.pixels_per_hour
        span = self._window_end - self._window_start
        offset = max(0.0, min(span, (pos.y() - _HEADER_HEIGHT) / pph))
        return col_index, self._window_start + offset

    def reposition_from_pixels(self, job: Any, x: int, y: int) -> None:
        if not self._column_dates:
            return
        col_index, hour = self._column_and_hour_at(QPoint(x, y))
        d = self._column_dates[col_index]
        new_start = _local_midnight(d) + datetime.timedelta(hours=hour)
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

    def _on_context_menu(self, pos) -> None:
        if not self._column_dates:
            return
        menu = QMenu(self)
        add_menu = menu.addMenu("Add Pier Operation")
        for cls in _pier_op_classes():
            label = _PIER_OP_LABELS.get(cls.__name__, cls.label)
            action = add_menu.addAction(label)
            action.setData((cls, label))
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None or chosen.data() is None:
            return
        block_cls, label = chosen.data()
        col_index, hour = self._column_and_hour_at(pos)
        start = _local_midnight(self._column_dates[col_index]) + datetime.timedelta(hours=hour)
        self._page.add_pier_operation(block_cls, label, start)

    def dragEnterEvent(self, event) -> None:
        if self._page.dragging_job is not None:
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._page.dragging_job is not None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        job = self._page.dragging_job
        if job is None or not self._column_dates:
            return
        col_index, hour = self._column_and_hour_at(event.position().toPoint())
        d = self._column_dates[col_index]
        new_start = _local_midnight(d) + datetime.timedelta(hours=hour)
        job.scheduled_start_utc = _format_utc(new_start.astimezone(datetime.UTC))
        self._page.save_active_scheduler()
        self._page.reload()
        event.acceptProposedAction()


class _UnscheduledBlockWidget(QFrame):
    """One not-yet-positioned job (SCHED-120): a small draggable block listed
    below the calendar rather than guessed onto it — drag it onto the grid to
    give it a start time (``_CalendarCanvas.dropEvent``), or right-click for
    Set Time…/Log/Remove."""

    def __init__(self, job: Any, page: SchedulePageWidget, parent=None) -> None:
        super().__init__(parent)
        self.job = job
        self._page = page
        self.setFrameShape(QFrame.Shape.Box)
        self.setFixedHeight(40)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 4, 2)
        self._label = QLabel(job.name)
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self._apply_style()
        self._drag_start_pos: QPoint | None = None

    def _apply_style(self) -> None:
        color = _job_color(self.job, self._page.window_ref)
        theme_mgr = getattr(self._page.window_ref, "_theme", None)
        border = theme_mgr.palette()["border"] if theme_mgr is not None else "#555555"
        self.setStyleSheet(
            f"_UnscheduledBlockWidget {{ background-color: {color.name()}; "
            f"border: 1px solid {border}; border-radius: 4px; }}"
        )

    def _on_context_menu(self, pos) -> None:
        menu = QMenu(self)
        set_time = menu.addAction("Set Time…")
        log = menu.addAction("Log")
        remove = menu.addAction("Remove from Schedule")
        action = menu.exec(self.mapToGlobal(pos))
        if action is set_time:
            dialog = _EditTimeDialog(self.job, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                dialog.apply()
                self._page.save_active_scheduler()
                self._page.reload()
        elif action is log:
            _LogDialog(self.job, self).exec()
        elif action is remove:
            self._page.remove_job(self.job)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_start_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._drag_start_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._drag_start_pos = None
            self._page.begin_job_drag(self.job)
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(self.job.name)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction)
            self._page.end_job_drag()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)


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
        self._build()
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

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._canvas = _CalendarCanvas(self)
        self._scroll.setWidget(self._canvas)
        body.addWidget(self._scroll, 1)

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
        self._mini_calendar.setSelectedDate(QDate(day_start.year, day_start.month, day_start.day))
        pier_name = self._active_pier_name()
        subject = pier_name or "Observatory"
        self._subtitle.setText(
            f"{subject} OPEN to CLOSE, starting the night of: {day_start.strftime('%A, %B %d, %Y')}")
        self._back_btn.setEnabled(self._displayed_day_offset > -_MAX_DAYS_BACK)
        self._canvas.refresh()

        while self._unscheduled_layout.count() > 1:
            item = self._unscheduled_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        untimed = self.untimed_jobs()
        for job in untimed:
            self._unscheduled_layout.insertWidget(
                self._unscheduled_layout.count() - 1, _UnscheduledBlockWidget(job, self))

        if pier_name is None:
            self._status.setText("Create a Pier to see its schedule.")
        else:
            self._status.setText(
                f"{len(scheduler.jobs)} entr{'y' if len(scheduler.jobs) == 1 else 'ies'} for {pier_name} "
                f"({len(untimed)} unscheduled).")
