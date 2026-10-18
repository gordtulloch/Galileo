# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Schedule page's calendar canvas, its draggable job blocks and the almanac helpers they draw with."""

from __future__ import annotations

import datetime
import math
from typing import Any
from PySide6.QtCore import QMimeData, QPoint, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QDrag, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QWidget
from galileo.ui.schedule_dialogs import _EditTimeDialog, _LogDialog, _format_utc, _now_utc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from galileo.ui.schedule import SchedulePageWidget



_AXIS_WIDTH = 56


_HEADER_HEIGHT = 40


_MIN_COLUMN_WIDTH = 170


_MIN_BLOCK_HEIGHT = 20


_BLOCK_MARGIN = 4


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


def _local_midnight(day: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time()).astimezone()


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
        edit = trajectory = None
        if self.job.kind == "session":
            edit = menu.addAction("Edit…")
            trajectory = menu.addAction("Show Trajectory…")
        remove = menu.addAction("Remove from Schedule")
        action = menu.exec(self.mapToGlobal(pos))
        if action is not None and action is edit:
            self._canvas._page.edit_job(self.job)
        elif action is not None and action is trajectory:
            self._canvas._page.show_trajectory(self.job)
        elif action is set_time:
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
            page = self._canvas._page
            if self.job.kind == "session" and page.is_over_unscheduled(event.globalPosition().toPoint()):
                # Dropped back on the Unscheduled tray: take it off the grid.
                page.unschedule_job(self.job)
            else:
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
        self._page.unschedule_job(job)

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
        edit = trajectory = None
        if self.job.kind == "session":
            edit = menu.addAction("Edit…")
            trajectory = menu.addAction("Show Trajectory…")
        log = menu.addAction("Log")
        remove = menu.addAction("Delete")
        action = menu.exec(self.mapToGlobal(pos))
        if action is not None and action is edit:
            self._page.edit_job(self.job)
        elif action is not None and action is trajectory:
            self._page.show_trajectory(self.job)
        elif action is set_time:
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
