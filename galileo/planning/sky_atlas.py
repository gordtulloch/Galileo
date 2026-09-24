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
import math
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
        # Simbad reports "no V magnitude" as NaN (or a masked cell); never pass a
        # non-finite value on as if it were a magnitude.
        return value if math.isfinite(value) else 99.0
    except Exception:
        logger.debug("Simbad V-magnitude lookup failed for %r", name, exc_info=True)
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


class TelescopiusNotConfiguredError(Exception):
    """A Telescopius operation (SKY-120) was requested with no user-supplied
    API key configured (:meth:`SkyAtlas.set_telescopius_api_key`) — Telescopius
    access is Patron/Sponsor-gated with no bundled/shared credential (Project
    Scope Document §6.9), so there's nothing to authenticate the request with."""


def _search_telescopius_sync(query: str, api_key: str) -> list[DeepSkyObject]:
    """Blocking Telescopius object-search/target-suggestion query (SKY-110,
    EXT-150), run off the UI thread via ``asyncio.to_thread`` by
    :meth:`SkyAtlas.search_online`.

    Not yet implemented against a real endpoint: per Project Scope Document
    §6.9, Telescopius's public API launched in 2023 with only a "quote of the
    day" endpoint, and its own staff describe target-search/suggestion
    endpoints as roadmap items rather than a documented, stable surface —
    committing to a specific endpoint path/params here would be a guess, not
    an integration (re-review when the API matures, per that section's own
    note). Raising here is deliberate, not an oversight: it lets the caller's
    existing broad-exception handling (the same "advisory-only, degrade
    silently" pattern `SAFE-050`'s weather lookup already uses) treat
    "not yet available" exactly like "unreachable" — augmentation is skipped,
    never blocking the offline-first/Simbad-fallback path (`SKY-010`/`SKY-100`)
    this layers on top of."""
    raise NotImplementedError(
        "Telescopius's target-search/suggestion endpoint isn't documented/stable yet "
        "— see docs/PSD.md §6.9"
    )


def _fetch_telescopius_observing_list_sync(list_name: str, api_key: str) -> list[dict]:
    """Blocking Telescopius observing-list fetch (SKY-120, EXT-150) — same
    not-yet-documented-endpoint caveat as :func:`_search_telescopius_sync`;
    raises so :meth:`SkyAtlas.import_telescopius_observing_list` surfaces a
    clear failure rather than silently returning nothing for what the user
    asked to be an explicit import action."""
    raise NotImplementedError(
        "Telescopius's observing-list endpoint isn't documented/stable yet "
        "— see docs/PSD.md §6.9"
    )


def constellation_for(ra_deg: float, dec_deg: float) -> str:
    """Return the IAU constellation name containing (*ra_deg*, *dec_deg*)
    (ported from Obsy's ``get_constellation`` usage in ``target_query``,
    ADR-005) — uses ``astropy.coordinates.get_constellation`` directly
    rather than Simbad, since Simbad doesn't return constellation as one of
    its queryable fields."""
    from astropy.coordinates import SkyCoord, get_constellation

    coord = SkyCoord(ra=ra_deg, dec=dec_deg, unit="deg", frame="icrs")
    return get_constellation(coord)


_HIPS2FITS_URL = "https://alasky.cds.unistra.fr/hips-image-services/hips2fits"

# DSS2's color composite (its red and blue plates combined), preferred over a
# single-band plate wherever it's available.
_DSS_HIPS_SURVEY = "CDS/P/DSS2/color"

# Size-aware thumbnail field of view (SKY-080): padded around the object's own
# angular size rather than a fixed window, so a point-source star and a
# multi-degree nebula both crop sensibly — clamped so a tiny/unknown size
# doesn't zoom in past what a 150x150 px thumbnail can usefully show, and a
# huge one doesn't shrink the object to a speck.
_THUMBNAIL_MIN_FOV_ARCMIN = 5.0
_THUMBNAIL_MAX_FOV_ARCMIN = 120.0
_THUMBNAIL_SIZE_PAD = 2.0
# Fallback field when the catalog/Simbad result carries no size at all
# (``size_arcmin`` 0 or unset) — the previous fixed window.
_THUMBNAIL_DEFAULT_FOV_ARCMIN = 15.0


def _thumbnail_field_arcmin(size_arcmin: float) -> float:
    """The thumbnail field of view (arcmin) for an object of *size_arcmin*
    angular size — padded so the object doesn't fill the frame edge-to-edge,
    clamped to sane bounds, falling back to a fixed default when the size is
    unknown (``<= 0``, e.g. a star with no catalog major-axis value)."""
    if size_arcmin <= 0:
        return _THUMBNAIL_DEFAULT_FOV_ARCMIN
    return min(max(size_arcmin * _THUMBNAIL_SIZE_PAD, _THUMBNAIL_MIN_FOV_ARCMIN), _THUMBNAIL_MAX_FOV_ARCMIN)


