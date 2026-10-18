# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Paints the Star Atlas: grid, boundaries, stars, deep-sky objects, planets, minor bodies, ground, horizon, labels and overlays."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from galileo.planning import minor_bodies as mb
from galileo.planning import star_atlas as sa


# Sky colour by the Sun's altitude (degrees): night → twilight → day.
_SKY_ALT_STOPS = [-18.0, -12.0, -6.0, 0.0, 8.0]


_SKY_RGB_STOPS = np.array([(3, 5, 12), (8, 14, 32), (30, 45, 85), (90, 120, 170), (110, 165, 225)], dtype=float)


_GRID_COLOR = QColor(70, 110, 160, 110)


_HORIZON_COLOR = QColor(200, 170, 90, 200)


_LABEL_COLOR = QColor(170, 195, 225)


_BOUNDARY_COLOR = QColor(190, 130, 210, 170)


_LINES_COLOR = QColor(110, 190, 170, 200)


_CONSTELLATION_LABEL_COLOR = QColor(190, 140, 215, 200)


_DSO_COLOR = QColor(120, 200, 150)


_BODY_COLOR = QColor(255, 214, 120)


_SELECT_COLOR = QColor(255, 90, 90)


# Telescope reticles (SKYMAP-090): where each Pier is pointing, and where it is on its way to.
_PIER_COLOR = QColor(120, 225, 255)


_PIER_SLEWING_COLOR = QColor(255, 190, 90)


_PIER_TARGET_COLOR = QColor(140, 175, 200)


# Comets, asteroids and satellites (SKYMAP-040).
_COMET_COLOR = QColor(150, 235, 255)


_ASTEROID_COLOR = QColor(255, 170, 120)


_SATELLITE_COLOR = QColor(190, 255, 150)


_SATELLITE_ECLIPSED_COLOR = QColor(110, 130, 105)


# Horizon obstructions: translucent, so the stars behind them can still be seen.
_OBSTRUCTION_RGBA = (220, 40, 40, 95)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as _MixinBase  # type checkers see a widget (it is mixed into one)
else:
    _MixinBase = object




