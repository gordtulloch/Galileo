# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Placing a mosaic's panes on one canvas by where they are on the sky (IMG-180).

Each pane is a flat image with a *pose*: the sky position of its centre and a CD matrix (degrees
per pixel) saying how its pixel axes lie on the sky. All the panes are projected onto the plane
tangent to the sky at the mosaic's centre; the canvas is that plane drawn at the reference CD's
scale and orientation. A pane is moved to its place by the affine map between the two, so panes that
are rotated, mirrored (after a meridian flip) or not quite where the mount was told to point still
land where the sky says they should. Where panes overlap they are feathered into one another and
their background levels are matched.

Poses start out *nominal* — the planned pane centres, north up and east left, turned by the mosaic's
rotation — and become *solved* when a plate solve of the pane arrives (:meth:`MosaicCanvas.solve`),
which supplies the true centre and, from the first one, the true orientation and scale. Domain core:
numpy and scipy only.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np

from galileo.tangent import sky_to_tangent

logger = logging.getLogger(__name__)

CD = tuple[float, float, float, float]      # (CD1_1, CD1_2, CD2_1, CD2_2): (xi, eta) = CD . (dx, dy)

_TOL = 1e-6
_MIN_OVERLAP_PIXELS = 64        # fewer shared pixels than this are not enough to match backgrounds on


@dataclass
class MosaicSky:
    """Where a mosaic is on the sky: its centre, how it is turned and the field of view of a pane."""
    centre_ra_deg: float
    centre_dec_deg: float
    rotation_deg: float
    fov_width_deg: float
    fov_height_deg: float
    panes: dict[int, tuple[float, float]]       # pane index -> planned (ra_deg, dec_deg) of its centre

    @classmethod
    def from_mosaic(cls, mosaic) -> MosaicSky | None:
        """The mosaic's sky geometry, or ``None`` when it was built without it (see ``Mosaic``)."""
        if (mosaic is None or mosaic.center_ra_deg is None or mosaic.center_dec_deg is None
                or not mosaic.fov_width_deg or not mosaic.fov_height_deg or not mosaic.panels):
            return None
        return cls(mosaic.center_ra_deg, mosaic.center_dec_deg, float(mosaic.rotation_deg or 0.0),
                   float(mosaic.fov_width_deg), float(mosaic.fov_height_deg),
                   {p.pane_index: (p.ra_deg, p.dec_deg) for p in mosaic.panels})


def nominal_cd(fov_width_deg: float, fov_height_deg: float, shape: tuple[int, ...], rotation_deg: float) -> CD:
    """The CD matrix a pane has when nothing is known but the plan: north up and east left as the
    array is shown (x to the right, y downwards), the camera turned by *rotation_deg* — the same
    sense ``FramingAssistant.create_mosaic`` turns the grid."""
    height, width = shape[:2]
    sx, sy = fov_width_deg / width, fov_height_deg / height
    c, s = math.cos(math.radians(rotation_deg)), math.sin(math.radians(rotation_deg))
    return (-sx * c, sy * s, -sx * s, -sy * c)


def _matrix(cd: CD) -> np.ndarray:
    return np.array([[cd[0], cd[1]], [cd[2], cd[3]]], dtype=np.float64)


@dataclass
class _Patch:
    """One pane warped onto the canvas: its pixels, the weight each has when panes are blended, and
    where it sits (canvas pixel of its first row and column)."""
    y0: int
    x0: int
    image: np.ndarray
    weight: np.ndarray              # 0 where the pane does not cover
    background: np.ndarray | float = 0.0


