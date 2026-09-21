# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Flat, single-colour vector icons for the sidebar navigation.

Drawn at runtime with ``QPainter`` rather than shipped as image assets, so
icon colour tracks the current theme/accent colour without needing a
separate image file per theme. Each entry in :data:`ICONS` is a small
``draw(painter, rect)`` callable; :func:`make_icon` rasterizes one into a
``QIcon`` at a given size and colour.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    # Qt is imported lazily inside the functions so this module loads without PySide6.
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QIcon, QPainter

DrawFn = Callable[["QPainter", "QRectF"], None]


def make_icon(name: str, color: str, size: int = 26) -> "QIcon":
    from PySide6.QtCore import Qt, QRectF
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.4, size * 0.06))
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    margin = size * 0.14
    ICONS[name](painter, QRectF(margin, margin, size - 2 * margin, size - 2 * margin))
    painter.end()
    return QIcon(pixmap)


def _star_points(cx: float, cy: float, outer: float, inner: float, points: int = 5, rotation: float = 90.0) -> list:
    from PySide6.QtCore import QPointF
    pts = []
    step = math.pi / points
    start = math.radians(rotation)
    for i in range(points * 2):
        rad = outer if i % 2 == 0 else inner
        ang = start + i * step
        pts.append(QPointF(cx + rad * math.cos(ang), cy - rad * math.sin(ang)))
    return pts


def _radial_ticks(painter, cx: float, cy: float, r_from: float, r_to: float, count: int) -> None:
    from PySide6.QtCore import QLineF
    for i in range(count):
        ang = i * (2 * math.pi / count)
        painter.drawLine(QLineF(
            cx + r_from * math.cos(ang), cy + r_from * math.sin(ang),
            cx + r_to * math.cos(ang), cy + r_to * math.sin(ang),
        ))


# ---------------------------------------------------------------------------
# Primary navigation icons
# ---------------------------------------------------------------------------

def _equipment(painter, r):
    from PySide6.QtCore import QPointF, QRectF
    body = QRectF(r.left(), r.top() + r.height() * 0.28, r.width(), r.height() * 0.55)
    painter.drawRoundedRect(body, 2, 2)
    painter.drawEllipse(body.center(), r.width() * 0.17, r.width() * 0.17)
    painter.drawRect(QRectF(r.left() + r.width() * 0.28, r.top(), r.width() * 0.26, r.height() * 0.16))


def _sky_atlas(painter, r):
    from PySide6.QtGui import QPolygonF
    c = r.center()
    painter.drawPolygon(QPolygonF(_star_points(c.x(), c.y(), r.width() * 0.5, r.width() * 0.21)))


def _star_atlas(painter, r):
    """A round sky chart: horizon circle with a few stars in it."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    c = r.center()
    painter.drawEllipse(c, r.width() * 0.5, r.height() * 0.5)
    painter.drawPolygon(QPolygonF(_star_points(c.x() - r.width() * 0.08, c.y() - r.height() * 0.04,
                                               r.width() * 0.26, r.width() * 0.11)))
    for dx, dy in ((0.24, -0.22), (0.2, 0.2), (-0.26, 0.22)):
        painter.drawPoint(QPointF(c.x() + r.width() * dx, c.y() + r.height() * dy))


def _framing(painter, r):
    from PySide6.QtCore import QLineF
    seg = r.width() * 0.32
    x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()
    for (cx, cy, dx, dy) in ((x0, y0, 1, 0), (x0, y0, 0, 1), (x1, y0, -1, 0), (x1, y0, 0, 1),
                              (x0, y1, 1, 0), (x0, y1, 0, -1), (x1, y1, -1, 0), (x1, y1, 0, -1)):
        painter.drawLine(QLineF(cx, cy, cx + dx * seg, cy + dy * seg))


def _flat_wizard(painter, r):
    c = r.center()
    radius = r.width() * 0.24
    painter.drawEllipse(c, radius, radius)
    _radial_ticks(painter, c.x(), c.y(), radius * 1.4, radius * 2.1, 8)


def _sequencer(painter, r):
    from PySide6.QtCore import QLineF
    n = 3
    step = r.height() / (n - 1) if n > 1 else 0
    for i in range(n):
        y = r.top() + step * i
        painter.drawLine(QLineF(r.left(), y, r.left() + r.width() * 0.16, y))
        painter.drawLine(QLineF(r.left() + r.width() * 0.32, y, r.right(), y))


def _imaging(painter, r):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    painter.drawRoundedRect(r, 2, 2)
    painter.drawEllipse(QPointF(r.left() + r.width() * 0.28, r.top() + r.height() * 0.32), r.width() * 0.09, r.width() * 0.09)
    painter.drawPolyline(QPolygonF([
        QPointF(r.left(), r.bottom() - r.height() * 0.08),
        QPointF(r.left() + r.width() * 0.38, r.top() + r.height() * 0.42),
        QPointF(r.left() + r.width() * 0.6, r.top() + r.height() * 0.66),
        QPointF(r.left() + r.width() * 0.78, r.top() + r.height() * 0.48),
        QPointF(r.right(), r.bottom() - r.height() * 0.08),
    ]))


def _solve(painter, r):
    """A crosshair around a star: the frame's centre being pinned to a place on the sky."""
    from PySide6.QtCore import QLineF
    from PySide6.QtGui import QPolygonF
    c = r.center()
    radius = r.width() * 0.3
    painter.drawEllipse(c, radius, radius)
    reach = r.width() * 0.5
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        painter.drawLine(QLineF(c.x() + dx * radius * 0.6, c.y() + dy * radius * 0.6, c.x() + dx * reach, c.y() + dy * reach))
    painter.setBrush(painter.pen().color())
    painter.drawPolygon(QPolygonF(_star_points(c.x(), c.y(), r.width() * 0.13, r.width() * 0.055)))


