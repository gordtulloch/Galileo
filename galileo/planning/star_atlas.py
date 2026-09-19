# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Star Atlas maths and star catalog (basic planetarium; SKYMAP-010, SKYMAP-020).

Everything here is plain numpy — no Qt — so the sky computation can be tested
without a display; :mod:`galileo.ui.star_atlas` is the widget that draws it.

* :func:`load_star_catalog` — the Yale Bright Star Catalogue (~9,100 stars to
  V≈6.5) fetched once from VizieR and cached, with a small built-in list of the
  brightest named stars as an offline fallback so the view is never empty.
* Sky maths — precession from J2000, sidereal time, equatorial → horizontal,
  and the stereographic projection the view is drawn with.
* :func:`solar_system_positions` — Sun, Moon and planets via astropy's built-in
  ephemeris (no download).
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_CATALOG_FILENAME = "galileo_star_catalog.json"

# (name, RA° J2000, Dec° J2000, V mag). Proper names are attached to the nearest
# catalogue star (within _NAME_MATCH_DEG), so these need only be accurate to a
# few arcminutes; the table is also the offline fallback catalog.
_NAMED_STARS: list[tuple[str, float, float, float]] = [
    ("Sirius", 101.287, -16.716, -1.46), ("Canopus", 95.988, -52.696, -0.74),
    ("Rigil Kentaurus", 219.900, -60.834, -0.01), ("Arcturus", 213.915, 19.182, -0.05),
    ("Vega", 279.235, 38.784, 0.03), ("Capella", 79.172, 45.998, 0.08),
    ("Rigel", 78.634, -8.202, 0.13), ("Procyon", 114.825, 5.225, 0.34),
    ("Achernar", 24.429, -57.237, 0.46), ("Betelgeuse", 88.793, 7.407, 0.50),
    ("Hadar", 210.956, -60.373, 0.61), ("Altair", 297.696, 8.868, 0.77),
    ("Acrux", 186.650, -63.099, 0.76), ("Aldebaran", 68.980, 16.509, 0.85),
    ("Spica", 201.298, -11.161, 0.97), ("Antares", 247.352, -26.432, 1.06),
    ("Pollux", 116.329, 28.026, 1.14), ("Fomalhaut", 344.413, -29.622, 1.16),
    ("Deneb", 310.358, 45.280, 1.25), ("Mimosa", 191.930, -59.689, 1.25),
    ("Regulus", 152.093, 11.967, 1.35), ("Adhara", 104.656, -28.972, 1.50),
    ("Castor", 113.650, 31.888, 1.58), ("Gacrux", 187.791, -57.113, 1.63),
    ("Shaula", 263.402, -37.104, 1.62), ("Bellatrix", 81.283, 6.350, 1.64),
    ("Elnath", 81.573, 28.608, 1.65), ("Miaplacidus", 138.300, -69.717, 1.67),
    ("Alnilam", 84.053, -1.202, 1.69), ("Alnair", 332.058, -46.961, 1.74),
    ("Alnitak", 85.190, -1.943, 1.77), ("Alioth", 193.507, 55.960, 1.76),
    ("Dubhe", 165.932, 61.751, 1.79), ("Mirfak", 51.081, 49.861, 1.80),
    ("Wezen", 107.098, -26.393, 1.83), ("Kaus Australis", 276.043, -34.385, 1.85),
    ("Alkaid", 206.885, 49.313, 1.86), ("Avior", 125.629, -59.510, 1.86),
    ("Atria", 252.166, -69.028, 1.92), ("Alhena", 99.428, 16.399, 1.93),
    ("Peacock", 306.412, -56.735, 1.94), ("Polaris", 37.955, 89.264, 1.98),
    ("Mirzam", 95.675, -17.956, 1.98), ("Alphard", 141.897, -8.659, 2.00),
    ("Hamal", 31.793, 23.462, 2.00), ("Diphda", 10.897, -17.987, 2.04),
    ("Nunki", 283.816, -26.297, 2.05), ("Saiph", 86.939, -9.670, 2.06),
    ("Alpheratz", 2.097, 29.091, 2.06), ("Kochab", 222.676, 74.156, 2.08),
    ("Rasalhague", 263.734, 12.560, 2.08), ("Algol", 47.042, 40.956, 2.12),
    ("Denebola", 177.265, 14.572, 2.14), ("Mintaka", 83.002, -0.299, 2.23),
    ("Sadr", 305.557, 40.257, 2.23), ("Schedar", 10.127, 56.537, 2.24),
    ("Eltanin", 269.152, 51.489, 2.23), ("Mizar", 200.981, 54.925, 2.23),
    ("Alphecca", 233.672, 26.715, 2.23), ("Merak", 165.460, 56.382, 2.37),
    ("Enif", 326.046, 9.875, 2.39), ("Markab", 346.190, 15.205, 2.49),
    ("Menkar", 45.570, 4.090, 2.53), ("Mira", 34.837, -2.977, 3.04),
    ("Albireo", 292.680, 27.960, 3.05), ("Thuban", 211.097, 64.376, 3.65),
]
_NAME_MATCH_DEG = 0.3