# Disk cache for thumbnails, keyed by field (ra/dec/size) — same technique as
# galileo.planning.framing's survey-image cache (_survey_cache_path/
# _cache_survey_image/_cached_survey_image): a repeat fetch for the same
# object (re-selecting a result, or the same object showing up again in a
# later search's result cards) is a disk read instead of another hips2fits
# request. Separate from add_to_target_list's own named
# "<object name>_thumbnail.jpg" file (SKY-080) — that one is keyed by name
# for a different purpose (an explicit, permanent per-target-list copy) and
# is unaffected by this general-purpose cache existing alongside it.

def _thumbnail_cache_path(
    ra_deg: float, dec_deg: float, width_arcmin: float, height_arcmin: float, size_px: int = 150,
) -> "Path":
    from galileo.platform import get_cache_dir
    # No suffix for the default 150px thumbnail size, so this doesn't change
    # the filename (and so invalidate) every thumbnail already cached before
    # size_px existed as a parameter; a non-default size (the Targets page's
    # click-to-enlarge full view, SKY-080) gets its own distinct cache entry
    # rather than colliding with — or being satisfied by — the small one.
    suffix = "" if size_px == 150 else f"_{size_px}px"
    name = f"skythumb_{ra_deg:.4f}_{dec_deg:.4f}_{width_arcmin:.2f}x{height_arcmin:.2f}{suffix}.jpg"
    return get_cache_dir() / name


def _cache_thumbnail(
    ra_deg: float, dec_deg: float, width_arcmin: float, height_arcmin: float, data: bytes, size_px: int = 150,
) -> None:
    try:
        _thumbnail_cache_path(ra_deg, dec_deg, width_arcmin, height_arcmin, size_px).write_bytes(data)
    except Exception:
        logger.debug("Could not cache sky atlas thumbnail", exc_info=True)


def _cached_thumbnail(
    ra_deg: float, dec_deg: float, width_arcmin: float, height_arcmin: float, size_px: int = 150,
) -> bytes:
    path = _thumbnail_cache_path(ra_deg, dec_deg, width_arcmin, height_arcmin, size_px)
    try:
        return path.read_bytes() if path.exists() else b""
    except Exception:
        return b""