def _scheduler(painter, r):
    from PySide6.QtCore import QLineF
    painter.drawEllipse(r)
    c = r.center()
    painter.drawLine(QLineF(c.x(), c.y(), c.x(), r.top() + r.height() * 0.22))
    painter.drawLine(QLineF(c.x(), c.y(), r.left() + r.width() * 0.7, c.y()))


def _library(painter, r):
    from PySide6.QtCore import QRectF
    n = 3
    gap = r.height() * 0.1
    h = (r.height() - gap * (n - 1)) / n
    for i in range(n):
        y = r.top() + i * (h + gap)
        painter.drawRoundedRect(QRectF(r.left(), y, r.width(), h), 1, 1)


def _variable_stars(painter, r):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    c = r.center()
    painter.save()
    painter.translate(c)
    painter.rotate(-18)
    painter.drawEllipse(QPointF(0, 0), r.width() * 0.52, r.height() * 0.2)
    painter.restore()
    painter.setBrush(painter.pen().color())
    painter.drawPolygon(QPolygonF(_star_points(c.x(), c.y(), r.width() * 0.19, r.width() * 0.08)))


def _options(painter, r):
    c = r.center()
    radius = r.width() * 0.3
    painter.drawEllipse(c, radius, radius)
    painter.drawEllipse(c, radius * 0.38, radius * 0.38)
    _radial_ticks(painter, c.x(), c.y(), radius * 1.12, radius * 1.42, 8)


def _power(painter, r):
    from PySide6.QtCore import QLineF, QRectF
    rect = QRectF(r.left(), r.top() + r.height() * 0.02, r.width(), r.height() * 0.96)
    # A 260° ring whose 100° gap is centred on 12 o'clock (behind the bar):
    # Qt angles run counter-clockwise from 3 o'clock, so it starts at 90° + 50°.
    painter.drawArc(rect, int(140 * 16), int(260 * 16))
    c = r.center()
    painter.drawLine(QLineF(c.x(), r.top(), c.x(), r.top() + r.height() * 0.5))


def _theme(painter, r):
    from PySide6.QtGui import QPainterPath
    from PySide6.QtCore import QRectF
    c = r.center()
    radius = r.width() * 0.42
    painter.drawEllipse(c, radius, radius)
    path = QPainterPath()
    path.addEllipse(c, radius, radius)
    painter.save()
    painter.setClipPath(path)
    painter.setBrush(painter.pen().color())
    painter.drawRect(QRectF(c.x(), r.top(), radius, r.height()))
    painter.restore()


def _manual(painter, r):
    from PySide6.QtCore import QLineF
    painter.drawRoundedRect(r, 2, 2)
    for i in range(3):
        y = r.top() + r.height() * 0.3 + i * r.height() * 0.22
        painter.drawLine(QLineF(r.left() + r.width() * 0.18, y, r.right() - r.width() * 0.18, y))


