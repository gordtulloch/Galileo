# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Guider page's plot widgets: guide graph, drift scatter, calibration plot, star view and the state lamp."""

from __future__ import annotations

import math
from typing import ClassVar
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QLabel, QWidget
from galileo.ui._image_view import ImagePreviewView


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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), _PLOT_BG)
        font = QFont(painter.font())
        font.setPointSizeF(8.0)
        painter.setFont(font)
        return painter

    @staticmethod
    def _dotted(color: QColor | None = None) -> QPen:
        pen = QPen(color or QColor(120, 120, 120))
        pen.setStyle(Qt.PenStyle.DotLine)
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
        mid = plot.center().y()

        self._draw_grid(painter, plot, mid)
        if self.samples:
            self._draw_samples(painter, plot, mid)
        self._draw_legend(painter, plot)
        painter.end()

    def _draw_grid(self, painter: QPainter, plot: QRectF, mid: float) -> None:
        """Grid lines and the Y (drift) / X (time ago) axis labels."""
        y_max = self.y_max
        painter.setPen(_PLOT_FG)
        for k in range(-2, 3):
            value = y_max * k / 2
            y = mid - k * plot.height() / 4
            painter.setPen(self._dotted() if k else QPen(QColor("#ffffff")))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(_PLOT_FG)
            painter.drawText(QRectF(0, y - 8, plot.left() - 4, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{value:g}")
        for k in range(5):
            x = plot.left() + k * plot.width() / 4
            painter.setPen(self._dotted())
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(_PLOT_FG)
            painter.drawText(QRectF(x - 25, plot.bottom() + 2, 50, 16), Qt.AlignmentFlag.AlignCenter,
                             _format_ago(self.window_s * (4 - k) / 4))
        painter.save()
        painter.translate(10, mid)
        painter.rotate(-90)
        painter.drawText(QRectF(-60, -8, 120, 16), Qt.AlignmentFlag.AlignCenter, f"Drift ({self.unit})")
        painter.restore()

    def _draw_samples(self, painter: QPainter, plot: QRectF, mid: float) -> None:
        """Correction bars, RMS guide lines, the RA/Dec lines and the SNR trace for the visible window."""
        y_max, scale = self.y_max, self.pixel_scale or 1.0
        t_now = self.samples[-1].t
        visible = [s for s in self.samples if t_now - s.t <= self.window_s]

        def x_of(s) -> float:
            return plot.right() - (t_now - s.t) / self.window_s * plot.width()

        def y_of(value: float) -> float:
            return mid - max(-y_max, min(y_max, value)) / y_max * plot.height() / 2

        painter.setClipRect(plot)
        if self.series["corr_ra"] or self.series["corr_dec"]:
            self._draw_correction_bars(painter, plot, mid, visible, x_of)
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
            self._draw_snr(painter, plot, visible, x_of)
        painter.setClipping(False)

    def _draw_correction_bars(self, painter: QPainter, plot: QRectF, mid: float, visible: list, x_of) -> None:
        """The RA / Dec correction pulses as translucent bars."""
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

    def _draw_snr(self, painter: QPainter, plot: QRectF, visible: list, x_of) -> None:
        """The SNR trace and its right-hand axis labels (the clip is lifted for the labels)."""
        snr_max = max(40.0, math.ceil(max(s.snr for s in visible) / 10) * 10) if visible else 40.0
        painter.setPen(QPen(_SNR, 1.2))
        painter.drawPolyline(QPolygonF([
            QPointF(x_of(s), plot.bottom() - s.snr / snr_max * plot.height()) for s in visible
        ]))
        painter.setClipping(False)
        painter.setPen(_SNR)
        for k in range(5):
            painter.drawText(QRectF(plot.right() + 4, plot.bottom() - k * plot.height() / 4 - 8, 40, 16),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{snr_max * k / 4:g}")

    def _draw_legend(self, painter: QPainter, plot: QRectF) -> None:
        x = plot.center().x() - 60
        for enabled, color, text in (
            (self.series["ra"], _RA, "RA"), (self.series["dec"], _DEC, "DE"),
            (self.series["snr"], _SNR, "SNR"), (self.series["rms"], _PLOT_FG, "RMS"),
        ):
            if enabled:
                painter.setPen(color)
                painter.drawText(QPointF(x, plot.bottom() - 6), f"– {text}")
                x += 34


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
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot)
            painter.drawEllipse(to_px(x, y), 2.0, 2.0)
        painter.setPen(_PLOT_FG)
        painter.drawText(QRectF(plot.left(), plot.bottom() + 4, side, 16), Qt.AlignmentFlag.AlignCenter,
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
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "No calibration this session")
        else:
            extent = max([abs(p.dx) for p in self.points] + [abs(p.dy) for p in self.points] + [1.0]) * 1.1
            k = min(plot.width(), plot.height()) / 2 / extent
            for point in self.points:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self._COLORS.get(point.direction, "#ffffff")))
                painter.drawEllipse(QPointF(c.x() + point.dx * k, c.y() - point.dy * k), 2.5, 2.5)
        cal = self.calibration or {}
        lines = []
        if "xAngle" in cal:
            lines.append(f"RA {cal['xAngle']:.1f}°  {cal.get('xRate', 0):.2f} px/s")
        if "yAngle" in cal:
            lines.append(f"Dec {cal['yAngle']:.1f}°  {cal.get('yRate', 0):.2f} px/s")
        painter.setPen(_PLOT_FG)
        painter.drawText(QRectF(4, self.height() - 40, self.width() - 8, 36), Qt.AlignmentFlag.AlignCenter, "\n".join(lines))
        painter.end()


class StarView(ImagePreviewView):
    """The guide-star cut-out PHD2 sends. Fits the window until the user zooms; drag to pan."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StarView")
        self.setMinimumHeight(160)
        self.setBackgroundBrush(QColor("#141414"))
        self._star: tuple[float, float] | None = None
        self.message = "No guide star image"

    def set_star_image(self, star) -> None:
        if star is None:
            self.clear_image()
            self._star = None
        else:
            data = np.frombuffer(star.pixels, dtype="<u2").reshape(star.height, star.width).astype(np.float32)
            lo, hi = float(np.median(data)), float(np.percentile(data, 99.8))
            if hi <= lo:
                hi = lo + 1.0
            grey = np.ascontiguousarray((np.clip((data - lo) / (hi - lo), 0, 1) ** 0.5 * 255).astype(np.uint8))
            self.show_array(grey)
            self._star = star.star_pos
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.has_image:
            painter = QPainter(self.viewport())
            painter.setPen(QColor("#8a949c"))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            painter.end()

    def drawForeground(self, painter, rect) -> None:
        super().drawForeground(painter, rect)
        if self.has_image and self._star:
            pen = QPen(QColor("#31e04a"))
            pen.setCosmetic(True)
            pen.setWidthF(1.5)
            painter.setPen(pen)
            box = 12.0
            cx, cy = self._star
            painter.drawRect(QRectF(cx - box / 2, cy - box / 2, box, box))


class _Lamp(QLabel):
    def __init__(self, color: str) -> None:
        super().__init__()
        self._color = color
        self.setFixedSize(14, 14)
        self.set_on(False)

    def set_on(self, on: bool) -> None:
        fill = self._color if on else "#2b2b2b"
        self.setStyleSheet(f"background: {fill}; border: 1px solid #555; border-radius: 7px;")
