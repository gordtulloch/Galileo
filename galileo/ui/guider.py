# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Guider screen (GUIDE-070 … GUIDE-090): a live view onto PHD2.

Laid out after the reference guiding screen (assets/samples/guide.png): control
panel, scope info and guide statistics on the left; the guide-star image, the
guide graph and the mount-drift / calibration plots on the right; PHD2's event
log along the bottom.

Everything shown comes from ``galileo.guiding.GuideModel`` — the page polls a
snapshot on a timer instead of being called from PHD2's reader thread, so no
Qt object is ever touched off the UI thread. Commands go out through
``GuidingService`` and return immediately; a rejected command shows up in the
log pane.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable
from typing import ClassVar

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from galileo.guiding import DEC_GUIDE_MODES, GuideSnapshot, GuidingService

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 4400
DRIVER_NAME = "PHD2"  # what the Guider's saved DeviceConfigRecord.driver holds

_PLOT_BG = QColor("#000000")
_PLOT_FG = QColor("#c8c8c8")
_RA = QColor("#4da3ff")
_DEC = QColor("#ff5a5a")
_SNR = QColor("#b6e36a")
_Y_RANGES = (0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 32.0)


def _format_ago(seconds: float) -> str:
    seconds = round(seconds)
    return f"-{seconds // 60:02d}:{seconds % 60:02d}" if seconds else "00:00"


class _PlotBase(QWidget):
    """A black plot canvas that paints its own background and axis text."""

    def _begin(self) -> QPainter:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), _PLOT_BG)
        font = QFont(painter.font())
        font.setPointSizeF(8.0)
        painter.setFont(font)
        return painter

    @staticmethod
    def _dotted(color: QColor | None = None) -> QPen:
        pen = QPen(color or QColor(120, 120, 120))
        pen.setStyle(Qt.DotLine)
        return pen