@dataclass
class StarCatalog:
    """Column-oriented star table (J2000 coordinates, degrees)."""
    ra: np.ndarray
    dec: np.ndarray
    mag: np.ndarray
    names: list[str]          # proper name ("Sirius") or "" — parallel to the arrays
    designations: list[str]   # catalogue designation ("9Alp CMa") or ""

    def __len__(self) -> int:
        return len(self.ra)

    def label(self, i: int) -> str:
        return self.names[i] or self.designations[i] or "Star"


def _fallback_catalog() -> StarCatalog:
    return StarCatalog(
        ra=np.array([s[1] for s in _NAMED_STARS]),
        dec=np.array([s[2] for s in _NAMED_STARS]),
        mag=np.array([s[3] for s in _NAMED_STARS]),
        names=[s[0] for s in _NAMED_STARS],
        designations=["" for _ in _NAMED_STARS],
    )


def _attach_proper_names(cat: StarCatalog) -> None:
    for name, ra, dec, _ in _NAMED_STARS:
        d_ra = (cat.ra - ra + 180.0) % 360.0 - 180.0
        sep = np.hypot(d_ra * np.cos(np.radians(dec)), cat.dec - dec)
        sep[cat.mag > 4.5] = np.inf   # only a bright star can carry a proper name
        i = int(np.argmin(sep))
        if sep[i] <= _NAME_MATCH_DEG:
            cat.names[i] = name


def _cache_path():
    from galileo.platform import get_cache_dir
    return get_cache_dir() / _CATALOG_FILENAME


def _fetch_bsc() -> StarCatalog | None:
    """Fetch the Yale Bright Star Catalogue (V/50) from VizieR."""
    try:
        import astropy.units as u
        from astropy.coordinates import SkyCoord
        from astroquery.vizier import Vizier

        result = Vizier(columns=["HR", "Name", "RAJ2000", "DEJ2000", "Vmag"], row_limit=-1).get_catalogs("V/50/catalog")
        if not result:
            return None
        rows = [
            (str(r["RAJ2000"]).strip(), str(r["DEJ2000"]).strip(), float(r["Vmag"]), str(r["Name"]).strip())
            for r in result[0]
            if str(r["RAJ2000"]).strip() and str(r["DEJ2000"]).strip()
            and str(r["RAJ2000"]) != "--" and not np.ma.is_masked(r["Vmag"])
        ]
        coords = SkyCoord([r[0] for r in rows], [r[1] for r in rows], unit=(u.hourangle, u.deg))
        cat = StarCatalog(
            ra=np.asarray(coords.ra.deg), dec=np.asarray(coords.dec.deg),
            mag=np.array([r[2] for r in rows]),
            names=["" for _ in rows], designations=[r[3] for r in rows],
        )
        _attach_proper_names(cat)
        return cat
    except Exception:
        logger.info("Could not fetch the Bright Star Catalogue from VizieR", exc_info=True)
        return None


def load_star_catalog() -> StarCatalog:
    """Load the cached star catalog, fetching and caching it on first use.
    Falls back to the ~60 brightest named stars if nothing is cached and the
    network is unavailable (not cached, so a later start retries)."""
    path = _cache_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text("utf-8"))
            return StarCatalog(
                ra=np.array(raw["ra"]), dec=np.array(raw["dec"]), mag=np.array(raw["mag"]),
                names=raw["names"], designations=raw["des"],
            )
        except Exception:
            logger.exception("Failed to read the cached star catalog; refetching")
    cat = _fetch_bsc()
    if cat is None or len(cat) == 0:
        logger.warning("Star catalog unavailable offline — showing only the brightest named stars.")
        return _fallback_catalog()
    try:
        path.write_text(json.dumps({
            "ra": np.round(cat.ra, 4).tolist(), "dec": np.round(cat.dec, 4).tolist(),
            "mag": np.round(cat.mag, 2).tolist(), "names": cat.names, "des": cat.designations,
        }), encoding="utf-8")
    except Exception:
        logger.exception("Failed to cache the star catalog")
    return cat


