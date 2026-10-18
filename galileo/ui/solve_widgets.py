# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Solve page's small widgets: a labelled result row, the pointing-error plot and the image view."""

from __future__ import annotations

import math
from dataclasses import dataclass
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen
from galileo.ui._image_view import ImagePreviewView
from galileo.ui.guider import _PlotBase


@dataclass
class SolveRow:
    """One solve, as one row of the results table."""
    fits_path: str
    status: str = "solving"                      # "solving" | "solved" | "failed"
    ra_deg: float | None = None                  # J2000
    dec_deg: float | None = None
    rotation_deg: float | None = None
    scale_arcsec_px: float | None = None
    reason: str = ""
    name: str = ""
    width_px: int = 0
    height_px: int = 0
    target: tuple[float, float] | None = None    # J2000; what the solution is compared against
    d_ra_arcsec: float | None = None             # solution minus target, east positive
    d_dec_arcsec: float | None = None            # solution minus target, north positive

    @property
    def error_arcsec(self) -> float | None:
        if self.d_ra_arcsec is None or self.d_dec_arcsec is None:
            return None
        return math.hypot(self.d_ra_arcsec, self.d_dec_arcsec)


def _nice_step(raw: float) -> float:
    """Round *raw* to 1, 2, 5 or 10 times a power of ten — an axis tick spacing people can read."""
    magnitude = 10 ** math.floor(math.log10(raw))
    fraction = raw / magnitude
    return magnitude * (1 if fraction < 1.5 else 2 if fraction < 3.5 else 5 if fraction < 7.5 else 10)


class SolveErrorPlot(_PlotBase):
    """Where each solution landed relative to its target: dRA against dDE, with rings at
    1×, 2× and 3× the accuracy the user asked for. The newest solution is drawn brightest."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(220, 220)
        self.points: list[tuple[float, float]] = []
        self.ring = 30.0                # arcsec; radius of the green ring

    def set_points(self, points: list[tuple[float, float]]) -> None:
        self.points = points
        self.update()

    def set_ring(self, arcsec: float) -> None:
        self.ring = arcsec
        self.update()

    def paintEvent(self, event) -> None:
        painter = self._begin()
        side = min(self.width() - 56, self.height() - 44)
        if side < 40:
            painter.end()
            return
        plot = QRectF((self.width() - side) / 2 + 12, 8, side, side)
        c = plot.center()
        half = max(self.ring * 3.3, max((max(abs(x), abs(y)) for x, y in self.points), default=0.0) * 1.15)
        k = side / 2 / half

        # axes and ticks
        painter.setPen(QPen(QColor("#e0d030"), 1))
        painter.drawLine(QPointF(plot.left(), c.y()), QPointF(plot.right(), c.y()))
        painter.drawLine(QPointF(c.x(), plot.top()), QPointF(c.x(), plot.bottom()))
        step = _nice_step(half / 4)
        painter.setPen(QColor("#c8c8c8"))
        tick = step
        while tick < half:
            for sign in (1, -1):
                painter.drawText(QRectF(c.x() + sign * tick * k - 20, plot.bottom() + 2, 40, 14), Qt.AlignmentFlag.AlignCenter, f"{sign * tick:g}")
                painter.drawText(QRectF(plot.left() - 34, c.y() - sign * tick * k - 7, 30, 14),
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{sign * tick:g}")
            tick += step

        # accuracy rings
        for mult, color in ((1, "#31c24a"), (2, "#e0c030"), (3, "#d63a3a")):
            fill = QColor(color)
            fill.setAlpha(36)
            painter.setPen(QPen(QColor(color), 1.4))
            painter.setBrush(fill)
            radius = mult * self.ring * k
            painter.drawEllipse(c, radius, radius)

        # solutions
        n = len(self.points)
        for i, (x, y) in enumerate(self.points):
            dot = QColor("#ffffff")
            dot.setAlpha(80 + int(175 * (i + 1) / n))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot)
            painter.drawEllipse(QPointF(c.x() + x * k, c.y() - y * k), 2.6, 2.6)
        painter.setPen(QColor("#c8c8c8"))
        painter.drawText(QRectF(plot.left(), plot.bottom() + 14, side, 14), Qt.AlignmentFlag.AlignCenter, "dRA (arcsec)")
        painter.save()
        painter.translate(10, c.y())
        painter.rotate(-90)
        painter.drawText(QRectF(-50, -8, 100, 14), Qt.AlignmentFlag.AlignCenter, "dDE (arcsec)")
        painter.restore()
        painter.end()


class SolveImageView(ImagePreviewView):
    """The frame being solved. Fits the window until the user zooms; drag to pan."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SolveImage")