def _about(painter, r):
    from PySide6.QtCore import QLineF, QPointF
    c = r.center()
    painter.drawEllipse(c, r.width() * 0.42, r.width() * 0.42)
    painter.drawLine(QLineF(c.x(), c.y() - r.height() * 0.02, c.x(), c.y() + r.height() * 0.24))
    painter.setBrush(painter.pen().color())
    painter.drawEllipse(QPointF(c.x(), c.y() - r.height() * 0.24), r.width() * 0.045, r.width() * 0.045)


# ---------------------------------------------------------------------------
# Equipment secondary navigation icons (device categories)
# ---------------------------------------------------------------------------

def _camera(painter, r):
    _equipment(painter, r)


def _mount(painter, r):
    from PySide6.QtCore import QLineF, QPointF
    painter.drawLine(QLineF(r.left(), r.bottom(), r.right(), r.top() + r.height() * 0.15))
    painter.drawEllipse(QPointF(r.right(), r.top() + r.height() * 0.15), r.width() * 0.08, r.width() * 0.08)
    painter.drawLine(QLineF(r.left() + r.width() * 0.2, r.bottom(), r.left() + r.width() * 0.55, r.bottom() - r.height() * 0.28))
    tri_x = r.left() + r.width() * 0.15
    painter.drawLine(QLineF(tri_x, r.bottom(), tri_x + r.width() * 0.3, r.bottom()))


def _filter_wheel(painter, r):
    c = r.center()
    painter.drawEllipse(c, r.width() * 0.48, r.width() * 0.48)
    painter.drawEllipse(c, r.width() * 0.14, r.width() * 0.14)
    _radial_ticks(painter, c.x(), c.y(), r.width() * 0.16, r.width() * 0.42, 6)


def _focuser(painter, r):
    c = r.center()
    painter.drawEllipse(c, r.width() * 0.48, r.width() * 0.48)
    painter.drawEllipse(c, r.width() * 0.24, r.width() * 0.24)


def _rotator(painter, r):
    from PySide6.QtCore import QRectF
    rect = QRectF(r.left(), r.top(), r.width(), r.height())
    painter.drawArc(rect, int(30 * 16), int(300 * 16))
    _arrow_head(painter, r.right() - r.width() * 0.02, r.top() + r.height() * 0.22, -40)


def _arrow_head(painter, x, y, angle_deg):
    from PySide6.QtCore import QLineF
    ang = math.radians(angle_deg)
    size = 5
    for off in (0.6, -0.6):
        a = ang + off
        painter.drawLine(QLineF(x, y, x - size * math.cos(a), y - size * math.sin(a)))


def _guider(painter, r):
    from PySide6.QtCore import QLineF
    c = r.center()
    painter.drawEllipse(c, r.width() * 0.46, r.width() * 0.46)
    painter.drawLine(QLineF(c.x(), r.top(), c.x(), r.top() + r.height() * 0.2))
    painter.drawLine(QLineF(c.x(), r.bottom(), c.x(), r.bottom() - r.height() * 0.2))
    painter.drawLine(QLineF(r.left(), c.y(), r.left() + r.width() * 0.2, c.y()))
    painter.drawLine(QLineF(r.right(), c.y(), r.right() - r.width() * 0.2, c.y()))


def _focus(painter, r):
    from PySide6.QtCore import QLineF
    # Camera-style focus brackets around a centre dot.
    arm = r.width() * 0.3
    for x, sx in ((r.left(), 1), (r.right(), -1)):
        for y, sy in ((r.top(), 1), (r.bottom(), -1)):
            painter.drawLine(QLineF(x, y, x + sx * arm, y))
            painter.drawLine(QLineF(x, y, x, y + sy * arm))
    painter.setBrush(painter.pen().color())
    painter.drawEllipse(r.center(), r.width() * 0.09, r.width() * 0.09)