class MosaicCanvas:
    """Composites pane images onto a canvas by sky position. See the module docstring."""

    def __init__(self, sky: MosaicSky, overlap_pct: float, match_background: bool = True) -> None:
        self.sky = sky
        self.overlap_pct = overlap_pct
        self.match_background = match_background
        self.pane_shape: tuple[int, ...] | None = None
        self.canvas: np.ndarray | None = None
        self._images: dict[int, np.ndarray] = {}
        self._patches: dict[int, _Patch] = {}
        self._order: list[int] = []                         # panes in the order their first frame arrived
        self._solved: dict[int, tuple[float, float, CD | None]] = {}
        self._reference_cd: CD | None = None                # the canvas's orientation and scale
        self._origin = (0.0, 0.0)                           # tangent-plane (x, y) of the canvas's top-left edge
        self.solved_panes = 0

    # -- poses ----------------------------------------------------------------------------------

    def _nominal(self) -> CD:
        assert self.pane_shape is not None
        return nominal_cd(self.sky.fov_width_deg, self.sky.fov_height_deg, self.pane_shape, self.sky.rotation_deg)

    def _canvas_cd(self) -> CD:
        return self._reference_cd or self._nominal()

    def _pose(self, index: int) -> tuple[float, float, CD]:
        if index in self._solved:
            ra, dec, cd = self._solved[index]
            return ra, dec, cd or self._canvas_cd()
        ra, dec = self.sky.panes[index]
        return ra, dec, self._canvas_cd()

    def _affine(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        """``(M, t)``: pane offset ``d`` from its centre pixel (x right, y down) to canvas-plane
        coordinates ``M d + t``, in canvas pixels measured from the mosaic centre."""
        ra, dec, cd = self._pose(index)
        xi, eta = sky_to_tangent(ra, dec, self.sky.centre_ra_deg, self.sky.centre_dec_deg)
        inverse = np.linalg.inv(_matrix(self._canvas_cd()))
        return inverse @ _matrix(cd), inverse @ np.array([xi, eta])

    def _extent(self, index: int) -> tuple[float, float, float, float] | None:
        """``(min_x, min_y, max_x, max_y)`` pixel edges the pane covers in canvas-plane coordinates."""
        assert self.pane_shape is not None
        height, width = self.pane_shape[:2]
        try:
            m, t = self._affine(index)
        except ValueError:
            return None
        corners = np.array([[sx * width / 2, sy * height / 2] for sx in (-1, 1) for sy in (-1, 1)])
        placed = corners @ m.T + t
        return float(placed[:, 0].min()), float(placed[:, 1].min()), float(placed[:, 0].max()), float(placed[:, 1].max())

    # -- layout ---------------------------------------------------------------------------------

    def _lay_out(self) -> None:
        """Size the canvas to the planned footprint of every pane and forget anything placed on a
        previous layout."""
        extents = [e for e in (self._extent(i) for i in self.sky.panes) if e is not None]
        min_x = min(e[0] for e in extents)
        min_y = min(e[1] for e in extents)
        width = max(1, math.ceil(max(e[2] for e in extents) - min_x - _TOL))
        height = max(1, math.ceil(max(e[3] for e in extents) - min_y - _TOL))
        self._origin = (min_x, min_y)
        pane_shape = self.pane_shape or ()
        shape = (height, width) if len(pane_shape) < 3 else (height, width, pane_shape[2])
        self.canvas = np.zeros(shape, dtype=np.float32)
        self._patches.clear()

    def _place(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        """``(M, t)`` of pane *index* with ``t`` taken to canvas pixel coordinates, so that a pane
        pixel ``(col, row)`` lands on canvas ``(x, y) = M (col - cx, row - cy) + t``."""
        m, t = self._affine(index)
        # Canvas pixel i has its centre at plane coordinate origin + i + 0.5.
        return m, t - np.array(self._origin) - 0.5

    def _grow_to_fit(self, index: int) -> None:
        """Extend the canvas (by whole pixels, so nothing already placed has to move within it) if a
        pane's solved position puts part of it outside."""
        assert self.canvas is not None
        extent = self._extent(index)
        if extent is None:
            return
        height, width = self.canvas.shape[:2]
        left = max(0, math.ceil(self._origin[0] - extent[0] - _TOL))
        top = max(0, math.ceil(self._origin[1] - extent[1] - _TOL))
        right = max(0, math.ceil(extent[2] - (self._origin[0] + width) - _TOL))
        bottom = max(0, math.ceil(extent[3] - (self._origin[1] + height) - _TOL))
        if not (left or top or right or bottom):
            return
        pad = [(top, bottom), (left, right)] + [(0, 0)] * (self.canvas.ndim - 2)
        self.canvas = np.pad(self.canvas, pad)
        self._origin = (self._origin[0] - left, self._origin[1] - top)
        for patch in self._patches.values():
            patch.y0 += top
            patch.x0 += left

    # -- warping --------------------------------------------------------------------------------

    def _feather(self) -> np.ndarray:
        """Per-pixel blending weight in pane space: ramps from the pane's edge inwards over about
        the overlap width, so a seam is crossed gradually."""
        assert self.pane_shape is not None
        height, width = self.pane_shape[:2]
        ramp = max(2.0, self.overlap_pct / 100.0 * min(height, width))
        rows = np.minimum(np.arange(height) + 1, height - np.arange(height))
        cols = np.minimum(np.arange(width) + 1, width - np.arange(width))
        return np.maximum(np.clip(np.minimum(rows[:, None], cols[None, :]) / ramp, 0.0, 1.0), 1e-3).astype(np.float32)

    def _make_patch(self, index: int) -> _Patch | None:
        assert self.pane_shape is not None and self.canvas is not None
        height, width = self.pane_shape[:2]
        try:
            m, t = self._place(index)
        except ValueError:
            return None
        image = self._images[index]
        feather = self._feather()
        canvas_h, canvas_w = self.canvas.shape[:2]
        aligned = np.allclose(m, np.eye(2), atol=_TOL)
        shift = t - np.array([(width - 1) / 2.0, (height - 1) / 2.0])      # canvas position of pane pixel (0, 0)
        if aligned and np.allclose(shift, np.round(shift), atol=1e-3):
            x0, y0 = round(shift[0]), round(shift[1])
            sx0, sy0 = max(0, -x0), max(0, -y0)
            sx1, sy1 = min(width, canvas_w - x0), min(height, canvas_h - y0)
            if sx1 <= sx0 or sy1 <= sy0:
                return None
            img, wt = image[sy0:sy1, sx0:sx1], feather[sy0:sy1, sx0:sx1]
            return _Patch(y0 + sy0, x0 + sx0, np.array(img, dtype=np.float32), np.array(wt, dtype=np.float32))
        return self._warp(image, feather, m, t, (height, width))

    def _warp(self, image, feather, m, t, pane_hw) -> _Patch | None:
        from scipy import ndimage
        assert self.canvas is not None
        height, width = pane_hw
        canvas_h, canvas_w = self.canvas.shape[:2]
        centre = np.array([(width - 1) / 2.0, (height - 1) / 2.0])
        corners = np.array([[sx * (width - 1) / 2.0, sy * (height - 1) / 2.0] for sx in (-1, 1) for sy in (-1, 1)])
        placed = corners @ m.T + t
        x0, y0 = max(0, math.floor(placed[:, 0].min()) - 1), max(0, math.floor(placed[:, 1].min()) - 1)
        x1, y1 = min(canvas_w, math.ceil(placed[:, 0].max()) + 2), min(canvas_h, math.ceil(placed[:, 1].max()) + 2)
        if x1 <= x0 or y1 <= y0:
            return None
        # scipy maps output (row, col) to input (row, col): input = A @ output + b, A = M^-1 in (y, x) order.
        inverse = np.linalg.inv(m)
        swap = np.array([[0.0, 1.0], [1.0, 0.0]])
        matrix = swap @ inverse @ swap
        offset = swap @ (inverse @ (np.array([x0, y0], dtype=np.float64) - t) + centre)

        def warp(plane: np.ndarray) -> np.ndarray:
            return ndimage.affine_transform(plane.astype(np.float32), matrix, offset=offset,
                                            output_shape=(y1 - y0, x1 - x0), order=1, mode="constant", cval=0.0)

        coverage = warp(np.ones((height, width), dtype=np.float32))
        valid = coverage > 0.5
        weight = (warp(feather) * valid).astype(np.float32)
        safe = np.where(valid, coverage, 1.0)
        if image.ndim == 2:
            warped = warp(image) / safe
        else:
            warped = np.stack([warp(image[..., c]) for c in range(image.shape[2])], axis=-1) / safe[..., None]
        return _Patch(y0, x0, np.where(valid[..., None] if image.ndim == 3 else valid, warped, 0).astype(np.float32), weight)

    # -- rendering ------------------------------------------------------------------------------

    def _accumulate(self, y0, y1, x0, x1, exclude: int | None = None):
        """``(sum of weight * pixel, sum of weight)`` of every patch over the canvas region."""
        assert self.canvas is not None
        shape = (y1 - y0, x1 - x0)
        total = np.zeros(shape + (() if self.canvas.ndim == 2 else (self.canvas.shape[2],)), dtype=np.float64)
        weight = np.zeros(shape, dtype=np.float64)
        for index, patch in self._patches.items():
            if index == exclude:
                continue
            h, w = patch.weight.shape
            ay0, ay1 = max(y0, patch.y0), min(y1, patch.y0 + h)
            ax0, ax1 = max(x0, patch.x0), min(x1, patch.x0 + w)
            if ay1 <= ay0 or ax1 <= ax0:
                continue
            wt = patch.weight[ay0 - patch.y0:ay1 - patch.y0, ax0 - patch.x0:ax1 - patch.x0]
            img = patch.image[ay0 - patch.y0:ay1 - patch.y0, ax0 - patch.x0:ax1 - patch.x0] + patch.background
            window = (slice(ay0 - y0, ay1 - y0), slice(ax0 - x0, ax1 - x0))
            total[window] += img * (wt if img.ndim == 2 else wt[..., None])
            weight[window] += wt
        return total, weight

    def _render(self, y0: int, y1: int, x0: int, x1: int) -> None:
        assert self.canvas is not None
        total, weight = self._accumulate(y0, y1, x0, x1)
        denominator = np.where(weight > 0, weight, 1.0)
        mean = total / (denominator if total.ndim == 2 else denominator[..., None])
        self.canvas[y0:y1, x0:x1] = mean.astype(np.float32)

    def _match_background(self, index: int, patch: _Patch) -> None:
        """Shift *patch* by the median difference from what the other panes already put in the
        region they share, so a change of sky glow between panes doesn't show as a step."""
        patch.background = 0.0
        if not self.match_background or len(self._patches) < 1:
            return
        h, w = patch.weight.shape
        total, weight = self._accumulate(patch.y0, patch.y0 + h, patch.x0, patch.x0 + w, exclude=index)
        shared = (weight > 0) & (patch.weight > 0.05)
        if int(shared.sum()) < _MIN_OVERLAP_PIXELS:
            return
        safe = np.where(weight > 0, weight, 1.0)
        others = total / (safe if total.ndim == 2 else safe[..., None])
        if patch.image.ndim == 2:
            patch.background = float(np.median(others[shared]) - np.median(patch.image[shared]))
        else:
            patch.background = np.median(others[shared], axis=0) - np.median(patch.image[shared], axis=0)

    def _install(self, index: int) -> None:
        patch = self._make_patch(index)
        if patch is None:
            self._patches.pop(index, None)
            logger.warning("Mosaic stack: pane %d falls outside the mosaic; not composited.", index)
            return
        self._match_background(index, patch)
        self._patches[index] = patch
        h, w = patch.weight.shape
        self._render(patch.y0, patch.y0 + h, patch.x0, patch.x0 + w)

    # -- public ---------------------------------------------------------------------------------

    def put(self, index: int, image: np.ndarray) -> np.ndarray | None:
        """Add pane *index*'s current stacked image (replacing its earlier one) and return the canvas."""
        if index not in self.sky.panes:
            logger.warning("Mosaic stack: pane %d is not one of the mosaic's panes; not composited.", index)
            return self.canvas
        if self.pane_shape is None:
            self.pane_shape = tuple(image.shape)
            self._lay_out()
        elif tuple(image.shape) != self.pane_shape:
            logger.warning("Mosaic stack: pane %d is %s, not the mosaic's %s panes; not composited.",
                           index, image.shape, self.pane_shape)
            return self.canvas
        self._images[index] = image
        if index not in self._order:
            self._order.append(index)
        self._install(index)
        return self.canvas

    def solve(self, index: int, ra_deg: float, dec_deg: float, cd: CD | None) -> np.ndarray | None:
        """Record the solved centre (and CD matrix, when the solver gave one) of pane *index* and
        move it, and from the first solution on, the canvas's orientation and scale, to match.
        A solution that is nowhere near the plan, or at the wrong scale, is a false match: it is
        ignored and the canvas is left as it was."""
        if self.pane_shape is None or index not in self.sky.panes:
            return self.canvas
        planned_ra, planned_dec = self.sky.panes[index]
        try:
            xi, eta = sky_to_tangent(ra_deg, dec_deg, planned_ra, planned_dec)
        except ValueError:
            return self.canvas
        if math.hypot(xi, eta) > 0.5 * max(self.sky.fov_width_deg, self.sky.fov_height_deg):
            logger.warning("Mosaic stack: the solve of pane %d is %.2f° from where it was aimed; ignored.",
                           index, math.hypot(xi, eta))
            return self.canvas
        if cd is not None:
            nominal = _matrix(self._nominal())
            ratio = abs(np.linalg.det(_matrix(cd)) / np.linalg.det(nominal))
            if not 0.64 < ratio < 1.5625:          # more than 25% off the planned pixel scale
                logger.warning("Mosaic stack: the solve of pane %d has the wrong scale; ignored.", index)
                return self.canvas
        self._solved[index] = (ra_deg, dec_deg, cd)
        self.solved_panes = len(self._solved)
        if cd is not None and self._reference_cd is None:
            self._reference_cd = cd
            self._lay_out()                         # a new orientation/scale: everything is placed afresh
            for started in self._order:
                self._install(started)
            return self.canvas
        self._grow_to_fit(index)
        if index in self._images:
            self._install(index)
        return self.canvas

    def crop(self) -> np.ndarray | None:
        """Trim the canvas to the panes that were actually captured (a stopped run leaves unfilled
        panes' room around the edge) and return it."""
        if self.canvas is None or not self._patches:
            return self.canvas
        _, weight = self._accumulate(0, self.canvas.shape[0], 0, self.canvas.shape[1])
        rows, cols = np.any(weight > 0, axis=1), np.any(weight > 0, axis=0)
        if not rows.any():
            return self.canvas
        top, bottom = int(np.argmax(rows)), int(len(rows) - np.argmax(rows[::-1]))
        left, right = int(np.argmax(cols)), int(len(cols) - np.argmax(cols[::-1]))
        self.canvas = np.ascontiguousarray(self.canvas[top:bottom, left:right])
        self._origin = (self._origin[0] + left, self._origin[1] + top)
        for patch in self._patches.values():
            patch.y0 -= top
            patch.x0 -= left
        return self.canvas
