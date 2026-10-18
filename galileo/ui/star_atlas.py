# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

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
import threading
from typing import TYPE_CHECKING, Any

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from galileo.planning import minor_bodies as mb
from galileo.planning import star_atlas as sa
from galileo.planning.sky_atlas import DSO_CATALOGS, catalogs_of
from galileo.ui.gc_guard import gc_paused
from galileo.ui.star_atlas_paint import (  # noqa: F401  (re-exported: constants/helpers that used to live in this module)
    StarAtlasPaintMixin,
    _ASTEROID_COLOR,
    _BODY_COLOR,
    _BOUNDARY_COLOR,
    _COMET_COLOR,
    _CONSTELLATION_LABEL_COLOR,
    _DSO_COLOR,
    _GRID_COLOR,
    _HORIZON_COLOR,
    _LABEL_COLOR,
    _LINES_COLOR,
    _OBSTRUCTION_RGBA,
    _PIER_COLOR,
    _PIER_SLEWING_COLOR,
    _PIER_TARGET_COLOR,
    _SATELLITE_COLOR,
    _SATELLITE_ECLIPSED_COLOR,
    _SELECT_COLOR,
    _SKY_ALT_STOPS,
    _SKY_RGB_STOPS,
)
from galileo.ui.star_atlas_input import (  # noqa: F401  (re-exported: constants/helpers that used to live in this module)
    StarAtlasInputMixin,
    format_dec,
    format_ra,
)

if TYPE_CHECKING:
    from galileo.planning.visibility import HorizonProfile

logger = logging.getLogger(__name__)


_FOV_COLOR = QColor(120, 225, 255, 230)

MAX_MAG_LIMIT = 7.0

# The on/off options the page offers as checkboxes. These and the chosen deep-sky
# catalogs are remembered between runs.
PERSISTED_TOGGLES = ("show_grid", "show_boundaries", "show_lines", "abbreviate_constellations",
                     "show_dsos", "show_bodies", "show_labels", "show_ground", "daylight_sky", "show_horizon",
                     "show_pier_markers", "show_fov", "show_comets", "show_asteroids", "show_satellites")

#: Display option -> the kind of orbital-element data it needs (downloaded on first use).
MINOR_BODY_TOGGLES = {"show_comets": mb.COMET, "show_asteroids": mb.ASTEROID, "show_satellites": mb.SATELLITE}


PREFS_NAMESPACE = "star_atlas"
_PREFS_LEGACY_FILE = "star_atlas.json"   # one-time import, then renamed *.migrated


def load_display_prefs() -> dict[str, Any]:
    """The remembered toggles and catalogs: ``{option: bool, ..., "dso_catalogs": [name, ...]}``.

    Missing, unreadable or unrecognised entries are left out so the view's defaults apply."""
    from galileo.settings_store import load_with_legacy
    raw = load_with_legacy(PREFS_NAMESPACE, _PREFS_LEGACY_FILE)
    prefs: dict[str, Any] = {k: raw[k] for k in PERSISTED_TOGGLES if isinstance(raw.get(k), bool)}
    if isinstance(raw.get("dso_catalogs"), list):
        prefs["dso_catalogs"] = [c for c in raw["dso_catalogs"] if c in DSO_CATALOGS]
    return prefs


def save_display_prefs(view: StarAtlasView) -> None:
    """Remember the view's toggles and deep-sky catalogs."""
    from galileo.settings_store import set_namespace
    data: dict[str, Any] = {k: bool(getattr(view, k)) for k in PERSISTED_TOGGLES}
    data["dso_catalogs"] = [c for c in DSO_CATALOGS if c in view.dso_catalogs]
    set_namespace(PREFS_NAMESPACE, data)


