# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Comets, asteroids and artificial satellites for the Star Atlas (SKYMAP-040).

Orbital elements come from public services and are cached on disk, refreshed
when the cache is older than ``MAX_AGE`` (elements drift, so a stale cache is
still used if the refresh fails):

* comets and asteroids — JPL Small-Body Database query API (JSON);
* satellites — CelesTrak two-line elements (the "visual" group: the brightest
  ones, including the ISS), propagated with SGP4.

Everything is plain numpy — no Qt — so it can be tested without a display.
Positions are geocentric J2000 for comets and asteroids and topocentric J2000
for satellites (a low orbit shifts by tens of degrees between observers).
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import math
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import numpy as np

from galileo.planning import star_atlas as sa

logger = logging.getLogger(__name__)

#: Kinds, in the order the Star Atlas offers them.
COMET, ASTEROID, SATELLITE = "Comet", "Asteroid", "Satellite"

#: How old a cached download may get before it is fetched again (seconds).
MAX_AGE = {COMET: 7 * 86400.0, ASTEROID: 30 * 86400.0, SATELLITE: 86400.0}

#: Only asteroids this bright (absolute magnitude H) are fetched; the list would be huge otherwise.
ASTEROID_MAX_H = 10.0
#: Faintest apparent magnitude shown.
COMET_MAG_LIMIT = 13.0
ASTEROID_MAG_LIMIT = 12.0
#: Satellites carry no magnitude in a TLE; a typical naked-eye value sizes the symbol.
SATELLITE_MAG = 3.0

_SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
_TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle"
_GAUSS_K = 0.01720209895           # Gaussian gravitational constant, AU^1.5 / day
_OBLIQUITY = math.radians(23.4392911)
_EARTH_RADIUS_KM = 6378.137
_EARTH_FLATTENING = 1.0 / 298.257223563
_TIMEOUT_S = 60
_DEFUNCT_COMET = re.compile(r"(^|\s)\d*D/")


@dataclass
class Orbits:
    """Heliocentric elements (ecliptic J2000) for a set of comets or asteroids.

    ``q`` is the perihelion distance (AU); ``tp`` the time of perihelion and ``epoch`` the epoch
    of ``ma`` (both Julian dates). A comet has ``tp`` (``ma`` is NaN), an asteroid has ``ma`` and
    ``epoch`` (``tp`` is NaN). ``m1``/``k1`` are the total-magnitude parameters of a comet and ``h``
    the absolute magnitude of an asteroid."""
    kind: str
    names: list[str]
    e: np.ndarray
    q: np.ndarray
    i: np.ndarray
    om: np.ndarray
    w: np.ndarray
    tp: np.ndarray
    ma: np.ndarray
    epoch: np.ndarray
    mag1: np.ndarray        # comet M1 or asteroid H
    k1: np.ndarray          # comet K1 (NaN for asteroids)

    def __len__(self) -> int:
        return len(self.names)

    @classmethod
    def empty(cls, kind: str) -> Orbits:
        z = np.empty(0)
        return cls(kind, [], z, z, z, z, z, z, z, z, z, z)


@dataclass
class Satellites:
    """Parsed TLEs: names plus the line pairs ``sgp4`` propagates."""
    names: list[str]
    lines: list[tuple[str, str]]

    def __len__(self) -> int:
        return len(self.names)

    @classmethod
    def empty(cls) -> Satellites:
        return cls([], [])


# ---------------------------------------------------------------------------
# Download and cache
# ---------------------------------------------------------------------------

def _cache_file(kind: str):
    from galileo.platform import get_cache_dir
    return get_cache_dir() / f"galileo_{kind.lower()}_elements.json"


def _read_cache(kind: str, *, allow_stale: bool) -> Any | None:
    path = _cache_file(kind)
    try:
        if not path.exists():
            return None
        if not allow_stale and time.time() - path.stat().st_mtime > MAX_AGE[kind]:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.info("Could not read the cached %s elements", kind, exc_info=True)
        return None


def _write_cache(kind: str, payload: Any) -> None:
    try:
        _cache_file(kind).write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        logger.info("Could not cache the %s elements", kind, exc_info=True)


def _http_get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as resp:
        return resp.read()