# ---------------------------------------------------------------------------
# Constellation boundaries
# ---------------------------------------------------------------------------

_BOUNDARY_FILENAME = "galileo_constellation_boundaries.json"
_B1875_JD = 2405889.25          # epoch of the Delporte/IAU boundary vertices
_BOUNDARY_STEP_DEG = 1.0        # edge densification: edges follow lines of constant RA/Dec in B1875

CONSTELLATION_NAMES: dict[str, str] = {
    "AND": "Andromeda", "ANT": "Antlia", "APS": "Apus", "AQL": "Aquila", "AQR": "Aquarius", "ARA": "Ara",
    "ARI": "Aries", "AUR": "Auriga", "BOO": "Boötes", "CAE": "Caelum", "CAM": "Camelopardalis",
    "CAP": "Capricornus", "CAR": "Carina", "CAS": "Cassiopeia", "CEN": "Centaurus", "CEP": "Cepheus",
    "CET": "Cetus", "CHA": "Chamaeleon", "CIR": "Circinus", "CMA": "Canis Major", "CMI": "Canis Minor",
    "CNC": "Cancer", "COL": "Columba", "COM": "Coma Berenices", "CRA": "Corona Australis",
    "CRB": "Corona Borealis", "CRT": "Crater", "CRU": "Crux", "CRV": "Corvus", "CVN": "Canes Venatici",
    "CYG": "Cygnus", "DEL": "Delphinus", "DOR": "Dorado", "DRA": "Draco", "EQU": "Equuleus",
    "ERI": "Eridanus", "FOR": "Fornax", "GEM": "Gemini", "GRU": "Grus", "HER": "Hercules",
    "HOR": "Horologium", "HYA": "Hydra", "HYI": "Hydrus", "IND": "Indus", "LAC": "Lacerta", "LEO": "Leo",
    "LEP": "Lepus", "LIB": "Libra", "LMI": "Leo Minor", "LUP": "Lupus", "LYN": "Lynx", "LYR": "Lyra",
    "MEN": "Mensa", "MIC": "Microscopium", "MON": "Monoceros", "MUS": "Musca", "NOR": "Norma",
    "OCT": "Octans", "OPH": "Ophiuchus", "ORI": "Orion", "PAV": "Pavo", "PEG": "Pegasus", "PER": "Perseus",
    "PHE": "Phoenix", "PIC": "Pictor", "PSA": "Piscis Austrinus", "PSC": "Pisces", "PUP": "Puppis",
    "PYX": "Pyxis", "RET": "Reticulum", "SCL": "Sculptor", "SCO": "Scorpius", "SCT": "Scutum",
    "SER1": "Serpens", "SER2": "Serpens", "SEX": "Sextans", "SGE": "Sagitta", "SGR": "Sagittarius",
    "TAU": "Taurus", "TEL": "Telescopium", "TRA": "Triangulum Australe", "TRI": "Triangulum",
    "TUC": "Tucana", "UMA": "Ursa Major", "UMI": "Ursa Minor", "VEL": "Vela", "VIR": "Virgo",
    "VOL": "Volans", "VUL": "Vulpecula",
}


@dataclass
class ConstellationBoundaries:
    """The 88 IAU constellation outlines as closed J2000 polylines.

    ``ra``/``dec`` hold every outline back to back; outline *i* is
    ``[starts[i]:starts[i + 1]]``. ``names``/``codes``/``center_ra``/``center_dec``
    are parallel to the outlines (Serpens is two outlines, Caput and Cauda;
    ``codes`` are the three-letter IAU abbreviations, both Serpens parts being SER)."""
    ra: np.ndarray
    dec: np.ndarray
    starts: list[int]
    names: list[str]
    center_ra: np.ndarray
    center_dec: np.ndarray
    codes: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.names)

    def outline(self, i: int) -> slice:
        return slice(self.starts[i], self.starts[i + 1])

    @classmethod
    def empty(cls) -> "ConstellationBoundaries":
        return cls(np.empty(0), np.empty(0), [0], [], np.empty(0), np.empty(0))