def _optics(painter, r):
    from PySide6.QtCore import QLineF, QRectF
    # A telescope tube seen from the side: barrel, dew-shield lip, and a focuser stub.
    barrel = QRectF(r.left(), r.top() + r.height() * 0.3, r.width() * 0.8, r.height() * 0.4)
    painter.drawRoundedRect(barrel, 2, 2)
    painter.drawLine(QLineF(barrel.left(), barrel.top() - r.height() * 0.06, barrel.left(), barrel.bottom() + r.height() * 0.06))
    painter.drawRect(QRectF(r.left() + r.width() * 0.8, r.top() + r.height() * 0.4, r.width() * 0.2, r.height() * 0.2))
    painter.drawLine(QLineF(r.left() + r.width() * 0.3, barrel.bottom(), r.left() + r.width() * 0.15, r.bottom()))
    painter.drawLine(QLineF(r.left() + r.width() * 0.3, barrel.bottom(), r.left() + r.width() * 0.45, r.bottom()))


def _switch(painter, r):
    from PySide6.QtCore import QPointF, QRectF
    body = QRectF(r.left(), r.top() + r.height() * 0.28, r.width(), r.height() * 0.44)
    painter.drawRoundedRect(body, body.height() / 2, body.height() / 2)
    painter.drawEllipse(QPointF(body.right() - body.height() / 2, body.center().y()), body.height() * 0.32, body.height() * 0.32)


def _flat_panel(painter, r):
    from PySide6.QtCore import QRectF
    painter.drawRoundedRect(QRectF(r.left(), r.top() + r.height() * 0.15, r.width(), r.height() * 0.7), 2, 2)
    c = r.center()
    painter.drawEllipse(c, r.width() * 0.14, r.width() * 0.14)


def _weather(painter, r):
    from PySide6.QtCore import QPointF, QRectF
    painter.drawEllipse(QRectF(r.left(), r.top() + r.height() * 0.15, r.width() * 0.55, r.height() * 0.45))
    painter.drawRoundedRect(QRectF(r.left() + r.width() * 0.15, r.top() + r.height() * 0.35, r.width() * 0.75, r.height() * 0.4), 4, 4)


def _dome(painter, r):
    from PySide6.QtCore import QLineF, QRectF
    rect = QRectF(r.left(), r.top(), r.width(), r.height() * 1.6)
    painter.drawArc(rect, 0, int(180 * 16))
    painter.drawLine(QLineF(r.left(), r.top() + r.height() * 0.5, r.right(), r.top() + r.height() * 0.5))


def _safety_monitor(painter, r):
    from PySide6.QtGui import QPolygonF
    from PySide6.QtCore import QPointF
    painter.drawPolygon(QPolygonF([
        QPointF(r.center().x(), r.top()),
        QPointF(r.right(), r.top() + r.height() * 0.22),
        QPointF(r.right(), r.top() + r.height() * 0.6),
        QPointF(r.center().x(), r.bottom()),
        QPointF(r.left(), r.top() + r.height() * 0.6),
        QPointF(r.left(), r.top() + r.height() * 0.22),
    ]))


def _images(painter, r):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPolygonF
    # A picture frame with a sun and a hillside.
    painter.drawRoundedRect(QRectF(r.left(), r.top() + r.height() * 0.12, r.width(), r.height() * 0.76), 2, 2)
    painter.drawEllipse(QPointF(r.left() + r.width() * 0.3, r.top() + r.height() * 0.36), r.width() * 0.08, r.width() * 0.08)
    painter.drawPolyline(QPolygonF([
        QPointF(r.left(), r.top() + r.height() * 0.8),
        QPointF(r.left() + r.width() * 0.38, r.top() + r.height() * 0.52),
        QPointF(r.left() + r.width() * 0.6, r.top() + r.height() * 0.7),
        QPointF(r.left() + r.width() * 0.75, r.top() + r.height() * 0.58),
        QPointF(r.right(), r.top() + r.height() * 0.82),
    ]))


def _sessions(painter, r):
    from PySide6.QtCore import QLineF, QPointF, QRectF
    # A calendar page: two binder rings over a header rule and a grid of nights.
    body = QRectF(r.left(), r.top() + r.height() * 0.14, r.width(), r.height() * 0.86)
    painter.drawRoundedRect(body, 2, 2)
    for x in (0.28, 0.72):
        painter.drawLine(QLineF(r.left() + r.width() * x, r.top(), r.left() + r.width() * x, r.top() + r.height() * 0.26))
    painter.drawLine(QLineF(body.left(), body.top() + body.height() * 0.28, body.right(), body.top() + body.height() * 0.28))
    for row in (0.5, 0.75):
        for col in (0.22, 0.5, 0.78):
            painter.drawPoint(QPointF(body.left() + body.width() * col, body.top() + body.height() * row))


