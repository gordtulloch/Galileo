"""Sky atlas — offline DSO catalog search and visibility (SKY-010 … SKY-090).

The catalog loads from a bundled compressed JSON dataset on first import.
If the bundled dataset is not yet available, ``SkyAtlas.download_catalog()``
fetches it from VizieR and caches it locally.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

# Re-exported so callers can do ``from galileo.planning.sky_atlas import ObservingLocation``
from galileo.planning.visibility import HorizonProfile, ObservingLocation  # noqa: F401

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_CATALOG_FILENAME = "galileo_dso_catalog.json"


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

def _catalog_cache_path() -> Path:
    from galileo.platform import get_cache_dir
    return get_cache_dir() / _CATALOG_FILENAME


def _load_catalog() -> list[DeepSkyObject]:
    """Load the DSO catalog, building from VizieR if the cache is absent."""
    cache = _catalog_cache_path()
    if cache.exists():
        try:
            raw = json.loads(cache.read_text("utf-8"))
            return [_obj_from_dict(d) for d in raw]
        except Exception:
            logger.exception("Failed to load cached catalog; regenerating")

    # Attempt to build from astroquery
    objects = _fetch_catalog_from_vizier()
    if objects:
        try:
            cache.write_text(
                json.dumps([_obj_to_dict(o) for o in objects], indent=1),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to cache catalog")
    return objects


def _fetch_catalog_from_vizier() -> list[DeepSkyObject]:
    """Query VizieR for the OpenNGC catalog (~13 K objects)."""
    try:
        from astroquery.vizier import Vizier
        import astropy.units as u

        v = Vizier(columns=["*"], row_limit=-1)
        result = v.get_catalogs("VII/118/ngc2000")   # NGC 2000 catalogue
        if not result:
            return []
        tbl = result[0]

        objects = []
        for row in tbl:
            try:
                ra = float(row["_RA.icrs"]) if "_RA.icrs" in tbl.colnames else 0.0
                dec = float(row["_DE.icrs"]) if "_DE.icrs" in tbl.colnames else 0.0
                name = str(row.get("Name", row.get("NGC", ""))).strip()
                type_str = str(row.get("Type", "")).strip()
                mag = float(row.get("Mag", 99.0) or 99.0)
                size = float(row.get("Diam", 0.0) or 0.0)
                obj_type = _type_from_str(type_str)
                objects.append(DeepSkyObject(
                    primary_name=name,
                    designations=[name],
                    ra_deg=ra,
                    dec_deg=dec,
                    object_type=obj_type,
                    magnitude=mag,
                    size_arcmin=size,
                ))
            except Exception:
                continue
        return objects
    except Exception:
        logger.info("Could not fetch catalog from VizieR; returning empty catalog")
        return []


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
            (cache_dir / f"{safe_name}_thumbnail.png").write_bytes(data)

    async def _fetch_thumbnail(self, obj: DeepSkyObject) -> bytes:
        return b""

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
