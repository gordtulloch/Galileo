# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Debayering (demosaicing) of one-shot-colour camera frames (IMG-110).

Pure numpy, no Qt and no device access. A one-shot-colour sensor records one
colour per pixel through a 2x2 colour-filter mosaic; ``debayer`` interpolates
the two missing colours at every pixel (bilinear) to give an RGB image.
"""

from __future__ import annotations

# The four 2x2 mosaic layouts, named by the colours of the top-left 2x2 block
# read left to right, top to bottom.
BAYER_PATTERNS = ("RGGB", "GRBG", "GBRG", "BGGR")
DEFAULT_PATTERN = "RGGB"    # the most common layout, and what a camera is set to until told otherwise

_RB_KERNEL = ((1, 2, 1), (2, 4, 2), (1, 2, 1))   # red / blue: 4 diagonal + 4 edge + centre neighbours
_G_KERNEL = ((0, 1, 0), (1, 4, 1), (0, 1, 0))    # green: the 4 edge neighbours + centre


def _convolve3(plane, kernel):
    """3x3 convolution with mirrored edges; divides by 4 (each kernel sums to 16 over a 4x sampling density)."""
    import numpy as np
    height, width = plane.shape
    padded = np.pad(plane, 1, mode="reflect")
    out = np.zeros((height, width), dtype=np.float32)
    for dy in range(3):
        for dx in range(3):
            weight = kernel[dy][dx]
            if weight:
                out += weight * padded[dy:dy + height, dx:dx + width]
    return out / 4.0


def debayer(mosaic, pattern: str):
    """Return the ``(height, width, 3)`` float32 RGB image for a 2-D Bayer
    ``mosaic``. Raw values are kept as they are (not scaled), so stretching
    and statistics see the same numbers the camera produced."""
    import numpy as np

    pattern = pattern.upper()
    if pattern not in BAYER_PATTERNS:
        raise ValueError(f"Unknown Bayer pattern {pattern!r}; expected one of {', '.join(BAYER_PATTERNS)}")
    data = np.asarray(mosaic)
    if data.ndim != 2:
        raise ValueError(f"Only a 2-D mosaic can be debayered, got shape {data.shape}")
    data = data.astype(np.float32)
    height, width = data.shape

    rows = np.arange(height)[:, None] & 1
    cols = np.arange(width)[None, :] & 1
    tile = [pattern[0:2], pattern[2:4]]           # tile[row parity][col parity]
    planes = []
    for colour, kernel in (("R", _RB_KERNEL), ("G", _G_KERNEL), ("B", _RB_KERNEL)):
        mask = np.zeros((height, width), dtype=np.float32)
        for row in (0, 1):
            for col in (0, 1):
                if tile[row][col] == colour:
                    mask[(rows == row) & (cols == col)] = 1.0
        planes.append(_convolve3(data * mask, kernel))
    return np.stack(planes, axis=-1)


def pattern_from_cfa(cfa_type: str | None, offset_x: int = 0, offset_y: int = 0) -> str | None:
    """The Bayer pattern of the frame as read out, from a sensor's CFA description: the *cfa_type*
    mosaic (``RGGB`` ...) shifted by the (x, y) pixel offsets of the first readout pixel into it.
    ``None`` if *cfa_type* is missing or not a Bayer layout, i.e. the sensor is mono."""
    if not cfa_type or cfa_type.upper() not in BAYER_PATTERNS:
        return None
    tile = [cfa_type.upper()[0:2], cfa_type.upper()[2:4]]
    row, col = int(offset_y) & 1, int(offset_x) & 1
    return tile[row][col] + tile[row][1 - col] + tile[1 - row][col] + tile[1 - row][1 - col]


def superpixel(mosaic, pattern: str):
    """A half-resolution ``(height // 2, width // 2, 3)`` float32 RGB image from a Bayer ``mosaic``:
    each 2x2 block gives one pixel (red, the mean of the two greens, blue). Far cheaper than
    :func:`debayer` and exact at that size, so it suits previews that are shown reduced anyway."""
    import numpy as np

    pattern = pattern.upper()
    if pattern not in BAYER_PATTERNS:
        raise ValueError(f"Unknown Bayer pattern {pattern!r}; expected one of {', '.join(BAYER_PATTERNS)}")
    data = np.asarray(mosaic)
    if data.ndim != 2:
        raise ValueError(f"Only a 2-D mosaic can be debayered, got shape {data.shape}")
    height, width = data.shape[0] // 2 * 2, data.shape[1] // 2 * 2
    data = data[:height, :width].astype(np.float32)
    planes = {"R": [], "G": [], "B": []}
    for row in (0, 1):
        for col in (0, 1):
            planes[pattern[row * 2 + col]].append(data[row::2, col::2])
    return np.stack([np.mean(planes[c], axis=0) for c in "RGB"], axis=-1)


def camera_pattern(camera) -> str | None:
    """The Bayer pattern *camera* reports for its frames, or ``None`` for a mono camera, no camera,
    or one that cannot say. Talks to the device (``asyncio.run``), so call it from a worker thread."""
    getter = getattr(camera, "get_bayer_pattern", None)
    if getter is None:
        return None
    import asyncio
    import logging
    try:
        pattern = asyncio.run(getter())
    except Exception:
        logging.getLogger(__name__).debug("Could not read the camera's Bayer pattern", exc_info=True)
        return None
    return pattern if isinstance(pattern, str) and pattern.upper() in BAYER_PATTERNS else None
