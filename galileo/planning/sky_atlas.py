# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Sky atlas — offline DSO catalog search and visibility (SKY-010 … SKY-090).

The catalog is OpenNGC (NGC/IC objects with their Messier and Caldwell
numbers), fetched from GitHub on first use and cached locally.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

# Re-exported so callers can do ``from galileo.planning.sky_atlas import ObservingLocation``
from galileo.planning.visibility import HorizonProfile, ObservingLocation  # noqa: F401

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# v1 was built from a VizieR query that lost every object's position, type and
# magnitude, so it is abandoned (and deleted) rather than read.
_CATALOG_FILENAME = "galileo_dso_catalog_v2.json"
_LEGACY_CATALOG_FILENAME = "galileo_dso_catalog.json"


class ObjectType(str, Enum):
    GALAXY = "Galaxy"
    NEBULA = "Nebula"
    CLUSTER = "Cluster"
    OPEN_CLUSTER = "OpenCluster"
    GLOBULAR_CLUSTER = "GlobularCluster"
    PLANETARY_NEBULA = "PlanetaryNebula"
    SUPERNOVA_REMNANT = "SupernovaRemnant"
    STAR = "Star"
    DOUBLE_STAR = "DoubleStar"
    ASTERISM = "Asterism"
    OTHER = "Other"


@dataclass
class DeepSkyObject:
    """One entry in the DSO catalog."""
    primary_name: str
    designations: list[str]
    ra_deg: float
    dec_deg: float
    object_type: ObjectType
    magnitude: float
    size_arcmin: float = 0.0
    description: str = ""

    def as_sequence_target(self) -> dict:
        return {
            "name": self.primary_name,
            "ra_deg": self.ra_deg,
            "dec_deg": self.dec_deg,
        }


class LocationManager:
    """Manages a list of named observing locations (SKY-060)."""

    def __init__(self) -> None:
        self._locations: dict[str, "ObservingLocation"] = {}

    def add(self, loc: "ObservingLocation") -> None:
        self._locations[loc.name] = loc

    def get(self, name: str) -> "ObservingLocation":
        return self._locations[name]

    @property
    def locations(self) -> list:
        return list(self._locations.values())


# ---------------------------------------------------------------------------
# Catalog loader
# ---------------------------------------------------------------------------

# The catalogs a user can pick between on the Star Atlas. An object belongs to
# one if any of its designations is in that catalog's numbering.
DSO_CATALOGS: tuple[str, ...] = ("Messier", "Caldwell", "NGC")
_CATALOG_PATTERNS = {
    "Messier": re.compile(r"^M\s?\d+$", re.IGNORECASE),
    "Caldwell": re.compile(r"^(?:C|Caldwell)\s?\d+$", re.IGNORECASE),
    "NGC": re.compile(r"^NGC\s?\d+", re.IGNORECASE),
}


def catalogs_of(obj: DeepSkyObject) -> set[str]:
    """Which of :data:`DSO_CATALOGS` *obj* belongs to."""
    names = [obj.primary_name, *obj.designations]
    return {cat for cat, pat in _CATALOG_PATTERNS.items() if any(pat.match(n.strip()) for n in names)}


_OPENNGC_URL = "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/"
_OPENNGC_TYPES = {
    "G": ObjectType.GALAXY, "GPair": ObjectType.GALAXY, "GTrpl": ObjectType.GALAXY, "GGroup": ObjectType.GALAXY,
    "OCl": ObjectType.OPEN_CLUSTER, "GCl": ObjectType.GLOBULAR_CLUSTER, "Cl+N": ObjectType.CLUSTER,
    "PN": ObjectType.PLANETARY_NEBULA, "SNR": ObjectType.SUPERNOVA_REMNANT,
    "HII": ObjectType.NEBULA, "DrkN": ObjectType.NEBULA, "EmN": ObjectType.NEBULA,
    "Neb": ObjectType.NEBULA, "RfN": ObjectType.NEBULA,
    "*": ObjectType.STAR, "Nova": ObjectType.STAR, "**": ObjectType.DOUBLE_STAR, "*Ass": ObjectType.ASTERISM,
    "Other": ObjectType.OTHER,
}
_OPENNGC_SKIP = {"Dup", "NonEx"}        # duplicate and non-existent entries
_DESIGNATION_RE = re.compile(r"^([A-Za-z]+?)0*(\d+)([A-Za-z]*)$")


def _catalog_cache_path() -> Path:
    from galileo.platform import get_cache_dir
    return get_cache_dir() / _CATALOG_FILENAME