def _fetch_sbdb(kind: str) -> dict | None:
    if kind == COMET:
        params = {"fields": "full_name,e,q,i,om,w,tp,M1,K1", "sb-kind": "c"}
    else:
        params = {"fields": "full_name,e,a,i,om,w,ma,epoch,H", "sb-kind": "a",
                  "sb-cdata": json.dumps({"AND": [f"H|LT|{ASTEROID_MAX_H}"]})}
    try:
        return json.loads(_http_get(f"{_SBDB_URL}?{urllib.parse.urlencode(params)}"))
    except Exception:
        logger.info("Could not fetch %s elements from JPL", kind, exc_info=True)
        return None


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def parse_sbdb(kind: str, payload: dict | None) -> Orbits:
    """Build :class:`Orbits` from a JPL SBDB query response (``{"fields": [...], "data": [[...]]}``).
    Rows with missing elements are dropped."""
    if not payload or not payload.get("data"):
        return Orbits.empty(kind)
    cols = {name: n for n, name in enumerate(payload["fields"])}
    rows = payload["data"]

    def col(name: str) -> np.ndarray:
        return np.array([_num(r[cols[name]]) if name in cols else float("nan") for r in rows])

    e, i, om, w = col("e"), col("i"), col("om"), col("w")
    names = [str(r[cols["full_name"]]).strip() for r in rows]
    if kind == COMET:
        q, tp, m1, k1 = col("q"), col("tp"), col("M1"), col("K1")
        ma = epoch = np.full(len(rows), np.nan)
        # "D/" comets are defunct (lost or disintegrated): their elements predict nothing real.
        defunct = np.array([bool(_DEFUNCT_COMET.search(name)) for name in names])
        valid = ~np.isnan(e + q + i + om + w + tp + m1 + k1) & (e < 1.2) & ~defunct
    else:
        a, ma, epoch, m1 = col("a"), col("ma"), col("epoch"), col("H")
        q = a * (1.0 - e)
        tp = k1 = np.full(len(rows), np.nan)
        valid = ~np.isnan(e + q + i + om + w + ma + epoch + m1) & (e < 1.0) & (a > 0.0)
    keep = np.nonzero(valid)[0]
    return Orbits(kind, [names[n] for n in keep], e[keep], q[keep], i[keep], om[keep], w[keep],
                  tp[keep], ma[keep], epoch[keep], m1[keep], k1[keep])


def parse_tles(text: str) -> Satellites:
    """Parse three-line element sets (name line, then TLE lines 1 and 2)."""
    names: list[str] = []
    pairs: list[tuple[str, str]] = []
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    n = 0
    while n + 2 < len(lines):
        if lines[n + 1].startswith("1 ") and lines[n + 2].startswith("2 "):
            names.append(lines[n].strip())
            pairs.append((lines[n + 1], lines[n + 2]))
            n += 3
        else:
            n += 1
    return Satellites(names, pairs)


def load_orbits(kind: str) -> Orbits:
    """Comet or asteroid elements: fresh cache, else a download, else a stale cache, else none."""
    payload = _read_cache(kind, allow_stale=False)
    if payload is None:
        payload = _fetch_sbdb(kind)
        if payload is not None:
            _write_cache(kind, payload)
        else:
            payload = _read_cache(kind, allow_stale=True)
    return parse_sbdb(kind, payload)


def load_satellites() -> Satellites:
    """Satellite TLEs, cached the same way as :func:`load_orbits`."""
    payload = _read_cache(SATELLITE, allow_stale=False)
    if payload is None:
        try:
            payload = {"tle": _http_get(_TLE_URL).decode("ascii", "replace")}
            _write_cache(SATELLITE, payload)
        except Exception:
            logger.info("Could not fetch satellite elements from CelesTrak", exc_info=True)
            payload = _read_cache(SATELLITE, allow_stale=True)
    return parse_tles(payload["tle"]) if payload else Satellites.empty()


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

def _kepler(mean_anom: np.ndarray, e: np.ndarray) -> np.ndarray:
    """Eccentric anomaly for elliptical orbits (Newton's method, vectorised)."""
    m = (mean_anom + np.pi) % (2.0 * np.pi) - np.pi
    big_e = np.where(e < 0.8, m, np.pi * np.sign(m) + 0 * m)
    for _ in range(30):
        step = (big_e - e * np.sin(big_e) - m) / (1.0 - e * np.cos(big_e))
        big_e = big_e - step
        if np.max(np.abs(step), initial=0.0) < 1e-10:
            break
    return big_e


