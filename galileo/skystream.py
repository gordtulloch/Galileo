# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Sky data for remote clients (SKYSTR-010 to SKYSTR-080).

A read-only service over the bundled catalog and the existing ephemeris — there is no second catalog.
It serves catalog objects by region, magnitude and level of detail, progressively (brightest first) with
a cursor that resumes an interrupted stream; ephemeris for an instant or a range; the site, horizon and
live pointing; and a static sky image for a client that cannot draw the sky itself. Every response
carries the Master's as-of time. Encoding is compact, quantised and delta-coded (schema version 1).
Streaming yields to a running session by lowering detail before it delays anything, is rate-limited per
client and capped in concurrent clients by a capability worked out from a measurement of this machine.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import math
import struct
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from galileo.core.ratelimit import RateLimiter

ENCODING_VERSION = 1
SUPPORTED_ENCODINGS = (1,)
MAGIC = b"GSK"
KIND_CATALOG = 1
# Magnitude cap for each level of detail (0 = coarsest); the last level is "everything".
LOD_MAGNITUDE = (4.0, 7.0, 10.0, 13.0, 99.0)
PAGE_SIZE = 500
BUSY_PAGE_SIZE = 100
MAX_RANGE_POINTS = 1440
_QUANTUM = 1000                 # degrees * 1000 -> 3.6 arcsecond steps
_MAG_QUANTUM = 100