def _load_catalog() -> list[DeepSkyObject]:
    """Load the DSO catalog, building it from OpenNGC if the cache is absent."""
    cache = _catalog_cache_path()
    try:
        cache.with_name(_LEGACY_CATALOG_FILENAME).unlink(missing_ok=True)
    except OSError:
        pass
    if cache.exists():
        try:
            raw = json.loads(cache.read_text("utf-8"))
            return [_obj_from_dict(d) for d in raw]
        except Exception:
            logger.exception("Failed to load cached catalog; regenerating")

    objects = _fetch_catalog_online()
    if objects:
        try:
            cache.write_text(
                json.dumps([_obj_to_dict(o) for o in objects]),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to cache catalog")
    return objects


def _sexagesimal_to_deg(text: str, hours: bool) -> float:
    sign = -1.0 if text.strip().startswith("-") else 1.0
    d, m, sec = (float(v) for v in text.strip().lstrip("+-").split(":"))
    value = sign * (d + m / 60.0 + sec / 3600.0)
    return value * 15.0 if hours else value


def _designation(name: str) -> str:
    """OpenNGC's zero-padded names → the usual form: NGC0224 → "NGC 224", M040 → "M40"."""
    m = _DESIGNATION_RE.match(name.strip())
    if not m:
        return name.strip()
    prefix, number, suffix = m.groups()
    return f"{prefix}{number}{suffix}" if prefix == "M" else f"{prefix} {number}{suffix}"


def _parse_openngc(*tables: str) -> list[DeepSkyObject]:
    """Build the catalog from OpenNGC's ``NGC.csv`` and ``addendum.csv`` text
    (semicolon-separated). Messier numbers come from the ``M`` column and
    Caldwell numbers from ``Identifiers`` (or the addendum's own ``C###`` names)."""
    objects: list[DeepSkyObject] = []
    for table in tables:
        for row in csv.DictReader(io.StringIO(table), delimiter=";"):
            try:
                if row["Type"] in _OPENNGC_SKIP or not row["RA"] or not row["Dec"]:
                    continue
                designations = [_designation(row["Name"])]
                messier = row.get("M", "").strip()
                if messier.isdigit() and f"M{int(messier)}" not in designations:
                    designations.insert(0, f"M{int(messier)}")
                for extra in row.get("Identifiers", "").split(","):
                    extra = re.sub(r"^C 0+(?=\d)", "C ", extra.strip())      # "C 020" → "C 20"
                    if extra and extra not in designations:
                        designations.append(extra)
                designations.extend(c.strip() for c in row.get("Common names", "").split(",") if c.strip())
                mag = next((float(row[k]) for k in ("V-Mag", "B-Mag") if row.get(k)), 99.0)
                objects.append(DeepSkyObject(
                    primary_name=designations[0],
                    designations=designations,
                    ra_deg=_sexagesimal_to_deg(row["RA"], hours=True),
                    dec_deg=_sexagesimal_to_deg(row["Dec"], hours=False),
                    object_type=_OPENNGC_TYPES.get(row["Type"], ObjectType.OTHER),
                    magnitude=mag,
                    size_arcmin=float(row["MajAx"]) if row.get("MajAx") else 0.0,
                ))
            except (ValueError, KeyError):
                continue
    return objects


def _fetch_catalog_online() -> list[DeepSkyObject]:
    """Fetch OpenNGC (~14 K NGC/IC objects with Messier and Caldwell cross-references)."""
    try:
        import urllib.request
        tables = []
        for filename in ("NGC.csv", "addendum.csv"):
            with urllib.request.urlopen(_OPENNGC_URL + filename, timeout=30) as resp:     # noqa: S310 — fixed https URL
                tables.append(resp.read().decode("utf-8"))
        return _parse_openngc(*tables)
    except Exception:
        logger.info("Could not fetch the deep-sky catalog; returning empty catalog", exc_info=True)
        return []


def _object_type_from_simbad_otype(otype: str) -> ObjectType:
    """Map a Simbad ``otype`` code to our closed :class:`ObjectType` set."""
    t = (otype or "").strip().lower()
    if t.startswith("gal") or t == "agn":
        return ObjectType.GALAXY
    if t.startswith("glc") or "globular" in t:
        return ObjectType.GLOBULAR_CLUSTER
    if t.startswith("opc") or "opencluster" in t.replace(" ", ""):
        return ObjectType.OPEN_CLUSTER
    if t.startswith("pn"):
        return ObjectType.PLANETARY_NEBULA
    if t.startswith("snr"):
        return ObjectType.SUPERNOVA_REMNANT
    if "neb" in t or t == "hii":
        return ObjectType.NEBULA
    if t == "**":
        return ObjectType.DOUBLE_STAR
    if t == "*":
        return ObjectType.STAR
    return ObjectType.OTHER


def _simbad_row_to_object(row) -> DeepSkyObject:
    """Convert one Simbad result-table row into a :class:`DeepSkyObject`,
    mirroring the field mapping in Obsy's ``target_query`` (``targets/views.py``,
    ADR-005) — main ID, coordinates, type — adapted to the lowercase
    ``main_id``/``ra``/``dec``/``otype`` columns the currently-installed
    astroquery returns (Obsy's ``MAIN_ID``/``RA``/``DEC``/``OTYPE_main`` and
    its ``SkyCoord`` sexagesimal-string parse are from an older Simbad
    response format; this astroquery version already returns ``ra``/``dec``
    as decimal degrees, so no coordinate parsing is needed). Magnitude is
    *not* read here — see :func:`_search_simbad_sync` for why it's a
    separate, best-effort lookup rather than part of this primary query."""
    main_id = str(row["main_id"]).strip()
    name = main_id.replace(" ", "")
    otype = str(row["otype"]) if "otype" in row.colnames else ""
    return DeepSkyObject(
        primary_name=name,
        designations=[name, main_id] if main_id != name else [name],
        ra_deg=float(row["ra"]),
        dec_deg=float(row["dec"]),
        object_type=_object_type_from_simbad_otype(otype),
        magnitude=99.0,
    )


def _simbad_magnitude_sync(name: str) -> float:
    """Best-effort V-magnitude lookup for one already-resolved Simbad object
    name, kept deliberately separate from the primary name/type/coordinate
    query in :func:`_search_simbad_sync`: requesting the ``V`` votable field
    on that primary query silently drops *any* object with no cataloged V
    magnitude — which includes most nebulae and clusters (M42, M45, the
    Orion Nebula, ...) — turning a plain name search for them into zero
    results with no error, confirmed against the live Simbad service. A
    failed/empty lookup here just leaves the object's magnitude unknown
    (``99.0``) rather than losing the match entirely."""
    try:
        from astroquery.simbad import Simbad  # type: ignore[import]

        simbad = Simbad()
        simbad.TIMEOUT = 8
        simbad.add_votable_fields("V")
        table = simbad.query_object(name, wildcard=False)
        if table is None or len(table) == 0:
            return 99.0
        value = float(table[0]["V"])
        return value if value == value else 99.0  # NaN check
    except Exception:
        return 99.0


def _search_simbad_sync(query: str) -> list[DeepSkyObject]:
    """Blocking Simbad object-name query (ported from Obsy's ``target_query``,
    ADR-005). Run off the UI thread via ``asyncio.to_thread`` by
    :meth:`SkyAtlas.search_online` — astroquery's Simbad client has no async
    API of its own.

    Only passes ``wildcard=True`` when *query* itself contains a ``*``/``?``
    wildcard character: Obsy always set ``wildcard=True``, but against the
    currently-installed astroquery/Simbad, wildcard mode requires the pattern
    to match Simbad's own identifier spacing (e.g. ``"M31"`` finds nothing,
    only ``"M31*"`` or ``"M 31"`` do) — confirmed against the live service —
    so a plain name is looked up via Simbad's normal alias-resolving lookup
    instead, which correctly resolves ``"M31"``, and wildcard search is still
    available whenever a caller actually wants a pattern match.
    """
    from astroquery.simbad import Simbad  # type: ignore[import]

    simbad = Simbad()
    simbad.TIMEOUT = 8
    simbad.add_votable_fields("otype")
    use_wildcard = any(ch in query for ch in "*?")
    table = simbad.query_object(query, wildcard=use_wildcard)
    if table is None:
        return []
    objects = []
    for row in table:
        try:
            objects.append(_simbad_row_to_object(row))
        except Exception:
            logger.debug("Could not parse Simbad result row for %r", query, exc_info=True)
    # Enrich with magnitude only when there are few enough results that a
    # per-object follow-up query stays cheap — a wildcard search can return
    # thousands of rows (e.g. "M31*"), which would otherwise turn one
    # search into thousands of extra network round trips.
    if 0 < len(objects) <= 10:
        for obj in objects:
            obj.magnitude = _simbad_magnitude_sync(obj.primary_name)
    return objects


def constellation_for(ra_deg: float, dec_deg: float) -> str:
    """Return the IAU constellation name containing (*ra_deg*, *dec_deg*)
    (ported from Obsy's ``get_constellation`` usage in ``target_query``,
    ADR-005) — uses ``astropy.coordinates.get_constellation`` directly
    rather than Simbad, since Simbad doesn't return constellation as one of
    its queryable fields."""
    from astropy.coordinates import SkyCoord, get_constellation

    coord = SkyCoord(ra=ra_deg, dec=dec_deg, unit="deg", frame="icrs")
    return get_constellation(coord)


_DSS_CUTOUT_URL = "https://archive.stsci.edu/cgi-bin/dss_search"


def _fetch_dss_thumbnail_sync(
    ra_deg: float,
    dec_deg: float,
    width_arcmin: float = 15.0,
    height_arcmin: float = 15.0,
    size_px: int = 150,
) -> bytes:
    """Blocking DSS cutout fetch + FITS-to-JPEG conversion (ported from
    Obsy's ``Target.save()``, ``targets/models.py``, ADR-005): request a
    FITS cutout centered on (*ra_deg*, *dec_deg*) from STScI's DSS search
    service, min/max-normalize the pixel data to 0..255, and resize to a
    *size_px* square JPEG. Run off the UI/event-loop thread via
    ``asyncio.to_thread`` by :meth:`SkyAtlas._fetch_thumbnail`. Returns
    ``b""`` on any failure rather than raising, since a missing thumbnail
    is never fatal to the caller."""
    import io

    try:
        import numpy as np
        import requests
        from astropy.io import fits
        from PIL import Image

        url = (
            f"{_DSS_CUTOUT_URL}?r={ra_deg}&d={dec_deg}"
            f"&w={width_arcmin}&h={height_arcmin}&e=J2000"
        )
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        with fits.open(io.BytesIO(resp.content)) as hdul:
            image_data = hdul[0].data.astype(np.float64)
        image_data = image_data - np.min(image_data)
        max_value = np.max(image_data)
        if max_value > 0:
            image_data = image_data / max_value * 255.0
        image = Image.fromarray(image_data.astype(np.uint8)).resize((size_px, size_px))
        buf = io.BytesIO()
        image.save(buf, format="JPEG")
        return buf.getvalue()
    except Exception:
        logger.debug(
            "Could not fetch DSS thumbnail for RA=%s Dec=%s", ra_deg, dec_deg, exc_info=True
        )
        return b""


def _type_from_str(type_str: str) -> ObjectType:
    t = type_str.lower()
    if "gal" in t:
        return ObjectType.GALAXY
    if "ocl" in t or "open" in t:
        return ObjectType.OPEN_CLUSTER
    if "gcl" in t or "glob" in t:
        return ObjectType.GLOBULAR_CLUSTER
    if "pln" in t:
        return ObjectType.PLANETARY_NEBULA
    if "neb" in t:
        return ObjectType.NEBULA
    return ObjectType.OTHER


def _obj_to_dict(o: DeepSkyObject) -> dict:
    return {
        "n": o.primary_name,
        "d": o.designations,
        "r": o.ra_deg,
        "c": o.dec_deg,
        "t": o.object_type.value,
        "m": o.magnitude,
        "s": o.size_arcmin,
    }


def _obj_from_dict(d: dict) -> DeepSkyObject:
    return DeepSkyObject(
        primary_name=d["n"],
        designations=d.get("d", [d["n"]]),
        ra_deg=d["r"],
        dec_deg=d["c"],
        object_type=ObjectType(d.get("t", "Other")),
        magnitude=d.get("m", 99.0),
        size_arcmin=d.get("s", 0.0),
    )


# ---------------------------------------------------------------------------
# Sky atlas
# ---------------------------------------------------------------------------

class SkyAtlas:
    """Searchable, filterable deep-sky object atlas (SKY-010 … SKY-090)."""

    def __init__(self, catalog: list[DeepSkyObject] | None = None) -> None:
        if catalog is not None:
            self._catalog = catalog
        else:
            self._catalog = _load_catalog()
        self._cache_dir: Path | None = None
        self._target_list: list[DeepSkyObject] = []

    # --- Catalog access ---------------------------------------------------

    def search(self, query: str) -> list[DeepSkyObject]:
        """Return objects whose name or designations match *query* (case-insensitive)."""
        q = query.strip().lower()
        if not q:
            return list(self._catalog)
        return [
            o for o in self._catalog
            if q in o.primary_name.lower()
            or any(q in d.lower() for d in o.designations)
        ]

    async def search_online(self, query: str) -> list[DeepSkyObject]:
        """Search for *query* via Simbad first — a live, comprehensive
        name/alias resolution beyond what the bundled/cached catalog holds,
        ported from Obsy's ``target_query`` (ADR-005) — falling back to the
        offline catalog (:meth:`search`) when Simbad is unreachable, times
        out, or finds nothing for *query*. This is the entry point the Sky
        Atlas page's search box calls; :meth:`search` itself stays local-only
        so core search still works with no internet (SKY-070/NFR-OFFLINE-010)."""
        q = query.strip()
        if not q:
            return list(self._catalog)
        try:
            online_results = await asyncio.to_thread(_search_simbad_sync, q)
        except Exception:
            logger.info("Simbad search for %r failed; falling back to local catalog", q, exc_info=True)
            online_results = []
        if online_results:
            logger.info("Simbad search for %r found %d object(s)", q, len(online_results))
            return online_results
        logger.info("Simbad search for %r found no results; falling back to local catalog", q)
        return self.search(q)

    def get_by_designation(self, designation: str) -> DeepSkyObject:
        """Return the object matching *designation* exactly, or raise KeyError."""
        for o in self._catalog:
            if designation in o.designations or designation == o.primary_name:
                return o
        raise KeyError(designation)

    def filter(
        self,
        object_types: list[ObjectType] | None = None,
        max_magnitude: float = 99.0,
        min_size_arcmin: float = 0.0,
        location: "ObservingLocation | None" = None,
        visible_tonight: bool = False,
        date_str: str | None = None,
    ) -> list[DeepSkyObject]:
        """Filter the catalog by type, magnitude, size, and visibility."""
        from galileo.planning.visibility import is_observable_tonight

        results = []
        for o in self._catalog:
            if object_types and o.object_type not in object_types:
                continue
            if o.magnitude > max_magnitude:
                continue
            if o.size_arcmin < min_size_arcmin:
                continue
            if visible_tonight and location:
                if not is_observable_tonight(o.ra_deg, o.dec_deg, location, date_str):
                    continue
            results.append(o)
        return results

    def altitude_chart(
        self,
        obj: DeepSkyObject,
        location: "ObservingLocation",
        date: str | None = None,
    ) -> dict:
        """Return an altitude-over-time chart for *obj* from *location*."""
        from galileo.planning.visibility import altitude_chart, HorizonProfile
        horizon = getattr(location, "_horizon", None)
        return altitude_chart(obj.ra_deg, obj.dec_deg, location, date, horizon)

    # --- Target list (for sky-survey thumbnail caching, SKY-080) ----------

    async def add_to_target_list(self, obj: DeepSkyObject) -> None:
        self._target_list.append(obj)
        cache_dir = self._cache_dir
        if cache_dir is None:
            from galileo.platform import get_cache_dir
            cache_dir = get_cache_dir()
        data = await self._fetch_thumbnail(obj)
        if data:
            safe_name = obj.primary_name.replace(" ", "_")
            (cache_dir / f"{safe_name}_thumbnail.jpg").write_bytes(data)

    async def _fetch_thumbnail(self, obj: DeepSkyObject) -> bytes:
        """Fetch a DSS sky-survey cutout thumbnail for *obj* from STScI
        (SKY-080), ported from Obsy's ``Target.save()`` (``targets/models.py``,
        ADR-005): a 15x15 arcmin FITS cutout, normalized and resized to a
        150x150 JPEG. Returns ``b""`` on any failure (no internet, malformed
        FITS, ...) so a missing thumbnail never blocks add-to-target-list or
        the Sky Atlas page's result-detail display."""
        return await asyncio.to_thread(_fetch_dss_thumbnail_sync, obj.ra_deg, obj.dec_deg)

    # --- Geocoding (SKY-090) ----------------------------------------------

    # Replaced by module-level function to allow mocking in tests:


async def geocode_location(place_name: str) -> dict:
    """Geocode a place name via the Open-Meteo geocoding API (SKY-090)."""
    import urllib.request
    import urllib.parse

    params = urllib.parse.urlencode({"name": place_name, "count": 1, "format": "json"})
    url = f"https://geocoding-api.open-meteo.com/v1/search?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            result = data.get("results", [{}])[0]
            return {
                "latitude": result.get("latitude", 0.0),
                "longitude": result.get("longitude", 0.0),
                "timezone": result.get("timezone", "UTC"),
            }
    except Exception:
        return {}