def heliocentric_ecliptic(orbits: Orbits, jd: float) -> np.ndarray:
    """Heliocentric ecliptic-J2000 positions (AU), shape ``(n, 3)``. Handles elliptical,
    near-parabolic and hyperbolic comet orbits (Barker's/hyperbolic Kepler for e >= ~1)."""
    n = len(orbits)
    if n == 0:
        return np.empty((0, 3))
    e, q = orbits.e, orbits.q
    ecc_ell = e < 0.98
    x_orb = np.zeros(n)
    y_orb = np.zeros(n)

    # Elliptical (all asteroids and most periodic comets).
    idx = np.nonzero(ecc_ell)[0]
    if len(idx):
        a = q[idx] / (1.0 - e[idx])
        mean_motion = _GAUSS_K / np.power(a, 1.5)
        if orbits.kind == ASTEROID:
            mean_anom = np.radians(orbits.ma[idx]) + mean_motion * (jd - orbits.epoch[idx])
        else:
            mean_anom = mean_motion * (jd - orbits.tp[idx])
        big_e = _kepler(mean_anom, e[idx])
        x_orb[idx] = a * (np.cos(big_e) - e[idx])
        y_orb[idx] = a * np.sqrt(1.0 - e[idx] ** 2) * np.sin(big_e)

    # Near-parabolic and hyperbolic comets: solve in terms of the true anomaly directly.
    idx = np.nonzero(~ecc_ell)[0]
    for j in idx.tolist():
        ej, qj = float(e[j]), float(q[j])
        dt = jd - float(orbits.tp[j])
        if abs(ej - 1.0) < 1e-6 or ej < 1.0:
            # Parabolic approximation (Barker's equation).
            w_ = 1.5 * _GAUSS_K * dt / math.sqrt(2.0 * qj ** 3)
            s = (w_ + math.sqrt(w_ * w_ + 1.0)) ** (1 / 3) - (math.sqrt(w_ * w_ + 1.0) - w_) ** (1 / 3)
            nu = 2.0 * math.atan(s)
            r = qj * (1.0 + s * s)
        else:
            a_h = qj / (ej - 1.0)
            mean_h = _GAUSS_K / math.sqrt(a_h ** 3) * dt
            h = math.asinh(mean_h / ej) if ej else 0.0
            for _ in range(50):
                step = (ej * math.sinh(h) - h - mean_h) / (ej * math.cosh(h) - 1.0)
                h -= step
                if abs(step) < 1e-10:
                    break
            nu = 2.0 * math.atan(math.sqrt((ej + 1.0) / (ej - 1.0)) * math.tanh(h / 2.0))
            r = a_h * (ej * math.cosh(h) - 1.0)
        x_orb[j], y_orb[j] = r * math.cos(nu), r * math.sin(nu)

    om, w, inc = np.radians(orbits.om), np.radians(orbits.w), np.radians(orbits.i)
    cos_o, sin_o, cos_w, sin_w = np.cos(om), np.sin(om), np.cos(w), np.sin(w)
    cos_i, sin_i = np.cos(inc), np.sin(inc)
    x = (cos_o * cos_w - sin_o * sin_w * cos_i) * x_orb + (-cos_o * sin_w - sin_o * cos_w * cos_i) * y_orb
    y = (sin_o * cos_w + cos_o * sin_w * cos_i) * x_orb + (-sin_o * sin_w + cos_o * cos_w * cos_i) * y_orb
    z = (sin_w * sin_i) * x_orb + (cos_w * sin_i) * y_orb
    return np.column_stack([x, y, z])


def _sun_earth_barycentric(when: _dt.datetime) -> tuple[np.ndarray, np.ndarray]:
    """Equatorial-J2000 barycentric positions (AU) of the Sun and the Earth (astropy's built-in
    ephemeris, no download)."""
    from astropy.coordinates import get_body_barycentric
    from astropy.time import Time

    t = Time(when.replace(tzinfo=None), scale="utc")
    sun = get_body_barycentric("sun", t)
    earth = get_body_barycentric("earth", t)
    return (np.array([sun.x.to("au").value, sun.y.to("au").value, sun.z.to("au").value]),
            np.array([earth.x.to("au").value, earth.y.to("au").value, earth.z.to("au").value]))


