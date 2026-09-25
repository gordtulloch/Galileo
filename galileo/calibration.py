# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Calibration service — flat wizard and calibration frame capture (CAL-010 … CAL-050)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from galileo.exceptions import FlatCalibrationError

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Summary of one calibration capture run."""
    frames_captured: int
    final_exposure_s: float
    filter_name: str = ""


class CalibrationService:
    """Automated calibration frame capture with adaptive flat-frame exposure."""

    def __init__(
        self,
        camera=None,
        filter_wheel=None,
        flat_panel=None,
        output_dir: Path | str = ".",
    ) -> None:
        self._camera = camera
        self._fw = filter_wheel
        self._flat_panel = flat_panel
        self._output_dir = Path(output_dir)

    # --- Flat wizard (CAL-010 … CAL-050) ----------------------------------

    async def run_flat_wizard(
        self,
        filter_name: str,
        count: int,
        target_adu: int,
        adu_tolerance: float = 0.05,
        min_exposure_s: float = 0.1,
        max_exposure_s: float = 60.0,
    ) -> CalibrationResult:
        """Adaptively find the right exposure then capture *count* flat frames."""
        # Prepare flat panel if available
        if self._flat_panel is not None:
            await self._flat_panel.open_cover()
            await self._flat_panel.set_brightness(128)

        try:
            exposure_s = await self._find_flat_exposure(
                target_adu, adu_tolerance, min_exposure_s, max_exposure_s
            )
            # Capture frames
            for i in range(count):
                await self._camera.start_exposure(
                    duration=exposure_s,
                    frame_type="Flat Field",
                    binning=1,
                )
                data = await self._camera.get_image_array()
                self._save_frame(data, "flat", filter_name, i + 1, exposure_s)
        finally:
            if self._flat_panel is not None:
                await self._flat_panel.close_cover()

        return CalibrationResult(
            frames_captured=count,
            final_exposure_s=exposure_s,
            filter_name=filter_name,
        )

    async def run_flat_wizard_all_filters(
        self,
        count_per_filter: int,
        target_adu: int,
    ) -> list[CalibrationResult]:
        """Run the flat wizard for every filter in the filter wheel (CAL-020)."""
        if self._fw is None:
            return [await self.run_flat_wizard("", count_per_filter, target_adu)]

        results = []
        for filter_name in self._fw.filter_names:
            await self._fw.move_to(self._fw.filter_names.index(filter_name))
            result = await self.run_flat_wizard(filter_name, count_per_filter, target_adu)
            results.append(result)
        return results

    async def capture_darks(
        self,
        exposure_s: float,
        count: int,
        binning: int = 1,
    ) -> CalibrationResult:
        """Capture *count* dark frames at *exposure_s* (CAL-030)."""
        for i in range(count):
            await self._camera.start_exposure(duration=exposure_s, frame_type="Dark Frame", binning=binning)
            data = await self._camera.get_image_array()
            self._save_frame(data, "dark", "", i + 1, exposure_s)
        return CalibrationResult(frames_captured=count, final_exposure_s=exposure_s)

    async def capture_biases(self, count: int, binning: int = 1) -> CalibrationResult:
        """Capture *count* bias frames (CAL-030)."""
        for i in range(count):
            await self._camera.start_exposure(duration=0.001, frame_type="Bias Frame", binning=binning)
            data = await self._camera.get_image_array()
            self._save_frame(data, "bias", "", i + 1, 0.001)
        return CalibrationResult(frames_captured=count, final_exposure_s=0.001)

    # --- Private helpers -------------------------------------------------

    async def _find_flat_exposure(
        self,
        target_adu: int,
        tolerance: float,
        min_exp: float,
        max_exp: float,
    ) -> float:
        """Binary-search for the exposure that produces *target_adu* (CAL-010)."""
        exposure_s = (min_exp + max_exp) / 2.0
        lo, hi = min_exp, max_exp

        for _ in range(12):   # max 12 binary-search iterations
            await self._camera.start_exposure(duration=exposure_s, frame_type="Flat Field")
            data = await self._camera.get_image_array()
            mean_adu = _mean_adu(data)

            rel_error = abs(mean_adu - target_adu) / target_adu
            if rel_error <= tolerance:
                return exposure_s

            if mean_adu < target_adu:
                lo = exposure_s
            else:
                hi = exposure_s
            exposure_s = (lo + hi) / 2.0

            if exposure_s >= max_exp * 0.99:
                raise FlatCalibrationError(
                    f"target ADU {target_adu} not reachable within {max_exp}s"
                )

        return exposure_s

    def _save_frame(self, data, frame_type: str, filter_name: str, idx: int, exp: float) -> None:
        try:
            import numpy as np
            from astropy.io import fits
            if data is None:
                data = np.zeros((10, 10), dtype=np.float32)
            name = f"{frame_type}_{filter_name}_{idx:04d}.fits".lstrip("_")
            path = self._output_dir / frame_type / name
            path.parent.mkdir(parents=True, exist_ok=True)
            hdr = fits.Header()
            hdr["IMAGETYP"] = frame_type
            hdr["FILTER"] = filter_name
            hdr["EXPTIME"] = exp
            fits.PrimaryHDU(data, header=hdr).writeto(path, overwrite=True)
        except Exception:
            logger.exception("Failed to save calibration frame")


def _mean_adu(data) -> float:
    try:
        import numpy as np
        return float(np.mean(data))
    except Exception:
        return 0.0