def _unit_vectors(ra_deg, dec_deg) -> np.ndarray:
    ra, dec = np.radians(ra_deg), np.radians(dec_deg)
    return np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])


def precess_to_j2000(ra_deg, dec_deg, jd: float):
    """Inverse of :func:`precess_from_j2000`: mean equator of date *jd* → J2000."""
    basis = [(0.0, 0.0), (90.0, 0.0), (0.0, 90.0)]
    cols = [_unit_vectors(*precess_from_j2000(np.array([ra]), np.array([dec]), jd)).ravel() for ra, dec in basis]
    v = np.linalg.inv(np.array(cols).T) @ _unit_vectors(np.asarray(ra_deg), np.asarray(dec_deg))
    return np.degrees(np.arctan2(v[1], v[0])) % 360.0, np.degrees(np.arcsin(np.clip(v[2], -1.0, 1.0)))


def build_boundaries(codes: list[str], ra1875, dec1875) -> ConstellationBoundaries:
    """Build the outlines from the raw B1875 vertices (consecutive rows of one
    code form one polygon; every edge runs along a line of constant RA or Dec,
    so each is densified along that line and only then precessed to J2000)."""
    ra1875, dec1875 = np.asarray(ra1875, dtype=float), np.asarray(dec1875, dtype=float)
    runs: list[tuple[str, list[int]]] = []
    for i, code in enumerate(codes):
        if runs and runs[-1][0] == code:
            runs[-1][1].append(i)
        else:
            runs.append((code, [i]))
    all_ra: list[np.ndarray] = []
    all_dec: list[np.ndarray] = []
    starts, names, abbrevs = [0], [], []
    centers = []
    for code, idx in runs:
        pts_ra, pts_dec = [], []
        for a, b in zip(idx, idx[1:] + idx[:1]):
            d_ra = (ra1875[b] - ra1875[a] + 180.0) % 360.0 - 180.0
            d_dec = dec1875[b] - dec1875[a]
            n = max(1, int(np.ceil(max(abs(d_ra), abs(d_dec)) / _BOUNDARY_STEP_DEG)))
            f = np.arange(n) / n
            pts_ra.append((ra1875[a] + d_ra * f) % 360.0)
            pts_dec.append(dec1875[a] + d_dec * f)
        ra_b, dec_b = np.concatenate(pts_ra), np.concatenate(pts_dec)
        ra_j, dec_j = precess_to_j2000(ra_b, dec_b, _B1875_JD)
        ra_j, dec_j = np.append(ra_j, ra_j[0]), np.append(dec_j, dec_j[0])     # close the loop
        all_ra.append(ra_j)
        all_dec.append(dec_j)
        starts.append(starts[-1] + len(ra_j))
        names.append(CONSTELLATION_NAMES.get(code, code))
        abbrevs.append(code[:3])
        mean = _unit_vectors(ra_j, dec_j).mean(axis=1)
        centers.append((np.degrees(np.arctan2(mean[1], mean[0])) % 360.0,
                        np.degrees(np.arcsin(np.clip(mean[2] / np.linalg.norm(mean), -1.0, 1.0)))))
    return ConstellationBoundaries(
        np.concatenate(all_ra), np.concatenate(all_dec), starts, names,
        np.array([c[0] for c in centers]), np.array([c[1] for c in centers]), abbrevs,
    )


def _boundary_cache_path():
    from galileo.platform import get_cache_dir
    return get_cache_dir() / _BOUNDARY_FILENAME


def _fetch_boundaries() -> dict[str, list] | None:
    """Fetch the Delporte constellation-boundary vertices (VizieR VI/49, B1875)."""
    try:
        from astroquery.vizier import Vizier
        result = Vizier(columns=["RAB1875", "DEB1875", "cst"], row_limit=-1).get_catalogs("VI/49/bound_18")
        if not result:
            return None
        t = result[0]
        return {"cst": [str(c).strip() for c in t["cst"]],
                "ra": [float(v) for v in t["RAB1875"]], "dec": [float(v) for v in t["DEB1875"]]}
    except Exception:
        logger.info("Could not fetch the constellation boundaries from VizieR", exc_info=True)
        return None


