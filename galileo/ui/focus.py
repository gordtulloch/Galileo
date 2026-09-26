# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Focus screen (FOC-010 … FOC-070): a live view onto an autofocus run.

Laid out after the reference focus screen (assets/samples/focus.png): the
focuser and camera controls on the left; the frame being measured, its star
statistics and the HFR V-curve on the right; the log along the bottom.

The screen shows a run, it does not own one. It follows the ``Focus*Event`` s
that ``galileo.autofocus.AutofocusService`` publishes on the event bus, so a
run started here, or by a sequencer trigger, is displayed the same way. Between
runs nothing is redrawn: the last run's frame, statistics and curve stay on
screen until the next run starts or Clear is pressed. The events arrive on
whatever thread the run is on, so the handlers only prepare data and hand it
to the UI thread through queued signals; no Qt widget is touched off it.
"""

from __future__ import annotations

import logging
import math
import threading

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from galileo.autofocus import AutofocusParams
from galileo.bus import FocusCompleteEvent, FocusFrameEvent, FocusStartedEvent, get_bus
from galileo.ui.guider import _PLOT_FG, _PlotBase
from galileo.ui.imaging import _auto_stretch

logger = logging.getLogger(__name__)

_PREVIEW_MAX_SIDE = 1024            # frames are decimated to about this before being stretched
_NO_STATS = "Stars: 0  HFR: -1.00  FWHM: --"
_IDLE_STATUS = "Idle — this screen updates while an autofocus run is in progress."
_HFR_COLOR = QColor("#4da3ff")
_FIT_COLOR = QColor("#ffa040")
_BEST_COLOR = QColor("#31c24a")


def _preview(frame) -> np.ndarray | None:
    """An 8-bit, auto-stretched, decimated copy of *frame* for display — ``(h, w)``
    or ``(h, w, 3)`` — or ``None`` if it isn't an image."""
    arr = np.asarray(frame)
    if arr.ndim == 3:
        arr = arr if arr.shape[2] == 3 else arr[..., 0]
    elif arr.ndim != 2:
        return None
    step = max(1, max(arr.shape[:2]) // _PREVIEW_MAX_SIDE)
    return _auto_stretch(arr[::step, ::step])


class FocusImageView(QWidget):
    """The frame being measured, fitted to the widget."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self._image: QImage | None = None
        self.message = "No focus run yet"

    @property
    def has_image(self) -> bool:
        return self._image is not None

    def set_image(self, data: np.ndarray | None) -> None:
        """Show *data*, an 8-bit ``(h, w)`` or ``(h, w, 3)`` array (see :func:`_preview`)."""
        if data is None:
            self._image = None
        else:
            data = np.ascontiguousarray(data)
            height, width = data.shape[:2]
            fmt = QImage.Format.Format_RGB888 if data.ndim == 3 else QImage.Format.Format_Grayscale8
            self._image = QImage(data.data, width, height, data.strides[0], fmt).copy()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#141414"))
        if self._image is None:
            painter.setPen(QColor("#8a949c"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
        else:
            scaled = self._image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(0, 0, scaled.width(), scaled.height())
            target.moveCenter(QPointF(self.width() / 2, self.height() / 2))
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(target, self._image)
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
    # and received on the UI thread.
    _started = Signal(object)
    _frame = Signal(object)
    _complete = Signal(object)
    _run_finished = Signal()

    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("FocusPage")
        self._window = window
        # A focus run is in progress, from anywhere. ``_receiving`` is set and
        # cleared on the run's own thread as its events arrive, so no frame is
        # missed while the UI thread catches up; ``_active`` follows on the UI
        # thread and drives the widgets.
        self._receiving = False
        self._active = False
        self._service = None             # the AutofocusService this page started, if any
        self._build()
        self._sync_buttons()
        self.reload()   # seed from the already-selected Pier's saved defaults, if any

        self._started.connect(self._on_started)
        self._frame.connect(self._on_frame)
        self._complete.connect(self._on_complete)
        self._run_finished.connect(self._on_run_finished)
        bus = get_bus()
        handlers = (
            (FocusStartedEvent, self._on_started_event),
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

    # --- Layout -----------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        title = QLabel("Focus")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        self.status_label = QLabel(_IDLE_STATUS)
        layout.addWidget(self.status_label)

        content = QHBoxLayout()
        content.setSpacing(12)
        content.addWidget(self._build_left_column())
        content.addLayout(self._build_right_column(), 1)
        layout.addLayout(content, 1)

        layout.addWidget(_heading("Log"))
        log_pane = self._window._build_log_pane()
        self._window._log_panes.append(log_pane)
        layout.addWidget(log_pane)

    def _build_left_column(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(380)
        box = QVBoxLayout(column)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)

        focuser = QGroupBox("Focuser")
        grid = QGridLayout(focuser)
        grid.addWidget(QLabel("Position:"), 0, 0)
        self.position_label = QLabel("—")
        grid.addWidget(self.position_label, 0, 1)
        grid.addWidget(QLabel("Temp.:"), 0, 2)
        self.temperature_label = QLabel("—")
        grid.addWidget(self.temperature_label, 0, 3)
        grid.addWidget(QLabel("Step size:"), 1, 0)
        self.step_spin = QSpinBox()
        self.step_spin.setRange(1, 100000)
        self.step_spin.setValue(AutofocusParams.step_size)
        self.step_spin.setSuffix(" steps")
        self.step_spin.setToolTip("Focuser steps between successive exposures.")
        grid.addWidget(self.step_spin, 1, 1)
        grid.addWidget(QLabel("Points:"), 1, 2)
        self.points_spin = QSpinBox()
        self.points_spin.setRange(3, 41)
        self.points_spin.setValue(AutofocusParams.num_points)
        self.points_spin.setToolTip("Number of exposures across the sweep, centred on the current position.")
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
        grid.addWidget(self.backlash_spin, 2, 1)
        self.autofocus_btn = QPushButton("Auto Focus")
        self.autofocus_btn.setObjectName("AccentButton")
        self.autofocus_btn.clicked.connect(self.start_autofocus)
        grid.addWidget(self.autofocus_btn, 3, 0, 1, 2)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip("Stop the run started here: the focuser goes back to where it began.")
        self.stop_btn.clicked.connect(self.stop_autofocus)
        grid.addWidget(self.stop_btn, 3, 2, 1, 2)
        box.addWidget(focuser)

        camera = QGroupBox("Camera")
        grid = QGridLayout(camera)
        grid.addWidget(QLabel("Camera:"), 0, 0)
        self.camera_label = QLabel("—")
        grid.addWidget(self.camera_label, 0, 1)
        grid.addWidget(QLabel("Exp:"), 1, 0)
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(0.01, 600.0)
        self.exposure_spin.setDecimals(2)
        self.exposure_spin.setValue(AutofocusParams.exposure_s)
        self.exposure_spin.setSuffix(" s")
        self.exposure_spin.setToolTip("Exposure time of each frame measured during the sweep.")
        grid.addWidget(self.exposure_spin, 1, 1)
        box.addWidget(camera)

        tools = QGroupBox("Tools")
        row = QHBoxLayout(tools)
        for text in ("Aberration Inspector", "CFZ", "Advisor"):
            button = QPushButton(text)
            button.setEnabled(False)
            button.setToolTip("Not implemented yet.")
            row.addWidget(button)
        box.addWidget(tools)

        box.addStretch(1)
        return column

    def _build_right_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)
        self.image_view = FocusImageView()
        column.addWidget(self.image_view, 3)

        stats = QHBoxLayout()
        stats.addWidget(_heading("V-Curve"))
        stats.addStretch(1)
        self.stats_label = QLabel(_NO_STATS)
        stats.addWidget(self.stats_label)
        stats.addStretch(1)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Forget the last run's frame, statistics and curve.")
        self.clear_btn.clicked.connect(self.clear)
        stats.addWidget(self.clear_btn)
        column.addLayout(stats)

        self.plot = VCurvePlot()
        column.addWidget(self.plot, 2)
        return column

    # --- Bus handlers (any thread) -----------------------------------------

    def _on_started_event(self, event) -> None:
        self._receiving = True
        self._started.emit(dict(event.payload))

    def _on_frame_event(self, event) -> None:
        if not self._receiving:
            return  # a frame outside a run entirely (nothing is displaying it) is not shown
        payload = event.payload
        self._frame.emit({
            "position": payload["position"], "hfr": payload["hfr"], "fwhm": payload["fwhm"],
            "star_count": payload["star_count"], "preview": _preview(payload["frame"]),
            "confirm": payload.get("confirm", False),
        })

    def _on_complete_event(self, event) -> None:
        self._receiving = False
        self._complete.emit(event.payload["result"])

    # --- Run display (UI thread) --------------------------------------------

    def _on_started(self, payload: dict) -> None:
        self._active = True
        self._reset_display()
        self.status_label.setText(
            f"Focusing — {payload['num_points']} exposures, {payload['step_size']} steps apart…")
        self._sync_buttons()

    def _on_frame(self, payload: dict) -> None:
        if payload["preview"] is not None:
            self.image_view.set_image(payload["preview"])
        self.stats_label.setText(
            f"Stars: {payload['star_count']}  HFR: {payload['hfr']:.2f}  FWHM: {payload['fwhm']:.2f}")
        self.position_label.setText(str(payload["position"]))
        if payload["confirm"]:
            # The post-move confirmation exposure at the computed best position: shown
            # so focus can be checked visually, but it isn't a sweep sample for the curve.
            self.status_label.setText(f"Focus complete — confirming at position {payload['position']}…")
        else:
            self.plot.add_point(payload["position"], payload["hfr"])
            self.status_label.setText(f"Focusing — position {payload['position']}, HFR {payload['hfr']:.2f}…")

    def _on_complete(self, result) -> None:
        self._active = False
        if result.success:
            self.plot.set_fit(result.curve_coefficients, result.best_position)
            self.status_label.setText(f"Focus complete — best position {result.best_position}.")
        else:
            self.status_label.setText(f"Focus failed — {result.failure_reason}.")
        self._sync_buttons()

    def _reset_display(self) -> None:
        self.image_view.set_image(None)
        self.plot.clear()
        self.stats_label.setText(_NO_STATS)

    def clear(self) -> None:
        """Forget the last run's frame, statistics and curve. A run in progress is left alone."""
        if self._active:
            return
        self._reset_display()
        self.status_label.setText(_IDLE_STATUS)

    def _sync_buttons(self) -> None:
        self.autofocus_btn.setEnabled(not self._active and self._service is None)
        self.stop_btn.setEnabled(self._service is not None)
        self.clear_btn.setEnabled(not self._active)

    # --- Starting and stopping a run -----------------------------------------

    def _camera(self):
        from galileo.ui.app_window import _camera_backend_key_for_slot
        return self._window._camera_backends.get(_camera_backend_key_for_slot(self._window._active_camera_slot))

    def _focuser(self):
        get_adapter = (self._window._device_pages.get("focuser") or {}).get("get_adapter")
        return get_adapter() if get_adapter is not None else None

    def start_autofocus(self) -> None:
        camera, focuser = self._camera(), self._focuser()
        missing = [name for name, device in (("camera", camera), ("focuser", focuser)) if device is None]
        if missing:
            QMessageBox.information(
                self._window._window, "Equipment not connected",
                f"Connect a {' and a '.join(missing)} on the Equipment pages first.",
            )
            return
        from galileo.autofocus import AutofocusService
        service = self._service = AutofocusService(
            camera=camera, focuser=focuser, exposure_s=self.exposure_spin.value(),
            backlash_compensation=self.backlash_spin.value(),
        )
        self._sync_buttons()
        threading.Thread(
            target=self._run_worker, args=(service, self.step_spin.value(), self.points_spin.value()),
            name="autofocus", daemon=True,
        ).start()

    def _run_worker(self, service, step_size: int, num_points: int) -> None:
        import asyncio
        try:
            asyncio.run(service.run(step_size=step_size, num_points=num_points))
        except Exception:
            logger.exception("Autofocus run failed")
        finally:
            self._run_finished.emit()

    def stop_autofocus(self) -> None:
        if self._service is not None:
            self._service.cancel()
            self.status_label.setText("Stopping — waiting for the current exposure to finish…")

    def _on_run_finished(self) -> None:
        self._service = None
        self._sync_buttons()

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
        if not self._active:
            self.position_label.setText(str(getattr(focuser, "position", "—")))
        temperature = getattr(focuser, "temperature", None)
        self.temperature_label.setText(f"{temperature:.1f} °C" if isinstance(temperature, (int, float)) else "—")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_devices()

    # --- Per-Pier settings (Options > Focus, FOC-070) -------------------------

    def reload(self) -> None:
        """Re-seed the run controls from the newly selected Pier's saved autofocus
        defaults (Options > Focus). Left alone while a run is in progress."""
        if self._active:
            return
        from galileo.observatory import get_autofocus_params
        params = get_autofocus_params(self._window._current_pier)
        self.step_spin.setValue(params.step_size)
        self.points_spin.setValue(params.num_points)
        self.exposure_spin.setValue(params.exposure_s)
        self.backlash_spin.setValue(params.backlash_compensation)
