# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Focus screen (FOC-010 … FOC-070): a live view onto an autofocus run.

Laid out after the reference focus screen (assets/samples/focus.png): the
focuser and camera controls on the left; the frame being measured, its star
statistics and the HFR V-curve on the right; the log along the bottom.

The screen shows a run, it does not own one. It follows the ``Focus*Event`` s
that ``galileo.autofocus.AutofocusService`` publishes on the event bus, so a
run started here, or by a session trigger, is displayed the same way. Between
runs nothing is redrawn: the last run's frame, statistics and curve stay on
screen until the next run starts or Clear is pressed. The events arrive on
whatever thread the run is on, so the handlers only prepare data and hand it
to the UI thread through queued signals; no Qt widget is touched off it.
"""

from __future__ import annotations

import logging
import math
import threading
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from galileo.autofocus import AutofocusParams
from galileo.debayer import camera_pattern
from galileo.bus import FocusCompleteEvent, FocusExposureStartedEvent, FocusFrameEvent, FocusStartedEvent, get_bus
from galileo.ui._image_view import ImagePreviewView, build_zoom_toolbar
from galileo.ui.guider import _PLOT_FG, _PlotBase
from galileo.ui.frame_layout import FrameLayoutChoice
from galileo.ui.imaging import _auto_stretch

logger = logging.getLogger(__name__)

_PREVIEW_MAX_SIDE = 1024            # frames are decimated to about this before being stretched
_NO_STATS = "Stars: 0  HFR: -1.00  FWHM: --"
_IDLE_STATUS = "Idle — this screen updates while an autofocus run is in progress."
_HFR_COLOR = QColor("#4da3ff")
_FIT_COLOR = QColor("#ffa040")
_BEST_COLOR = QColor("#31c24a")


def _preview(frame, bayer_pattern: str | None = None) -> np.ndarray | None:
    """An 8-bit, auto-stretched, decimated copy of *frame* for display — ``(h, w)``
    or ``(h, w, 3)`` — or ``None`` if it isn't an image. With *bayer_pattern* a mono mosaic is
    shown in colour (a half-resolution superpixel debayer, before any decimation, which would
    otherwise destroy the mosaic). Star measurements are always made on the raw frame."""
    arr = np.asarray(frame)
    if arr.ndim == 3:
        arr = arr if arr.shape[2] == 3 else arr[..., 0]
    elif arr.ndim != 2:
        return None
    elif bayer_pattern:
        from galileo.debayer import superpixel
        arr = superpixel(arr, bayer_pattern)
    step = max(1, max(arr.shape[:2]) // _PREVIEW_MAX_SIDE)
    return _auto_stretch(arr[::step, ::step])


class FocusImageView(ImagePreviewView):
    """The frame being measured. Fits the window until the user zooms; drag to pan."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("FocusImage")
        self.setMinimumSize(320, 240)
        self.setBackgroundBrush(QColor("#141414"))
        self.message = "No focus run yet"

    def set_image(self, data: np.ndarray | None) -> None:
        """Show *data*, an 8-bit ``(h, w)`` or ``(h, w, 3)`` array (see :func:`_preview`)."""
        if data is None:
            self.clear_image()
        else:
            self.show_array(data)
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.has_image:
            painter = QPainter(self.viewport())
            painter.setPen(QColor("#8a949c"))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            painter.end()


