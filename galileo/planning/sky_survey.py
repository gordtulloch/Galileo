"""Real sky behind the atlas: Axel Mellinger's all-sky Milky Way photo-mosaic, in the HiPS format (SKYMAP-100).

A HiPS survey cuts the sky into HEALPix cells at each order, 12 * 4**order of them, each a 512-pixel JPEG, so a wide view
needs a few coarse tiles and a deep one a few fine ones. Mellinger's is one continuous mosaic, so the background is even
from edge to edge. (The Digitized Sky Survey colour tiles this used first are a patchwork of photographic plates, each with
its own background level and some with no blue at all, which showed as a patchy, discontiguous sky.) The tiles are not
ours to redistribute: nothing is bundled, they are fetched to this computer's cache as they are needed, and SURVEY_CREDIT is
shown with them. Everything here runs without Qt, for the plugin too.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Callable, Iterable
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from galileo.planning.star_atlas import Viewport

logger = logging.getLogger(__name__)

SURVEY_CREDIT = "Mellinger color optical survey - (c) Axel Mellinger, via CDS"
MAX_ORDER = 4                         # the survey's finest: about 25 arcsec per pixel, as fine as the mosaic is
TILE_SIDE = 512
FETCH_ABOVE_FOV_DEG = 3.0             # a view narrower than this fetches nothing: it draws what is already held
# Tried in turn; the first that answers is remembered. The first two are CDS's own pair, the third is CDS's older host
# name (a separate DNS entry), the last is the registry's independent mirror at IAS Orsay (a different institution, so it
# survives a CDS-wide outage).
_MIRRORS = ("https://alasky.cds.unistra.fr/MellingerRGB", "https://alaskybis.cds.unistra.fr/MellingerRGB",
            "https://alasky.u-strasbg.fr/MellingerRGB", "https://healpix.ias.u-psud.fr/CDS_P_Mellinger_color")
_ORDER0_DEG_PER_PIXEL = 58.63 / TILE_SIDE
_MEMORY_TILES = 128                   # decoded, at 0.75 MB each
_MAX_VIEW_TILES = 96                  # never ask for more than memory can hold at once
_DISK_LIMIT_BYTES = 1024 * 1024 * 1024
_RETRY_FAILED_S = 300.0
_OFFLINE_PAUSE_S = 60.0
_WORKERS = 4


# ---------------------------------------------------------------------------
# HEALPix
# ---------------------------------------------------------------------------

def face_xy(ra_deg, dec_deg) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The base cell (0-11) of J2000 positions and where in it they are, x and y each 0-1 (HEALPix nested)."""
    ra = np.radians(np.asarray(ra_deg, dtype=float))
    z = np.sin(np.radians(np.asarray(dec_deg, dtype=float)))
    tt = (ra / (np.pi / 2.0)) % 4.0
    jp, jm = 0.5 + tt - 0.75 * z, 0.5 + tt + 0.75 * z
    ifp, ifm = np.floor(jp), np.floor(jm)
    face_eq = np.where(ifp == ifm, (ifp % 4) + 4, np.where(ifp < ifm, ifp % 4, (ifm % 4) + 8))
    x_eq, y_eq = jm - ifm, 1.0 - (jp - ifp)
    ntt = np.minimum(np.floor(tt), 3.0)
    tp = tt - ntt
    tmp = np.sqrt(3.0 * (1.0 - np.abs(z)))
    a, b = np.minimum(tp * tmp, 1.0), np.minimum((1.0 - tp) * tmp, 1.0)
    north = z > 0.0
    face_polar = np.where(north, ntt, ntt + 8)
    x_polar, y_polar = np.where(north, 1.0 - b, a), np.where(north, 1.0 - a, b)
    equatorial = np.abs(z) <= 2.0 / 3.0
    return (np.where(equatorial, face_eq, face_polar).astype(np.int64),
            np.where(equatorial, x_eq, x_polar), np.where(equatorial, y_eq, y_polar))