class StarAtlasView(StarAtlasInputMixin, StarAtlasPaintMixin, QWidget):
    """Interactive sky view. Signals: ``objectSelected(dict)`` when an object is
    clicked or found; ``viewChanged()`` after any pan/zoom/time change;
    ``catalogsLoaded(stars, dsos)`` once the background catalog load finishes."""

    objectSelected = Signal(dict)
    # Fires on every selection change — None when the selection is cleared, a dict when one is made.
    # objectSelected fires only for non-None; selectionChanged fires for both, so listeners can
    # react to deselection (e.g. disabling action buttons in the detail panel).
    selectionChanged = Signal(object)
    # Right-click: the object under the cursor (None over empty sky), the global position for a menu,
    # and the sky coords at the click (always a dict with ra_deg/dec_deg/alt/az, or None on error).
    contextMenuRequested = Signal(object, QPoint, object)
    viewChanged = Signal()
    catalogsLoaded = Signal(int, int)
    # (kind, number of orbits/TLEs loaded) once a comet/asteroid/satellite download finishes.
    minorBodiesLoaded = Signal(str, int)
    _catalogsReady = Signal(object, object, object, object)
    _minorReady = Signal(str, object)

    LIVE_INTERVAL_MS = 10_000
    HIT_RADIUS_PX = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.latitude = 0.0
        self.longitude = 0.0
        self.when = _dt.datetime.now(_dt.UTC).replace(tzinfo=None)

        # Display options (toggled from the page).
        self.mag_limit = 5.5
        self.dso_mag_limit = 9.0
        self.show_grid = True
        self.show_boundaries = True
        self.show_lines = True
        self.abbreviate_constellations = False
        self.show_dsos = True
        self.dso_catalogs: set[str] = {"Messier"}      # which of sky_atlas.DSO_CATALOGS are drawn
        self.show_bodies = True
        self.show_labels = True
        self.show_ground = True
        self.daylight_sky = True
        self.show_horizon = False       # shade the horizon obstructions (Options > Star Atlas)
        self._horizon: HorizonProfile | None = None
        # Telescope reticles, one per Pier (SKYMAP-090); the page refills these as the mounts move.
        self.show_pier_markers = True
        self.pier_markers: list[dict[str, Any]] = []
        self.show_fov = True            # the field-of-view rectangle around a marker that has one (SKYMAP-050)
        # Comets, asteroids and satellites (SKYMAP-040), downloaded when first switched on.
        self.show_comets = False
        self.show_asteroids = False
        self.show_satellites = False
        self._minor_data: dict[str, Any] = {}
        self._minor_loading: set[str] = set()
        self._minor: list[dict[str, Any]] = []
        self._minor_alt = self._minor_az = np.empty(0)
        self.elevation_m = 0.0

        self.view = sa.Viewport()
        self.selected: dict[str, Any] | None = None
        self.tracked: dict[str, Any] | None = None

        self._stars: sa.StarCatalog = sa._fallback_catalog()
        self._dsos: list = []
        self._bounds: sa.ConstellationBoundaries = sa.ConstellationBoundaries.empty()
        self._lines: sa.ConstellationLines = sa.ConstellationLines.empty()
        self._dso_ra = self._dso_dec = self._dso_mag = np.empty(0)
        self._dso_members: dict[str, np.ndarray] = {}
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
        self._minorReady.connect(self._on_minor_loaded)

        self._recompute()

    # -- public API ----------------------------------------------------------

    def load_catalogs(self) -> None:
        """Load the star and deep-sky catalogs off the UI thread (the first run
        fetches the star catalog from VizieR, which can take a few seconds)."""
        def work() -> None:
            with gc_paused():
                self._load_catalogs_paused()

        threading.Thread(target=work, name="star-atlas-catalogs", daemon=True).start()

    def _load_catalogs_paused(self) -> None:
        """The body of the catalog-loading thread (runs with the cyclic GC paused; see ``gc_guard``)."""
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
            lines = sa.load_constellation_lines()
        except Exception:
            logger.exception("Could not load the constellation lines")
            lines = sa.ConstellationLines.empty()
        try:
            self._catalogsReady.emit(stars, dsos, bounds, lines)
        except RuntimeError:
            pass  # widget was destroyed while loading

    def set_catalogs(self, stars: sa.StarCatalog, dsos: list,
                     boundaries: sa.ConstellationBoundaries | None = None,
                     lines: sa.ConstellationLines | None = None) -> None:
        self._stars = stars
        self._bounds = boundaries if boundaries is not None else sa.ConstellationBoundaries.empty()
        self._lines = lines if lines is not None else sa.ConstellationLines.empty()
        member_sets = [catalogs_of(d) for d in dsos]
        # An object with no known magnitude is dropped, unless it is in a curated
        # list (Messier / Caldwell — e.g. the Coalsack), where it is always shown.
        keep = [i for i, d in enumerate(dsos) if d.magnitude < 90.0 or member_sets[i] & {"Messier", "Caldwell"}]
        self._dsos = [dsos[i] for i in keep]
        self._dso_ra = np.array([d.ra_deg for d in self._dsos])
        self._dso_dec = np.array([d.dec_deg for d in self._dsos])
        self._dso_mag = np.array([d.magnitude if d.magnitude < 90.0 else 0.0 for d in self._dsos])
        self._dso_members = {cat: np.array([cat in member_sets[i] for i in keep], dtype=bool) for cat in DSO_CATALOGS}
        self._recompute()
        self.update()

    def dso_catalog_counts(self) -> dict[str, int]:
        """Number of loaded deep-sky objects in each catalog."""
        return {cat: int(mask.sum()) for cat, mask in self._dso_members.items()}

    def set_dso_catalogs(self, catalogs) -> None:
        """Choose which deep-sky catalogs are drawn."""
        self.dso_catalogs = set(catalogs)
        self.update()

    def _dso_selected(self) -> np.ndarray:
        selected = np.zeros(len(self._dsos), dtype=bool)
        for cat in self.dso_catalogs:
            if cat in self._dso_members:
                selected |= self._dso_members[cat]
        return selected

    def set_location(self, latitude: float, longitude: float) -> None:
        self.latitude, self.longitude = latitude, longitude
        self._recompute()
        self._after_change()

    def set_time(self, when_utc: _dt.datetime) -> None:
        self.when = when_utc.replace(tzinfo=None) if when_utc.tzinfo is None else when_utc.astimezone(
            _dt.UTC).replace(tzinfo=None)
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
        if name in MINOR_BODY_TOGGLES:
            self.refresh_minor_bodies()
        self.update()

    def refresh_minor_bodies(self) -> None:
        """Download the orbital elements of every enabled kind that isn't loaded yet (off the UI
        thread; cached on disk and refreshed when stale - SKYMAP-040), then recompute positions."""
        for option, kind in MINOR_BODY_TOGGLES.items():
            if getattr(self, option) and kind not in self._minor_data and kind not in self._minor_loading:
                self._minor_loading.add(kind)
                threading.Thread(target=self._load_minor, args=(kind,), name=f"star-atlas-{kind.lower()}",
                                 daemon=True).start()
        self._recompute_minor()

    def _load_minor(self, kind: str) -> None:
        with gc_paused():
            try:
                data = mb.load_satellites() if kind == mb.SATELLITE else mb.load_orbits(kind)
            except Exception:
                logger.exception("Could not load %s elements", kind)
                data = None
            try:
                self._minorReady.emit(kind, data)
            except RuntimeError:
                pass  # widget was destroyed while loading

    def _on_minor_loaded(self, kind: str, data) -> None:
        self._minor_loading.discard(kind)
        if data is not None:
            self._minor_data[kind] = data
        self._recompute_minor()
        self.update()
        self.minorBodiesLoaded.emit(kind, 0 if data is None else len(data))

    def set_pier_markers(self, markers: list[dict[str, Any]]) -> None:
        """Show a reticle for each Pier (SKYMAP-090). Each marker is a dict with J2000
        ``ra_deg``/``dec_deg``, a ``label``, and optional ``slewing`` (drawn dashed and in a
        different colour) and ``target`` (the J2000 position it is slewing to, drawn as a fainter
        reticle joined to the telescope's by a line). Replaces whatever was shown before."""
        self.pier_markers = list(markers)
        self.update()

    def set_horizon(self, horizon: HorizonProfile | None) -> None:
        """The obstruction horizon to shade when ``show_horizon`` is on (``None`` for none)."""
        self._horizon = horizon if horizon is not None and horizon.points else None
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
        self.selectionChanged.emit(obj)

    def find_object(self, query: str) -> dict[str, Any] | None:
        """Look an object up by name across bodies, stars and deep-sky objects."""
        q = query.strip().lower()
        if not q:
            return None
        for i, body in enumerate(self._bodies):
            if body["name"].lower() == q:
                return self._body_object(i)
        for i, body in enumerate(self._minor):
            if q in body["name"].lower():
                return self._minor_object(i)
        best = None
        for i in range(len(self._stars)):
            names = (self._stars.names[i].lower(), self._stars.designations[i].lower())
            if (q in names or any(n and q in n for n in names)) and (best is None or self._stars.mag[i] < self._stars.mag[best]):
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
        self._line_alt, self._line_az = self._altaz_arrays(self._lines.ra, self._lines.dec)
        self._bnd_center_alt, self._bnd_center_az = self._altaz_arrays(self._bounds.center_ra, self._bounds.center_dec)
        self._bodies = sa.solar_system_positions(self.when)
        if self._bodies:
            ra = np.array([b["ra_deg"] for b in self._bodies])
            dec = np.array([b["dec_deg"] for b in self._bodies])
            alt, az = self._altaz_arrays(ra, dec)
            for b, a, z in zip(self._bodies, alt, az, strict=True):
                b["alt"], b["az"] = float(a), float(z)
            self._sun_alt = next((b["alt"] for b in self._bodies if b["name"] == "Sun"), -30.0)
        else:
            self._sun_alt = -30.0
        self._body_alt = np.array([b["alt"] for b in self._bodies])
        self._body_az = np.array([b["az"] for b in self._bodies])
        self._recompute_minor()

    def _recompute_minor(self) -> None:
        """Positions of the enabled comets, asteroids and satellites at the view's time and place."""
        found: list[dict[str, Any]] = []
        try:
            for option, kind in MINOR_BODY_TOGGLES.items():
                data = self._minor_data.get(kind)
                if not getattr(self, option) or data is None:
                    continue
                if kind == mb.SATELLITE:
                    found += mb.satellite_positions(data, self.when, self.latitude, self.longitude, self.elevation_m)
                else:
                    found += mb.minor_body_positions(data, self.when)
        except Exception:
            logger.exception("Could not compute comet/asteroid/satellite positions")
            found = []
        self._minor = found
        if found:
            self._minor_alt, self._minor_az = self._altaz_arrays(
                np.array([b["ra_deg"] for b in found]), np.array([b["dec_deg"] for b in found]))
        else:
            self._minor_alt = self._minor_az = np.empty(0)

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
        if obj.get("kind") == "minor":
            for b, alt, az in zip(self._minor, self._minor_alt, self._minor_az, strict=True):
                if b["name"] == obj["name"]:      # these move; the live position beats the one captured on click
                    return float(alt), float(az)
        alt, az = self._altaz_arrays(np.array([obj["ra_deg"]]), np.array([obj["dec_deg"]]))
        return float(alt[0]), float(az[0])

    def _after_change(self) -> None:
        if self.tracked is not None:
            alt, az = self._altaz_of(self.tracked)
            self.view.alt0, self.view.az0 = float(np.clip(alt, -10.0, 90.0)), az % 360.0
        self.update()
        self.viewChanged.emit()

    def _tick_live(self) -> None:
        self.set_time(_dt.datetime.now(_dt.UTC))

    def _on_catalogs(self, stars, dsos, bounds, lines) -> None:
        self.set_catalogs(stars, dsos, bounds, lines)
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

    def _minor_object(self, i: int) -> dict[str, Any]:
        b = self._minor[i]
        return {"kind": "minor", "name": b["name"], "designation": "", "type": b["kind"], "ra_deg": b["ra_deg"],
                "dec_deg": b["dec_deg"], "mag": b["mag"], "alt": float(self._minor_alt[i]),
                "az": float(self._minor_az[i])}

    # -- projection of the visible sets --------------------------------------

    def _viewport(self) -> sa.Viewport:
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
        sets["dsos"] = (self._visible(self._dso_alt, self._dso_az,
                                    (self._dso_mag <= self.dso_mag_limit) & self._dso_selected(), vp)
                        if self.show_dsos else (np.empty(0, dtype=int), np.empty(0), np.empty(0)))
        sets["bodies"] = (self._visible(self._body_alt, self._body_az, np.ones(len(self._bodies), dtype=bool), vp)
                          if self.show_bodies else (np.empty(0, dtype=int), np.empty(0), np.empty(0)))
        sets["minor"] = self._visible(self._minor_alt, self._minor_az, np.ones(len(self._minor), dtype=bool), vp)
        return sets

    def _star_radius(self, mag: float) -> float:
        return float(min(9.0, max(0.7, 0.6 + 0.5 * (self.mag_limit - mag))))

    # -- painting ------------------------------------------------------------


    # -- interaction ---------------------------------------------------------