class DriftGraph(_PlotBase):
    """Guide error over time — the guide graph: RA/Dec error as lines, SNR on
    the right-hand axis, correction pulses as bars, and ±RMS guide lines."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 170)
        self.samples: list = []
        self.pixel_scale: float | None = None
        self.unit = "px"
        self.rms_ra = self.rms_dec = 0.0
        self.series = {"ra": True, "dec": True, "snr": True, "corr_ra": False, "corr_dec": False, "rms": True}
        self.window_s = 120.0
        self.range_index = 3  # ±3 by default

    @property
    def y_max(self) -> float:
        return _Y_RANGES[self.range_index]

    def zoom(self, step: int) -> None:
        """+1 zooms in (smaller error range), -1 zooms out."""
        self.range_index = min(max(self.range_index - step, 0), len(_Y_RANGES) - 1)
        self.update()

    def set_data(self, samples, pixel_scale, unit, rms_ra, rms_dec) -> None:
        self.samples, self.pixel_scale, self.unit = samples, pixel_scale, unit
        self.rms_ra, self.rms_dec = rms_ra, rms_dec
        self.update()

    def paintEvent(self, event) -> None:
        painter = self._begin()
        plot = QRectF(46, 8, self.width() - 92, self.height() - 32)
        if plot.width() < 20 or plot.height() < 20:
            painter.end()
            return
        y_max, scale = self.y_max, self.pixel_scale or 1.0
        mid = plot.center().y()

        # grid + axis labels
        painter.setPen(_PLOT_FG)
        for k in range(-2, 3):
            value = y_max * k / 2
            y = mid - k * plot.height() / 4
            painter.setPen(self._dotted() if k else QPen(QColor("#ffffff")))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(_PLOT_FG)
            painter.drawText(QRectF(0, y - 8, plot.left() - 4, 16), Qt.AlignRight | Qt.AlignVCenter, f"{value:g}")
        for k in range(5):
            x = plot.left() + k * plot.width() / 4
            painter.setPen(self._dotted())
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(_PLOT_FG)
            painter.drawText(QRectF(x - 25, plot.bottom() + 2, 50, 16), Qt.AlignCenter,
                             _format_ago(self.window_s * (4 - k) / 4))
        painter.save()
        painter.translate(10, mid)
        painter.rotate(-90)
        painter.drawText(QRectF(-60, -8, 120, 16), Qt.AlignCenter, f"Drift ({self.unit})")
        painter.restore()

        samples = self.samples
        if samples:
            t_now = samples[-1].t
            visible = [s for s in samples if t_now - s.t <= self.window_s]

            def x_of(s) -> float:
                return plot.right() - (t_now - s.t) / self.window_s * plot.width()

            def y_of(value: float) -> float:
                return mid - max(-y_max, min(y_max, value)) / y_max * plot.height() / 2

            painter.setClipRect(plot)
            if self.series["corr_ra"] or self.series["corr_dec"]:
                pmax = max([abs(s.ra_pulse_ms) for s in visible] + [abs(s.dec_pulse_ms) for s in visible] + [100.0])
                for enabled, color, attr, dx in (
                    (self.series["corr_ra"], _RA, "ra_pulse_ms", -1.0), (self.series["corr_dec"], _DEC, "dec_pulse_ms", 1.0),
                ):
                    if not enabled:
                        continue
                    bar = QColor(color)
                    bar.setAlpha(110)
                    for s in visible:
                        h = getattr(s, attr) / pmax * plot.height() / 2
                        painter.fillRect(QRectF(x_of(s) + dx, mid - max(h, 0), 2, abs(h)), bar)
            if self.series["rms"]:
                for enabled, color, rms in ((self.series["ra"], _RA, self.rms_ra), (self.series["dec"], _DEC, self.rms_dec)):
                    if enabled and rms:
                        painter.setPen(self._dotted(color))
                        for sign in (1, -1):
                            painter.drawLine(QPointF(plot.left(), y_of(sign * rms)), QPointF(plot.right(), y_of(sign * rms)))
            for key, color, attr in (("ra", _RA, "ra"), ("dec", _DEC, "dec")):
                if self.series[key]:
                    painter.setPen(QPen(color, 1.4))
                    painter.drawPolyline(QPolygonF([QPointF(x_of(s), y_of(getattr(s, attr) * scale)) for s in visible]))
            if self.series["snr"]:
                snr_max = max(40.0, math.ceil(max(s.snr for s in visible) / 10) * 10) if visible else 40.0
                painter.setPen(QPen(_SNR, 1.2))
                painter.drawPolyline(QPolygonF([
                    QPointF(x_of(s), plot.bottom() - s.snr / snr_max * plot.height()) for s in visible
                ]))
                painter.setClipping(False)
                painter.setPen(_SNR)
                for k in range(5):
                    painter.drawText(QRectF(plot.right() + 4, plot.bottom() - k * plot.height() / 4 - 8, 40, 16),
                                     Qt.AlignLeft | Qt.AlignVCenter, f"{snr_max * k / 4:g}")
            painter.setClipping(False)

        # legend
        x = plot.center().x() - 60
        for enabled, color, text in (
            (self.series["ra"], _RA, "RA"), (self.series["dec"], _DEC, "DE"),
            (self.series["snr"], _SNR, "SNR"), (self.series["rms"], _PLOT_FG, "RMS"),
        ):
            if enabled:
                painter.setPen(color)
                painter.drawText(QPointF(x, plot.bottom() - 6), f"– {text}")
                x += 34
        painter.end()


class DriftScatter(_PlotBase):
    """Mount Drift tab: where the guide star has been, with target rings."""

    HISTORY = 200

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.points: list[tuple[float, float]] = []
        self.unit = "px"
        self.ring = 1.0  # radius of the green ring; yellow/red are 2× and 3×

    def set_data(self, samples, pixel_scale, unit) -> None:
        scale = pixel_scale or 1.0
        self.points = [(s.ra * scale, s.dec * scale) for s in samples[-self.HISTORY:]]
        self.unit = unit
        self.update()

    def paintEvent(self, event) -> None:
        painter = self._begin()
        side = min(self.width() - 60, self.height() - 40)
        if side < 40:
            painter.end()
            return
        plot = QRectF((self.width() - side) / 2 + 10, 8, side, side)
        half = self.ring * 3.6  # room for the red ring
        c = plot.center()

        def to_px(x: float, y: float) -> QPointF:
            return QPointF(c.x() + x / half * side / 2, c.y() - y / half * side / 2)

        painter.setPen(self._dotted())
        painter.drawLine(QPointF(plot.left(), c.y()), QPointF(plot.right(), c.y()))
        painter.drawLine(QPointF(c.x(), plot.top()), QPointF(c.x(), plot.bottom()))
        for mult, color in ((1, "#31c24a"), (2, "#e0c030"), (3, "#d63a3a")):
            painter.setPen(QPen(QColor(color), 1.5))
            radius = mult * self.ring / half * side / 2
            painter.drawEllipse(c, radius, radius)
        n = len(self.points)
        for i, (x, y) in enumerate(self.points):
            dot = QColor("#ffffff")
            dot.setAlpha(60 + int(195 * (i + 1) / n))  # older points fade out
            painter.setPen(Qt.NoPen)
            painter.setBrush(dot)
            painter.drawEllipse(to_px(x, y), 2.0, 2.0)
        painter.setPen(_PLOT_FG)
        painter.drawText(QRectF(plot.left(), plot.bottom() + 4, side, 16), Qt.AlignCenter,
                         f"dRA ({self.unit})   ring = {self.ring:g}")
        painter.end()


class CalibrationPlot(_PlotBase):
    """Calibration Plot tab: the star's path during PHD2's last calibration."""

    _COLORS: ClassVar[dict[str, str]] = {"West": "#4da3ff", "East": "#9cc9ff", "North": "#ff5a5a", "South": "#ffa0a0", "Backlash": "#aaaaaa"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.points: list = []
        self.calibration: dict | None = None

    def set_data(self, points, calibration) -> None:
        self.points, self.calibration = points, calibration
        self.update()

    def paintEvent(self, event) -> None:
        painter = self._begin()
        plot = QRectF(8, 8, self.width() - 16, self.height() - 52)
        c = plot.center()
        painter.setPen(self._dotted())
        painter.drawLine(QPointF(plot.left(), c.y()), QPointF(plot.right(), c.y()))
        painter.drawLine(QPointF(c.x(), plot.top()), QPointF(c.x(), plot.bottom()))
        painter.setPen(_PLOT_FG)
        if not self.points:
            painter.drawText(plot, Qt.AlignCenter, "No calibration this session")
        else:
            extent = max([abs(p.dx) for p in self.points] + [abs(p.dy) for p in self.points] + [1.0]) * 1.1
            k = min(plot.width(), plot.height()) / 2 / extent
            for point in self.points:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(self._COLORS.get(point.direction, "#ffffff")))
                painter.drawEllipse(QPointF(c.x() + point.dx * k, c.y() - point.dy * k), 2.5, 2.5)
        cal = self.calibration or {}
        lines = []
        if "xAngle" in cal:
            lines.append(f"RA {cal['xAngle']:.1f}°  {cal.get('xRate', 0):.2f} px/s")
        if "yAngle" in cal:
            lines.append(f"Dec {cal['yAngle']:.1f}°  {cal.get('yRate', 0):.2f} px/s")
        painter.setPen(_PLOT_FG)
        painter.drawText(QRectF(4, self.height() - 40, self.width() - 8, 36), Qt.AlignCenter, "\n".join(lines))
        painter.end()


class StarView(QWidget):
    """The guide-star cut-out PHD2 sends, stretched and scaled to fit."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(160)
        self._image: QImage | None = None
        self._star: tuple[float, float] | None = None
        self._size = (1, 1)
        self.message = "No guide star image"

    def set_star_image(self, star) -> None:
        if star is None:
            self._image = None
        else:
            data = np.frombuffer(star.pixels, dtype="<u2").reshape(star.height, star.width).astype(np.float32)
            lo, hi = float(np.median(data)), float(np.percentile(data, 99.8))
            if hi <= lo:
                hi = lo + 1.0
            grey = np.ascontiguousarray((np.clip((data - lo) / (hi - lo), 0, 1) ** 0.5 * 255).astype(np.uint8))
            self._image = QImage(grey.data, star.width, star.height, star.width, QImage.Format_Grayscale8).copy()
            self._star, self._size = star.star_pos, (star.width, star.height)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#141414"))
        if self._image is None:
            painter.setPen(QColor("#8a949c"))
            painter.drawText(self.rect(), Qt.AlignCenter, self.message)
            painter.end()
            return
        side = min(self.width(), self.height())
        target = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        painter.drawImage(target, self._image)
        if self._star:
            k = side / max(self._size)
            cx, cy = target.left() + self._star[0] * k, target.top() + self._star[1] * k
            painter.setPen(QPen(QColor("#31e04a"), 1.5))
            box = max(10.0, 12 * k)
            painter.drawRect(QRectF(cx - box / 2, cy - box / 2, box, box))
        painter.end()


