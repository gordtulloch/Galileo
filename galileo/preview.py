# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Server-side previews and tiles for remote clients and the outreach guest mode (PREV-010 to PREV-060).

``PreviewService.render`` turns a frame reference into a stretched, binned, size-limited JPEG with an
optional histogram and statistics; ``tile`` serves a pyramid so a client can pan and zoom. Results are
cached under a byte budget (least recently used out). Rendering never runs on the UI thread: the
numpy work runs in a worker thread, star statistics go to the process pool (they hold the GIL), and
under a running session the service shrinks size and quality instead of delaying imaging.

Guest mode encodes from pixel data only — no FITS header, EXIF or comment can reach the output — and
:func:`assert_clean` refuses any JPEG that carries more than the picture. Guest output is never cached.
"""

from __future__ import annotations

import asyncio
import io
import threading
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

TILE = 256
DEFAULT_BUDGET = 64 * 1024 * 1024
GUEST_MAX_SIZE = 1024
GUEST_QUALITY = 75
BUSY_MAX_SIZE = 512
BUSY_QUALITY = 70
# For a Gaussian star, FWHM = 2.355 sigma and the flux-weighted mean radius (our HFR) = 1.253 sigma.
FWHM_PER_HFR = 2.355 / 1.253


class PreviewError(Exception):
    """A preview that cannot be made (unknown frame, unsafe output)."""


@dataclass(frozen=True)
class PreviewParams:
    stretch: int = 50                 # 0..100: how much of each tail is clipped (IMG-190)
    bin: int = 1                      # 1, 2, 3 or 4
    max_size: int = 1024              # longest side in pixels
    quality: int = 85                 # JPEG quality
    histogram: bool = False
    stats: bool = False               # star count, HFR, FWHM
    guest: bool = False

    def clamped(self, max_size_limit: int, quality_limit: int) -> PreviewParams:
        """The same request inside the bounds of the options ``preview.max_size`` / ``preview.quality``
        (PREV-060); a guest is held to the stricter guest limits."""
        size_cap = min(max_size_limit, GUEST_MAX_SIZE) if self.guest else max_size_limit
        quality_cap = min(quality_limit, GUEST_QUALITY) if self.guest else quality_limit
        return PreviewParams(
            stretch=max(0, min(100, self.stretch)), bin=max(1, min(4, self.bin)),
            max_size=max(16, min(size_cap, self.max_size)), quality=max(10, min(quality_cap, self.quality)),
            histogram=self.histogram and not self.guest, stats=self.stats and not self.guest, guest=self.guest)

    def degraded(self) -> PreviewParams:
        """Smaller and lighter, for use while a session is running (PREV-040)."""
        return PreviewParams(self.stretch, self.bin, min(self.max_size, BUSY_MAX_SIZE),
                             min(self.quality, BUSY_QUALITY), self.histogram, self.stats, self.guest)


@dataclass(frozen=True)
class Preview:
    data: bytes
    width: int
    height: int
    content_type: str = "image/jpeg"
    histogram: dict[str, list[float]] | None = None
    stats: dict[str, float] | None = None
    degraded: bool = False


# A source gives ``(version, pixels)`` for a frame reference, or None. ``version`` changes when the
# frame behind a reference does (a new exposure), so a cached preview is never stale.
Source = Callable[[str], tuple[str, np.ndarray] | None]


class PreviewCache:
    """Least-recently-used cache bounded by bytes (PREV-030)."""

    def __init__(self, budget: int = DEFAULT_BUDGET) -> None:
        self._budget, self._used = budget, 0
        self._items: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
        self._sizes: dict[tuple[Any, ...], int] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple[Any, ...]) -> Any | None:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
            return None

    def put(self, key: tuple[Any, ...], value: Any, size: int) -> None:
        if size > self._budget:
            return
        with self._lock:
            if key in self._items:
                self._used -= self._sizes[key]
            self._items[key], self._sizes[key] = value, size
            self._items.move_to_end(key)
            self._used += size
            while self._used > self._budget:
                old, _ = self._items.popitem(last=False)
                self._used -= self._sizes.pop(old)

    @property
    def used(self) -> int:
        return self._used

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._sizes.clear()
            self._used = 0


# -- pure numpy / Pillow steps -----------------------------------------------------------------
def _plane(data: np.ndarray) -> np.ndarray:
    """Float32 ``(h, w)`` or ``(h, w, 3)``; a channel-first cube is moved to channel-last."""
    d = np.asarray(data)
    if d.ndim == 3 and d.shape[0] in (3, 4) and d.shape[-1] not in (3, 4):
        d = np.moveaxis(d, 0, -1)
    if d.ndim == 3:
        d = d[..., :3]
    if d.ndim not in (2, 3):
        raise PreviewError("not an image")
    return d.astype(np.float32, copy=False)


def _bin(d: np.ndarray, n: int) -> np.ndarray:
    if n <= 1:
        return d
    h, w = (d.shape[0] // n) * n, (d.shape[1] // n) * n
    d = d[:h, :w]
    return d.reshape(h // n, n, w // n, n, *d.shape[2:]).mean(axis=(1, 3))


def stretch_limits(d: np.ndarray, level: int) -> tuple[np.ndarray, np.ndarray]:
    """Per-plane (lo, hi) clip points: ``level`` 0..100 clips up to 2.5 % from each tail."""
    margin = max(0, min(100, level)) / 40.0
    planes = d if d.ndim == 3 else d[..., None]
    lo = np.array([np.percentile(planes[..., i], margin) for i in range(planes.shape[-1])])
    hi = np.array([np.percentile(planes[..., i], 100.0 - margin) for i in range(planes.shape[-1])])
    return lo, hi


def apply_stretch(d: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    planes = d if d.ndim == 3 else d[..., None]
    out = np.clip((planes - lo) / (hi - lo + 1e-9), 0, 1)
    out = (out * 255).astype(np.uint8)
    return out if d.ndim == 3 else out[..., 0]


def _fit(img: Any, max_size: int) -> Any:
    from PIL import Image
    w, h = img.size
    scale = max_size / max(w, h)
    if scale >= 1:
        return img
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.BILINEAR)


def _encode(arr: np.ndarray, quality: int) -> bytes:
    """JPEG from pixels alone: Pillow is given no EXIF, ICC profile or comment."""
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG", quality=quality, optimize=False, exif=b"", icc_profile=None)
    return buf.getvalue()


def _histogram(d: np.ndarray) -> dict[str, list[float]]:
    counts, edges = np.histogram(d.ravel(), bins=256)
    return {"bins": edges[:-1].tolist(), "counts": counts.tolist()}


def _star_stats(frame: np.ndarray) -> dict[str, float]:
    """Module-level so it can go to the process pool (SEP holds the GIL)."""
    from galileo.autofocus import _measure_stars
    gray = frame if frame.ndim == 2 else frame.mean(axis=-1)
    hfr, count = _measure_stars(gray)
    return {"star_count": float(count), "hfr": float(hfr), "fwhm": float(hfr) * FWHM_PER_HFR if count else 0.0}


def assert_clean(jpeg: bytes) -> None:
    """Raise unless *jpeg* holds nothing but the picture (PREV-050): no APPn segment other than the bare
    JFIF header, no comment, no trailing data. A guest preview must never carry metadata."""
    if jpeg[:2] != b"\xff\xd8":
        raise PreviewError("not a JPEG")
    i, n = 2, len(jpeg)
    while i + 4 <= n:
        if jpeg[i] != 0xFF:
            raise PreviewError("malformed JPEG")
        marker = jpeg[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0xD9:
            if i + 2 != n:
                raise PreviewError("data after the end of the image")
            return
        length = int.from_bytes(jpeg[i + 2:i + 4], "big")
        body = jpeg[i + 4:i + 2 + length]
        if marker == 0xE0:
            if not body.startswith(b"JFIF\x00"):
                raise PreviewError("unexpected APP0 segment")
        elif 0xE1 <= marker <= 0xEF or marker == 0xFE:
            raise PreviewError(f"metadata segment 0x{marker:02X} in a guest image")
        if marker == 0xDA:                           # start of scan: the entropy-coded data follows
            end = jpeg.rfind(b"\xff\xd9")
            if end < 0 or end + 2 != n:
                raise PreviewError("malformed JPEG")
            return
        i += 2 + length
    raise PreviewError("malformed JPEG")


class PreviewService:
    def __init__(self, sources: dict[str, Source], *, cache: PreviewCache | None = None,
                 busy: Callable[[], bool] | None = None, max_size_limit: int = 4096, quality_limit: int = 95,
                 star_stats: Callable[[np.ndarray], Awaitable[dict[str, float]]] | None = None) -> None:
        self._sources = sources
        self.cache = cache if cache is not None else PreviewCache()
        self._busy = busy or (lambda: False)
        self._max_size, self._quality = max_size_limit, quality_limit
        self._star_stats = star_stats

    def _load(self, ref: str) -> tuple[str, np.ndarray]:
        kind = ref.split(":", 1)[0]
        source = self._sources.get(kind)
        found = source(ref) if source else None
        if found is None:
            raise PreviewError("no such frame")
        return found

    def _effective(self, params: PreviewParams) -> tuple[PreviewParams, bool]:
        p = params.clamped(self._max_size, self._quality)
        if self._busy():
            smaller = p.degraded()
            return smaller, smaller != p
        return p, False

    async def render(self, ref: str, params: PreviewParams | None = None) -> Preview:
        params, degraded = self._effective(params or PreviewParams())
        version, data = await asyncio.to_thread(self._load, ref)
        key = ("preview", ref, version, params)
        if not params.guest:
            hit = self.cache.get(key)
            if hit is not None:
                return hit
        preview = await asyncio.to_thread(self._render, data, params, degraded)
        if params.stats:
            stats = await self._stats(_plane(data))
            preview = Preview(**{**preview.__dict__, "stats": stats})
        if not params.guest:                         # PREV-030 / PREV-050: nothing a guest sees is cached
            self.cache.put(key, preview, len(preview.data))
        return preview

    @staticmethod
    def _render(data: np.ndarray, params: PreviewParams, degraded: bool) -> Preview:
        from PIL import Image
        d = _bin(_plane(data), params.bin)
        lo, hi = stretch_limits(d, params.stretch)
        img = _fit(Image.fromarray(apply_stretch(d, lo, hi)), params.max_size)
        arr = np.asarray(img)
        jpeg = _encode(arr, params.quality)
        if params.guest:
            assert_clean(jpeg)
        return Preview(jpeg, img.width, img.height, histogram=_histogram(d) if params.histogram else None,
                       degraded=degraded)

    async def _stats(self, frame: np.ndarray) -> dict[str, float]:
        if self._star_stats is not None:
            return await self._star_stats(frame)
        from galileo.core.compute import run_cpu
        return dict(await run_cpu(_star_stats, frame))

    # -- tiles (PREV-020) --------------------------------------------------------------------
    async def tile(self, ref: str, level: int, x: int, y: int, params: PreviewParams | None = None) -> bytes:
        """One 256-pixel JPEG tile of the pyramid: level 0 is full resolution, each level halves it. The
        stretch is fixed per frame, so neighbouring tiles join without seams and two frames asked for
        with the same parameters can be compared tile for tile."""
        params, _ = self._effective(params or PreviewParams())
        if params.guest:
            raise PreviewError("tiles are not offered to guests")
        version, data = await asyncio.to_thread(self._load, ref)
        key = ("tile", ref, version, level, x, y, params)
        hit = self.cache.get(key)
        if hit is not None:
            return bytes(hit)
        jpeg = await asyncio.to_thread(self._tile, data, level, x, y, params)
        self.cache.put(key, jpeg, len(jpeg))
        return jpeg

    @staticmethod
    def _tile(data: np.ndarray, level: int, x: int, y: int, params: PreviewParams) -> bytes:
        from PIL import Image
        if not 0 <= level <= 12 or x < 0 or y < 0:
            raise PreviewError("no such tile")
        d = _bin(_plane(data), params.bin)
        lo, hi = stretch_limits(d, params.stretch)             # from the whole frame, not the tile
        img = Image.fromarray(apply_stretch(d, lo, hi))
        if level:
            f = 1 << level
            img = img.resize((max(1, img.width // f), max(1, img.height // f)), Image.Resampling.BILINEAR)
        left, top = x * TILE, y * TILE
        if left >= img.width or top >= img.height:
            raise PreviewError("no such tile")
        return _encode(np.asarray(img.crop((left, top, min(left + TILE, img.width), min(top + TILE, img.height)))),
                       params.quality)

    @staticmethod
    def tile_grid(shape: tuple[int, ...], level: int, bin_: int = 1) -> tuple[int, int]:
        """Tiles across and down at *level* for a frame of *shape*."""
        h, w = shape[0] // max(1, bin_), shape[1] // max(1, bin_)
        f = 1 << level
        return -(-max(1, w // f) // TILE), -(-max(1, h // f) // TILE)


__all__ = ["BUSY_MAX_SIZE", "GUEST_MAX_SIZE", "GUEST_QUALITY", "TILE", "Preview", "PreviewCache", "PreviewError",
           "PreviewParams", "PreviewService", "Source", "apply_stretch", "assert_clean", "stretch_limits"]