class VCurvePlot(_PlotBase):
    """HFR against focuser position: one point per exposure, then the fitted
    curve and the best-focus position once the run completes."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.points: list[tuple[int, float]] = []
        self.coefficients: tuple | None = None
        self.best_position: int | None = None

    def clear(self) -> None:
        self.points, self.coefficients, self.best_position = [], None, None
        self.update()

    def add_point(self, position: int, hfr: float) -> None:
        self.points.append((position, hfr))
        self.update()

    def set_fit(self, coefficients: tuple | None, best_position: int | None) -> None:
        self.coefficients, self.best_position = coefficients, best_position
        self.update()

    def _x_range(self) -> tuple[float, float]:
        xs = [p for p, _ in self.points]
        if self.best_position is not None:
            xs.append(self.best_position)
        if not xs:
            return 0.0, 5.0
        lo, hi = min(xs), max(xs)
        pad = (hi - lo) * 0.05 or 1.0
        return lo - pad, hi + pad

    def _y_max(self) -> float:
        finite = [h for _, h in self.points if math.isfinite(h)]
        return max(5.0, math.ceil(max(finite) * 1.1)) if finite else 5.0

    def paintEvent(self, event) -> None:
        painter = self._begin()
        plot = QRectF(46, 8, self.width() - 62, self.height() - 34)
        if plot.width() < 20 or plot.height() < 20:
            painter.end()
            return
        x_lo, x_hi = self._x_range()
        y_max = self._y_max()

        def x_of(x: float) -> float:
            return plot.left() + (x - x_lo) / (x_hi - x_lo) * plot.width()

        def y_of(y: float) -> float:
            return plot.bottom() - max(0.0, min(y_max, y)) / y_max * plot.height()

        painter.setPen(QPen(QColor("#ffffff")))
        painter.drawRect(plot)
        for k in range(6):
            x = plot.left() + k * plot.width() / 5
            painter.setPen(self._dotted())
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(_PLOT_FG)
            painter.drawText(QRectF(x - 30, plot.bottom() + 2, 60, 16), Qt.AlignmentFlag.AlignCenter, f"{x_lo + k * (x_hi - x_lo) / 5:.0f}")
        step = max(1, math.ceil(y_max / 5))
        for value in range(0, int(y_max) + 1, step):
            y = y_of(value)
            painter.setPen(self._dotted())
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(_PLOT_FG)
            painter.drawText(QRectF(0, y - 8, plot.left() - 4, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{value}")
        painter.save()
        painter.translate(10, plot.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-60, -8, 120, 16), Qt.AlignmentFlag.AlignCenter, "HFR (pix)")
        painter.restore()

        painter.setClipRect(plot)
        if self.coefficients is not None:
            a, b, c = self.coefficients
            xs = [x_lo + i * (x_hi - x_lo) / 100 for i in range(101)]
            painter.setPen(QPen(_FIT_COLOR, 1.4))
            painter.drawPolyline(QPolygonF([QPointF(x_of(x), y_of(a * x * x + b * x + c)) for x in xs]))
        if self.best_position is not None:
            painter.setPen(QPen(_BEST_COLOR, 1.2, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x_of(self.best_position), plot.top()), QPointF(x_of(self.best_position), plot.bottom()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_HFR_COLOR)
        for position, hfr in self.points:
            if math.isfinite(hfr):
                painter.drawEllipse(QPointF(x_of(position), y_of(hfr)), 3.0, 3.0)
        painter.end()


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("CriteriaHeading")
    return label


class FocusPage(QWidget):
    """The Focus section."""

    # Emitted from the event-bus handlers (which run on the autofocus thread)
    # and received on the UI thread. Each carries the Pier key the run belongs
    # to, alongside the same payload as before, so two Piers running autofocus
    # at once never cross-contaminate each other's display.
    _started = Signal(object, object)
    _frame = Signal(object, object)
    _complete = Signal(object, object)
    _run_finished = Signal(object)
    _manual_frame = Signal(object, object)
    _exposure_started = Signal(object, float)

    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("FocusPage")
        self._window = window
        # A focus run is in progress, from anywhere, keyed by Pier — two Piers
        # can each have their own AutofocusService running at once. ``_receiving``
        # is set and cleared on the run's own thread as its events arrive, so no
        # frame is missed while the UI thread catches up; ``_active`` follows on
        # the UI thread and drives the widgets. ``_last_run`` is what a Pier's own
        # widgets get repainted from when switching back to it, whether that
        # Pier is idle, mid-run or just finished.
        self._receiving: dict = {}
        self._active: dict = {}
        self._services: dict = {}        # pier key -> the AutofocusService running there, if any
        self._last_run: dict = {}
        # Manual-focus capture/loop, independent of an autofocus sweep. ``_manual_active``
        # is set on the worker thread for the duration of a single Capture or a running
        # Loop; ``_manual_stop`` is the Loop's own stop flag, checked between exposures.
        self._manual_active: dict = {}
        self._manual_stop: dict = {}
        # Exposure in flight per Pier: (monotonic start time, duration in s). Drives the camera
        # panel's progress bar from a short UI timer, so no per-second camera polling is needed.
        self._exposure: dict = {}
        # The camera's Bayer pattern per Pier (None = mono), read when a run starts, so frames
        # are shown in colour; used from the run's worker thread, hence a plain dict.
        self._bayer: dict = {}
        self._exposure_timer = QTimer(self)
        self._exposure_timer.timeout.connect(self._update_exposure_bar)
        # True while ``reload()`` is setting the step/points/exposure/backlash spin boxes from a
        # saved Pier's settings, so those set-calls' own ``valueChanged`` signals don't immediately
        # save the just-loaded values right back (and, for a Pier with none saved yet, don't create
        # a settings row out of the defaults just by looking at it).
        self._loading_settings = False
        self._build()
        self._sync_buttons()
        self.reload()   # seed from the already-selected Pier's saved defaults, if any

        self._started.connect(self._on_started)
        self._frame.connect(self._on_frame)
        self._complete.connect(self._on_complete)
        self._run_finished.connect(self._on_run_finished)
        self._manual_frame.connect(self._on_manual_frame)
        self._exposure_started.connect(self._on_exposure_started)
        bus = get_bus()
        handlers = (
            (FocusStartedEvent, self._on_started_event),
            (FocusExposureStartedEvent, self._on_exposure_started_event),
            (FocusFrameEvent, self._on_frame_event),
            (FocusCompleteEvent, self._on_complete_event),
        )
        for event_type, handler in handlers:
            bus.subscribe(event_type, handler)
        # Don't leave handlers on the process-wide bus that point at a deleted page.
        self.destroyed.connect(lambda *_: [bus.unsubscribe(t, h) for t, h in handlers])

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_devices)
        self._timer.start(1000)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        choice = getattr(self, "layout_choice", None)
        if choice is not None:
            choice.fit_width()

    # --- Layout -----------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        title = QLabel("Focus")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        self.status_label = QLabel(_IDLE_STATUS)
        self.status_label.setProperty("helpKey", "status")
        layout.addWidget(self.status_label)

        self._content = QHBoxLayout()
        self._content.setSpacing(12)
        self._content.addWidget(self._build_left_column())
        self._right = self._build_right_column()
        self._content.addWidget(self._right, 1)
        layout.addLayout(self._content, 1)
        self.layout_choice = FrameLayoutChoice(self, self._image_box, self._apply_orientation)
        self._left_layout.insertWidget(self._left_layout.count() - 1, self.layout_choice.group)

        layout.addWidget(_heading("Log"))
        log_pane = self._window._build_log_pane()
        self._window._log_panes.append(log_pane)
        layout.addWidget(log_pane)

    def _build_left_column(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(380)
        box = QVBoxLayout(column)
        self._left_layout = box
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)

        focuser = QGroupBox("Focuser")
        grid = QGridLayout(focuser)
        grid.addWidget(QLabel("Position:"), 0, 0)
        self.position_label = QLabel("—")
        self.position_label.setProperty("helpKey", "position")
        grid.addWidget(self.position_label, 0, 1)
        grid.addWidget(QLabel("Temp.:"), 0, 2)
        self.temperature_label = QLabel("—")
        self.temperature_label.setProperty("helpKey", "temp")
        grid.addWidget(self.temperature_label, 0, 3)
        grid.addWidget(QLabel("Step size:"), 1, 0)
        self.step_spin = QSpinBox()
        self.step_spin.setRange(1, 100000)
        self.step_spin.setValue(AutofocusParams.step_size)
        self.step_spin.setSuffix(" steps")
        self.step_spin.setToolTip("Focuser steps between successive exposures.")
        self.step_spin.valueChanged.connect(self._save_autofocus_params)
        grid.addWidget(self.step_spin, 1, 1)
        grid.addWidget(QLabel("Points:"), 1, 2)
        self.points_spin = QSpinBox()
        self.points_spin.setRange(3, 41)
        self.points_spin.setValue(AutofocusParams.num_points)
        self.points_spin.setToolTip("Number of exposures across the sweep, centred on the current position.")
        self.points_spin.valueChanged.connect(self._save_autofocus_params)
        grid.addWidget(self.points_spin, 1, 3)
        grid.addWidget(QLabel("Backlash:"), 2, 0)
        self.backlash_spin = QSpinBox()
        self.backlash_spin.setRange(0, 100000)
        self.backlash_spin.setValue(AutofocusParams.backlash_compensation)
        self.backlash_spin.setSuffix(" steps")
        self.backlash_spin.setToolTip(
            "Overshoot then return by this many steps before every focuser move during a run, so "
            "mechanical backlash is taken up the same way each time (0 disables compensation)."
        )
        self.backlash_spin.valueChanged.connect(self._save_autofocus_params)
        grid.addWidget(self.backlash_spin, 2, 1)
        self.autofocus_btn = QPushButton("Auto Focus")
        self.autofocus_btn.setObjectName("AccentButton")
        self.autofocus_btn.clicked.connect(self.start_autofocus)
        grid.addWidget(self.autofocus_btn, 3, 0, 1, 2)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip("Stop the run started here: the focuser goes back to where it began.")
        self.stop_btn.clicked.connect(self.stop_autofocus)
        grid.addWidget(self.stop_btn, 3, 2, 1, 2)
        self.filter_offsets_btn = QPushButton("Filter Offsets")
        self.filter_offsets_btn.setToolTip(
            "Measure each filter's focus offset relative to a Primary filter, and apply it "
            "automatically on future filter changes without a full autofocus run (FOC-060)."
        )
        self.filter_offsets_btn.clicked.connect(self.open_filter_offsets_dialog)
        grid.addWidget(self.filter_offsets_btn, 4, 0, 1, 4)
        box.addWidget(focuser)

        camera = QGroupBox("Camera")
        grid = QGridLayout(camera)
        grid.addWidget(QLabel("Camera:"), 0, 0)
        self.camera_label = QLabel("—")
        self.camera_label.setProperty("helpKey", "camera")
        grid.addWidget(self.camera_label, 0, 1)
        grid.addWidget(QLabel("Exp:"), 1, 0)
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(0.01, 600.0)
        self.exposure_spin.setDecimals(2)
        self.exposure_spin.setValue(AutofocusParams.exposure_s)
        self.exposure_spin.setSuffix(" s")
        self.exposure_spin.setToolTip("Exposure time of each frame measured during the sweep.")
        self.exposure_spin.valueChanged.connect(self._save_autofocus_params)
        grid.addWidget(self.exposure_spin, 1, 1)
        self.exposure_bar = QProgressBar()
        self.exposure_bar.setRange(0, 1000)
        self.exposure_bar.setToolTip("Progress of the exposure in flight.")
        self.exposure_bar.setProperty("helpKey", "exposure progress")
        grid.addWidget(self.exposure_bar, 2, 0, 1, 2)
        self.exposure_bar.setFormat("—")
        box.addWidget(camera)

        manual = QGroupBox("Manual Focus")
        grid = QGridLayout(manual)
        grid.addWidget(QLabel("Position:"), 0, 0)
        self.manual_position_spin = QSpinBox()
        self.manual_position_spin.setRange(0, 1_000_000)
        self.manual_position_spin.setToolTip("Focuser position to move to.")
        grid.addWidget(self.manual_position_spin, 0, 1)
        self.manual_move_btn = QPushButton("Move")
        self.manual_move_btn.setToolTip("Move the focuser to the position above.")
        self.manual_move_btn.clicked.connect(self.manual_move)
        grid.addWidget(self.manual_move_btn, 0, 2)
        self.capture_btn = QPushButton("Capture")
        self.capture_btn.setToolTip("Take a single exposure and measure its HFR.")
        self.capture_btn.clicked.connect(self.manual_capture)
        grid.addWidget(self.capture_btn, 1, 0)
        self.loop_btn = QPushButton("Loop")
        self.loop_btn.setToolTip("Repeat exposures so focus can be fine-tuned by eye.")
        self.loop_btn.clicked.connect(self.start_loop)
        grid.addWidget(self.loop_btn, 1, 1)
        self.manual_stop_btn = QPushButton("Stop")
        self.manual_stop_btn.setToolTip("Stop the exposure loop.")
        self.manual_stop_btn.setEnabled(False)
        self.manual_stop_btn.clicked.connect(self.stop_loop)
        grid.addWidget(self.manual_stop_btn, 1, 2)
        self.emergency_set_btn = QPushButton("Set Emergency")
        self.emergency_set_btn.setToolTip(
            "Remember the focuser's current position as the emergency focus, to come back to "
            "if you are ever wildly out of focus."
        )
        self.emergency_set_btn.clicked.connect(self.set_emergency_focus)
        grid.addWidget(self.emergency_set_btn, 2, 0)
        self.emergency_go_btn = QPushButton("Go to Emergency")
        self.emergency_go_btn.setToolTip("Move the focuser back to the saved emergency focus position.")
        self.emergency_go_btn.clicked.connect(self.go_to_emergency_focus)
        grid.addWidget(self.emergency_go_btn, 2, 1)
        self.emergency_label = QLabel("—")
        self.emergency_label.setProperty("helpKey", "emergency position")
        self.emergency_label.setToolTip("The saved emergency focus position.")
        grid.addWidget(self.emergency_label, 2, 2)
        box.addWidget(manual)

        box.addStretch(1)
        return column

    def _build_right_column(self) -> QWidget:
        """Two boxes the layout can arrange: the frame (with its zoom toolbar) and the V-curve
        (with the statistics line). Landscape stacks them in this column; portrait moves them
        into the page itself (see :meth:`_apply_orientation`)."""
        right = QWidget()
        self._right_layout = QVBoxLayout(right)
        self._right_layout.setContentsMargins(0, 0, 0, 0)
        self._right_layout.setSpacing(8)

        self._image_box = QWidget()
        column = QVBoxLayout(self._image_box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        self.image_view = FocusImageView()
        self.image_view.setProperty("helpKey", "frame")
        column.addLayout(build_zoom_toolbar(self.image_view))
        column.addWidget(self.image_view, 1)

        self._curve_box = QWidget()
        column = QVBoxLayout(self._curve_box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        stats = QHBoxLayout()
        stats.addWidget(_heading("V-Curve"))
        stats.addStretch(1)
        self.stats_label = QLabel(_NO_STATS)
        self.stats_label.setProperty("helpKey", "statistics")
        stats.addWidget(self.stats_label)
        stats.addStretch(1)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Forget the last run's frame, statistics and curve.")
        self.clear_btn.clicked.connect(self.clear)
        stats.addWidget(self.clear_btn)
        column.addLayout(stats)

        self.plot = VCurvePlot()
        self.plot.setProperty("helpKey", "v-curve")
        column.addWidget(self.plot, 1)
        self._right_layout.addWidget(self._image_box, 3)
        self._right_layout.addWidget(self._curve_box, 2)
        return right

    def _apply_orientation(self, orientation: str) -> None:
        """Landscape: the frame above the V-curve, right of the controls. Portrait: the V-curve
        beside the controls and the frame in its own full-height column at the right."""
        from galileo.ui.imaging import PORTRAIT
        for box in (self._image_box, self._curve_box):
            self._right_layout.removeWidget(box)
            self._content.removeWidget(box)
        if orientation == PORTRAIT:
            self._content.removeWidget(self._right)
            self._right.setVisible(False)
            self._content.addWidget(self._curve_box, 1)
            self._content.addWidget(self._image_box)
        else:
            self._right.setVisible(True)
            self._content.addWidget(self._right, 1)
            self._right_layout.addWidget(self._image_box, 3)
            self._right_layout.addWidget(self._curve_box, 2)
        self._image_box.setVisible(True)
        self._curve_box.setVisible(True)

    # --- Bus handlers (any thread) -----------------------------------------

    def _on_started_event(self, event) -> None:
        key = event.payload.get("pier_key")
        self._receiving[key] = True
        self._started.emit(key, dict(event.payload))

    def _on_exposure_started_event(self, event) -> None:
        self._exposure_started.emit(event.payload.get("pier_key"), float(event.payload.get("duration_s", 0.0)))

    def _on_frame_event(self, event) -> None:
        key = event.payload.get("pier_key")
        if not self._receiving.get(key):
            return  # a frame outside a run entirely (nothing is displaying it) is not shown
        payload = event.payload
        self._frame.emit(key, {
            "position": payload["position"], "hfr": payload["hfr"], "fwhm": payload["fwhm"],
            "star_count": payload["star_count"], "preview": _preview(payload["frame"], self._bayer.get(key)),
            "confirm": payload.get("confirm", False),
        })

    def _on_complete_event(self, event) -> None:
        key = event.payload.get("pier_key")
        self._receiving[key] = False
        self._complete.emit(key, event.payload["result"])

    # --- Run display (UI thread) --------------------------------------------

    def _pier_key(self):
        from galileo.current_object import pier_key
        return pier_key(self._window._current_pier)

    def _on_exposure_started(self, key, duration_s: float) -> None:
        self._exposure[key] = (time.monotonic(), duration_s)
        if not self._exposure_timer.isActive():
            self._exposure_timer.start(100)
        self._update_exposure_bar()

    def _end_exposure(self, key) -> None:
        self._exposure.pop(key, None)
        self._update_exposure_bar()

    def _update_exposure_bar(self) -> None:
        """Repaint the progress bar from the displayed Pier's exposure in flight (if any). Once
        the exposure's time is up it holds at 100% until the frame arrives (download/measure)."""
        current = self._exposure.get(self._pier_key())
        if current is None:
            self.exposure_bar.setValue(0)
            self.exposure_bar.setFormat("—")
        else:
            start, duration = current
            elapsed = min(time.monotonic() - start, duration)
            self.exposure_bar.setValue(int(1000 * elapsed / duration) if duration > 0 else 1000)
            self.exposure_bar.setFormat(f"{elapsed:.1f} / {duration:.1f} s")
        if not self._exposure and self._exposure_timer.isActive():
            self._exposure_timer.stop()

    def _on_started(self, key, payload: dict) -> None:
        self._active[key] = True
        self._last_run[key] = {
            "points": [], "fit": None, "stats": _NO_STATS, "preview": None, "position": None,
            "status": f"Focusing — {payload['num_points']} exposures, {payload['step_size']} steps apart…",
        }
        if key == self._pier_key():
            self._reset_display()
            self.status_label.setText(self._last_run[key]["status"])
        self._sync_buttons()

    def _on_frame(self, key, payload: dict) -> None:
        self._end_exposure(key)
        run = self._last_run.setdefault(key, {
            "points": [], "fit": None, "stats": _NO_STATS, "preview": None, "position": None, "status": "",
        })
        if payload["preview"] is not None:
            run["preview"] = payload["preview"]
        run["stats"] = f"Stars: {payload['star_count']}  HFR: {payload['hfr']:.2f}  FWHM: {payload['fwhm']:.2f}"
        run["position"] = payload["position"]
        if payload["confirm"]:
            # The post-move confirmation exposure at the computed best position: shown
            # so focus can be checked visually, but it isn't a sweep sample for the curve.
            run["status"] = f"Focus complete — confirming at position {payload['position']}…"
        else:
            run["points"].append((payload["position"], payload["hfr"]))
            run["status"] = f"Focusing — position {payload['position']}, HFR {payload['hfr']:.2f}…"
        if key != self._pier_key():
            return
        if payload["preview"] is not None:
            self.image_view.set_image(payload["preview"])
            self.layout_choice.set_frame(payload["preview"])
        self.stats_label.setText(run["stats"])
        self.position_label.setText(str(payload["position"]))
        if not payload["confirm"]:
            self.plot.add_point(payload["position"], payload["hfr"])
        self.status_label.setText(run["status"])

    def _on_complete(self, key, result) -> None:
        self._end_exposure(key)
        self._active[key] = False
        run = self._last_run.setdefault(key, {
            "points": [], "fit": None, "stats": _NO_STATS, "preview": None, "position": None, "status": "",
        })
        if result.success:
            run["fit"] = (result.curve_coefficients, result.best_position)
            run["status"] = f"Focus complete — best position {result.best_position}."
        else:
            run["status"] = f"Focus failed — {result.failure_reason}."
        if key == self._pier_key():
            if result.success:
                self.plot.set_fit(*run["fit"])
            self.status_label.setText(run["status"])
        self._sync_buttons()

    def _reset_display(self) -> None:
        self.image_view.set_image(None)
        self.plot.clear()
        self.stats_label.setText(_NO_STATS)

    def _redraw_from_last(self, key) -> None:
        """Repaint the frame/plot/stats/status from *key*'s own stored run state
        (or the idle display if it has none) — used when switching Piers."""
        run = self._last_run.get(key)
        if run is None:
            self._reset_display()
            self.status_label.setText(_IDLE_STATUS)
            return
        self.image_view.set_image(run["preview"])
        self.plot.clear()
        for position, hfr in run["points"]:
            self.plot.add_point(position, hfr)
        if run["fit"] is not None:
            self.plot.set_fit(*run["fit"])
        self.stats_label.setText(run["stats"])
        self.position_label.setText(str(run["position"]) if run["position"] is not None else "—")
        self.status_label.setText(run["status"] or _IDLE_STATUS)

    def clear(self) -> None:
        """Forget the last run's frame, statistics and curve. A run in progress is left alone."""
        key = self._pier_key()
        if self._busy(key):
            return
        self._last_run.pop(key, None)
        self._reset_display()
        self.status_label.setText(_IDLE_STATUS)

    def _busy(self, key) -> bool:
        """Whether *key*'s Pier has an autofocus sweep or a manual capture/loop in progress."""
        return (
            self._active.get(key, False)
            or self._services.get(key) is not None
            or self._manual_active.get(key, False)
        )

    def _autofocus_busy(self, key) -> bool:
        """Whether *key*'s Pier has an autofocus sweep running (which owns the focuser)."""
        return self._active.get(key, False) or self._services.get(key) is not None

    def _sync_buttons(self) -> None:
        key = self._pier_key()
        busy = self._busy(key)
        self.autofocus_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(self._services.get(key) is not None)
        self.filter_offsets_btn.setEnabled(not busy)
        self.clear_btn.setEnabled(not busy)
        # Moving the focuser while a manual Loop runs is how you focus by eye.
        self.manual_move_btn.setEnabled(not self._autofocus_busy(key))
        self.emergency_set_btn.setEnabled(not self._autofocus_busy(key))
        self.emergency_go_btn.setEnabled(not self._autofocus_busy(key) and self._emergency_position() is not None)
        self.capture_btn.setEnabled(not busy)
        self.loop_btn.setEnabled(not busy)
        self.manual_stop_btn.setEnabled(self._manual_active.get(key, False))

    # --- Starting and stopping a run -----------------------------------------

    def _camera(self):
        from galileo.ui.app_window import _camera_backend_key_for_slot
        return self._window._camera_backends.get(_camera_backend_key_for_slot(self._window._active_camera_slot))

    def _focuser(self):
        get_adapter = (self._window._device_pages.get("focuser") or {}).get("get_adapter")
        return get_adapter() if get_adapter is not None else None

    def _filter_wheel(self):
        return (self._window._device_pages.get("filter_wheel") or {}).get("adapter")

    def open_filter_offsets_dialog(self) -> None:
        from galileo.ui.filter_offsets_dialog import FilterOffsetsDialog
        dialog = FilterOffsetsDialog(self)
        dialog.exec()

    def start_autofocus(self) -> None:
        key = self._pier_key()
        if self._services.get(key) is not None:
            QMessageBox.information(
                self._window._window, "Autofocus already running",
                "An autofocus run is already in progress on this Pier.",
            )
            return
        camera, focuser = self._camera(), self._focuser()
        missing = [name for name, device in (("camera", camera), ("focuser", focuser)) if device is None]
        if missing:
            QMessageBox.information(
                self._window._window, "Equipment not connected",
                f"Connect a {' and a '.join(missing)} on the Equipment pages first.",
            )
            return
        from galileo.autofocus import AutofocusService
        service = self._services[key] = AutofocusService(
            camera=camera, focuser=focuser, exposure_s=self.exposure_spin.value(),
            backlash_compensation=self.backlash_spin.value(), pier_key=key,
        )
        self._sync_buttons()
        threading.Thread(
            target=self._run_worker, args=(service, key, self.step_spin.value(), self.points_spin.value()),
            name="autofocus", daemon=True,
        ).start()

    def _run_worker(self, service, key, step_size: int, num_points: int) -> None:
        import asyncio
        self._bayer[key] = camera_pattern(getattr(service, "_camera", None))
        try:
            asyncio.run(service.run(step_size=step_size, num_points=num_points))
        except Exception:
            logger.exception("Autofocus run failed")
        finally:
            self._run_finished.emit(key)

    def stop_autofocus(self) -> None:
        # Stops whichever Pier is currently displayed's own run — a different
        # Pier's in-flight autofocus is untouched.
        service = self._services.get(self._pier_key())
        if service is not None:
            service.cancel()
            self.status_label.setText("Stopping — waiting for the current exposure to finish…")

    def _on_run_finished(self, key) -> None:
        self._end_exposure(key)
        self._services.pop(key, None)
        self._sync_buttons()

    # --- Manual focus (Move / Capture / Loop) --------------------------------

    def _emergency_position(self) -> int | None:
        from galileo.observatory import get_emergency_focus
        try:
            return get_emergency_focus(self._window._current_pier)
        except Exception:
            logger.exception("Could not read the emergency focus position")
            return None

    def _show_emergency(self) -> None:
        position = self._emergency_position()
        self.emergency_label.setText("—" if position is None else str(position))
        self._sync_buttons()

    def set_emergency_focus(self) -> None:
        pier = self._window._current_pier
        focuser = self._focuser()
        if pier is None:
            QMessageBox.information(
                self._window._window, "No Pier selected",
                "Select (or create) an Observatory and Pier first; the emergency focus is saved per Pier.",
            )
            return
        position = getattr(focuser, "position", None) if focuser is not None else None
        if position is None:
            QMessageBox.information(
                self._window._window, "Focuser not connected",
                "Connect a focuser on the Equipment page first.",
            )
            return
        from galileo.observatory import set_emergency_focus
        if not set_emergency_focus(pier, int(position)):
            QMessageBox.information(
                self._window._window, "Save the focuser first",
                "Save the focuser's settings on Equipment > Focuser first; the emergency focus is kept with them.",
            )
            return
        logger.info("Emergency focus saved at position %d.", position)
        self.status_label.setText(f"Emergency focus saved at position {int(position)}.")
        self._show_emergency()

    def go_to_emergency_focus(self) -> None:
        position = self._emergency_position()
        if position is None:
            return
        self.manual_position_spin.setValue(position)
        self.manual_move()

    def manual_move(self) -> None:
        key = self._pier_key()
        focuser = self._focuser()
        if focuser is None:
            QMessageBox.information(
                self._window._window, "Focuser not connected",
                "Connect a focuser on the Equipment page first.",
            )
            return
        if self._autofocus_busy(key):
            return
        position = self.manual_position_spin.value()
        from galileo.autofocus import AutofocusService
        service = AutofocusService(focuser=focuser, backlash_compensation=self.backlash_spin.value(), pier_key=key)
        logger.info("Manual focus: move requested to position %d.", position)
        import asyncio
        try:
            asyncio.run(service.move_to(position))
        except Exception:
            logger.exception("Manual focus move failed")
            self.status_label.setText("Move failed — see log.")
            return
        self.status_label.setText(f"Moved to position {position}.")
        self.position_label.setText(str(position))

    def manual_capture(self) -> None:
        self._start_manual(loop=False)

    def start_loop(self) -> None:
        self._start_manual(loop=True)

    def _start_manual(self, loop: bool) -> None:
        key = self._pier_key()
        camera = self._camera()
        if camera is None:
            QMessageBox.information(
                self._window._window, "Camera not connected",
                "Connect a camera on the Equipment page first.",
            )
            return
        if self._busy(key):
            return
        focuser = self._focuser()
        from galileo.autofocus import AutofocusService
        service = AutofocusService(camera=camera, exposure_s=self.exposure_spin.value(), pier_key=key)
        self._manual_stop[key] = threading.Event()
        self._manual_active[key] = True
        self._sync_buttons()
        threading.Thread(
            target=self._manual_worker, args=(service, key, focuser, loop),
            name="manual-focus", daemon=True,
        ).start()

    def _manual_worker(self, service, key, focuser, loop: bool) -> None:
        import asyncio
        stop_event = self._manual_stop[key]
        pattern = self._bayer[key] = camera_pattern(getattr(service, "_camera", None))
        try:
            while True:
                try:
                    result = asyncio.run(service.measure_once())
                except Exception:
                    logger.exception("Manual focus capture failed")
                    break
                if result is not None:
                    frame, hfr, fwhm, star_count = result
                    position = getattr(focuser, "position", None) if focuser is not None else None
                    self._manual_frame.emit(key, {
                        "position": position, "hfr": hfr, "fwhm": fwhm,
                        "star_count": star_count, "preview": _preview(frame, pattern),
                    })
                if not loop or stop_event.is_set():
                    break
        finally:
            self._manual_active[key] = False
            self._run_finished.emit(key)

    def stop_loop(self) -> None:
        stop_event = self._manual_stop.get(self._pier_key())
        if stop_event is not None:
            stop_event.set()
            self.status_label.setText("Stopping — waiting for the current exposure to finish…")

    def _on_manual_frame(self, key, payload: dict) -> None:
        self._end_exposure(key)
        run = self._last_run.setdefault(key, {
            "points": [], "fit": None, "stats": _NO_STATS, "preview": None, "position": None, "status": "",
        })
        if payload["preview"] is not None:
            run["preview"] = payload["preview"]
        run["stats"] = f"Stars: {payload['star_count']}  HFR: {payload['hfr']:.2f}  FWHM: {payload['fwhm']:.2f}"
        run["position"] = payload["position"]
        position_text = "—" if payload["position"] is None else str(payload["position"])
        run["status"] = f"Manual focus — position {position_text}, HFR {payload['hfr']:.2f}."
        if key != self._pier_key():
            return
        if payload["preview"] is not None:
            self.image_view.set_image(payload["preview"])
            self.layout_choice.set_frame(payload["preview"])
        self.stats_label.setText(run["stats"])
        self.position_label.setText(position_text)
        self.status_label.setText(run["status"])

    # --- Device readout ------------------------------------------------------

    def _refresh_devices(self) -> None:
        """Cheap, cached readouts only — no device I/O. Skipped while the page is hidden."""
        if not self.isVisible():
            return
        from galileo.ui.app_window import _camera_slot_label
        camera_name = _camera_slot_label(self._window._active_camera_slot)
        self.camera_label.setText(f"{camera_name} ({'connected' if self._camera() is not None else 'not connected'})")
        focuser = self._focuser()
        if focuser is None:
            self.position_label.setText("—")
            self.temperature_label.setText("—")
            return
        if not self._active.get(self._pier_key(), False):
            position = getattr(focuser, "position", None)
            self.position_label.setText("—" if position is None else str(position))
            if position is not None and not self.manual_position_spin.hasFocus():
                self.manual_position_spin.blockSignals(True)
                self.manual_position_spin.setValue(int(position))
                self.manual_position_spin.blockSignals(False)
        temperature = getattr(focuser, "temperature", None)
        self.temperature_label.setText(f"{temperature:.1f} °C" if isinstance(temperature, (int, float)) else "—")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_devices()

    # --- Per-Pier settings (FOC-070) -----------------------------------------

    def reload(self) -> None:
        """Re-seed the run controls from the newly selected Pier's saved autofocus
        defaults (edited here or on Options > Focus — the two stay in sync), and
        repaint the frame/plot/stats/status/buttons for whichever Pier is now
        selected — idle, mid-run, or just finished."""
        key = self._pier_key()
        self._update_exposure_bar()
        self._show_emergency()
        if not self._active.get(key, False):
            from galileo.observatory import get_autofocus_params
            params = get_autofocus_params(self._window._current_pier)
            self._loading_settings = True
            try:
                self.step_spin.setValue(params.step_size)
                self.points_spin.setValue(params.num_points)
                self.exposure_spin.setValue(params.exposure_s)
                self.backlash_spin.setValue(params.backlash_compensation)
            finally:
                self._loading_settings = False
        self._redraw_from_last(key)
        self._sync_buttons()

    def _save_autofocus_params(self) -> None:
        """Persist the step/points/exposure/backlash controls as this Pier's saved
        autofocus defaults as soon as the user changes one, so they're there again
        next time the screen (or Options > Focus, which reads the same record) loads —
        not only when explicitly saved from Options > Focus."""
        if self._loading_settings:
            return
        pier = self._window._current_pier
        if pier is None:
            return
        from galileo.autofocus import AutofocusParams
        from galileo.observatory import save_autofocus_params
        save_autofocus_params(pier, AutofocusParams(
            step_size=self.step_spin.value(), num_points=self.points_spin.value(),
            exposure_s=self.exposure_spin.value(), backlash_compensation=self.backlash_spin.value(),
        ))
        refresh = getattr(self._window, "_focus_settings_refresh", None)
        if refresh is not None:
            refresh()