def load_constellation_boundaries() -> ConstellationBoundaries:
    """Load the cached constellation outlines, fetching and caching the raw
    vertices on first use. Empty (no boundaries drawn) if unavailable offline."""
    path = _boundary_cache_path()
    raw = None
    if path.exists():
        try:
            raw = json.loads(path.read_text("utf-8"))
        except Exception:
            logger.exception("Failed to read the cached constellation boundaries; refetching")
    if raw is None:
        raw = _fetch_boundaries()
        if raw is None:
            logger.warning("Constellation boundaries unavailable offline — none will be drawn.")
            return ConstellationBoundaries.empty()
        try:
            path.write_text(json.dumps(raw), encoding="utf-8")
        except Exception:
            logger.exception("Failed to cache the constellation boundaries")
    try:
        return build_boundaries(raw["cst"], raw["ra"], raw["dec"])
    except Exception:
        logger.exception("Could not build the constellation boundaries")
        return ConstellationBoundaries.empty()


# ---------------------------------------------------------------------------
# Constellation outlines (stick figures)
# ---------------------------------------------------------------------------

_LINES_FILENAME = "galileo_constellation_lines.json"
_LINES_URL = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/constellations.lines.json"
_LINES_STEP_DEG = 2.0           # segments are densified so they curve with the projection instead of cutting corners


@dataclass
class ConstellationLines:
    """Constellation stick figures as J2000 polylines.

    ``ra``/``dec`` hold every polyline back to back; polyline *i* is
    ``[starts[i]:starts[i + 1]]``."""
    ra: np.ndarray
    dec: np.ndarray
    starts: list[int]

    def __len__(self) -> int:
        return len(self.starts) - 1

    def polyline(self, i: int) -> slice:
        return slice(self.starts[i], self.starts[i + 1])

    @classmethod
    def empty(cls) -> "ConstellationLines":
        return cls(np.empty(0), np.empty(0), [0])


def build_constellation_lines(polylines: list[list[list[float]]]) -> ConstellationLines:
    """Build the figures from raw ``[[ra, dec], ...]`` polylines (RA may be
    -180..180; consecutive vertices are joined along the great circle, sampled
    every ``_LINES_STEP_DEG`` so the segments follow the curved projection)."""
    all_ra: list[np.ndarray] = []
    all_dec: list[np.ndarray] = []
    starts = [0]
    for line in polylines:
        if len(line) < 2:
            continue
        pts = np.asarray(line, dtype=float)
        vec = _unit_vectors(pts[:, 0], pts[:, 1])
        seg_ra, seg_dec = [], []
        for a, b in zip(range(len(pts) - 1), range(1, len(pts))):
            va, vb = vec[:, a], vec[:, b]
            angle = float(np.degrees(np.arccos(np.clip(va @ vb, -1.0, 1.0))))
            n = max(1, int(np.ceil(angle / _LINES_STEP_DEG)))
            if n == 1 or angle < 1e-9:
                pts_v = va[:, None]
            else:
                t = np.arange(n) / n
                w = np.radians(angle)
                pts_v = (np.sin((1 - t) * w)[None, :] * va[:, None] + np.sin(t * w)[None, :] * vb[:, None]) / np.sin(w)
            seg_ra.append(np.degrees(np.arctan2(pts_v[1], pts_v[0])) % 360.0)
            seg_dec.append(np.degrees(np.arcsin(np.clip(pts_v[2], -1.0, 1.0))))
        seg_ra.append(np.array([pts[-1, 0] % 360.0]))
        seg_dec.append(np.array([pts[-1, 1]]))
        ra, dec = np.concatenate(seg_ra), np.concatenate(seg_dec)
        all_ra.append(ra)
        all_dec.append(dec)
        starts.append(starts[-1] + len(ra))
    if not all_ra:
        return ConstellationLines.empty()
    return ConstellationLines(np.concatenate(all_ra), np.concatenate(all_dec), starts)


def _lines_cache_path():
    from galileo.platform import get_cache_dir
    return get_cache_dir() / _LINES_FILENAME