def _mappings(painter, r):
    from PySide6.QtCore import QLineF
    # Two opposing arrows: one value replaced by another.
    y1, y2 = r.top() + r.height() * 0.32, r.top() + r.height() * 0.68
    painter.drawLine(QLineF(r.left(), y1, r.right(), y1))
    painter.drawLine(QLineF(r.right(), y1, r.right() - r.width() * 0.2, y1 - r.height() * 0.16))
    painter.drawLine(QLineF(r.right(), y1, r.right() - r.width() * 0.2, y1 + r.height() * 0.16))
    painter.drawLine(QLineF(r.right(), y2, r.left(), y2))
    painter.drawLine(QLineF(r.left(), y2, r.left() + r.width() * 0.2, y2 - r.height() * 0.16))
    painter.drawLine(QLineF(r.left(), y2, r.left() + r.width() * 0.2, y2 + r.height() * 0.16))


def _dedup(painter, r):
    from PySide6.QtCore import QRectF
    # Two overlapping sheets.
    side = r.width() * 0.66
    painter.drawRoundedRect(QRectF(r.left(), r.top(), side, side), 2, 2)
    painter.drawRoundedRect(QRectF(r.right() - side, r.bottom() - side, side, side), 2, 2)


def _cloud(painter, r):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainterPath
    # A cloud outline: a flat base with three overlapping puffs.
    base = r.top() + r.height() * 0.78
    path = QPainterPath()
    path.moveTo(r.left() + r.width() * 0.2, base)
    path.arcTo(QRectF(r.left(), r.top() + r.height() * 0.42, r.width() * 0.4, r.height() * 0.36), 270, -180)
    path.arcTo(QRectF(r.left() + r.width() * 0.16, r.top() + r.height() * 0.14, r.width() * 0.44, r.height() * 0.5), 200, -170)
    path.arcTo(QRectF(r.left() + r.width() * 0.44, r.top() + r.height() * 0.28, r.width() * 0.4, r.height() * 0.4), 100, -160)
    path.arcTo(QRectF(r.left() + r.width() * 0.62, r.top() + r.height() * 0.42, r.width() * 0.38, r.height() * 0.36), 90, -180)
    path.lineTo(r.left() + r.width() * 0.2, base)
    painter.drawPath(path)


def _merge(painter, r):
    from PySide6.QtCore import QLineF, QPointF
    # Two lines converging into one, with an arrow head.
    mid = QPointF(r.left() + r.width() * 0.5, r.center().y())
    painter.drawLine(QLineF(r.left(), r.top() + r.height() * 0.15, mid.x(), mid.y()))
    painter.drawLine(QLineF(r.left(), r.bottom() - r.height() * 0.15, mid.x(), mid.y()))
    painter.drawLine(QLineF(mid.x(), mid.y(), r.right(), mid.y()))
    painter.drawLine(QLineF(r.right(), mid.y(), r.right() - r.width() * 0.22, mid.y() - r.height() * 0.18))
    painter.drawLine(QLineF(r.right(), mid.y(), r.right() - r.width() * 0.22, mid.y() + r.height() * 0.18))


ICONS: dict[str, DrawFn] = {
    "equipment": _equipment,
    "star_atlas": _star_atlas,
    "sky_atlas": _sky_atlas,
    "framing": _framing,
    "flat_wizard": _flat_wizard,
    "sequencer": _sequencer,
    "imaging": _imaging,
    "solve": _solve,
    "scheduler": _scheduler,
    "library": _library,
    "variable_stars": _variable_stars,
    "options": _options,
    "power": _power,
    "theme": _theme,
    "manual": _manual,
    "about": _about,
    "camera": _camera,
    "mount": _mount,
    "filter_wheel": _filter_wheel,
    "focuser": _focuser,
    "rotator": _rotator,
    "guider": _guider,
    "focus": _focus,
    "optics": _optics,
    "switch": _switch,
    "flat_panel": _flat_panel,
    "weather": _weather,
    "dome": _dome,
    "safety_monitor": _safety_monitor,
    "images": _images,
    "sessions": _sessions,
    "mappings": _mappings,
    "dedup": _dedup,
    "cloud": _cloud,
    "merge": _merge,
}