class _Lamp(QLabel):
    def __init__(self, color: str) -> None:
        super().__init__()
        self._color = color
        self.setFixedSize(14, 14)
        self.set_on(False)

    def set_on(self, on: bool) -> None:
        fill = self._color if on else "#2b2b2b"
        self.setStyleSheet(f"background: {fill}; border: 1px solid #555; border-radius: 7px;")


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("CriteriaHeading")
    return label


class GuiderPage(QWidget):
    """The Guiding section. One PHD2 connection per Pier (GUIDE-060)."""

    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("GuiderPage")
        self._window = window
        self._services: dict = {}
        self._connecting: set = set()
        self._saved_phd2 = False
        self._last_key: tuple | None = None
        self._ticks = 0
        self._build()
        self.refresh_view(None)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(250)

    # --- Layout -----------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        title = QLabel("Guiding")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        # connection row: PHD2 has no device list to scan — it is one host:port
        row = QHBoxLayout()
        row.addWidget(QLabel("PHD2 host"))
        self.host_edit = QLineEdit(DEFAULT_HOST)
        self.host_edit.setPlaceholderText("FQDN or IP of the machine running PHD2, e.g. localhost or 192.168.1.50")
        self.host_edit.setMaxLength(60)
        row.addWidget(self.host_edit, 1)
        row.addWidget(QLabel("Port"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_PORT)
        self.port_spin.setToolTip("PHD2's event-server port: 4400 for the first PHD2 instance, 4401 for the second, …")
        row.addWidget(self.port_spin)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("AccentButton")
        self.connect_btn.clicked.connect(self.connect_to_phd2)
        row.addWidget(self.connect_btn)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.disconnect_from_phd2)
        row.addWidget(self.disconnect_btn)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("AccentButton")
        self.save_btn.setToolTip("Save this host and port under the selected Observatory and Pier.")
        self.save_btn.clicked.connect(self.save)
        row.addWidget(self.save_btn)
        layout.addLayout(row)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        content = QWidget()
        grid = QHBoxLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        grid.addWidget(self._build_left_column())
        grid.addLayout(self._build_right_column(), 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # PHD2's own event log (newest first), not the application log the other pages tail.
        self.event_log = self._window._build_log_pane()
        self.event_log.setFixedHeight(self.event_log.fontMetrics().lineSpacing() * 7 + 12)
        layout.addWidget(self.event_log)

    def _build_left_column(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(340)
        box = QVBoxLayout(column)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)

        train_row = QHBoxLayout()
        train_row.addWidget(QLabel("Train:"))
        self.train_combo = QComboBox()
        self.train_combo.currentIndexChanged.connect(lambda _i: self._force_render())
        train_row.addWidget(self.train_combo, 1)
        box.addLayout(train_row)

        box.addWidget(_heading("Control"))
        buttons = QGridLayout()
        self.loop_btn = QPushButton("Loop")
        self.guide_btn = QPushButton("Guide")
        self.guide_btn.setObjectName("AccentButton")
        self.stop_btn = QPushButton("Stop")
        self.find_btn = QPushButton("Auto Star")
        self.dither_btn = QPushButton("Dither")
        for i, button in enumerate((self.loop_btn, self.guide_btn, self.stop_btn)):
            buttons.addWidget(button, 0, i)
        buttons.addWidget(self.find_btn, 1, 0)
        buttons.addWidget(self.dither_btn, 1, 1)
        box.addLayout(buttons)
        self.loop_btn.clicked.connect(lambda: self._send("loop"))
        self.guide_btn.clicked.connect(lambda: self._send("guide", recalibrate=self.recal_check.isChecked()))
        self.stop_btn.clicked.connect(lambda: self._send("stop"))
        self.find_btn.clicked.connect(lambda: self._send("find_star"))
        self.dither_btn.clicked.connect(lambda: self._send("request_dither"))

        form = QGridLayout()
        form.addWidget(QLabel("Exp:"), 0, 0)
        self.exposure_combo = QComboBox()
        self.exposure_combo.activated.connect(self._on_exposure_chosen)
        form.addWidget(self.exposure_combo, 0, 1)
        form.addWidget(QLabel("Dec:"), 1, 0)
        self.dec_combo = QComboBox()
        self.dec_combo.addItems(DEC_GUIDE_MODES)
        self.dec_combo.setToolTip("Which Dec corrections PHD2 may send: Off, Auto (both), or North / South only.")
        self.dec_combo.activated.connect(lambda _i: self._send("set_dec_guide_mode", self.dec_combo.currentText()))
        form.addWidget(self.dec_combo, 1, 1)
        self.recal_check = QCheckBox("Recalibrate on Guide")
        form.addWidget(self.recal_check, 2, 0, 1, 2)
        self.clear_cal_btn = QPushButton("Clear Calibration")
        self.clear_cal_btn.clicked.connect(lambda: self._send("clear_calibration"))
        form.addWidget(self.clear_cal_btn, 3, 0, 1, 2)
        box.addLayout(form)

        equip = QHBoxLayout()
        self.equip_connect_btn = QPushButton("Connect Equipment")
        self.equip_connect_btn.setToolTip("Tell PHD2 to connect its own camera and mount.")
        self.equip_disconnect_btn = QPushButton("Disconnect Equipment")
        self.equip_connect_btn.clicked.connect(lambda: self._send("set_equipment_connected", True))
        self.equip_disconnect_btn.clicked.connect(lambda: self._send("set_equipment_connected", False))
        equip.addWidget(self.equip_connect_btn)
        equip.addWidget(self.equip_disconnect_btn)
        box.addLayout(equip)

        box.addWidget(_heading("Scope / Lens Info"))
        scope = QGridLayout()
        self.scope_values = {}
        for i, (key, text) in enumerate((
            ("focal", "Focal length"), ("aperture", "Aperture"), ("ratio", "Focal ratio"),
            ("scale", "Guide scale"), ("fov", "Guide FOV"),
        )):
            scope.addWidget(QLabel(text), i, 0)
            self.scope_values[key] = QLabel("—")
            scope.addWidget(self.scope_values[key], i, 1)
        box.addLayout(scope)

        box.addWidget(_heading("Guide Info"))
        info = QGridLayout()
        self.info_unit_labels = {}
        info.addWidget(QLabel("RA"), 0, 1)
        info.addWidget(QLabel("DEC"), 0, 2)
        self.info: dict[str, tuple[QLabel, ...]] = {}
        rows = (("delta", "Guiding delta"), ("pulse", "Pulse length (ms)"), ("rms", "RMS (RA/DEC)"))
        for i, (key, text) in enumerate(rows, start=1):
            label = QLabel(text)
            self.info_unit_labels[key] = label
            info.addWidget(label, i, 0)
            self.info[key] = (QLabel("—"), QLabel("—"))
            info.addWidget(self.info[key][0], i, 1)
            info.addWidget(self.info[key][1], i, 2)
        for i, (key, text) in enumerate((("total", "Total RMS"), ("snr", "Guide SNR"), ("star", "Star mass / HFD")), start=4):
            info.addWidget(QLabel(text), i, 0)
            self.info[key] = (QLabel("—"),)
            info.addWidget(self.info[key][0], i, 1, 1, 2)
        box.addLayout(info)

        lamps = QHBoxLayout()
        self.lamps = {"idle": _Lamp("#31c24a"), "prep": _Lamp("#f0d020"), "run": _Lamp("#e04040")}
        for key, text in (("idle", "Idle"), ("prep", "Prep"), ("run", "Run")):
            lamps.addWidget(self.lamps[key])
            lamps.addWidget(QLabel(text))
            lamps.addStretch(1)
        box.addLayout(lamps)
        self.state_label = QLabel("")
        box.addWidget(self.state_label)
        box.addStretch(1)
        return column

    def _build_right_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)
        self.star_view = StarView()
        column.addWidget(self.star_view, 3)

        lower = QHBoxLayout()
        graph_box = QVBoxLayout()
        self.graph = DriftGraph()
        graph_box.addWidget(self.graph, 1)

        toggles = QGridLayout()
        self.toggle_checks = {}
        for i, (key, text) in enumerate((
            ("ra", "RA"), ("dec", "DEC"), ("snr", "SNR"), ("corr_ra", "Corr RA"), ("corr_dec", "Corr DEC"), ("rms", "RMS"),
        )):
            check = QCheckBox(text)
            check.setChecked(self.graph.series[key])
            check.toggled.connect(lambda on, k=key: self._toggle_series(k, on))
            self.toggle_checks[key] = check
            toggles.addWidget(check, i // 3, i % 3)
        zoom_in, zoom_out = QPushButton("+"), QPushButton("−")
        zoom_in.setToolTip("Zoom the guide graph in (smaller error range).")
        zoom_out.setToolTip("Zoom the guide graph out (larger error range).")
        zoom_in.clicked.connect(lambda: self.graph.zoom(1))
        zoom_out.clicked.connect(lambda: self.graph.zoom(-1))
        toggles.addWidget(zoom_in, 0, 3)
        toggles.addWidget(zoom_out, 1, 3)
        toggles.addWidget(QLabel("Trace:"), 0, 4)
        trace = QSlider(Qt.Horizontal)
        trace.setRange(30, 600)
        trace.setValue(int(self.graph.window_s))
        trace.setToolTip("How many seconds of history the graph shows.")
        trace.valueChanged.connect(self._set_window)
        toggles.addWidget(trace, 1, 4)
        toggles.setColumnStretch(4, 1)
        graph_box.addLayout(toggles)
        lower.addLayout(graph_box, 1)

        self.plot_tabs = QTabWidget()
        self.scatter = DriftScatter()
        self.calibration_plot = CalibrationPlot()
        drift_tab = QWidget()
        drift_box = QVBoxLayout(drift_tab)
        drift_box.setContentsMargins(0, 0, 0, 0)
        drift_box.addWidget(self.scatter, 1)
        ring_row = QHBoxLayout()
        ring_row.addStretch(1)
        ring_row.addWidget(QLabel("Ring:"))
        self.ring_spin = QDoubleSpinBox()
        self.ring_spin.setRange(0.1, 10.0)
        self.ring_spin.setSingleStep(0.5)
        self.ring_spin.setValue(self.scatter.ring)
        self.ring_spin.setToolTip("Radius of the green target ring; the yellow and red rings are 2× and 3× this.")
        self.ring_spin.valueChanged.connect(self._set_ring)
        ring_row.addWidget(self.ring_spin)
        drift_box.addLayout(ring_row)
        self.plot_tabs.addTab(drift_tab, "Mount Drift")
        self.plot_tabs.addTab(self.calibration_plot, "Calibration Plot")
        self.plot_tabs.setFixedWidth(300)
        lower.addWidget(self.plot_tabs)
        column.addLayout(lower, 2)
        return column

    # --- Small handlers ---------------------------------------------------

    def _toggle_series(self, key: str, on: bool) -> None:
        self.graph.series[key] = on
        self.graph.update()

    def _set_window(self, seconds: int) -> None:
        self.graph.window_s = float(seconds)
        self.graph.update()

    def _set_ring(self, value: float) -> None:
        self.scatter.ring = value
        self.scatter.update()

    def _force_render(self) -> None:
        self._last_key = None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_tubes()

    # --- Pier persistence (registered as the page's "reload"/"autoconnect") ----

    def _pier_key(self):
        return getattr(self._window._current_pier, "id", None)

    def reload(self) -> None:
        """Load this Pier's saved PHD2 host/port, and forget nothing about its live connection."""
        cfg = None
        if self._window._current_pier is not None:
            from galileo.observatory import get_device_config
            try:
                cfg = get_device_config(self._window._current_pier, "guider")
            except Exception:
                logger.exception("Could not load saved guider config")
        self._saved_phd2 = cfg is not None and cfg.driver == DRIVER_NAME
        # A guider saved before PHD2 support (an INDI/Alpaca device) has no PHD2 host to offer.
        host, port = (cfg.server or DEFAULT_HOST, cfg.port) if cfg is not None and self._saved_phd2 else (DEFAULT_HOST, DEFAULT_PORT)
        service = self._services.get(self._pier_key())
        if service is not None and service.is_connected:
            host, port = service.host, service.port
        self.host_edit.setText(host)
        self.port_spin.setValue(port)
        self.refresh_tubes()
        self._force_render()

    def autoconnect(self) -> None:
        """Reconnect to a saved PHD2 host after a Pier switch or at startup."""
        service = self._services.get(self._pier_key())
        if self._saved_phd2 and (service is None or not service.is_connected):
            self.connect_to_phd2()

    def save(self) -> None:
        pier = self._window._current_pier
        if pier is None:
            QMessageBox.warning(
                self._window._window, "No Pier selected",
                "Select (or create) an Observatory and Pier before saving equipment settings.",
            )
            return
        from galileo.observatory import save_device_config
        host = self.host_edit.text().strip() or DEFAULT_HOST
        try:
            save_device_config(pier, "guider", driver=DRIVER_NAME, server=host,
                               port=self.port_spin.value(), device_name=DRIVER_NAME)
        except Exception:
            logger.exception("Could not save guider config for Pier %r", pier.name)
            return
        self._saved_phd2 = True
        logger.info("Saved guider settings for Pier %r: PHD2 at %s:%s", pier.name, host, self.port_spin.value())
        self._window._window.statusBar().showMessage(f"Saved guider settings for Pier {pier.name!r}.", 4000)

    def refresh_tubes(self) -> None:
        """Repopulate the Train selector from the Pier's saved optical tubes."""
        from galileo.ui.app_window import _optical_tube_label
        tubes = []
        if self._window._current_pier is not None:
            from galileo.observatory import list_optical_tubes
            try:
                tubes = list_optical_tubes(self._window._current_pier)
            except Exception:
                logger.exception("Could not load optical tubes for the Guider screen")
        previous = self.train_combo.currentIndex()
        self.train_combo.blockSignals(True)
        self.train_combo.clear()
        for i, tube in enumerate(tubes):
            self.train_combo.addItem(_optical_tube_label(tube, i), tube)
        if not tubes:
            self.train_combo.addItem("None defined — see Equipment > Optics", None)
        self.train_combo.setCurrentIndex(previous if 0 <= previous < self.train_combo.count() else 0)
        self.train_combo.blockSignals(False)
        self._force_render()

    # --- Connection and commands ------------------------------------------

    def _service(self) -> GuidingService | None:
        return self._services.get(self._pier_key())

    def connect_to_phd2(self) -> None:
        key = self._pier_key()
        host = self.host_edit.text().strip() or DEFAULT_HOST
        port = self.port_spin.value()
        service = self._services.get(key)
        if service is not None and service.is_connected:
            return
        if key in self._connecting:
            return
        if service is None or (service.host, service.port) != (host, port):
            service = self._services[key] = GuidingService(host, port)
        self._connecting.add(key)
        service.model.log(f"Connecting to PHD2 at {host}:{port}…")
        threading.Thread(target=self._connect_worker, args=(key, service), name="phd2-connect", daemon=True).start()
        self._force_render()

    def _connect_worker(self, key, service: GuidingService) -> None:
        import asyncio
        try:
            asyncio.run(service.connect())
            service.sync_state()
        except Exception as exc:
            logger.warning("Could not connect to PHD2 at %s:%s: %s", service.host, service.port, exc)
            service.model.log(f"Could not connect to PHD2 at {service.host}:{service.port}: {exc}")
        finally:
            self._connecting.discard(key)

    def disconnect_from_phd2(self) -> None:
        service = self._service()
        if service is not None:
            import asyncio
            asyncio.run(service.disconnect())
        self._force_render()

    def _send(self, command: str, *args, **kwargs) -> None:
        service = self._service()
        if service is None or not service.is_connected:
            return
        method: Callable[..., object] = {"guide": service.guide, "loop": service.loop, "stop": service.stop,
                  "find_star": service.find_star, "request_dither": service.request_dither,
                  "set_dec_guide_mode": service.set_dec_guide_mode, "clear_calibration": service.clear_calibration,
                  "set_equipment_connected": service.set_equipment_connected}[command]
        method(*args, **kwargs)

    def _on_exposure_chosen(self, index: int) -> None:
        ms = self.exposure_combo.itemData(index)
        service = self._service()
        if ms is not None and service is not None and service.is_connected:
            service.set_exposure(ms)

    # --- Refresh ----------------------------------------------------------

    def _tick(self) -> None:
        service = self._service()
        self._ticks += 1
        if service is not None and self._ticks % 4 == 0:
            service.poll(want_star_image=self.isVisible())
        key = (id(service), service.model.version if service else None, self._pier_key() in self._connecting)
        if key != self._last_key:
            self._last_key = key
            self.refresh_view(service.model.snapshot() if service else None)

    def refresh_view(self, snap: GuideSnapshot | None) -> None:
        connected = snap is not None and snap.connected
        connecting = self._pier_key() in self._connecting
        equipment = snap is not None and snap.connected and snap.equipment_connected
        state = snap.app_state if snap else "Stopped"

        self.host_edit.setEnabled(not connected and not connecting)
        self.port_spin.setEnabled(not connected and not connecting)
        self.connect_btn.setEnabled(not connected and not connecting)
        self.connect_btn.setText("Connecting…" if connecting else "Connect")
        self.disconnect_btn.setEnabled(connected)
        if snap is not None and connected:
            version = f" (PHD2 {snap.phd_version})" if snap.phd_version else ""
            equip = "equipment connected" if equipment else "equipment not connected — use Connect Equipment"
            self.status_label.setText(f"Connected to PHD2{version} — {equip}.")
        else:
            self.status_label.setText("Not connected to PHD2. Start PHD2, then enter its host and click Connect.")

        idle_states = ("Stopped", "Selected", "LostLock", "Paused")
        self.equip_connect_btn.setEnabled(connected and not equipment)
        self.equip_disconnect_btn.setEnabled(equipment)
        self.loop_btn.setEnabled(equipment and state in idle_states)
        self.guide_btn.setEnabled(equipment and state in ("Stopped", "Selected", "Looping", "LostLock", "Paused"))
        self.stop_btn.setEnabled(equipment and state != "Stopped")
        self.find_btn.setEnabled(equipment and state in ("Looping", "Selected", "LostLock"))
        self.dither_btn.setEnabled(equipment and state == "Guiding")
        self.exposure_combo.setEnabled(connected)
        self.dec_combo.setEnabled(connected)
        self.clear_cal_btn.setEnabled(equipment and state not in ("Calibrating", "Guiding"))

        self._render_choices(snap)
        for key, lamp in self.lamps.items():
            lamp.set_on(snap is not None and connected and snap.phase == key)
        self.state_label.setText(f"State: {state}{' (settling)' if snap and snap.settling else ''}" if connected else "")

        tube = self.train_combo.currentData()
        self._render_scope(tube, snap)
        self._render_info(snap)

        samples = snap.samples if snap else []
        self.graph.set_data(samples, snap.pixel_scale if snap else None, snap.unit if snap else "px",
                            snap.rms_ra if snap else 0.0, snap.rms_dec if snap else 0.0)
        self.scatter.set_data(samples, snap.pixel_scale if snap else None, snap.unit if snap else "px")
        self.calibration_plot.set_data(snap.calibration_points if snap else [], snap.calibration if snap else None)
        self.star_view.set_star_image(snap.star_image if snap else None)

        text = "\n".join(reversed(snap.log)) if snap else ""  # newest first, like the reference screen
        if self.event_log.toPlainText() != text:
            self.event_log.setPlainText(text)

    def _render_choices(self, snap: GuideSnapshot | None) -> None:
        options = list(snap.exposure_options_ms) if snap else []
        current = snap.exposure_ms if snap else None
        if current is not None and current not in options:
            options = sorted(options + [current])
        self.exposure_combo.blockSignals(True)
        self.exposure_combo.clear()
        for ms in options:
            self.exposure_combo.addItem(f"{ms / 1000:g} s", ms)
        if current is not None:
            self.exposure_combo.setCurrentIndex(options.index(current))
        self.exposure_combo.blockSignals(False)
        if snap and snap.dec_mode in DEC_GUIDE_MODES:
            self.dec_combo.setCurrentText(snap.dec_mode)

    def _render_scope(self, tube, snap: GuideSnapshot | None) -> None:
        focal = getattr(tube, "focal_length_mm", None)
        aperture = getattr(tube, "aperture_mm", None)
        scale = snap.pixel_scale if snap else None
        values = self.scope_values
        values["focal"].setText(f"{focal:g} mm" if focal else "—")
        values["aperture"].setText(f"{aperture:g} mm" if aperture else "—")
        values["ratio"].setText(f"f/{focal / aperture:.1f}" if focal and aperture else "—")
        values["scale"].setText(f"{scale:.2f} ″/px" if scale else "—")
        if snap and scale and snap.frame_size:
            width, height = (px * scale / 60 for px in snap.frame_size)
            values["fov"].setText(f"{width:.1f}′ × {height:.1f}′")
        else:
            values["fov"].setText("—")

    def _render_info(self, snap: GuideSnapshot | None) -> None:
        unit = "″" if snap and snap.pixel_scale else " px"
        self.info_unit_labels["delta"].setText(f"Guiding delta ({unit.strip()}):")
        last = snap.samples[-1] if snap and snap.samples else None
        scale = (snap.pixel_scale or 1.0) if snap else 1.0

        def put(key: str, *texts: str) -> None:
            for label, text in zip(self.info[key], texts):
                label.setText(text)

        if last is None:
            put("delta", "—", "—")
            put("pulse", "—", "—")
            put("snr", "—")
            put("star", "—")
        else:
            put("delta", f"{last.ra * scale:+.2f}", f"{last.dec * scale:+.2f}")
            put("pulse", f"{last.ra_pulse_ms:+.0f}", f"{last.dec_pulse_ms:+.0f}")
            put("snr", f"{last.snr:.1f}")
            put("star", f"{last.star_mass:.0f} / {last.hfd:.1f}")
        if snap and snap.samples:
            put("rms", f"{snap.rms_ra:.2f}", f"{snap.rms_dec:.2f}")
            put("total", f"{snap.rms_total:.2f} {unit.strip()}")
        else:
            put("rms", "—", "—")
            put("total", "—")