def minor_body_positions(orbits: Orbits, when: _dt.datetime, mag_limit: float | None = None) -> list[dict[str, Any]]:
    """Geocentric J2000 positions of the comets or asteroids brighter than *mag_limit*, as
    ``{"name", "kind", "ra_deg", "dec_deg", "mag", "distance_au"}`` dicts."""
    if len(orbits) == 0:
        return []
    if mag_limit is None:
        mag_limit = COMET_MAG_LIMIT if orbits.kind == COMET else ASTEROID_MAG_LIMIT
    jd = sa.julian_date(when)
    helio = heliocentric_ecliptic(orbits, jd)
    cos_e, sin_e = math.cos(_OBLIQUITY), math.sin(_OBLIQUITY)
    equ = np.column_stack([helio[:, 0], helio[:, 1] * cos_e - helio[:, 2] * sin_e,
                           helio[:, 1] * sin_e + helio[:, 2] * cos_e])
    sun_bary, earth_bary = _sun_earth_barycentric(when)
    geo = equ + sun_bary - earth_bary
    delta = np.linalg.norm(geo, axis=1)
    r = np.linalg.norm(helio, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        if orbits.kind == COMET:
            mag = orbits.mag1 + 5.0 * np.log10(delta) + orbits.k1 * np.log10(r)
        else:
            mag = orbits.mag1 + 5.0 * np.log10(r * delta)
    ra = np.degrees(np.arctan2(geo[:, 1], geo[:, 0])) % 360.0
    dec = np.degrees(np.arcsin(np.clip(geo[:, 2] / delta, -1.0, 1.0)))
    keep = np.nonzero(np.isfinite(mag) & (mag <= mag_limit))[0]
    return [{"name": orbits.names[n], "kind": orbits.kind, "ra_deg": float(ra[n]), "dec_deg": float(dec[n]),
             "mag": float(mag[n]), "distance_au": float(delta[n])} for n in keep.tolist()]


def _observer_eci_km(lat_deg: float, lst_deg: float, elevation_m: float = 0.0) -> np.ndarray:
    """Observer position in the true-equator inertial frame (km), on the WGS-84 ellipsoid."""
    lat, lst = math.radians(lat_deg), math.radians(lst_deg)
    f = _EARTH_FLATTENING
    c = 1.0 / math.sqrt(math.cos(lat) ** 2 + (1.0 - f) ** 2 * math.sin(lat) ** 2)
    s = (1.0 - f) ** 2 * c
    h = elevation_m / 1000.0
    return np.array([(_EARTH_RADIUS_KM * c + h) * math.cos(lat) * math.cos(lst),
                     (_EARTH_RADIUS_KM * c + h) * math.cos(lat) * math.sin(lst),
                     (_EARTH_RADIUS_KM * s + h) * math.sin(lat)])


def satellite_positions(sats: Satellites, when: _dt.datetime, latitude: float, longitude: float,
                        elevation_m: float = 0.0) -> list[dict[str, Any]]:
    """Topocentric J2000 positions of the satellites at *when*, as dicts with ``sunlit`` (False
    while the satellite is in the Earth's shadow and so invisible). Satellites whose elements
    no longer propagate are skipped."""
    if len(sats) == 0:
        return []
    from sgp4.api import Satrec, jday

    when = when.replace(tzinfo=None)
    jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute, when.second + when.microsecond / 1e6)
    jd_full = jd + fr
    observer = _observer_eci_km(latitude, sa.local_sidereal_deg(jd_full, longitude), elevation_m)
    sun = next((b for b in sa.solar_system_positions(when) if b["name"] == "Sun"), None)
    sun_dir = None
    if sun is not None:
        ra_d, dec_d = sa.precess_from_j2000(sun["ra_deg"], sun["dec_deg"], jd_full)
        sun_dir = np.array(sa._unit_vectors(ra_d, dec_d)).ravel()
    out: list[dict[str, Any]] = []
    for name, (l1, l2) in zip(sats.names, sats.lines, strict=False):
        try:
            err, pos, _vel = Satrec.twoline2rv(l1, l2).sgp4(jd, fr)
        except Exception:
            continue
        if err != 0:
            continue
        pos_v = np.array(pos)
        topo = pos_v - observer
        rng = float(np.linalg.norm(topo))
        ra_date = math.degrees(math.atan2(topo[1], topo[0])) % 360.0
        dec_date = math.degrees(math.asin(max(-1.0, min(1.0, topo[2] / rng))))
        ra, dec = sa.precess_to_j2000(ra_date, dec_date, jd_full)
        sunlit = True
        if sun_dir is not None:
            along = float(np.dot(pos_v, sun_dir))
            sunlit = along > 0.0 or float(np.linalg.norm(pos_v - along * sun_dir)) > _EARTH_RADIUS_KM
        out.append({"name": name, "kind": SATELLITE, "ra_deg": float(ra), "dec_deg": float(dec),
                    "mag": SATELLITE_MAG, "distance_km": rng, "sunlit": sunlit})
    return out