def _fetch_hips_thumbnail_sync(
    ra_deg: float,
    dec_deg: float,
    width_arcmin: float = 15.0,
    height_arcmin: float = 15.0,
    size_px: int = 150,
) -> bytes:
    """Blocking HiPS cutout fetch (ported from Obsy's ``Target.save()``,
    ``targets/models.py``, ADR-005; migrated from STScI's dss_search CGI,
    which caps cutout size, to the CDS hips2fits service, which doesn't):
    request a pre-rendered JPEG cutout centered on (*ra_deg*, *dec_deg*) from
    the ``CDS/P/DSS2/color`` HiPS survey (no local FITS decoding/normalization
    needed, since the color survey is already an 8-bit-per-channel rendering),
    sized to a *size_px* square. Run off the UI/event-loop thread via
    ``asyncio.to_thread`` by :meth:`SkyAtlas._fetch_thumbnail`. Returns ``b""``
    on any failure rather than raising, since a missing thumbnail is never
    fatal to the caller."""
    import io

    try:
        import requests
        from PIL import Image

        fov_deg = max(width_arcmin, height_arcmin) / 60.0
        resp = requests.get(
            _HIPS2FITS_URL,
            params={
                "hips": _DSS_HIPS_SURVEY,
                "width": size_px,
                "height": size_px,
                "fov": fov_deg,
                "projection": "TAN",
                "coordsys": "icrs",
                "ra": ra_deg,
                "dec": dec_deg,
                "format": "jpg",
            },
            timeout=15,
        )
        resp.raise_for_status()
        # Round-trip through PIL to confirm the response is actually a decodable
        # image (a service error can still come back with a 200 status).
        image = Image.open(io.BytesIO(resp.content)).convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="JPEG")
        return buf.getvalue()
    except Exception:
        logger.debug(
            "Could not fetch HiPS thumbnail for RA=%s Dec=%s", ra_deg, dec_deg, exc_info=True
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
    """Searchable, filterable deep-sky object atlas (SKY-010 … SKY-120)."""

    def __init__(self, catalog: list[DeepSkyObject] | None = None) -> None:
        if catalog is not None:
            self._catalog = catalog
        else:
            self._catalog = _load_catalog()
        self._cache_dir: Path | None = None
        self._target_list: list[DeepSkyObject] = []
        self._telescopius_api_key: str | None = None

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
        """Search for *query* primarily via the offline catalog (:meth:`search`,
        SKY-010), falling back to a live Simbad lookup (ported from Obsy's
        ``target_query``, ADR-005) only when the catalog has no match — SKY-100:
        catalog-first, Simbad-fallback, so ordinary object-name search satisfies
        NFR-OFFLINE-010's no-internet guarantee the same way catalog browse/
        filter/chart already did, not just as a side effect of Simbad happening
        to be unreachable. This is the entry point the Sky Atlas page's search
        box calls; :meth:`search` itself stays local-only so core search still
        works with no internet (SKY-070/NFR-OFFLINE-010).

        When a Telescopius API key is configured (:meth:`set_telescopius_api_key`,
        SKY-110), Telescopius's own target-search/suggestion data is layered on
        top of whatever the offline-first/Simbad-fallback path above already
        found — additive, never a substitute for it, and unavailable/failed
        Telescopius augmentation never affects that path's own result."""
        q = query.strip()
        if not q:
            return list(self._catalog)
        offline_results = self.search(q)
        if offline_results:
            results = list(offline_results)
        else:
            logger.info("No offline catalog match for %r; falling back to Simbad", q)
            try:
                results = await asyncio.to_thread(_search_simbad_sync, q)
            except Exception:
                logger.info("Simbad search for %r failed; no results", q, exc_info=True)
                results = []
            if results:
                logger.info("Simbad search for %r found %d object(s)", q, len(results))
            else:
                logger.info("Simbad search for %r found no results", q)

        if self._telescopius_api_key:
            try:
                telescopius_results = await asyncio.to_thread(
                    _search_telescopius_sync, q, self._telescopius_api_key,
                )
            except Exception:
                logger.info("Telescopius search for %r unavailable; continuing without it", q, exc_info=True)
                telescopius_results = []
            for obj in telescopius_results:
                if obj not in results:
                    results.append(obj)

        return results

    def set_telescopius_api_key(self, api_key: str | None) -> None:
        """Configure (or clear, with ``None``) the user-supplied Telescopius API
        key (SKY-110/SKY-120, EXT-150) — bring-your-own-key only, entered in
        Options; Galileo neither bundles nor proxies a shared credential
        (Project Scope Document §6.9)."""
        self._telescopius_api_key = api_key or None

    @property
    def telescopius_api_key(self) -> str | None:
        return self._telescopius_api_key

    async def import_telescopius_observing_list(self, list_name: str) -> list[dict]:
        """Import the named observing list from the user's own Telescopius
        account (SKY-120, EXT-150) as target dicts (``name``/``ra_deg``/
        ``dec_deg``) ready to feed into a session/target list. Raises
        :class:`TelescopiusNotConfiguredError` with no API key configured —
        unlike search augmentation (SKY-110), this is an explicit user-triggered
        action with no offline fallback to degrade to, so a clear failure is
        more useful than silently importing nothing."""
        if not self._telescopius_api_key:
            raise TelescopiusNotConfiguredError(
                "No Telescopius API key configured — set one in Options to import an observing list."
            )
        return await asyncio.to_thread(
            _fetch_telescopius_observing_list_sync, list_name, self._telescopius_api_key,
        )

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
        max_size_arcmin: float = 0.0,
        location: "ObservingLocation | None" = None,
        visible_tonight: bool = False,
        min_altitude_deg: float = 20.0,
        min_duration_hours: float = 0.0,
        min_moon_separation_deg: float = 0.0,
        catalogs: "set[str] | None" = None,
        date_str: str | None = None,
    ) -> list[DeepSkyObject]:
        """Filter the catalog by type, magnitude, size (a min/max range — a
        catalog object with no recorded size, ``size_arcmin`` 0, always passes
        *max_size_arcmin*, the same way it already always failed a nonzero
        *min_size_arcmin*, so an unmeasured size is only ever a filter-out
        via the min bound, never the max one), visibility (SKY-020) — when
        *visible_tonight* is set with a *location*, reaches at least
        *min_altitude_deg* (default 20°) for at least *min_duration_hours*
        (default 0 — any single sample at/above the threshold counts, matching
        the original SKY-020 check) tonight, matching the reference
        Telescopius layout's "reach an altitude of X for at least Y hours"
        filter (`assets/samples/target.png`) — Moon distance: with a
        *location* and *min_moon_separation_deg* > 0, excludes anything closer
        to the Moon (at local midnight, a single reference time, not tracked
        across the night) than that, matching that same layout's "Distance
        from the Moon" filter. The Moon's own position is computed once for
        the whole call, not per object, so this stays cheap even against the
        full catalog — and *catalogs*: a subset of :data:`DSO_CATALOGS`
        (Messier/Caldwell/NGC) an object must belong to at least one of
        (:func:`catalogs_of`), matching that same layout's "Catalog" filter —
        the same catalog-membership logic the Star Atlas/skymap's own overlay
        toggles already use (`galileo.ui.star_atlas`), reused here rather than
        duplicated for a second purpose."""
        from galileo.planning.visibility import is_observable_tonight, moon_position_deg, moon_separation_deg

        moon_pos = moon_position_deg(location, date_str) if min_moon_separation_deg > 0 and location else None

        results = []
        for o in self._catalog:
            if object_types and o.object_type not in object_types:
                continue
            if o.magnitude > max_magnitude:
                continue
            if o.size_arcmin < min_size_arcmin:
                continue
            if max_size_arcmin > 0 and o.size_arcmin > max_size_arcmin:
                continue
            if catalogs and not (catalogs_of(o) & catalogs):
                continue
            if visible_tonight and location:
                if not is_observable_tonight(
                    o.ra_deg, o.dec_deg, location, date_str, min_altitude_deg, min_duration_hours,
                ):
                    continue
            if moon_pos is not None:
                if moon_separation_deg(o.ra_deg, o.dec_deg, *moon_pos) < min_moon_separation_deg:
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
        from galileo.planning.visibility import altitude_chart
        horizon = getattr(location, "_horizon", None)
        return altitude_chart(obj.ra_deg, obj.dec_deg, location, date, horizon)

    def altitude_charts_batch(
        self,
        objs: list[DeepSkyObject],
        location: "ObservingLocation",
        date: str | None = None,
    ) -> list[dict]:
        """:meth:`altitude_chart` for many *objs* at once, ~16x faster than
        calling it per object (one vectorized astropy transform instead of
        many) — see :func:`galileo.planning.visibility.altitude_charts_batch`.
        No horizon-obstruction support, unlike :meth:`altitude_chart` itself."""
        from galileo.planning.visibility import altitude_charts_batch
        return altitude_charts_batch([(o.ra_deg, o.dec_deg) for o in objs], location, date)

    def rise_transit_set(
        self,
        obj: DeepSkyObject,
        location: "ObservingLocation",
        date: str | None = None,
        chart: "dict | None" = None,
    ) -> dict:
        """Return *obj*'s rise/transit/set times from *location* tonight
        (SKY-030). Pass an already-computed *chart* (:meth:`altitude_chart`/
        one element of :meth:`altitude_charts_batch`) to skip recomputing it."""
        from galileo.planning.visibility import rise_transit_set
        horizon = getattr(location, "_horizon", None)
        return rise_transit_set(obj.ra_deg, obj.dec_deg, location, date, horizon, chart=chart)

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

    async def _fetch_thumbnail(self, obj: DeepSkyObject, size_px: int = 150) -> bytes:
        """Fetch a DSS2 color sky-survey cutout thumbnail for *obj* via the CDS
        hips2fits service (SKY-080), ported from Obsy's ``Target.save()``
        (``targets/models.py``, ADR-005): a field sized around *obj*'s own
        angular size (:func:`_thumbnail_field_arcmin`) rather than a fixed
        window, cropped as a *size_px* square JPEG (default 150, the small
        result-tile thumbnail size; a caller wanting a bigger click-to-enlarge
        view — the Targets page's full-image overlay — passes a larger
        *size_px*, over the *same* field of view, just more pixels of it).
        Checks the on-disk cache (:func:`_cached_thumbnail`, keyed by
        ra/dec/field/size_px) first and writes a successful fetch back to it
        (:func:`_cache_thumbnail`), so re-fetching the same object at the same
        size — a later search's result tile, or reopening the full-image
        overlay — is a disk read rather than another network request. Returns
        ``b""`` on any failure (no internet, an unreadable response, ...) so a
        missing thumbnail never blocks add-to-target-list or the Sky Atlas
        page's result display."""
        field_arcmin = _thumbnail_field_arcmin(obj.size_arcmin)
        cached = _cached_thumbnail(obj.ra_deg, obj.dec_deg, field_arcmin, field_arcmin, size_px)
        if cached:
            return cached
        data = await asyncio.to_thread(
            _fetch_hips_thumbnail_sync, obj.ra_deg, obj.dec_deg, field_arcmin, field_arcmin, size_px,
        )
        if data:
            _cache_thumbnail(obj.ra_deg, obj.dec_deg, field_arcmin, field_arcmin, data, size_px)
        return data

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
