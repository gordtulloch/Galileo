# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Observatory dashboard screen (OBS-060, OBS-150): every Pier's activity at a glance.

One very compact timeline per Pier of the selected Observatory — lanes for the session, mount,
meridian flip, guiding, plate solving, focusing and capture, plus the guide error as a trace and a
scatter plot — drawn from what ``galileo.dashboard_timeline`` has been recording. Above the
timelines is a strip for plugins that publish a view on the Dashboard (a plugin's *Publish on
Dashboard* option, OBS-150), sized to whatever height the timelines leave free so that every Pier's
timeline stays in view.

The page records in the background whether or not it is on screen (an in-memory sample of each Pier
once a second, on the UI thread, reading only state that already exists in memory). Reading the
Piers and their queued jobs touches the database, so that is done on a worker thread, every couple
of seconds while the screen is showing and rarely otherwise; the UI thread never starts a second
collection while one is running.
"""

from __future__ import annotations

import contextlib
import logging
import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from galileo import dashboard_timeline as tl
from galileo.dashboard_timeline import PierActivity, PierTimeline, TimelineRecorder

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_MS = 2000
HIDDEN_REFRESH_EVERY = 8          # while the screen is not showing, collect on every 8th refresh
SAMPLE_INTERVAL_MS = 1000
MIN_PLUGIN_STRIP_H = 140          # the plugin strip is never squeezed below this (the page scrolls instead)

_now: Callable[[], float] = time.time     # replaced in tests


# --- Data (no Qt state; tested directly) -----------------------------------------------------

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
    every other Pier reports disconnected. Each row gains ``selected``, ``pier_key`` and ``pier_id``."""
    from galileo.current_object import pier_key
    from galileo.observatory import Observatory, Pier

    runs, schedulers = runs or {}, schedulers or {}
    observatory = Observatory(observatory_name)
    keys, ids = {}, {}
    for record in pier_records:
        pier = Pier(record.name)
        key = pier_key(record)
        keys[record.name] = key
        ids[record.name] = getattr(record, "id", None)
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
        row["pier_key"] = keys[row["pier_name"]]
        row["pier_id"] = ids[row["pier_name"]]
        row["sequence_state"] = str(getattr(row["sequence_state"], "value", row["sequence_state"]))
    return rows


def describe_scheduler(row: dict) -> str:
    """The scheduler summary: the running job, the queue depth, or idle."""
    if row["scheduler_state"] == "running":
        more = f" (+{row['queued_jobs']} queued)" if row["queued_jobs"] else ""
        return f"running: {row['active_job']}{more}"
    if row["scheduler_state"] == "queued":
        return f"{row['queued_jobs']} queued"
    return "idle"


def describe_pier(row: dict | None, activity: PierActivity) -> str:
    """The one-line status in a Pier timeline's header."""
    parts: list[str] = []
    if activity.session:
        name = f" {activity.session_label}" if activity.session_label else ""
        parts.append(f"Session{name}: {activity.session}")
    elif row is not None and row.get("scheduler_state") != "idle":
        parts.append(describe_scheduler(row))
    else:
        parts.append("No session")
    if activity.mount:
        parts.append(f"mount {activity.mount}")
    elif row is not None and row.get("equipment_state") == "disconnected":
        parts.append("not connected")
    if activity.guide:
        parts.append(f"guiding: {activity.guide}" if activity.guide != "guiding" else "guiding")
    if activity.guide_error is not None:
        parts.append(f"error {math.hypot(*activity.guide_error):.2f}″")
    return " · ".join(parts)


def _local(t: float) -> datetime:
    return datetime.fromtimestamp(t, tz=UTC).astimezone()


_TICK_STEPS_S = (300, 600, 900, 1800, 3600, 7200, 10800, 21600)


def nice_ticks(t0: float, t1: float, max_ticks: int = 9) -> list[float]:
    """Times (epoch seconds) of the time-axis ticks in ``[t0, t1]``: the smallest of 5 min … 6 h
    that gives no more than *max_ticks*, on round local clock times."""
    span = max(1.0, t1 - t0)
    step = next((s for s in _TICK_STEPS_S if span / s <= max_ticks), _TICK_STEPS_S[-1])
    offset = _local(t0).utcoffset()
    off = offset.total_seconds() if offset is not None else 0.0
    first = math.ceil((t0 + off) / step) * step - off
    ticks = []
    t = first
    while t <= t1:
        ticks.append(t)
        t += step
    return ticks


