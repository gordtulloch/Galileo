# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Survey cutouts built from static HiPS tiles (SKY-080, FRAME-020).

The CDS ``hips2fits`` cutout service (and CDS's tile hosts) are unavailable, so a cutout is made here instead from the
DSS2 colour HiPS tiles mirrored by IRSA (``HIPS_BASE``), which is a plain tile tree with no cutout service. Each output
pixel of a north-up TAN view is mapped to the sky, then to the HEALPix tile and pixel holding it, using the same HEALPix
helpers as ``galileo.planning.sky_survey``. Blocking: run off the UI thread.
"""

from __future__ import annotations

import contextlib
import io
import logging
import math
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from galileo.planning.sky_survey import TILE_SIDE, _tile_in_face, face_xy

logger = logging.getLogger(__name__)

HIPS_BASE = "https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color"
HIPS_MAX_ORDER = 9                    # the survey's finest (hips_order in its properties file)
_ORDER0_DEG_PER_PIXEL = 58.63 / TILE_SIDE
_MAX_TILES = 64                       # a degenerate request coarsens rather than fetching hundreds of tiles
_TIMEOUT_S = 20

_cache_lock = threading.Lock()


def _tile_path(order: int, npix: int) -> str:
    return f"Norder{order}/Dir{(npix // 10000) * 10000}/Npix{npix}.jpg"


def _cache_file(order: int, npix: int):
    from galileo.platform import get_cache_dir
    return get_cache_dir() / "hips" / "DSS2color" / _tile_path(order, npix)


def _tile(order: int, npix: int) -> np.ndarray | None:
    """One decoded tile (``512 x 512 x 3``) from the disk cache or IRSA, or ``None`` if it can't be had."""
    from PIL import Image

    path = _cache_file(order, npix)
    data: bytes | None = None
    with contextlib.suppress(OSError):
        data = path.read_bytes()
    if data is None:
        request = urllib.request.Request(  # noqa: S310 - fixed https host
            f"{HIPS_BASE}/{_tile_path(order, npix)}", headers={"User-Agent": "Galileo"})
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:  # noqa: S310
                data = response.read()
        except (urllib.error.URLError, OSError):
            logger.debug("HiPS tile %s/%s unavailable", order, npix, exc_info=True)
            return None
        if not data.startswith(b"\xff\xd8"):
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(f"{path.name}.{threading.get_ident()}.part")
            partial.write_bytes(data)
            partial.replace(path)
        except OSError:
            logger.debug("Could not cache HiPS tile", exc_info=True)
    try:
        return np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.uint8)
    except Exception:
        logger.debug("Could not decode HiPS tile %s/%s", order, npix, exc_info=True)
        return None


def fetch_cutout(ra_deg: float, dec_deg: float, fov_deg: float, width_px: int, height_px: int) -> bytes:
    """A north-up (east left) TAN JPEG of ``width_px x height_px`` centred on the position; *fov_deg* spans the longer
    side. Returns ``b""`` if no tile could be fetched (offline, service down) - a missing survey image is never fatal."""
    from PIL import Image

    width_px, height_px = max(1, int(width_px)), max(1, int(height_px))
    scale = math.radians(fov_deg) / max(width_px, height_px)           # radians per output pixel
    cols, rows = np.meshgrid(np.arange(width_px) - (width_px - 1) / 2.0, np.arange(height_px) - (height_px - 1) / 2.0)
    xi, eta = -cols * scale, -rows * scale                               # east to the left, north up
    ra0, dec0 = math.radians(ra_deg), math.radians(dec_deg)
    rho = np.hypot(xi, eta)
    c = np.arctan(rho)
    sin_c, cos_c = np.sin(c), np.cos(c)
    safe_rho = np.where(rho == 0.0, 1.0, rho)
    dec = np.arcsin(np.clip(cos_c * math.sin(dec0) + eta * sin_c * math.cos(dec0) / safe_rho, -1.0, 1.0))
    ra = ra0 + np.arctan2(xi * sin_c, rho * math.cos(dec0) * cos_c - eta * math.sin(dec0) * sin_c)
    ra_deg_grid, dec_deg_grid = np.degrees(ra).ravel() % 360.0, np.degrees(dec).ravel()

    face, x, y = face_xy(ra_deg_grid, dec_deg_grid)
    order = max(0, min(HIPS_MAX_ORDER, math.ceil(math.log2(_ORDER0_DEG_PER_PIXEL / max(math.degrees(scale), 1e-9)))))
    while True:
        npix, fx, fy = _tile_in_face(face, x, y, order)
        needed = np.unique(npix)
        if len(needed) <= _MAX_TILES or order == 0:
            break
        order -= 1

    with ThreadPoolExecutor(max_workers=4) as pool:
        tiles = dict(zip((int(n) for n in needed), pool.map(lambda n: _tile(order, int(n)), needed), strict=True))
    if not any(t is not None for t in tiles.values()):
        return b""

    out = np.zeros((width_px * height_px, 3), dtype=np.uint8)
    for n, image in tiles.items():
        if image is None:
            continue
        inside = npix == n
        r = np.minimum((fx[inside] * TILE_SIDE).astype(np.int64), TILE_SIDE - 1)
        k = np.minimum((fy[inside] * TILE_SIDE).astype(np.int64), TILE_SIDE - 1)
        out[inside] = image[r, k]
    buf = io.BytesIO()
    Image.fromarray(out.reshape(height_px, width_px, 3)).save(buf, format="JPEG", quality=90)
    return buf.getvalue()