def _tile_in_face(face, x, y, order: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    side = 1 << order
    tx = np.minimum((x * side).astype(np.int64), side - 1)
    ty = np.minimum((y * side).astype(np.int64), side - 1)
    npix = np.zeros_like(tx)
    for bit in range(order):
        npix |= ((tx >> bit) & 1) << (2 * bit)
        npix |= ((ty >> bit) & 1) << (2 * bit + 1)
    return face * (1 << (2 * order)) + npix, x * side - tx, y * side - ty


def tile_of(ra_deg, dec_deg, order: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The tile holding J2000 positions, and where in it, fx and fy each 0-1. In the tile's image the column is ``fy``
    and the row ``fx`` (measured: it puts catalog stars on the photographs' stars; no other of the 8 symmetries does)."""
    face, x, y = face_xy(ra_deg, dec_deg)
    return _tile_in_face(face, x, y, order)


def order_for(deg_per_screen_pixel: float) -> int:
    """The order to draw at: one finer than just matching the screen, because a tile's JPEG blocks show otherwise."""
    return max(0, min(MAX_ORDER, 1 + math.ceil(math.log2(_ORDER0_DEG_PER_PIXEL / max(deg_per_screen_pixel, 1e-6)))))


# ---------------------------------------------------------------------------
# Getting tiles
# ---------------------------------------------------------------------------

_fetch_lock = threading.Lock()
_mirrors = list(_MIRRORS)
_offline_until = 0.0
_written = 0


def _cache_root() -> Path:
    from galileo.platform import get_cache_dir
    return Path(get_cache_dir()) / "sky_survey" / "MellingerRGB"


def _tile_path(order: int, npix: int) -> str:
    return f"Norder{order}/Dir{(npix // 10000) * 10000}/Npix{npix}.jpg"


def _fetch_tile(order: int, npix: int) -> bytes | None:
    """From the first mirror that answers. No such tile is ``None``; every mirror unreachable raises ``OSError``."""
    global _offline_until
    if time.monotonic() < _offline_until:
        raise OSError("not trying again yet")
    with _fetch_lock:
        order_tried = list(_mirrors)
    for base in order_tried:
        request = urllib.request.Request(f"{base}/{_tile_path(order, npix)}", headers={"User-Agent": "Galileo"})  # noqa: S310 - fixed https mirrors
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed https mirrors
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            logger.debug("Sky survey mirror %s answered %s", base, exc.code)
        except OSError:
            logger.debug("Sky survey mirror %s unreachable", base)
        with _fetch_lock:                     # try the one that works first from now on
            if base in _mirrors and len(_mirrors) > 1:
                _mirrors.remove(base)
                _mirrors.append(base)
    _offline_until = time.monotonic() + _OFFLINE_PAUSE_S
    raise OSError("no sky survey mirror reachable")


def _trim_disk(root: Path) -> None:
    files = [(f.stat().st_mtime, f.stat().st_size, f) for f in root.rglob("*.jpg")]
    total = sum(size for _, size, _ in files)
    for _, size, path in sorted(files, key=lambda item: item[0]):
        if total <= _DISK_LIMIT_BYTES:
            return
        path.unlink(missing_ok=True)
        total -= size


def tile_jpeg(order: int, npix: int) -> bytes | None:
    """One tile from the cache or the internet; ``None`` if it can't be had. Blocks: never on a UI or listener thread."""
    global _written
    root = _cache_root()
    path = root / _tile_path(order, npix)
    try:
        return path.read_bytes()
    except OSError:
        pass
    try:
        data = _fetch_tile(order, npix)
    except Exception:
        logger.debug("Could not fetch sky survey tile %s/%s", order, npix, exc_info=True)
        return None
    if data is None or not data.startswith(b"\xff\xd8"):
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f"{path.name}.{threading.get_ident()}.part")
        partial.write_bytes(data)
        partial.replace(path)                 # never leave half a tile for the next start to trust
        _written += 1
        if _written % 500 == 0:
            _trim_disk(root)
    except OSError:
        logger.exception("Could not cache a sky survey tile")
    return data


class SurveyTiles:
    """Decoded tiles for drawing. ``want`` says what's in view now; workers fetch and decode it off the UI thread, the
    latest view first, and ``on_arrival`` is called from a worker each time one is ready."""

    def __init__(self, on_arrival: Callable[[], None] | None = None) -> None:
        self._on_arrival = on_arrival
        self._decoded: OrderedDict[tuple[int, int], np.ndarray] = OrderedDict()
        self._queue: list[tuple[int, int]] = []
        self._busy: set[tuple[int, int]] = set()
        self._failed: dict[tuple[int, int], float] = {}
        self._changed = threading.Condition()
        self._started = False
        self.generation = 0                   # moves when a tile arrives, so a drawn view knows it's out of date

    def tile(self, order: int, npix: int) -> np.ndarray | None:
        with self._changed:
            found = self._decoded.get((order, npix))
            if found is not None:
                self._decoded.move_to_end((order, npix))
            return found

    def want(self, keys: Iterable[tuple[int, int]]) -> None:
        now = time.monotonic()
        with self._changed:
            self._queue = [k for k in keys if k not in self._decoded and k not in self._busy
                           and now >= self._failed.get(k, 0.0)]
            if self._queue:
                if not self._started:
                    self._started = True
                    for i in range(_WORKERS):
                        threading.Thread(target=self._work, name=f"sky-survey-{i}", daemon=True).start()
                self._changed.notify_all()

    def _work(self) -> None:
        while True:
            with self._changed:
                while not self._queue:
                    self._changed.wait()
                key = self._queue.pop(0)
                self._busy.add(key)
            pixels = self._load(key)
            with self._changed:
                self._busy.discard(key)
                if pixels is None:
                    self._failed[key] = time.monotonic() + _RETRY_FAILED_S
                    continue
                self._decoded[key] = pixels
                while len(self._decoded) > _MEMORY_TILES:
                    self._decoded.popitem(last=False)
                self.generation += 1
            if self._on_arrival is not None:
                try:
                    self._on_arrival()
                except RuntimeError:          # its window has gone: tiles aren't its business any more
                    return

    @staticmethod
    def _load(key: tuple[int, int]) -> np.ndarray | None:
        data = tile_jpeg(*key)
        if data is None:
            return None
        try:
            from PIL import Image
            return np.asarray(Image.open(BytesIO(data)).convert("RGB"), dtype=np.uint8)
        except Exception:
            logger.warning("Could not decode sky survey tile %s", key, exc_info=True)
            return None


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def render_view(tiles: SurveyTiles, vp: Viewport, lst_deg: float, latitude_deg: float, jd: float,
                step: int = 2) -> np.ndarray:
    """The sky in view, every *step* pixels: ``h x w x 3`` uint8, for the painter to scale up. Asks for what's missing and
    meanwhile draws it from any coarser tile it has, so the picture sharpens instead of having holes. Zoomed in past
    FETCH_ABOVE_FOV_DEG it asks for nothing new, so panning there never waits on the network."""
    from galileo.planning.star_atlas import precess_to_j2000

    ys, xs = np.mgrid[step / 2.0:vp.height:step, step / 2.0:vp.width:step]
    alt_deg, az_deg = vp.unproject(xs, ys)
    alt, az, lat = np.radians(alt_deg), np.radians(az_deg), np.radians(latitude_deg)
    dec = np.arcsin(np.clip(np.sin(alt) * np.sin(lat) + np.cos(alt) * np.cos(lat) * np.cos(az), -1.0, 1.0))
    hour = np.arctan2(-np.cos(alt) * np.sin(az), np.sin(alt) * np.cos(lat) - np.cos(alt) * np.sin(lat) * np.cos(az))
    ra_j2000, dec_j2000 = precess_to_j2000(((lst_deg - np.degrees(hour)) % 360.0).ravel(), np.degrees(dec).ravel(), jd)
    face, x, y = face_xy(ra_j2000, dec_j2000)

    order = order_for(math.degrees(1.0 / vp.scale))
    npix, _, _ = _tile_in_face(face, x, y, order)
    needed, counts = np.unique(npix, return_counts=True)
    while len(needed) > _MAX_VIEW_TILES and order > 0:
        order -= 1
        npix, _, _ = _tile_in_face(face, x, y, order)
        needed, counts = np.unique(npix, return_counts=True)
    biggest_first = needed[np.argsort(-counts)]
    if vp.fov_deg >= FETCH_ABOVE_FOV_DEG:
        tiles.want((order, int(n)) for n in biggest_first)

    out = np.zeros((xs.size, 3), dtype=np.uint8)
    todo = np.arange(xs.size)
    for level in range(order, -1, -1):
        if not len(todo):
            break
        npix, fx, fy = _tile_in_face(face[todo], x[todo], y[todo], level)
        wanted = np.unique(npix)
        filled = np.zeros(len(todo), dtype=bool)
        for n in wanted:
            image = tiles.tile(level, int(n))
            if image is None:
                continue
            inside = npix == n
            rows = np.minimum((fx[inside] * TILE_SIDE).astype(np.int64), TILE_SIDE - 1)
            cols = np.minimum((fy[inside] * TILE_SIDE).astype(np.int64), TILE_SIDE - 1)
            out[todo[inside]] = image[rows, cols]
            filled |= inside
        todo = todo[~filled]
    return out.reshape(*xs.shape, 3)