def guide_scale(samples: list[tuple[float, float, float]], floor: float = 1.0) -> float:
    """Half-height of the guide trace's vertical axis in arcsec: the largest error seen, rounded up
    to a whole arcsecond, and never less than *floor*."""
    peak = max((max(abs(ra), abs(dec)) for _t, ra, dec in samples), default=0.0)
    return max(floor, float(math.ceil(peak)))


# --- Painting ----------------------------------------------------------------------------------

_GREEN = {tl.OK: "#34c759", tl.WARN: "#ffd60a", tl.BAD: "#ff453a", tl.LIGHT: "#f2f2f2", tl.CAL: "#3b82f6"}
# Night-vision theme: red channel only (UI-011), told apart by brightness.
_RED = {tl.OK: "#8a0000", tl.WARN: "#c80000", tl.BAD: "#ff0000", tl.LIGHT: "#e00000", tl.CAL: "#500000"}


class PierTimelineWidget(QWidget):
    """One Pier's timeline: header, seven lanes, guide trace, time axis and guide scatter."""

    HEADER_H = 16
    LANE_H = 11
    LANE_GAP = 1
    LABEL_W = 50
    SCATTER_W = 96
    PLOT_H = 44
    AXIS_H = 12
    PAD = 4
    HEIGHT = HEADER_H + len(tl.LANES) * (LANE_H + LANE_GAP) + 3 + PLOT_H + AXIS_H + 2

    open_requested = Signal()

    def __init__(self, timeline: PierTimeline, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.timeline = timeline
        self.title = timeline.name
        self.status = ""
        self.selected = False
        self._colors = {k: QColor(v) for k, v in _GREEN.items()}
        self._palette = {"bg": "#1c2126", "lane": "#263238", "grid": "#37474f", "text": "#d7dadd", "dim": "#8a949c"}
        self._red = False
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(320)
        self.setMouseTracking(True)
        self.setObjectName("PierTimeline")

    def set_theme(self, palette: dict, red: bool) -> None:
        self._palette = {"bg": palette["surface_alt"], "lane": palette["bg"], "grid": palette["border"],
                         "text": palette["text"], "dim": palette["text_dim"]}
        self._red = red
        self._colors = {k: QColor(v) for k, v in (_RED if red else _GREEN).items()}
        self.update()

    def set_info(self, title: str, status: str, selected: bool) -> None:
        if (title, status, selected) != (self.title, self.status, self.selected):
            self.title, self.status, self.selected = title, status, selected
            self.update()

    # --- Geometry ---------------------------------------------------------------------

    def _x_range(self) -> tuple[float, float]:
        return self.PAD + self.LABEL_W, self.width() - self.SCATTER_W - 2 * self.PAD

    def _lane_y(self, index: int) -> float:
        return self.HEADER_H + index * (self.LANE_H + self.LANE_GAP)

    def _plot_top(self) -> float:
        return self._lane_y(len(tl.LANES)) + 3

    # --- Painting ---------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        pal = self._palette
        p.fillRect(self.rect(), QColor(pal["bg"]))
        now = _now()
        t0, t1 = self.timeline.window(now)
        x0, x1 = self._x_range()
        if x1 - x0 < 20:
            return

        def tx(t: float) -> float:
            return x0 + (t - t0) / (t1 - t0) * (x1 - x0)

        small = QFont(self.font())
        small.setPointSizeF(7.5)
        bold = QFont(small)
        bold.setBold(True)
        bold.setPointSizeF(8.5)

        # Header: Pier name and its one-line status.
        p.setFont(bold)
        p.setPen(QColor(pal["text"]))
        label = self.title + (" •" if self.selected else "")
        p.drawText(QRectF(self.PAD, 0, self.width(), self.HEADER_H), Qt.AlignmentFlag.AlignVCenter, label)
        name_w = p.fontMetrics().horizontalAdvance(label) + 12
        p.setFont(small)
        p.setPen(QColor(pal["dim"]))
        p.drawText(QRectF(self.PAD + name_w, 0, self.width() - name_w - 2 * self.PAD, self.HEADER_H),
                   Qt.AlignmentFlag.AlignVCenter, self.status)

        # Time grid and axis labels.
        plot_top = self._plot_top()
        axis_y = plot_top + self.PLOT_H
        grid = QPen(QColor(pal["grid"]))
        grid.setWidth(1)
        for t in nice_ticks(t0, t1):
            x = tx(t)
            p.setPen(grid)
            p.drawLine(QPointF(x, self.HEADER_H), QPointF(x, axis_y))
            p.setPen(QColor(pal["dim"]))
            stamp = _local(t).strftime("%H:%M")
            p.drawText(QRectF(x - 20, axis_y + 1, 40, self.AXIS_H), Qt.AlignmentFlag.AlignCenter, stamp)

        # Lanes.
        for i, lane in enumerate(tl.LANES):
            y = self._lane_y(i)
            p.fillRect(QRectF(x0, y, x1 - x0, self.LANE_H), QColor(pal["lane"]))
            p.setPen(QColor(pal["dim"]))
            p.drawText(QRectF(self.PAD, y, self.LABEL_W - 4, self.LANE_H),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, tl.LANE_LABELS[lane])
            inset = 0.5 if lane == tl.CAPTURE else 0.0
            for seg in self.timeline.segments(lane):
                end = now if seg.end is None else seg.end
                if end < t0:
                    continue
                xa, xb = max(x0, tx(seg.start)), min(x1, tx(end))
                p.fillRect(QRectF(xa + inset, y + 1, max(1.0, xb - xa - 2 * inset), self.LANE_H - 2),
                           self._colors.get(seg.state, self._colors[tl.OK]))

        # Guide trace.
        samples = [s for s in self.timeline.guide_samples() if s[0] >= t0]
        scale = guide_scale(samples)
        stride = max(1, len(samples) // max(1, int(2 * (x1 - x0))))     # about two points per pixel is plenty
        mid = plot_top + self.PLOT_H / 2
        p.fillRect(QRectF(x0, plot_top, x1 - x0, self.PLOT_H), QColor(pal["lane"]))
        p.setPen(grid)
        p.drawLine(QPointF(x0, mid), QPointF(x1, mid))
        p.setPen(QColor(pal["dim"]))
        p.setFont(small)
        p.drawText(QRectF(self.PAD, plot_top, self.LABEL_W - 4, 12),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"±{scale:g}″")
        trace_colors = (self._colors[tl.CAL], self._colors[tl.BAD] if not self._red else self._colors[tl.LIGHT])
        for column, color, name, ly in ((1, trace_colors[0], "RA", 14), (2, trace_colors[1], "Dec", 25)):
            p.setPen(color)
            p.drawText(QRectF(self.PAD, plot_top + ly, self.LABEL_W - 4, 11),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, name)
            pen = QPen(color)
            pen.setWidthF(1.0)
            p.setPen(pen)
            previous = None
            for sample in samples[::stride]:
                point = QPointF(tx(sample[0]), mid - sample[column] / scale * (self.PLOT_H / 2 - 1))
                if previous is not None and sample[0] - previous[0] <= 30 * stride:
                    p.drawLine(QPointF(tx(previous[0]), previous[1]), point)
                previous = (sample[0], point.y())

        self._paint_scatter(p, samples, scale)
        p.end()

    def _paint_scatter(self, p: QPainter, samples: list, scale: float) -> None:
        """The guide error of the last couple of minutes as a dot cloud inside 1″ / 2″ rings."""
        pal = self._palette
        side = float(self.SCATTER_W)
        left = self.width() - self.PAD - side
        top = self.HEADER_H
        size = min(side, self._plot_top() + self.PLOT_H - top)
        centre = QPointF(left + side / 2, top + size / 2)
        half = size / 2 - 1
        extent = max(2.0, scale)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor(pal["grid"]))
        p.drawLine(QPointF(centre.x() - half, centre.y()), QPointF(centre.x() + half, centre.y()))
        p.drawLine(QPointF(centre.x(), centre.y() - half), QPointF(centre.x(), centre.y() + half))
        for radius_arcsec, color in ((1.0, self._colors[tl.OK]), (2.0, self._colors[tl.WARN])):
            r = radius_arcsec / extent * half
            if r <= half:
                p.setPen(color)
                p.drawEllipse(centre, r, r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._colors[tl.LIGHT]))
        for _t, ra, dec in samples[-120:]:
            p.drawEllipse(QPointF(centre.x() + ra / extent * half, centre.y() - dec / extent * half), 1.2, 1.2)

    # --- Interaction --------------------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        x0, x1 = self._x_range()
        lane_index = int((pos.y() - self.HEADER_H) // (self.LANE_H + self.LANE_GAP))
        if not (0 <= lane_index < len(tl.LANES) and x0 <= pos.x() <= x1):
            QToolTip.hideText()
            return
        now = _now()
        t0, t1 = self.timeline.window(now)
        t = t0 + (pos.x() - x0) / (x1 - x0) * (t1 - t0)
        lane = tl.LANES[lane_index]
        for seg in self.timeline.segments(lane):
            end = now if seg.end is None else seg.end
            if seg.start <= t <= end:
                began = _local(seg.start).strftime("%H:%M:%S")
                minutes = (end - seg.start) / 60
                text = f"{tl.LANE_LABELS[lane]}: {seg.state}" + (f" — {seg.label}" if seg.label else "")
                QToolTip.showText(event.globalPosition().toPoint(), f"{text}\nfrom {began}, {minutes:.1f} min", self)
                return
        QToolTip.hideText()

    def mouseDoubleClickEvent(self, _event) -> None:
        self.open_requested.emit()


# --- The page ------------------------------------------------------------------------------------

class DashboardPage(QWidget):
    """The multi-Pier activity dashboard (OBS-060, OBS-150)."""

    _collected = Signal(object)         # rows from the worker thread, delivered on the UI thread

    def __init__(self, window: Any) -> None:
        super().__init__()
        self.setObjectName("DashboardPage")
        self._app = window
        self._busy = False
        self._rows: list[dict] = []
        self._recorder = TimelineRecorder()
        self._widgets: dict[Any, PierTimelineWidget] = {}
        self._plugin_widgets: dict[str, QWidget] = {}
        self._ticks = 0
        self._manual: dict[str, Any] = {"focus": None, "align": None}    # Pier key of a focus / solve run from its own screen

        outer = QVBoxLayout(self)
        title = QLabel("Dashboard")
        title.setObjectName("PageTitle")
        outer.addWidget(title)
        self._subtitle = QLabel()
        outer.addWidget(self._subtitle)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self._content = QVBoxLayout(content)
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(6)
        self._strip = QWidget()                       # plugins' published views sit here, above the timelines
        self._strip.setObjectName("DashboardPluginStrip")
        self._strip_layout = QHBoxLayout(self._strip)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(6)
        self._strip.hide()
        self._content.addWidget(self._strip)
        self._piers = QVBoxLayout()
        self._piers.setSpacing(6)
        self._content.addLayout(self._piers)
        self._content.addStretch(1)
        self._scroll.setWidget(content)
        outer.addWidget(self._scroll, 1)

        self._collected.connect(self._show)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._sampler = QTimer(self)
        self._sampler.setInterval(SAMPLE_INTERVAL_MS)
        self._sampler.timeout.connect(self.sample)
        self._sampler.start()
        self._subscribe_bus()
        self.sync_plugins()
        self._render([])

    # --- Manual focus / solve runs (started from their own screens; they carry no Pier) -------

    def _subscribe_bus(self) -> None:
        from galileo.bus import (
            FocusCompleteEvent,
            FocusStartedEvent,
            SolveCompleteEvent,
            SolveStartedEvent,
            get_bus,
        )
        bus = get_bus()
        pairs = ((FocusStartedEvent, "focus", True), (FocusCompleteEvent, "focus", False),
                 (SolveStartedEvent, "align", True), (SolveCompleteEvent, "align", False))
        handlers = []
        for event_type, what, start in pairs:
            def handler(_event, what=what, start=start) -> None:
                self._manual[what] = self._selected_key() if start else None
            bus.subscribe(event_type, handler)
            handlers.append((event_type, handler))

        def unsubscribe(*_args) -> None:
            for event_type, handler in handlers:
                bus.unsubscribe(event_type, handler)

        self.destroyed.connect(unsubscribe)

    def _selected_key(self) -> Any:
        from galileo.current_object import pier_key
        return pier_key(getattr(self._app, "_current_pier", None))

    # --- Recording -----------------------------------------------------------------------------

    def sample(self) -> None:
        """Fold every Pier's current state into its timeline. Runs every second, on or off screen;
        reads in-memory state only."""
        rows = self._rows
        if not rows:
            return
        app = self._app
        controller = getattr(app, "__dict__", {}).get("_session_controller")
        progress = controller.progress_snapshot() if controller is not None else {}
        pages = getattr(app, "_device_pages", {})
        selected = self._selected_key()
        now = _now()
        for row in rows:
            key = row["pier_key"]
            is_selected = key == selected
            try:
                mount = self._device(pages.get("mount"), "adapter", "adapter_for", key, is_selected)
                guider = self._device(pages.get("guider"), "get_service", "service_for", row.get("pier_id"),
                                      is_selected, call_selected=True)
            except Exception:
                logger.exception("Could not read the devices of Pier %r", row["pier_name"])
                mount = guider = None
            run, name = progress.get(key, (None, ""))
            activity = tl.activity_from_progress(
                run, mount, guider, manual_focus=self._manual["focus"] == key,
                manual_align=self._manual["align"] == key, session_name=name)
            self._recorder.timeline(key, row["pier_name"]).record(activity, now)

    @staticmethod
    def _device(state: dict | None, selected_name: str, other_name: str, other_key: Any,
                is_selected: bool, call_selected: bool = False) -> Any:
        state = state or {}
        if is_selected:
            getter = state.get(selected_name)
            return (getter() if call_selected and getter else getter) if getter else None
        lookup = state.get(other_name)
        return lookup(other_key) if lookup else None

    # --- Plugin strip --------------------------------------------------------------------------

    def sync_plugins(self) -> None:
        """Show the views of exactly the plugins that are enabled and ticked *Publish on Dashboard*."""
        from galileo.plugins import is_published_on_dashboard
        pm = getattr(self._app, "_plugin_manager", None)
        wanted: dict[str, Any] = {}
        if pm is not None:
            for plugin in pm.get_ui_registry().get_dashboard_plugins():
                try:
                    if pm.is_active(plugin.name) and is_published_on_dashboard(plugin):
                        wanted[plugin.name] = plugin
                except Exception:
                    logger.exception("Could not tell whether plugin %r publishes on the Dashboard", plugin.name)
        for name in [n for n in self._plugin_widgets if n not in wanted]:
            widget = self._plugin_widgets.pop(name)
            self._strip_layout.removeWidget(widget)
            widget.deleteLater()
        for name, plugin in wanted.items():
            if name in self._plugin_widgets:
                continue
            try:
                widget = plugin.build_dashboard_widget()
            except Exception:
                logger.exception("Plugin %r dashboard view failed to build", name)
                continue
            if widget is not None:
                self._plugin_widgets[name] = widget
                self._strip_layout.addWidget(widget, 1)
        self._strip.setVisible(bool(self._plugin_widgets))
        self._fit_strip()

    def _fit_strip(self) -> None:
        """Give the plugin strip whatever height the Pier timelines leave free, so all of them stay
        visible; with very many Piers the strip keeps a minimum and the page scrolls."""
        if not self._plugin_widgets:
            return
        spacing = self._content.spacing()
        timelines = len(self._widgets) * (PierTimelineWidget.HEIGHT + self._piers.spacing())
        used = self._subtitle.geometry().bottom() + 12 + timelines + spacing
        self._strip.setFixedHeight(max(MIN_PLUGIN_STRIP_H, self.height() - used))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_strip()

    # --- Refresh ---------------------------------------------------------------------------------

    def _tick(self) -> None:
        self._ticks += 1
        if self.isVisible() or self._ticks % HIDDEN_REFRESH_EVERY == 0:
            self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.sync_plugins()
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

    # --- Display ---------------------------------------------------------------------------------

    def _render(self, rows: list[dict]) -> None:
        self._rows = rows
        observatory = getattr(self._app, "_current_observatory", None)
        if observatory is None:
            self._subtitle.setText("No Observatory selected.")
        else:
            self._subtitle.setText(f"{observatory.name} — {len(rows)} Pier{'s' if len(rows) != 1 else ''}")
        self._recorder.forget_except(r["pier_key"] for r in rows)
        theme = getattr(self._app, "_theme", None)
        palette = theme.palette() if theme is not None else None
        red = False
        if theme is not None:
            from galileo.ui.theme import Theme
            red = theme.current_theme == Theme.RED

        keys = [r["pier_key"] for r in rows]
        for key in [k for k in self._widgets if k not in keys]:
            gone = self._widgets.pop(key)
            self._piers.removeWidget(gone)
            gone.deleteLater()
        for index, row in enumerate(rows):
            key = row["pier_key"]
            timeline = self._recorder.timeline(key, row["pier_name"])
            existing = self._widgets.get(key)
            widget = existing if existing is not None else PierTimelineWidget(timeline)
            if existing is None:
                widget.open_requested.connect(lambda k=key: self.open_pier(k))
                self._widgets[key] = widget
            self._piers.insertWidget(index, widget)
            if palette is not None:
                widget.set_theme(palette, red)
            widget.set_info(row["pier_name"], describe_pier(row, timeline.latest), bool(row.get("selected")))
            widget.update()
        self._fit_strip()

    def open_pier(self, key: Any) -> None:
        """Make the Pier with *key* the working Pier (the focused single-Pier view) — a double-click
        on its timeline."""
        row = next((r for r in self._rows if r["pier_key"] == key), None)
        combo = getattr(self._app, "_pier_combo", None)
        if row is None or combo is None:
            return
        index = combo.findText(row["pier_name"])
        if index < 0:
            return
        combo.setCurrentIndex(index)
        self._app._on_pier_activated(index)
        self.reload()
