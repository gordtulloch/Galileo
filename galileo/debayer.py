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
