# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Autofocus service — HFR curve fitting and focuser control (FOC-010 … FOC-080)."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from galileo.bus import FocusCompleteEvent, FocusFrameEvent, FocusStartedEvent, get_bus
from galileo.core.compute import run_cpu

logger = logging.getLogger(__name__)

# This module's HFR → FWHM conversion, shared by the aberration inspector and
# the autofocus frame measurements so the two report comparable numbers.
_FWHM_PER_HFR = 1.5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AutofocusParams:
    """Configuration for one autofocus run (FOC-070)."""
    step_size: int = 200
    num_points: int = 9
    exposure_s: float = 3.0
    backlash_compensation: int = 0
    filter_name: str = ""


@dataclass
class AutofocusResult:
    """Result of one autofocus run."""
    success: bool
    best_position: int = 0
    failure_reason: str = ""
    sample_points: list[tuple[int, float]] | None = None
    curve_coefficients: tuple | None = None


# ---------------------------------------------------------------------------
# Curve fitting
# ---------------------------------------------------------------------------

def fit_parabola(positions: list[int], hfr_values: list[float]) -> tuple:
    """Fit a parabola to (position, HFR) pairs; return (a, b, c) coefficients."""
    import numpy as np
    coeffs = np.polyfit(positions, hfr_values, 2)
    return tuple(float(c) for c in coeffs)


def vertex_of_parabola(coeffs: tuple) -> float:
    """Return the x-coordinate (focuser position) of the parabola's vertex."""
    a, b, c = coeffs
    if a == 0:
        return 0.0
    return -b / (2 * a)


# ---------------------------------------------------------------------------
# Autofocus service
# ---------------------------------------------------------------------------