class SkyStreamError(Exception):
    """A request the service cannot or will not serve; ``status`` is an HTTP-style code."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# -- the binary encoding (versioned schema) ------------------------------------------------------
def _put_varint(out: bytearray, value: int) -> None:
    value = (value << 1) ^ (value >> 63)                     # zigzag: small magnitudes stay small
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)


def _get_varint(buf: bytes, pos: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7
    return (result >> 1) ^ -(result & 1), pos


@dataclass(frozen=True)
class SkyObject:
    index: int          # position in the catalog, stable for a given catalog
    ra: float           # degrees, J2000
    dec: float
    mag: float
    kind: int = 0       # 0 star, 1 deep-sky object


def encode_objects(objects: list[SkyObject], version: int = ENCODING_VERSION) -> bytes:
    """Header (magic, version, kind, count) then, sorted by RA, delta-coded varints for RA, Dec, magnitude
    and catalog index, and one byte of object kind."""
    if version not in SUPPORTED_ENCODINGS:
        raise SkyStreamError(f"encoding {version} is not offered", 406)
    out = bytearray(MAGIC + struct.pack("<BBI", version, KIND_CATALOG, len(objects)))
    p_ra = p_dec = p_mag = p_idx = 0
    for o in sorted(objects, key=lambda x: x.ra):
        ra, dec = round(o.ra * _QUANTUM), round(o.dec * _QUANTUM)
        mag, idx = round(o.mag * _MAG_QUANTUM), o.index
        for value, previous in ((ra, p_ra), (dec, p_dec), (mag, p_mag), (idx, p_idx)):
            _put_varint(out, value - previous)
        out.append(o.kind)
        p_ra, p_dec, p_mag, p_idx = ra, dec, mag, idx
    return bytes(out)


def decode_objects(buf: bytes) -> list[SkyObject]:
    """The inverse of :func:`encode_objects` (what a client does); positions come back to the quantum."""
    if buf[:3] != MAGIC:
        raise SkyStreamError("not a sky stream")
    version, kind, count = struct.unpack_from("<BBI", buf, 3)
    if version not in SUPPORTED_ENCODINGS or kind != KIND_CATALOG:
        raise SkyStreamError(f"unsupported encoding {version}", 406)
    pos, p = 3 + 6, [0, 0, 0, 0]
    out = []
    for _ in range(count):
        for i in range(4):
            delta, pos = _get_varint(buf, pos)
            p[i] += delta
        out.append(SkyObject(p[3], p[0] / _QUANTUM, p[1] / _QUANTUM, p[2] / _MAG_QUANTUM, buf[pos]))
        pos += 1
    return out


# -- sources ------------------------------------------------------------------------------------
class SkyCatalog(Protocol):
    """Columns of every object, parallel arrays in catalog order."""

    ra: np.ndarray
    dec: np.ndarray
    mag: np.ndarray
    kind: np.ndarray


@dataclass
class ArrayCatalog:
    ra: np.ndarray
    dec: np.ndarray
    mag: np.ndarray
    kind: np.ndarray


def bundled_catalog() -> ArrayCatalog:
    """Stars (kind 0) and deep-sky objects (kind 1) from the catalogs the sky views already use."""
    from galileo.planning.sky_atlas import SkyAtlas
    from galileo.planning.star_atlas import load_star_catalog
    stars = load_star_catalog()
    dso = SkyAtlas().filter()
    ra = np.concatenate([stars.ra, np.array([o.ra_deg for o in dso])])
    dec = np.concatenate([stars.dec, np.array([o.dec_deg for o in dso])])
    mag = np.concatenate([stars.mag, np.array([o.magnitude if o.magnitude < 90 else 99.0 for o in dso])])
    kind = np.concatenate([np.zeros(len(stars), np.uint8), np.ones(len(dso), np.uint8)])
    return ArrayCatalog(ra.astype(np.float64), dec.astype(np.float64), mag.astype(np.float64), kind)


def angular_separation_deg(ra1: Any, dec1: Any, ra2: float, dec2: float) -> Any:
    a1, d1, a2, d2 = np.radians(ra1), np.radians(dec1), math.radians(ra2), math.radians(dec2)
    c = np.sin(d1) * math.sin(d2) + np.cos(d1) * math.cos(d2) * np.cos(a1 - a2)
    return np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))


@dataclass(frozen=True)
class Capability:
    available: bool                  # whether streaming is offered at all
    vr_available: bool               # full-detail streaming for a headset
    max_clients: int
    max_page: int
    rate_per_s: float
    encodings: tuple[int, ...]
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"available": self.available, "vr_available": self.vr_available,
                "max_clients": self.max_clients, "max_page": self.max_page, "rate_per_s": self.rate_per_s,
                "encodings": list(self.encodings), **({"reason": self.reason} if self.reason else {})}


def derive_capability(page_ms: float) -> Capability:
    """Streaming limits from how long this machine takes to build and encode a page (SKYSTR-060) — a
    measurement, not a platform name. A fast machine serves VR-class streaming; a slow one serves
    tablets, phones and browsers with reduced limits and says why VR is not offered."""
    if page_ms < 40:
        return Capability(True, True, 4, PAGE_SIZE, 20.0, SUPPORTED_ENCODINGS)
    if page_ms < 250:
        return Capability(True, False, 2, 250, 8.0, SUPPORTED_ENCODINGS,
                          "This computer builds sky pages too slowly for headset-class streaming.")
    return Capability(True, False, 1, BUSY_PAGE_SIZE, 3.0, SUPPORTED_ENCODINGS,
                      "This computer is too slow for headset-class streaming; reduced limits apply.")


class SkyStreamService:
    def __init__(
        self, catalog: Callable[[], SkyCatalog] | SkyCatalog, *,
        ephemeris: Callable[[dt.datetime], list[dict[str, Any]]] | None = None,
        site: Callable[[], dict[str, Any]] | None = None,
        pointing: Callable[[], dict[str, Any] | None] | None = None,
        busy: Callable[[], bool] | None = None, clock: Callable[[], float] = time.time,
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._catalog_src = catalog
        self._catalog: SkyCatalog | None = None if callable(catalog) else catalog
        self._ephemeris, self._site, self._pointing = ephemeris, site, pointing
        self._busy = busy or (lambda: False)
        self._clock, self._timer = clock, timer
        self._capability: Capability | None = None
        self._limiter: RateLimiter | None = None
        self._active: set[str] = set()

    # -- common ------------------------------------------------------------------------
    def as_of(self) -> str:
        return dt.datetime.fromtimestamp(self._clock(), dt.UTC).isoformat()

    def _cat(self) -> SkyCatalog:
        if self._catalog is None:
            self._catalog = self._catalog_src() if callable(self._catalog_src) else self._catalog_src  # type: ignore[assignment]
        assert self._catalog is not None  # noqa: S101 - just assigned
        return self._catalog

    # -- capability (SKYSTR-060) -------------------------------------------------------
    def benchmark(self) -> Capability:
        """Time building and encoding one full page, then derive the limits from it."""
        start = self._timer()
        cat = self._cat()
        n = len(cat.ra)
        if n:
            self._page(cat, float(cat.ra[0]), float(cat.dec[0]), 180.0, 99.0, 0, PAGE_SIZE)
        page_ms = (self._timer() - start) * 1000.0
        self._capability = derive_capability(page_ms)
        self._limiter = RateLimiter(self._clock, capacity=max(2, int(self._capability.rate_per_s)),
                                    per_s=self._capability.rate_per_s)
        return self._capability

    def capability(self) -> Capability:
        return self._capability or self.benchmark()

    # -- concurrency and rate (SKYSTR-070) ----------------------------------------------
    @contextmanager
    def stream(self, client: str):
        """Hold a streaming slot; refused when the cap is reached or the client is over its rate."""
        cap = self.capability()
        if client not in self._active and len(self._active) >= cap.max_clients:
            raise SkyStreamError("the sky stream is serving as many clients as this computer can", 503)
        assert self._limiter is not None  # noqa: S101 - set by benchmark()
        if not self._limiter.allow(client):
            raise SkyStreamError("too many requests; slow down", 429)
        self._active.add(client)
        try:
            yield
        finally:
            self._active.discard(client)

    # -- catalog (SKYSTR-010, 020) ---------------------------------------------------------
    @staticmethod
    def _page(cat: SkyCatalog, ra: float, dec: float, radius: float, mag_limit: float, offset: int,
              size: int) -> tuple[list[SkyObject], int, int]:
        sep = angular_separation_deg(cat.ra, cat.dec, ra, dec)
        picked = np.nonzero((sep <= radius) & (cat.mag <= mag_limit))[0]
        order = picked[np.argsort(cat.mag[picked], kind="stable")]          # brightest first
        window = order[offset:offset + size]
        objs = [SkyObject(int(i), float(cat.ra[i]), float(cat.dec[i]), float(cat.mag[i]), int(cat.kind[i]))
                for i in window]
        return objs, len(order), offset + len(window)

    @staticmethod
    def _query_id(ra: float, dec: float, radius: float, mag_limit: float) -> str:
        return hashlib.sha256(f"{ra:.4f}|{dec:.4f}|{radius:.3f}|{mag_limit:.2f}".encode()).hexdigest()[:8]

    async def catalog(self, ra: float, dec: float, radius: float, limit_mag: float = 99.0, lod: int = 4,
                      cursor: str = "", encoding: int = ENCODING_VERSION) -> dict[str, Any]:
        """One page of objects in the region, brightest first, as encoded bytes plus a continuation cursor
        (``""`` when done). While a session runs the page and the detail shrink instead of the stream waiting."""
        if not (0 <= ra < 360 and -90 <= dec <= 90 and 0 < radius <= 180):
            raise SkyStreamError("region out of range")
        if encoding not in SUPPORTED_ENCODINGS:
            raise SkyStreamError(f"encoding {encoding} is not offered", 406)
        cap = self.capability()
        lod = max(0, min(len(LOD_MAGNITUDE) - 1, lod))
        busy = self._busy()
        if busy:
            lod = min(lod, 2)
        mag_limit = min(limit_mag, LOD_MAGNITUDE[lod])
        query = self._query_id(ra, dec, radius, mag_limit)
        offset = 0
        if cursor:
            try:
                tag, query_id, off = cursor.split(":")
                offset = int(off)
            except ValueError:
                raise SkyStreamError("bad cursor") from None
            if tag != "v1" or query_id != query or offset < 0:
                raise SkyStreamError("the cursor does not belong to this request")
        size = min(cap.max_page, BUSY_PAGE_SIZE if busy else PAGE_SIZE)
        objs, total, nxt = await asyncio.to_thread(self._page, self._cat(), ra, dec, radius, mag_limit, offset, size)
        data = await asyncio.to_thread(encode_objects, objs, encoding)
        return {"data": data, "count": len(objs), "total": total, "encoding": encoding, "as_of": self.as_of(),
                "next": f"v1:{query}:{nxt}" if nxt < total else "", "degraded": busy}

    # -- ephemeris (SKYSTR-030) ----------------------------------------------------------
    async def ephemeris(self, when: dt.datetime, end: dt.datetime | None = None,
                        step_s: float = 3600.0) -> dict[str, Any]:
        if self._ephemeris is None:
            raise SkyStreamError("no ephemeris is available", 503)
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.UTC)
        if end is None:
            return {"as_of": self.as_of(), "bodies": await asyncio.to_thread(self._ephemeris, when)}
        if end.tzinfo is None:
            end = end.replace(tzinfo=dt.UTC)
        if end < when or step_s <= 0 or (end - when).total_seconds() / step_s > MAX_RANGE_POINTS:
            raise SkyStreamError(f"ask for at most {MAX_RANGE_POINTS} steps, in order")
        times, t = [], when
        while t <= end:
            times.append(t)
            t += dt.timedelta(seconds=step_s)
        series = [{"time": t.isoformat(), "bodies": await asyncio.to_thread(self._ephemeris, t)} for t in times]
        return {"as_of": self.as_of(), "series": series}

    # -- site and pointing (SKYSTR-040) --------------------------------------------------
    def site(self) -> dict[str, Any]:
        return {"as_of": self.as_of(), **(self._site() if self._site else {})}

    def pointing(self) -> dict[str, Any]:
        return {"as_of": self.as_of(), "mount": self._pointing() if self._pointing else None}


# -- the static sky image (SKYSTR-080) --------------------------------------------------------------
def project(ra: Any, dec: Any, ra0: float, dec0: float) -> tuple[Any, Any, Any]:
    """Stereographic projection about (ra0, dec0): east to the left. Returns x, y (radians-ish) and a mask
    of points on the visible hemisphere."""
    a, d = np.radians(ra), np.radians(dec)
    a0, d0 = math.radians(ra0), math.radians(dec0)
    cosc = np.sin(d0) * np.sin(d) + math.cos(d0) * np.cos(d) * np.cos(a - a0)
    k = 2.0 / (1.0 + np.where(cosc > -0.999, cosc, -0.999))
    x = -k * np.cos(d) * np.sin(a - a0)
    y = k * (math.cos(d0) * np.sin(d) - math.sin(d0) * np.cos(d) * np.cos(a - a0))
    return x, y, cosc > 0


def render_static_image(
    cat: SkyCatalog, ra0: float, dec0: float, fov_deg: float, *, size: int = 800, limit_mag: float = 8.0,
    lines: Any | None = None, mount: tuple[float, float] | None = None, field_deg: tuple[float, float] | None = None,
    horizon: list[tuple[float, float]] | None = None,
) -> bytes:
    """A PNG of the sky about (ra0, dec0): stars to *limit_mag*, constellation lines, the mount's position,
    the field of view rectangle and the horizon. Drawn on the Master for a client that cannot render the sky."""
    import io

    from PIL import Image, ImageDraw
    img = Image.new("RGB", (size, size), (6, 10, 24))
    draw = ImageDraw.Draw(img)
    r_half = 2.0 * math.tan(math.radians(min(fov_deg, 170.0)) / 4.0)
    scale = (size / 2) / r_half

    def px(x: Any, y: Any) -> tuple[Any, Any]:
        return size / 2 + x * scale, size / 2 - y * scale

    if lines is not None and len(lines):
        x, y, ok = project(lines.ra, lines.dec, ra0, dec0)
        sx, sy = px(x, y)
        for i in range(len(lines)):
            sl = lines.polyline(i)
            pts = [(float(a), float(b)) for a, b, o in zip(sx[sl], sy[sl], ok[sl], strict=True) if o]
            if len(pts) > 1:
                draw.line(pts, fill=(40, 70, 110), width=1)
    x, y, ok = project(cat.ra, cat.dec, ra0, dec0)
    sx, sy = px(x, y)
    inside = ok & (cat.mag <= limit_mag) & (np.abs(sx - size / 2) < size / 2) & (np.abs(sy - size / 2) < size / 2)
    for j in np.nonzero(inside)[0]:
        r = max(1.0, (limit_mag - float(cat.mag[j])) * 0.55 + 1.0)
        colour = (255, 235, 200) if cat.kind[j] == 0 else (150, 220, 255)
        draw.ellipse((sx[j] - r, sy[j] - r, sx[j] + r, sy[j] + r), fill=colour)
    if horizon:
        hx, hy, hok = project(np.array([p[0] for p in horizon]), np.array([p[1] for p in horizon]), ra0, dec0)
        hsx, hsy = px(hx, hy)
        pts = [(float(a), float(b)) for a, b, o in zip(hsx, hsy, hok, strict=True) if o]
        if len(pts) > 1:
            draw.line(pts, fill=(120, 80, 40), width=2)
    if field_deg is not None:
        w, h = (field_deg[0] / fov_deg) * size, (field_deg[1] / fov_deg) * size
        cx, cy = size / 2, size / 2
        if mount is not None:
            mx, my, _ = project(np.array([mount[0]]), np.array([mount[1]]), ra0, dec0)
            cx, cy = (float(v[0]) for v in px(mx, my))
        draw.rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), outline=(255, 90, 90), width=2)
    if mount is not None:
        mx, my, mok = project(np.array([mount[0]]), np.array([mount[1]]), ra0, dec0)
        if mok[0]:
            cx, cy = (float(v[0]) for v in px(mx, my))
            draw.line((cx - 10, cy, cx + 10, cy), fill=(255, 90, 90), width=2)
            draw.line((cx, cy - 10, cx, cy + 10), fill=(255, 90, 90), width=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


__all__ = ["ENCODING_VERSION", "LOD_MAGNITUDE", "SUPPORTED_ENCODINGS", "ArrayCatalog", "Capability", "SkyObject",
           "SkyStreamError", "SkyStreamService", "angular_separation_deg", "bundled_catalog", "decode_objects",
           "derive_capability", "encode_objects", "project", "render_static_image"]