def _fetch_constellation_lines() -> list[list[list[float]]] | None:
    """Fetch the constellation stick figures (d3-celestial, BSD-3, J2000 lon/lat)."""
    try:
        import urllib.request
        with urllib.request.urlopen(_LINES_URL, timeout=20) as resp:     # noqa: S310 — fixed https URL
            data = json.loads(resp.read().decode("utf-8"))
        lines = [[[float(lon), float(lat)] for lon, lat in line]
                 for feature in data["features"] for line in feature["geometry"]["coordinates"]]
        return lines or None
    except Exception:
        logger.info("Could not fetch the constellation lines", exc_info=True)
        return None


def load_constellation_lines() -> ConstellationLines:
    """Load the cached constellation figures, fetching and caching the raw
    polylines on first use. Empty (none drawn) if unavailable offline."""
    path = _lines_cache_path()
    raw = None
    if path.exists():
        try:
            raw = json.loads(path.read_text("utf-8"))
        except Exception:
            logger.exception("Failed to read the cached constellation lines; refetching")
    if raw is None:
        raw = _fetch_constellation_lines()
        if raw is None:
            logger.warning("Constellation lines unavailable offline — none will be drawn.")
            return ConstellationLines.empty()
        try:
            path.write_text(json.dumps(raw), encoding="utf-8")
        except Exception:
            logger.exception("Failed to cache the constellation lines")
    try:
        return build_constellation_lines(raw)
    except Exception:
        logger.exception("Could not build the constellation lines")
        return ConstellationLines.empty()


# ---------------------------------------------------------------------------
# Time and coordinates
# ---------------------------------------------------------------------------

def julian_date(when: _dt.datetime) -> float:
    """Julian date of *when* (naive datetimes are taken as UTC)."""
    if when.tzinfo is not None:
        when = when.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    epoch = _dt.datetime(2000, 1, 1, 12)
    return 2451545.0 + (when - epoch).total_seconds() / 86400.0


def local_sidereal_deg(jd: float, longitude_deg: float) -> float:
    """Local mean sidereal time in degrees (longitude east positive)."""
    t = (jd - 2451545.0) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t
    return (gmst + longitude_deg) % 360.0


def precess_from_j2000(ra_deg, dec_deg, jd: float):
    """Precess J2000 equatorial coordinates to the mean equator of date (Meeus, IAU 1976)."""
    t = (jd - 2451545.0) / 36525.0
    zeta = np.radians((2306.2181 * t + 0.30188 * t * t + 0.017998 * t ** 3) / 3600.0)
    z = np.radians((2306.2181 * t + 1.09468 * t * t + 0.018203 * t ** 3) / 3600.0)
    theta = np.radians((2004.3109 * t - 0.42665 * t * t - 0.041833 * t ** 3) / 3600.0)
    ra, dec = np.radians(ra_deg), np.radians(dec_deg)
    a = np.cos(dec) * np.sin(ra + zeta)
    b = np.cos(theta) * np.cos(dec) * np.cos(ra + zeta) - np.sin(theta) * np.sin(dec)
    c = np.sin(theta) * np.cos(dec) * np.cos(ra + zeta) + np.cos(theta) * np.sin(dec)
    return np.degrees(np.arctan2(a, b) + z) % 360.0, np.degrees(np.arcsin(np.clip(c, -1.0, 1.0)))


def equatorial_to_horizontal(ra_deg, dec_deg, lst_deg: float, latitude_deg: float):
    """(alt°, az°) for coordinates of date; azimuth is measured from north through east."""
    h = np.radians(lst_deg - np.asarray(ra_deg))
    dec, lat = np.radians(dec_deg), np.radians(latitude_deg)
    sin_alt = np.sin(dec) * np.sin(lat) + np.cos(dec) * np.cos(lat) * np.cos(h)
    az = np.arctan2(-np.cos(dec) * np.sin(h), np.sin(dec) * np.cos(lat) - np.cos(dec) * np.sin(lat) * np.cos(h))
    return np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0))), np.degrees(az) % 360.0


def horizontal_to_equatorial(alt_deg: float, az_deg: float, lst_deg: float, latitude_deg: float):
    """Inverse of :func:`equatorial_to_horizontal`, for one point: (ra°, dec°) of date."""
    alt, az, lat = np.radians(alt_deg), np.radians(az_deg), np.radians(latitude_deg)
    sin_dec = np.sin(alt) * np.sin(lat) + np.cos(alt) * np.cos(lat) * np.cos(az)
    dec = np.arcsin(np.clip(sin_dec, -1.0, 1.0))
    h = np.arctan2(-np.cos(alt) * np.sin(az), np.sin(alt) * np.cos(lat) - np.cos(alt) * np.sin(lat) * np.cos(az))
    return float((lst_deg - np.degrees(h)) % 360.0), float(np.degrees(dec))