class AutofocusService:
    """Runs an autofocus routine using HFR measurements at multiple positions."""

    def __init__(
        self,
        camera=None,
        focuser=None,
        output_dir: Path | str = ".",
        event_bus=None,
        exposure_s: float = AutofocusParams.exposure_s,
        backlash_compensation: int = AutofocusParams.backlash_compensation,
        pier_key=None,
    ) -> None:
        self._camera = camera
        self._focuser = focuser
        self._output_dir = Path(output_dir)
        self._event_bus = event_bus
        # Carried on every published event so a listener subscribed process-wide
        # (the Focus screen) can tell which Pier's run this is — two Piers can
        # each have their own AutofocusService running at once.
        self.pier_key = pier_key
        self.exposure_s = exposure_s
        self.backlash_compensation = backlash_compensation
        self._filter_offsets: dict[str, int] = {}
        self._current_position: int = 5000
        self._last_best_position: int | None = None
        self._cancelled = False
        self.last_run: AutofocusResult | None = None

    # --- Public API -------------------------------------------------------

    def cancel(self) -> None:
        """Ask a running :meth:`run` to stop after the exposure in progress; it
        puts the focuser back where it started and reports a failure."""
        self._cancelled = True

    async def run(self, step_size: int = 200, num_points: int = 9) -> AutofocusResult:
        """Sweep the focuser across *num_points* positions and fit a curve (FOC-010).

        Publishes a ``FocusStartedEvent``, a ``FocusFrameEvent`` per measured
        exposure and, however the run ends, a ``FocusCompleteEvent``, so screens
        can follow a run started from anywhere (the Focus screen, a sequencer
        trigger)."""
        self._cancelled = False
        initial_position = self._get_current_position()
        positions = self._sample_positions(initial_position, step_size, num_points)
        self._publish(FocusStartedEvent(
            source="autofocus", positions=positions, initial_position=initial_position,
            step_size=step_size, num_points=num_points, pier_key=self.pier_key,
        ))
        logger.info("Autofocus started: %d points, %d steps apart, from position %d.",
                    num_points, step_size, initial_position)
        result = AutofocusResult(success=False, failure_reason="Autofocus did not complete")
        try:
            result = await self._sweep(initial_position, positions)
            return result
        except Exception as exc:
            result = AutofocusResult(success=False, failure_reason=str(exc))
            raise
        finally:
            if result.success:
                logger.info("Autofocus complete: best focus at position %d.", result.best_position)
            else:
                logger.warning("Autofocus failed: %s.", result.failure_reason)
            self._publish(FocusCompleteEvent(source="autofocus", result=result, pier_key=self.pier_key))

    async def _sweep(self, initial_position: int, positions: list[int]) -> AutofocusResult:
        hfr_values: list[float] = []

        for pos in positions:
            await self._move_to(pos)
            hfr = await self._measure_hfr()
            hfr_values.append(hfr)
            if self._cancelled:
                await self._move_to(initial_position)
                result = AutofocusResult(
                    success=False,
                    failure_reason="Cancelled",
                    sample_points=list(zip(positions, hfr_values)),
                )
                self.last_run = result
                return result

        # Validate measurements
        if any(math.isnan(h) for h in hfr_values) or len(set(hfr_values)) < 2:
            await self._move_to(initial_position)
            result = AutofocusResult(
                success=False,
                failure_reason="No valid HFR measurements — check camera/stars",
                sample_points=list(zip(positions, hfr_values)),
            )
            self.last_run = result
            return result

        try:
            coeffs = fit_parabola(positions, hfr_values)
            best = int(round(vertex_of_parabola(coeffs)))
            self._last_best_position = best
        except Exception as exc:
            await self._move_to(initial_position)
            result = AutofocusResult(
                success=False,
                failure_reason=str(exc),
                sample_points=list(zip(positions, hfr_values)),
            )
            self.last_run = result
            return result

        # FOC-020: the routine isn't done at "computed the best position" — it
        # must actually move the focuser there and confirm with an exposure.
        await self.apply_and_confirm(best)
        result = AutofocusResult(
            success=True,
            best_position=best,
            sample_points=list(zip(positions, hfr_values)),
            curve_coefficients=coeffs,
        )
        self.last_run = result
        return result

    async def apply_and_confirm(self, best_position: int) -> None:
        """Move to *best_position* and take a confirmation exposure (FOC-020),
        so whatever is watching the run gets a look at focus at the position
        actually used, not just the last sweep sample."""
        await self._move_to(best_position)
        await self._measure_hfr(confirm=True)

    async def run_manual(self, step_size: int = 200, num_points: int = 9) -> AutofocusResult:
        """User-initiated autofocus run (FOC-050)."""
        return await self.run(step_size=step_size, num_points=num_points)

    async def run_triggered(self, reason: str = "", threshold: float = 0.0) -> AutofocusResult:
        """Trigger-initiated autofocus run (FOC-050)."""
        return await self.run()

    async def move_to(self, position: int) -> None:
        """Move the focuser directly to *position*, applying the same backlash
        compensation as a sweep move — used for a manual (non-sweep) focus move."""
        await self._move_to(position)

    async def measure_once(self) -> tuple | None:
        """Take one exposure at the current focuser position and return
        ``(frame, hfr, fwhm, star_count)``, or ``None`` if the camera returned
        no frame — used for a manual focus capture/loop, outside of a sweep
        and without publishing a ``FocusFrameEvent``."""
        if self._camera is None:
            return None
        await self._camera.start_exposure(duration=self.exposure_s)
        frame = await self._camera.get_image_array()
        if frame is None:
            return None
        hfr, star_count = await run_cpu(_measure_stars, frame)
        return frame, hfr, hfr * _FWHM_PER_HFR, star_count

    async def apply_filter_offset(self, from_filter: str, to_filter: str) -> None:
        """Move the focuser by the delta between filter offsets (FOC-060)."""
        from_offset = self._filter_offsets.get(from_filter, 0)
        to_offset = self._filter_offsets.get(to_filter, 0)
        new_position = self._current_position + (to_offset - from_offset)
        await self._move_to(new_position)

    async def run_aberration_inspection(self) -> AberrationResult | None:
        """Compute per-region HFR indicators across the frame (FOC-080)."""
        frame = await self._camera.get_image_array()
        if frame is None:
            return None
        return await run_cpu(_compute_regional_hfr, frame)

    # --- Private helpers --------------------------------------------------

    def _get_current_position(self) -> int:
        if self._focuser is not None:
            return int(getattr(self._focuser, "position", self._current_position))
        return self._current_position

    async def _move_to(self, position: int) -> None:
        self._current_position = position
        if self._focuser is None:
            return
        if self.backlash_compensation > 0:
            # Always approach from the same direction: overshoot past the target, then come back
            # to it, so mechanical backlash is taken up the same way on every move (FOC-070).
            await self._focuser.move_to(max(0, position - self.backlash_compensation))
        await self._focuser.move_to(position)

    async def _measure_hfr(self, confirm: bool = False) -> float:
        """Take a short exposure and return the mean HFR of detected stars.

        *confirm* marks this as the post-move confirmation exposure rather
        than a sweep sample, so a listener (the Focus screen) can show it
        without folding it into the V-curve."""
        if self._camera is None:
            return 2.0
        await self._camera.start_exposure(duration=self.exposure_s)
        frame = await self._camera.get_image_array()
        if frame is None:
            return float("nan")
        # SEP holds the GIL for the whole extraction (seconds on a full frame), so a thread would
        # still freeze the UI — it has to be a worker process (NFR-PERF-020).
        hfr, star_count = await run_cpu(_measure_stars, frame)
        logger.info("Focuser position %d: %d stars, HFR %.2f.", self._current_position, star_count, hfr)
        self._publish(FocusFrameEvent(
            source="autofocus", position=self._current_position, frame=frame,
            hfr=hfr, fwhm=hfr * _FWHM_PER_HFR, star_count=star_count, confirm=confirm,
            pier_key=self.pier_key,
        ))
        return hfr

    def _publish(self, event) -> None:
        (self._event_bus if self._event_bus is not None else get_bus()).publish(event)

    @staticmethod
    def _sample_positions(center: int, step: int, num: int) -> list[int]:
        half = (num - 1) // 2
        return [center + (i - half) * step for i in range(num)]