class StarAtlasPaintMixin(_MixinBase):
    """Paints the Star Atlas: grid, boundaries, stars, deep-sky objects, planets, minor bodies, ground, horizon, labels and overlays."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def paintEvent(self, _event) -> None:
        vp = self._viewport()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        brightness = float(np.clip((self._sun_alt + 18.0) / 26.0, 0.0, 1.0)) if self.daylight_sky else 0.0
        sky = (tuple(np.interp(self._sun_alt, _SKY_ALT_STOPS, _SKY_RGB_STOPS[:, c]) for c in range(3))
               if self.daylight_sky else (3, 5, 12))
        p.fillRect(self.rect(), QColor(*(int(v) for v in sky)))

        if self.show_grid:
            self._draw_grid(p, vp)
        if self.show_boundaries:
            self._draw_boundaries(p, vp)
        if self.show_lines:
            self._draw_lines(p, vp)

        sets = self._sets(vp)
        self._draw_dsos(p, vp, sets["dsos"])
        self._draw_stars(p, sets["stars"])
        self._draw_bodies(p, sets["bodies"])
        self._draw_minor_bodies(p, sets["minor"])
        if self.show_ground:
            self._draw_ground(p, vp, brightness)
        if self.show_horizon and self._horizon is not None:
            self._draw_obstructions(p, vp)
        self._draw_horizon(p, vp)
        self._draw_labels(p, vp, sets)
        self._draw_selection(p, vp)
        self._draw_pier_markers(p, vp)
        self._draw_overlay(p)
        p.end()

    def _polyline(self, p: QPainter, x, y, vis) -> None:
        limit = max(self.width(), self.height())
        path = QPainterPath()
        pen_down = False
        px = py = 0.0
        for xi, yi, vi in zip(x.tolist(), y.tolist(), vis.tolist(), strict=True):
            if vi and (not pen_down or math.hypot(xi - px, yi - py) < limit):
                if pen_down:
                    path.lineTo(xi, yi)
                else:
                    path.moveTo(xi, yi)
                    pen_down = True
            else:
                pen_down = bool(vi)
                if vi:
                    path.moveTo(xi, yi)
            px, py = xi, yi
        p.drawPath(path)

    def _draw_grid(self, p: QPainter, vp) -> None:
        p.setPen(QPen(_GRID_COLOR, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        step = 15 if vp.fov_deg > 25 else 5
        decs = np.linspace(-90.0, 90.0, 181)
        for ra in range(0, 360, step):
            alt, az = sa.equatorial_to_horizontal(np.full_like(decs, float(ra)), decs, self._lst, self.latitude)
            x, y, vis = vp.project(alt, az)
            self._polyline(p, x, y, vis)
        ras = np.linspace(0.0, 360.0, 361)
        for dec in range(-75, 90, step if step == 5 else 15):
            alt, az = sa.equatorial_to_horizontal(ras, np.full_like(ras, float(dec)), self._lst, self.latitude)
            x, y, vis = vp.project(alt, az)
            self._polyline(p, x, y, vis)

    def _draw_boundaries(self, p: QPainter, vp) -> None:
        if len(self._bounds) == 0:
            return
        x, y, vis = vp.project(self._bnd_alt, self._bnd_az)
        p.setPen(QPen(_BOUNDARY_COLOR, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(len(self._bounds)):
            s = self._bounds.outline(i)
            xs, ys, vs = x[s], y[s], vis[s]
            if not (vs & (xs > -50) & (xs < vp.width + 50) & (ys > -50) & (ys < vp.height + 50)).any():
                continue        # nothing of this outline is on screen (edges may still cross, but only when zoomed out)
            self._polyline(p, xs, ys, vs)

    def _draw_lines(self, p: QPainter, vp) -> None:
        if len(self._lines) == 0:
            return
        x, y, vis = vp.project(self._line_alt, self._line_az)
        p.setPen(QPen(_LINES_COLOR, 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(len(self._lines)):
            s = self._lines.polyline(i)
            xs, ys, vs = x[s], y[s], vis[s]
            if not (vs & (xs > -50) & (xs < vp.width + 50) & (ys > -50) & (ys < vp.height + 50)).any():
                continue
            self._polyline(p, xs, ys, vs)

    def _draw_stars(self, p: QPainter, star_set) -> None:
        idx, xs, ys = star_set
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 240))
        mags = self._stars.mag[idx]
        for m, x, y in zip(mags.tolist(), xs.tolist(), ys.tolist(), strict=True):
            r = self._star_radius(m)
            p.drawEllipse(QPointF(x, y), r, r)

    def _draw_dsos(self, p: QPainter, vp, dso_set) -> None:
        idx, xs, ys = dso_set
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_DSO_COLOR, 1))
        px_per_arcmin = vp.scale * 2.0 * math.tan(math.radians(1.0 / 60.0) / 2.0)
        for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist(), strict=True):
            d = self._dsos[i]
            r = float(min(40.0, max(3.5, d.size_arcmin * px_per_arcmin / 2.0)))
            kind = d.object_type.value
            if kind == "Galaxy":
                p.drawEllipse(QPointF(x, y), r * 1.3, r * 0.7)
            elif kind in ("OpenCluster", "GlobularCluster", "Cluster"):
                pen = QPen(_DSO_COLOR, 1, Qt.PenStyle.DashLine if kind == "OpenCluster" else Qt.PenStyle.SolidLine)
                p.setPen(pen)
                p.drawEllipse(QPointF(x, y), r, r)
                if kind == "GlobularCluster":
                    p.drawLine(QPointF(x - r, y), QPointF(x + r, y))
                    p.drawLine(QPointF(x, y - r), QPointF(x, y + r))
                p.setPen(QPen(_DSO_COLOR, 1))
            elif kind == "PlanetaryNebula":
                p.drawEllipse(QPointF(x, y), r * 0.6, r * 0.6)
                p.drawLine(QPointF(x - r, y), QPointF(x - r * 0.6, y))
                p.drawLine(QPointF(x + r * 0.6, y), QPointF(x + r, y))
            else:
                p.drawRect(QRectF(x - r, y - r, 2 * r, 2 * r))

    def _draw_bodies(self, p: QPainter, body_set) -> None:
        idx, xs, ys = body_set
        for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist(), strict=True):
            name = self._bodies[i]["name"]
            if name == "Sun":
                p.setPen(QPen(QColor(255, 235, 150), 2))
                p.setBrush(QColor(255, 220, 90))
                p.drawEllipse(QPointF(x, y), 8, 8)
            elif name == "Moon":
                p.setPen(QPen(QColor(200, 200, 205), 1))
                p.setBrush(QColor(225, 225, 230))
                p.drawEllipse(QPointF(x, y), 8, 8)
            else:
                p.setPen(QPen(QColor(255, 255, 255), 1))
                p.setBrush(_BODY_COLOR)
                r = float(min(6.0, max(2.5, 3.0 - 0.4 * self._bodies[i]["mag"])))
                p.drawEllipse(QPointF(x, y), r, r)

    def _draw_minor_bodies(self, p: QPainter, minor_set) -> None:
        """Comets (a dot in a soft coma), asteroids (a small square) and satellites (a triangle, dim
        while in the Earth's shadow) - SKYMAP-040."""
        idx, xs, ys = minor_set
        for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist(), strict=True):
            body = self._minor[i]
            kind = body["kind"]
            if kind == mb.COMET:
                p.setPen(Qt.PenStyle.NoPen)
                halo = QColor(_COMET_COLOR)
                halo.setAlpha(70)
                p.setBrush(halo)
                p.drawEllipse(QPointF(x, y), 8, 8)
                p.setPen(QPen(_COMET_COLOR, 1.2))
                p.setBrush(_COMET_COLOR)
                p.drawEllipse(QPointF(x, y), 2.5, 2.5)
            elif kind == mb.ASTEROID:
                p.setPen(QPen(_ASTEROID_COLOR, 1))
                p.setBrush(_ASTEROID_COLOR)
                p.drawRect(QRectF(x - 2.5, y - 2.5, 5, 5))
            else:
                color = _SATELLITE_COLOR if body.get("sunlit", True) else _SATELLITE_ECLIPSED_COLOR
                p.setPen(QPen(color, 1))
                p.setBrush(color)
                tri = QPainterPath()
                tri.moveTo(x, y - 4)
                tri.lineTo(x + 3.6, y + 3)
                tri.lineTo(x - 3.6, y + 3)
                tri.closeSubpath()
                p.drawPath(tri)

    def _draw_ground(self, p: QPainter, vp, brightness: float) -> None:
        """Shade everything below the horizon, computed on a coarse pixel grid
        (the horizon is a circle in this projection, but not always one that
        fits the view, so the mask is built per pixel rather than as a path)."""
        cell = 3
        gw, gh = max(1, vp.width // cell), max(1, vp.height // cell)
        sx, sy = np.meshgrid((np.arange(gw) + 0.5) * cell, (np.arange(gh) + 0.5) * cell)
        alt, _ = vp.unproject(sx, sy)
        below = alt < 0.0
        r, g, b = (int(12 + 40 * brightness), int(16 + 46 * brightness), int(14 + 38 * brightness))
        arr = np.zeros((gh, gw, 4), dtype=np.uint8)
        arr[below] = (b, g, r, 238)          # Format_ARGB32 is BGRA in memory (little-endian)
        img = QImage(arr.data, gw, gh, gw * 4, QImage.Format.Format_ARGB32).copy()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(QRectF(0, 0, gw * cell, gh * cell), img)

    def _draw_obstructions(self, p: QPainter, vp) -> None:
        """Shade the sky between the horizon and the obstruction altitude at each
        azimuth in translucent red, on the same coarse pixel grid as the ground."""
        cell = 2
        gw, gh = max(1, vp.width // cell), max(1, vp.height // cell)
        sx, sy = np.meshgrid((np.arange(gw) + 0.5) * cell, (np.arange(gh) + 0.5) * cell)
        alt, az = vp.unproject(sx, sy)
        horizon = self._horizon
        if horizon is None:
            return
        blocked = (alt >= 0.0) & (alt < horizon.min_altitudes(az))
        r, g, b, a = _OBSTRUCTION_RGBA
        arr = np.zeros((gh, gw, 4), dtype=np.uint8)
        arr[blocked] = (b, g, r, a)          # Format_ARGB32 is BGRA in memory (little-endian)
        img = QImage(arr.data, gw, gh, gw * 4, QImage.Format.Format_ARGB32).copy()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(QRectF(0, 0, gw * cell, gh * cell), img)

    def _draw_horizon(self, p: QPainter, vp) -> None:
        az = np.linspace(0.0, 360.0, 361)
        x, y, vis = vp.project(np.zeros_like(az), az)
        p.setPen(QPen(_HORIZON_COLOR, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        self._polyline(p, x, y, vis)
        font = QFont(p.font())
        font.setBold(True)
        p.setFont(font)
        p.setPen(_HORIZON_COLOR)
        for label, a in (("N", 0), ("NE", 45), ("E", 90), ("SE", 135), ("S", 180), ("SW", 225), ("W", 270), ("NW", 315)):
            lx, ly, lv = vp.project(np.array([2.5]), np.array([float(a)]))
            if lv[0] and 0 <= lx[0] <= vp.width and 0 <= ly[0] <= vp.height:
                p.drawText(QPointF(lx[0] - 5, ly[0]), label)

    def _label_limit(self, vp) -> float:
        return min(self.mag_limit, 2.0 + 1.5 * math.log2(max(1.0, 100.0 / vp.fov_deg)))

    def _draw_labels(self, p: QPainter, vp, sets) -> None:
        if not self.show_labels:
            return
        font = QFont(p.font())
        font.setPointSizeF(8.5)
        font.setBold(False)
        p.setFont(font)
        p.setPen(_LABEL_COLOR)
        limit = self._label_limit(vp)
        idx, xs, ys = sets["stars"]
        for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist(), strict=True):
            if self._stars.mag[i] > limit:
                continue
            text = self._stars.names[i] or (self._stars.designations[i] if vp.fov_deg < 30 else "")
            if text:
                p.drawText(QPointF(x + self._star_radius(self._stars.mag[i]) + 3, y - 2), text)
        p.setPen(_DSO_COLOR)
        idx, xs, ys = sets["dsos"]       # every drawn deep-sky object is labelled
        for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist(), strict=True):
            p.drawText(QPointF(x + 7, y - 4), self._dsos[i].primary_name)
        p.setPen(_BODY_COLOR)
        idx, xs, ys = sets["bodies"]
        for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist(), strict=True):
            p.drawText(QPointF(x + 10, y - 4), self._bodies[i]["name"])
        idx, xs, ys = sets["minor"]
        for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist(), strict=True):
            body = self._minor[i]
            if body["kind"] == mb.ASTEROID and (vp.fov_deg > 40.0 or body["mag"] > 9.5):
                continue                    # hundreds of asteroids: label only the bright ones, zoomed in
            if body["kind"] == mb.SATELLITE and vp.fov_deg > 70.0:
                continue
            p.setPen({mb.COMET: _COMET_COLOR, mb.ASTEROID: _ASTEROID_COLOR}.get(body["kind"], _SATELLITE_COLOR))
            p.drawText(QPointF(x + 8, y - 4), body["name"])
        if len(self._bounds):       # names don't depend on the boundary lines being shown
            self._draw_constellation_names(p, vp)

    def _draw_constellation_names(self, p: QPainter, vp) -> None:
        x, y, vis = vp.project(self._bnd_center_alt, self._bnd_center_az)
        p.setPen(_CONSTELLATION_LABEL_COLOR)
        metrics = p.fontMetrics()
        for i, name in enumerate(self._bounds.names):
            if not vis[i] or (self._bnd_center_alt[i] < -0.5 and self.show_ground):
                continue
            if 0 <= x[i] <= vp.width and 0 <= y[i] <= vp.height:
                text = self._bounds.codes[i] if self.abbreviate_constellations else name.upper()
                p.drawText(QPointF(x[i] - metrics.horizontalAdvance(text) / 2.0, y[i]), text)

    def _draw_selection(self, p: QPainter, vp) -> None:
        for obj, color in ((self.selected, _SELECT_COLOR), (self.tracked, QColor(255, 255, 255, 120))):
            if obj is None:
                continue
            alt, az = self._altaz_of(obj)
            x, y, vis = vp.project(np.array([alt]), np.array([az]))
            if vis[0]:
                p.setPen(QPen(color, 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(x[0], y[0]), 14, 14)

    def _draw_pier_markers(self, p: QPainter, vp) -> None:
        """Draw each Pier's telescope reticle (SKYMAP-090). A mount that is slewing is drawn in
        the slewing colour with a line to its target, so the reticle can be watched crossing the
        sky as the slew runs."""
        if not self.show_pier_markers:
            return
        font = QFont(p.font())
        font.setPointSizeF(8.5)
        font.setBold(True)
        p.setFont(font)
        for marker in self.pier_markers:
            here = self._marker_point(vp, marker)
            if here is None:
                continue
            slewing = bool(marker.get("slewing"))
            color = _PIER_SLEWING_COLOR if slewing else _PIER_COLOR
            target = marker.get("target")
            there = self._marker_point(vp, target) if target else None
            if there is not None and math.hypot(there[0] - here[0], there[1] - here[1]) > 4:
                # Where it is headed, and the path still to go.
                p.setPen(QPen(_PIER_TARGET_COLOR, 1.0, Qt.PenStyle.DotLine))
                p.drawLine(QPointF(*here), QPointF(*there))
                self._draw_reticle(p, there, _PIER_TARGET_COLOR, dashed=False, radius=8)
            self._draw_reticle(p, here, color, dashed=slewing)
            if self.show_fov and marker.get("fov"):
                self._draw_fov(p, vp, marker, color)
            label = str(marker.get("label") or "")
            if label:
                p.setPen(color)
                p.drawText(QPointF(here[0] + 20, here[1] - 8), label)

    def _draw_fov(self, p: QPainter, vp, marker: dict[str, Any], color: QColor) -> None:
        """The telescope's field-of-view rectangle around its pointing position (SKYMAP-050),
        from the same ``FOV`` the Framing Assistant computes (FRAME-010). Drawn only once it is big
        enough on screen to read as a rectangle rather than a dot inside the reticle."""
        from galileo.planning.framing import fov_outline_radec

        fov = marker["fov"]
        try:
            ra, dec = fov_outline_radec(float(marker["ra_deg"]), float(marker["dec_deg"]),
                                        float(fov["width_deg"]), float(fov["height_deg"]),
                                        float(fov.get("rotation_deg", 0.0)))
        except (KeyError, TypeError, ValueError):
            return
        alt, az = self._altaz_arrays(ra, dec)
        x, y, vis = vp.project(alt, az)
        if not vis.all() or (x.max() - x.min() < 6 and y.max() - y.min() < 6):
            return
        p.setPen(QPen(color, 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        self._polyline(p, x, y, vis)

    def _marker_point(self, vp, marker) -> tuple[float, float] | None:
        """Screen position of a marker's J2000 coordinates, or ``None`` if it isn't in view."""
        if not marker:
            return None
        try:
            alt, az = self._altaz_arrays(np.array([float(marker["ra_deg"])]), np.array([float(marker["dec_deg"])]))
        except (KeyError, TypeError, ValueError):
            return None
        x, y, vis = vp.project(alt, az)
        return (float(x[0]), float(y[0])) if vis[0] else None

    @staticmethod
    def _draw_reticle(p: QPainter, point: tuple[float, float], color: QColor,
                      dashed: bool = False, radius: float = 13.0) -> None:
        """A circle with four ticks and a gap in the middle, so what it is on stays visible."""
        x, y = point
        pen = QPen(color, 1.6)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(x, y), radius, radius)
        p.setPen(QPen(color, 1.6))
        inner, outer = radius * 0.45, radius * 1.5
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p.drawLine(QPointF(x + dx * inner, y + dy * inner), QPointF(x + dx * outer, y + dy * outer))

    def _draw_overlay(self, p: QPainter) -> None:
        font = QFont(p.font())
        font.setPointSizeF(8.5)
        font.setBold(False)
        p.setFont(font)
        p.setPen(QColor(220, 230, 240, 200))
        p.drawText(QPointF(10, 18), f"Alt {self.view.alt0:.1f}°  Az {self.view.az0:.1f}°  ·  FOV {self.view.fov_deg:.1f}°")
        p.drawText(QPointF(10, self.height() - 10), self._cursor_text())