# ---------------------------------------------------------------------------
# Sun, Moon, planets
# ---------------------------------------------------------------------------

# Rough visual magnitudes, used only to size the symbols.
SOLAR_SYSTEM_BODIES: list[tuple[str, float]] = [
    ("Sun", -26.7), ("Moon", -12.0), ("Mercury", 0.0), ("Venus", -4.0), ("Mars", 0.5),
    ("Jupiter", -2.0), ("Saturn", 0.5), ("Uranus", 5.7), ("Neptune", 7.8),
]


def solar_system_positions(when: _dt.datetime) -> list[dict[str, Any]]:
    """Geocentric J2000 positions of the Sun, Moon and planets at *when*
    (astropy's built-in ephemeris, so no download). Bodies that fail are skipped."""
    out: list[dict[str, Any]] = []
    try:
        from astropy.coordinates import get_body
        from astropy.time import Time
        if when.tzinfo is not None:
            when = when.astimezone(_dt.timezone.utc).replace(tzinfo=None)
        t = Time(when, scale="utc")
    except Exception:
        logger.exception("Could not set up the solar-system ephemeris")
        return out
    for name, mag in SOLAR_SYSTEM_BODIES:
        try:
            c = get_body(name.lower(), t)
            out.append({"name": name, "ra_deg": float(c.ra.deg), "dec_deg": float(c.dec.deg), "mag": mag})
        except Exception:
            logger.exception("Could not compute the position of %s", name)
    return out


# ---------------------------------------------------------------------------
# Stereographic projection
# ---------------------------------------------------------------------------

@dataclass
class Viewport:
    """Where the view looks (alt/az of the centre, vertical field of view) and its pixel size."""
    az0: float = 180.0
    alt0: float = 40.0
    fov_deg: float = 100.0
    width: int = 800
    height: int = 600

    @property
    def scale(self) -> float:
        """Pixels per unit of stereographic radius (2·tan(c/2))."""
        return (self.height / 2.0) / (2.0 * np.tan(np.radians(self.fov_deg) / 4.0))

    def project(self, alt_deg, az_deg):
        """Screen ``(x, y, visible)`` for horizontal coordinates. Azimuth
        increases to the right, as when standing and facing the centre of the
        view (facing south, east is on the left). ``visible`` excludes the far
        hemisphere, where the projection runs off to infinity."""
        alt, az = np.radians(alt_deg), np.radians(az_deg)
        alt0, az0 = np.radians(self.alt0), np.radians(self.az0)
        d_az = az - az0
        cos_c = np.sin(alt0) * np.sin(alt) + np.cos(alt0) * np.cos(alt) * np.cos(d_az)
        visible = cos_c > -0.85
        k = 2.0 / (1.0 + np.where(visible, cos_c, 0.0))
        x = k * np.cos(alt) * np.sin(d_az)
        y = k * (np.cos(alt0) * np.sin(alt) - np.sin(alt0) * np.cos(alt) * np.cos(d_az))
        return self.width / 2.0 + x * self.scale, self.height / 2.0 - y * self.scale, visible

    def unproject(self, sx, sy):
        """Horizontal ``(alt°, az°)`` under screen position(s) *sx*, *sy*."""
        x = (np.asarray(sx, dtype=float) - self.width / 2.0) / self.scale
        y = -(np.asarray(sy, dtype=float) - self.height / 2.0) / self.scale
        rho = np.hypot(x, y)
        c = 2.0 * np.arctan(rho / 2.0)
        alt0, az0 = np.radians(self.alt0), np.radians(self.az0)
        safe = np.where(rho == 0.0, 1.0, rho)
        alt = np.arcsin(np.clip(np.cos(c) * np.sin(alt0) + y * np.sin(c) * np.cos(alt0) / safe, -1.0, 1.0))
        az = az0 + np.arctan2(x * np.sin(c), rho * np.cos(alt0) * np.cos(c) - y * np.sin(alt0) * np.sin(c))
        return np.degrees(alt), np.degrees(az) % 360.0
