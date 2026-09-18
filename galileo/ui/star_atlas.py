"""Star Atlas view — a basic planetarium widget (SKYMAP-010, SKYMAP-020).

Draws the sky above the configured location at a chosen time: stars from the
Bright Star Catalogue, deep-sky objects from the Sky Atlas catalog, and the
Sun, Moon and planets, in a stereographic projection with pan (drag), zoom
(wheel), click-to-identify and double-click-to-centre-and-track. The sky
maths lives in :mod:`galileo.planning.star_atlas`; this module only draws.
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
import threading
from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from galileo.planning import star_atlas as sa

logger = logging.getLogger(__name__)

# Sky colour by the Sun's altitude (degrees): night → twilight → day.
_SKY_ALT_STOPS = [-18.0, -12.0, -6.0, 0.0, 8.0]
_SKY_RGB_STOPS = np.array([(3, 5, 12), (8, 14, 32), (30, 45, 85), (90, 120, 170), (110, 165, 225)], dtype=float)

_GRID_COLOR = QColor(70, 110, 160, 110)
_HORIZON_COLOR = QColor(200, 170, 90, 200)
_LABEL_COLOR = QColor(170, 195, 225)
_BOUNDARY_COLOR = QColor(190, 130, 210, 170)
_CONSTELLATION_LABEL_COLOR = QColor(190, 140, 215, 200)
_DSO_COLOR = QColor(120, 200, 150)
_BODY_COLOR = QColor(255, 214, 120)
_SELECT_COLOR = QColor(255, 90, 90)

MAX_MAG_LIMIT = 7.0


def format_ra(deg: float) -> str:
    total = (deg % 360.0) / 15.0 * 3600.0
    return f"{int(total // 3600):02d}h {int(total % 3600 // 60):02d}m {total % 60:04.1f}s"


def format_dec(deg: float) -> str:
    sign = "-" if deg < 0 else "+"
    total = abs(deg) * 3600.0
    return f"{sign}{int(total // 3600):02d}° {int(total % 3600 // 60):02d}′ {total % 60:02.0f}″"


class StarAtlasView(QWidget):
    """Interactive sky view. Signals: ``objectSelected(dict)`` when an object is
    clicked or found; ``viewChanged()`` after any pan/zoom/time change;
    ``catalogsLoaded(stars, dsos)`` once the background catalog load finishes."""

    objectSelected = Signal(dict)
    viewChanged = Signal()
    catalogsLoaded = Signal(int, int)
    _catalogsReady = Signal(object, object, object)

    LIVE_INTERVAL_MS = 10_000
    HIT_RADIUS_PX = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.latitude = 0.0
        self.longitude = 0.0
        self.when = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)

        # Display options (toggled from the page).
        self.mag_limit = 5.5
        self.dso_mag_limit = 9.0
        self.show_grid = True
        self.show_boundaries = True
        self.show_dsos = True
        self.show_bodies = True
        self.show_labels = True
        self.show_ground = True
        self.daylight_sky = True

        self.view = sa.Viewport()
        self.selected: dict[str, Any] | None = None
        self.tracked: dict[str, Any] | None = None

        self._stars: sa.StarCatalog = sa._fallback_catalog()
        self._dsos: list = []
        self._bounds: sa.ConstellationBoundaries = sa.ConstellationBoundaries.empty()
        self._dso_ra = self._dso_dec = self._dso_mag = np.empty(0)
        self._bodies: list[dict[str, Any]] = []
        self._sun_alt = -30.0
        self._lst = 0.0
        self._jd = 0.0
        self._cursor: tuple[float, float] | None = None
        self._press_pos: QPointF | None = None
        self._dragging = False

        self._live = QTimer(self)
        self._live.setInterval(self.LIVE_INTERVAL_MS)
        self._live.timeout.connect(self._tick_live)
        self._catalogsReady.connect(self._on_catalogs)

        self._recompute()

    # -- public API ----------------------------------------------------------

    def load_catalogs(self) -> None:
        """Load the star and deep-sky catalogs off the UI thread (the first run
        fetches the star catalog from VizieR, which can take a few seconds)."""
        def work() -> None:
            try:
                stars = sa.load_star_catalog()
            except Exception:
                logger.exception("Could not load the star catalog")
                stars = sa._fallback_catalog()
            try:
                from galileo.planning.sky_atlas import SkyAtlas
                dsos = SkyAtlas().search("")
            except Exception:
                logger.exception("Could not load the deep-sky catalog")
                dsos = []
            try:
                bounds = sa.load_constellation_boundaries()
            except Exception:
                logger.exception("Could not load the constellation boundaries")
                bounds = sa.ConstellationBoundaries.empty()
            try:
                self._catalogsReady.emit(stars, dsos, bounds)
            except RuntimeError:
                pass  # widget was destroyed while loading
        threading.Thread(target=work, name="star-atlas-catalogs", daemon=True).start()

    def set_catalogs(self, stars: "sa.StarCatalog", dsos: list,
                     boundaries: "sa.ConstellationBoundaries | None" = None) -> None:
        self._stars = stars
        self._bounds = boundaries if boundaries is not None else sa.ConstellationBoundaries.empty()
        self._dsos = [d for d in dsos if d.magnitude < 90.0]
        self._dso_ra = np.array([d.ra_deg for d in self._dsos])
        self._dso_dec = np.array([d.dec_deg for d in self._dsos])
        self._dso_mag = np.array([d.magnitude for d in self._dsos])
        self._recompute()
        self.update()

    def set_location(self, latitude: float, longitude: float) -> None:
        self.latitude, self.longitude = latitude, longitude
        self._recompute()
        self._after_change()

    def set_time(self, when_utc: _dt.datetime) -> None:
        self.when = when_utc.replace(tzinfo=None) if when_utc.tzinfo is None else when_utc.astimezone(
            _dt.timezone.utc).replace(tzinfo=None)
        self._recompute()
        self._after_change()

    def set_live(self, live: bool) -> None:
        if live:
            self._tick_live()
            self._live.start()
        else:
            self._live.stop()

    def set_option(self, name: str, value: Any) -> None:
        setattr(self, name, value)
        self.update()

    def set_fov(self, fov_deg: float) -> None:
        self.view.fov_deg = float(np.clip(fov_deg, 0.5, 150.0))
        self._after_change()

    def center_on_altaz(self, alt: float, az: float) -> None:
        self.view.alt0 = float(np.clip(alt, -10.0, 90.0))
        self.view.az0 = az % 360.0
        self._after_change()

    def center_on(self, obj: dict[str, Any], track: bool = False) -> None:
        alt, az = self._altaz_of(obj)
        self.tracked = obj if track else None
        self.center_on_altaz(alt, az)

    def select(self, obj: dict[str, Any] | None) -> None:
        self.selected = obj
        self.update()
        if obj is not None:
            self.objectSelected.emit(obj)

    def find(self, query: str) -> dict[str, Any] | None:
        """Look an object up by name across bodies, stars and deep-sky objects."""
        q = query.strip().lower()
        if not q:
            return None
        for i, body in enumerate(self._bodies):
            if body["name"].lower() == q:
                return self._body_object(i)
        best = None
        for i in range(len(self._stars)):
            names = (self._stars.names[i].lower(), self._stars.designations[i].lower())
            if q in names or any(n and q in n for n in names):
                if best is None or self._stars.mag[i] < self._stars.mag[best]:
                    best = i
        if best is not None:
            return self._star_object(best)
        for i, dso in enumerate(self._dsos):
            if q == dso.primary_name.lower() or q in (d.lower() for d in dso.designations):
                return self._dso_object(i)
        for i, dso in enumerate(self._dsos):
            if q in dso.primary_name.lower():
                return self._dso_object(i)
        return None

    # -- sky computation -----------------------------------------------------

    def _recompute(self) -> None:
        """Recompute the horizontal coordinates of everything for the current time/place."""
        self._jd = sa.julian_date(self.when)
        self._lst = sa.local_sidereal_deg(self._jd, self.longitude)
        self._star_alt, self._star_az = self._altaz_arrays(self._stars.ra, self._stars.dec)
        self._dso_alt, self._dso_az = self._altaz_arrays(self._dso_ra, self._dso_dec)
        self._bnd_alt, self._bnd_az = self._altaz_arrays(self._bounds.ra, self._bounds.dec)
        self._bnd_center_alt, self._bnd_center_az = self._altaz_arrays(self._bounds.center_ra, self._bounds.center_dec)
        self._bodies = sa.solar_system_positions(self.when)
        if self._bodies:
            ra = np.array([b["ra_deg"] for b in self._bodies])
            dec = np.array([b["dec_deg"] for b in self._bodies])
            alt, az = self._altaz_arrays(ra, dec)
            for b, a, z in zip(self._bodies, alt, az):
                b["alt"], b["az"] = float(a), float(z)
            self._sun_alt = next((b["alt"] for b in self._bodies if b["name"] == "Sun"), -30.0)
        else:
            self._sun_alt = -30.0
        self._body_alt = np.array([b["alt"] for b in self._bodies])
        self._body_az = np.array([b["az"] for b in self._bodies])

    def _altaz_arrays(self, ra, dec):
        if len(ra) == 0:
            return np.empty(0), np.empty(0)
        ra_d, dec_d = sa.precess_from_j2000(ra, dec, self._jd)
        return sa.equatorial_to_horizontal(ra_d, dec_d, self._lst, self.latitude)

    def _altaz_of(self, obj: dict[str, Any]) -> tuple[float, float]:
        if obj.get("kind") == "body":
            for b in self._bodies:
                if b["name"] == obj["name"]:
                    return b["alt"], b["az"]
        alt, az = self._altaz_arrays(np.array([obj["ra_deg"]]), np.array([obj["dec_deg"]]))
        return float(alt[0]), float(az[0])

    def _after_change(self) -> None:
        if self.tracked is not None:
            alt, az = self._altaz_of(self.tracked)
            self.view.alt0, self.view.az0 = float(np.clip(alt, -10.0, 90.0)), az % 360.0
        self.update()
        self.viewChanged.emit()

    def _tick_live(self) -> None:
        self.set_time(_dt.datetime.now(_dt.timezone.utc))

    def _on_catalogs(self, stars, dsos, bounds) -> None:
        self.set_catalogs(stars, dsos, bounds)
        self.catalogsLoaded.emit(len(self._stars), len(self._dsos))

    def effective_mag_limit(self) -> float:
        """Faintest star drawn: the setting, brought down as the Sun rises."""
        if not self.daylight_sky:
            return self.mag_limit
        washout = float(np.clip((self._sun_alt + 12.0) / 12.0, 0.0, 1.0))
        return self.mag_limit - washout * (self.mag_limit + 2.0)

    # -- object records ------------------------------------------------------

    def _star_object(self, i: int) -> dict[str, Any]:
        return {"kind": "star", "name": self._stars.label(i), "designation": self._stars.designations[i],
                "type": "Star", "ra_deg": float(self._stars.ra[i]), "dec_deg": float(self._stars.dec[i]),
                "mag": float(self._stars.mag[i]), "alt": float(self._star_alt[i]), "az": float(self._star_az[i])}

    def _dso_object(self, i: int) -> dict[str, Any]:
        d = self._dsos[i]
        return {"kind": "dso", "name": d.primary_name, "designation": ", ".join(d.designations[:3]),
                "type": d.object_type.value, "ra_deg": d.ra_deg, "dec_deg": d.dec_deg, "mag": d.magnitude,
                "size_arcmin": d.size_arcmin, "alt": float(self._dso_alt[i]), "az": float(self._dso_az[i])}

    def _body_object(self, i: int) -> dict[str, Any]:
        b = self._bodies[i]
        kind = "Sun" if b["name"] == "Sun" else "Moon" if b["name"] == "Moon" else "Planet"
        return {"kind": "body", "name": b["name"], "designation": "", "type": kind, "ra_deg": b["ra_deg"],
                "dec_deg": b["dec_deg"], "mag": b["mag"], "alt": b["alt"], "az": b["az"]}

    # -- projection of the visible sets --------------------------------------

    def _viewport(self) -> "sa.Viewport":
        self.view.width, self.view.height = max(1, self.width()), max(1, self.height())
        return self.view

    def _visible(self, alt, az, mask, vp) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(indices, x, y) of the *mask*-selected items that land inside the view."""
        if len(alt) == 0:
            return np.empty(0, dtype=int), np.empty(0), np.empty(0)
        x, y, vis = vp.project(alt, az)
        margin = 20
        inside = vis & mask & (x > -margin) & (x < vp.width + margin) & (y > -margin) & (y < vp.height + margin)
        if self.show_ground:
            inside &= alt > -0.5
        idx = np.nonzero(inside)[0]
        return idx, x[idx], y[idx]

    def _sets(self, vp) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
        sets = {"stars": self._visible(self._star_alt, self._star_az, self._stars.mag <= self.effective_mag_limit(), vp)}
        sets["dsos"] = (self._visible(self._dso_alt, self._dso_az, self._dso_mag <= self.dso_mag_limit, vp)
                        if self.show_dsos else (np.empty(0, dtype=int), np.empty(0), np.empty(0)))
        sets["bodies"] = (self._visible(self._body_alt, self._body_az, np.ones(len(self._bodies), dtype=bool), vp)
                          if self.show_bodies else (np.empty(0, dtype=int), np.empty(0), np.empty(0)))
        return sets

    def _star_radius(self, mag: float) -> float:
        return float(min(9.0, max(0.7, 0.6 + 0.5 * (self.mag_limit - mag))))

    # -- painting ------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802 — Qt override
        vp = self._viewport()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        brightness = float(np.clip((self._sun_alt + 18.0) / 26.0, 0.0, 1.0)) if self.daylight_sky else 0.0
        sky = (tuple(np.interp(self._sun_alt, _SKY_ALT_STOPS, _SKY_RGB_STOPS[:, c]) for c in range(3))
               if self.daylight_sky else (3, 5, 12))
        p.fillRect(self.rect(), QColor(*(int(v) for v in sky)))

        if self.show_grid:
            self._draw_grid(p, vp)
        if self.show_boundaries:
            self._draw_boundaries(p, vp)

        sets = self._sets(vp)
        self._draw_dsos(p, vp, sets["dsos"])
        self._draw_stars(p, sets["stars"])
        self._draw_bodies(p, sets["bodies"])
        if self.show_ground:
            self._draw_ground(p, vp, brightness)
        self._draw_horizon(p, vp)
        self._draw_labels(p, vp, sets)
        self._draw_selection(p, vp)
        self._draw_overlay(p)
        p.end()

    def _polyline(self, p: QPainter, x, y, vis) -> None:
        limit = max(self.width(), self.height())
        path = QPainterPath()
        pen_down = False
        px = py = 0.0
        for xi, yi, vi in zip(x.tolist(), y.tolist(), vis.tolist()):
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
        p.setBrush(Qt.NoBrush)
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
        p.setBrush(Qt.NoBrush)
        for i in range(len(self._bounds)):
            s = self._bounds.outline(i)
            xs, ys, vs = x[s], y[s], vis[s]
            if not (vs & (xs > -50) & (xs < vp.width + 50) & (ys > -50) & (ys < vp.height + 50)).any():
                continue        # nothing of this outline is on screen (edges may still cross, but only when zoomed out)
            self._polyline(p, xs, ys, vs)

    def _draw_stars(self, p: QPainter, star_set) -> None:
        idx, xs, ys = star_set
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 240))
        mags = self._stars.mag[idx]
        for m, x, y in zip(mags.tolist(), xs.tolist(), ys.tolist()):
            r = self._star_radius(m)
            p.drawEllipse(QPointF(x, y), r, r)

    def _draw_dsos(self, p: QPainter, vp, dso_set) -> None:
        idx, xs, ys = dso_set
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_DSO_COLOR, 1))
        px_per_arcmin = vp.scale * 2.0 * math.tan(math.radians(1.0 / 60.0) / 2.0)
        for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist()):
            d = self._dsos[i]
            r = float(min(40.0, max(3.5, d.size_arcmin * px_per_arcmin / 2.0)))
            kind = d.object_type.value
            if kind == "Galaxy":
                p.drawEllipse(QPointF(x, y), r * 1.3, r * 0.7)
            elif kind in ("OpenCluster", "GlobularCluster", "Cluster"):
                pen = QPen(_DSO_COLOR, 1, Qt.DashLine if kind == "OpenCluster" else Qt.SolidLine)
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
        for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist()):
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
        img = QImage(arr.data, gw, gh, gw * 4, QImage.Format_ARGB32).copy()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(QRectF(0, 0, gw * cell, gh * cell), img)

    def _draw_horizon(self, p: QPainter, vp) -> None:
        az = np.linspace(0.0, 360.0, 361)
        x, y, vis = vp.project(np.zeros_like(az), az)
        p.setPen(QPen(_HORIZON_COLOR, 1.5))
        p.setBrush(Qt.NoBrush)
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
        for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist()):
            if self._stars.mag[i] > limit:
                continue
            text = self._stars.names[i] or (self._stars.designations[i] if vp.fov_deg < 30 else "")
            if text:
                p.drawText(QPointF(x + self._star_radius(self._stars.mag[i]) + 3, y - 2), text)
        p.setPen(_DSO_COLOR)
        if vp.fov_deg <= 60:
            idx, xs, ys = sets["dsos"]
            for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist()):
                if self._dso_mag[i] <= min(self.dso_mag_limit, 8.5):
                    p.drawText(QPointF(x + 7, y - 4), self._dsos[i].primary_name)
        p.setPen(_BODY_COLOR)
        idx, xs, ys = sets["bodies"]
        for i, x, y in zip(idx.tolist(), xs.tolist(), ys.tolist()):
            p.drawText(QPointF(x + 10, y - 4), self._bodies[i]["name"])
        if self.show_boundaries and len(self._bounds):
            self._draw_constellation_names(p, vp)

    def _draw_constellation_names(self, p: QPainter, vp) -> None:
        x, y, vis = vp.project(self._bnd_center_alt, self._bnd_center_az)
        p.setPen(_CONSTELLATION_LABEL_COLOR)
        metrics = p.fontMetrics()
        for i, name in enumerate(self._bounds.names):
            if not vis[i] or self._bnd_center_alt[i] < -0.5 and self.show_ground:
                continue
            if 0 <= x[i] <= vp.width and 0 <= y[i] <= vp.height:
                text = name.upper()
                p.drawText(QPointF(x[i] - metrics.horizontalAdvance(text) / 2.0, y[i]), text)

    def _draw_selection(self, p: QPainter, vp) -> None:
        for obj, color in ((self.selected, _SELECT_COLOR), (self.tracked, QColor(255, 255, 255, 120))):
            if obj is None:
                continue
            alt, az = self._altaz_of(obj)
            x, y, vis = vp.project(np.array([alt]), np.array([az]))
            if vis[0]:
                p.setPen(QPen(color, 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x[0], y[0]), 14, 14)

    def _draw_overlay(self, p: QPainter) -> None:
        font = QFont(p.font())
        font.setPointSizeF(8.5)
        font.setBold(False)
        p.setFont(font)
        p.setPen(QColor(220, 230, 240, 200))
        p.drawText(QPointF(10, 18), f"Alt {self.view.alt0:.1f}°  Az {self.view.az0:.1f}°  ·  FOV {self.view.fov_deg:.1f}°")
        p.drawText(QPointF(10, self.height() - 10), self._cursor_text())

    def _cursor_text(self) -> str:
        if self._cursor is None:
            return ""
        alt, az = self.view.unproject(*self._cursor)
        ra, dec = sa.horizontal_to_equatorial(float(alt), float(az), self._lst, self.latitude)
        return f"Alt {float(alt):.1f}°  Az {float(az):.1f}°   RA {format_ra(ra)}  Dec {format_dec(dec)}  (of date)"

    # -- interaction ---------------------------------------------------------

    def object_at(self, x: float, y: float) -> dict[str, Any] | None:
        """Nearest visible object within a few pixels of screen position (x, y)."""
        sets = self._sets(self._viewport())
        best, best_d = None, float(self.HIT_RADIUS_PX)
        makers = {"bodies": self._body_object, "stars": self._star_object, "dsos": self._dso_object}
        for key in ("bodies", "stars", "dsos"):      # bodies win ties, then stars, then DSOs
            idx, xs, ys = sets[key]
            if len(idx) == 0:
                continue
            d = np.hypot(xs - x, ys - y)
            j = int(np.argmin(d))
            if d[j] < best_d:
                best, best_d = makers[key](int(idx[j])), float(d[j])
        return best

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position()
            self._dragging = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        self._cursor = (pos.x(), pos.y())
        if self._press_pos is not None and event.buttons() & Qt.LeftButton:
            delta = pos - self._press_pos
            if not self._dragging and delta.manhattanLength() > 4:
                self._dragging = True
                self.tracked = None
            if self._dragging:
                deg_per_px = self.view.fov_deg / max(1, self.height())
                # Dragging the sky right brings what was to the left (lower azimuth) to the centre.
                self.view.az0 = (self.view.az0 - delta.x() * deg_per_px / max(0.25, math.cos(math.radians(self.view.alt0)))) % 360.0
                self.view.alt0 = float(np.clip(self.view.alt0 + delta.y() * deg_per_px, -10.0, 90.0))
                self._press_pos = pos
                self.viewChanged.emit()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._press_pos is not None:
            if not self._dragging:
                self.select(self.object_at(event.position().x(), event.position().y()))
            self._press_pos = None
            self._dragging = False

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            obj = self.object_at(event.position().x(), event.position().y())
            if obj is not None:
                self.select(obj)
                self.center_on(obj, track=True)

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._cursor = None
        self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.set_fov(self.view.fov_deg * (0.85 ** steps))