# ---------------------------------------------------------------------------
# Regional aberration inspection
# ---------------------------------------------------------------------------

@dataclass
class RegionResult:
    region_name: str
    hfr: float
    fwhm: float

    def __contains__(self, item: str) -> bool:  # allows ``"hfr" in region``
        return hasattr(self, item)


@dataclass
class AberrationResult:
    regions: list[RegionResult]


def _compute_regional_hfr(frame) -> AberrationResult:
    """Split the frame into a 2×2 grid and compute HFR per quadrant."""
    h, w = frame.shape[:2]
    quadrants = [
        ("top-left", frame[:h // 2, :w // 2]),
        ("top-right", frame[:h // 2, w // 2:]),
        ("bottom-left", frame[h // 2:, :w // 2]),
        ("bottom-right", frame[h // 2:, w // 2:]),
    ]
    regions = []
    for name, quad in quadrants:
        hfr = _compute_hfr(quad)
        regions.append(RegionResult(region_name=name, hfr=hfr, fwhm=hfr * _FWHM_PER_HFR))
    return AberrationResult(regions=regions)


def _to_2d(frame):
    """Collapse a colour frame to one plane for star detection — SEP requires 2-D,
    and colour carries no extra information here (same conversion as
    ``galileo.platesolve.frame_for_solver``: Alpaca hands back ``(height, width, 3)``,
    a FITS cube is plane-first)."""
    import numpy as np
    array = np.asarray(frame)
    if array.ndim <= 2:
        return array
    if array.shape[-1] in (3, 4):
        colour_axis = array.ndim - 1
    elif array.shape[0] in (3, 4):
        colour_axis = 0
    else:
        colour_axis = min(range(array.ndim), key=lambda axis: array.shape[axis])
    return array.mean(axis=colour_axis)


def _measure_stars(frame) -> tuple[float, int]:
    """``(hfr, star_count)`` for *frame*, detecting stars with SEP if available.

    HFR is the classic autofocus "half flux radius" — the flux-weighted mean
    distance of background-subtracted pixels from the star's centroid, out to
    an outer aperture (see lost-infinity.com's HFD write-up: HFR = Σ(Vᵢ·dᵢ)/ΣVᵢ,
    HFD = 2·HFR) — not ``sep.flux_radius``'s curve-of-growth radius. The two
    aren't the same size for a defocused, near-uniform "donut" star profile,
    and ``sep.flux_radius`` was coming out roughly an order of magnitude
    smaller than the values focusing software conventionally reports (and
    than the V-curve plot is scaled for).

    The HFR falls back to 2.0 when no stars are found and to a crude contrast
    estimate when SEP is unavailable or fails; the star count is 0 in both cases."""
    import numpy as np
    array = _to_2d(frame)
    try:
        import sep
        data = array.astype(np.float64)
        bkg = sep.Background(data)
        data_sub = data - bkg
        objects = sep.extract(data_sub, 1.5, err=bkg.globalrms)
        if len(objects) == 0:
            return 2.0, 0
        height, width = data_sub.shape
        radii = []
        for x, y, a in zip(objects["x"], objects["y"], objects["a"]):
            r_outer = min(max(6.0 * float(a), 6.0), 40.0)
            x0, x1 = max(0, int(x - r_outer)), min(width, int(x + r_outer) + 1)
            y0, y1 = max(0, int(y - r_outer)), min(height, int(y + r_outer) + 1)
            yy, xx = np.mgrid[y0:y1, x0:x1]
            dist = np.hypot(xx - x, yy - y)
            values = np.clip(data_sub[y0:y1, x0:x1][dist <= r_outer], 0.0, None)
            total = values.sum()
            if total > 0:
                radii.append(float((values * dist[dist <= r_outer]).sum() / total))
        if not radii:
            return 2.0, len(objects)
        return float(np.median(radii)), len(objects)
    except Exception:
        logger.exception("Star detection failed; falling back to a contrast-based HFR estimate.")
        return float(np.std(array) / (np.mean(array) + 1e-6) * 2.0) or 2.0, 0


def _compute_hfr(frame) -> float:
    """Estimate the mean HFR of stars in *frame* using SEP if available."""
    return _measure_stars(frame)[0]
