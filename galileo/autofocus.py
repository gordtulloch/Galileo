"""Autofocus service — HFR curve fitting and focuser control (FOC-010 … FOC-080)."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
        output_dir: "Path | str" = ".",
        event_bus=None,
    ) -> None:
        self._camera = camera
        self._focuser = focuser
        self._output_dir = Path(output_dir)
        self._event_bus = event_bus
        self._filter_offsets: dict[str, int] = {}
        self._current_position: int = 5000
        self._last_best_position: int | None = None
        self.last_run: AutofocusResult | None = None

    # --- Public API -------------------------------------------------------

    async def run(self, step_size: int = 200, num_points: int = 9) -> AutofocusResult:
        """Sweep the focuser across *num_points* positions and fit a curve (FOC-010)."""
        initial_position = self._get_current_position()

        positions = self._sample_positions(initial_position, step_size, num_points)
        hfr_values: list[float] = []

        for pos in positions:
            await self._move_to(pos)
            hfr = await self._measure_hfr()
            hfr_values.append(hfr)

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
            result = AutofocusResult(
                success=True,
                best_position=best,
                sample_points=list(zip(positions, hfr_values)),
                curve_coefficients=coeffs,
            )
        except Exception as exc:
            await self._move_to(initial_position)
            result = AutofocusResult(
                success=False,
                failure_reason=str(exc),
                sample_points=list(zip(positions, hfr_values)),
            )

        self.last_run = result
        return result

    async def apply_and_confirm(self, best_position: int) -> None:
        """Move to *best_position* and take a confirmation exposure (FOC-020)."""
        await self._move_to(best_position)
        await self._measure_hfr()

    async def run_manual(self, step_size: int = 200, num_points: int = 9) -> AutofocusResult:
        """User-initiated autofocus run (FOC-050)."""
        return await self.run(step_size=step_size, num_points=num_points)

    async def run_triggered(self, reason: str = "", threshold: float = 0.0) -> AutofocusResult:
        """Trigger-initiated autofocus run (FOC-050)."""
        return await self.run()

    async def apply_filter_offset(self, from_filter: str, to_filter: str) -> None:
        """Move the focuser by the delta between filter offsets (FOC-060)."""
        from_offset = self._filter_offsets.get(from_filter, 0)
        to_offset = self._filter_offsets.get(to_filter, 0)
        new_position = self._current_position + (to_offset - from_offset)
        await self._move_to(new_position)

    async def run_aberration_inspection(self) -> "AberrationResult | None":
        """Compute per-region HFR indicators across the frame (FOC-080)."""
        import numpy as np
        frame = await self._camera.get_image_array()
        if frame is None:
            return None
        return _compute_regional_hfr(frame)

    # --- Private helpers --------------------------------------------------

    def _get_current_position(self) -> int:
        if self._focuser is not None:
            return int(getattr(self._focuser, "position", self._current_position))
        return self._current_position

    async def _move_to(self, position: int) -> None:
        self._current_position = position
        if self._focuser is not None:
            await self._focuser.move_to(position)

    async def _measure_hfr(self) -> float:
        """Take a short exposure and return the mean HFR of detected stars."""
        if self._camera is None:
            return 2.0
        frame = await self._camera.get_image_array()
        if frame is None:
            return float("nan")
        return _compute_hfr(frame)

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
    import numpy as np
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
        regions.append(RegionResult(region_name=name, hfr=hfr, fwhm=hfr * 1.5))
    return AberrationResult(regions=regions)


def _compute_hfr(frame) -> float:
    """Estimate the mean HFR of stars in *frame* using SEP if available."""
    try:
        import sep
        import numpy as np
        data = frame.astype(np.float64)
        bkg = sep.Background(data)
        data_sub = data - bkg
        objects = sep.extract(data_sub, 1.5, err=bkg.globalrms)
        if len(objects) == 0:
            return 2.0
        # Approximate HFR as FWHM/2 via flux-radius
        return float(np.median(objects["a"] + objects["b"]) / 2)
    except Exception:
        import numpy as np
        return float(np.std(frame) / (np.mean(frame) + 1e-6) * 2.0) or 2.0
