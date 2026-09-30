# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Calibration service — flat wizard and calibration frame capture (CAL-010 … CAL-070)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from galileo.exceptions import FlatCalibrationError, OutsideTwilightError

logger = logging.getLogger(__name__)

# Flats Assistant dialog options (CAL-060/CAL-070) — "Flat Method" and "Method" dropdowns.
FLAT_METHODS = ("Sky Flats", "Observatory Panel", "Flat Panel")
ADU_METHODS = ("Average", "Median")

# Where Sky Flats points the mount: high altitude (away from the horizon's
# murk and gradient) in the East, away from the Milky Way/ecliptic and most
# bright stars — the standard amateur sky-flat vantage point. Tracking is
# turned off while pointed here (CAL-070) so any star in the field trails
# into a faint streak across the exposure instead of staying a sharp, bright
# point that would bias the average/median ADU reading.
SKY_FLAT_ALTITUDE_DEG = 75.0
SKY_FLAT_AZIMUTH_DEG = 90.0

# Bounds/iteration limits for the Sky Flats adaptive-exposure search (CAL-070).
_SKY_FLAT_MIN_EXPOSURE_S = 0.0005
_SKY_FLAT_MAX_EXPOSURE_S = 60.0
_SKY_FLAT_MAX_ATTEMPTS = 15


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
        mount=None,
        output_dir: Path | str = ".",
    ) -> None:
        self._camera = camera
        self._fw = filter_wheel
        self._flat_panel = flat_panel
        self._mount = mount
        self._output_dir = Path(output_dir)
        self.stop_requested = False

    def request_stop(self) -> None:
        """Ask a running Sky Flats run to stop after its current exposure (CAL-070's
        Flats Assistant Stop button) — checked between exposures and between filters,
        never mid-exposure, so it never aborts a capture already in flight."""
        self.stop_requested = True

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

    # --- Sky Flats (CAL-070) -----------------------------------------------

    async def run_sky_flats_all_filters(
        self,
        filters: list[str] | None,
        count: int,
        max_well_depth: int,
        location=None,
        measure: str = "Average",
        exposure_s: float | None = None,
        exposure_increment_s: float = 0.1,
        target_fraction: float = 0.5,
        adu_tolerance: float = 0.10,
        on_filter_start=None,
        on_frame_done=None,
    ) -> list[CalibrationResult]:
        """Run :meth:`run_sky_flats` once for each of *filters* (``None`` or
        empty to capture through whichever single filter the wheel is
        already on, or with no wheel at all) — the Filter field's "All"
        option (CAL-070). The twilight check and the slew-to-vantage-point/
        tracking-off bracket happen once here, not once per filter, since
        re-slewing between filters would gain nothing: the same sky position
        is still usable across the whole run.

        *on_filter_start(filter_name, index, total)* and *on_frame_done(filter_name,
        frame_index, frame_total)* are optional progress callbacks for a UI
        thread to report through, mirroring ``run_flat_wizard``'s own
        callback-free design plus the countdown-style callbacks the Imaging
        page's capture threads already use elsewhere in this codebase."""
        self._require_twilight(location)
        names = list(filters) if filters else ([""] if self._fw is None else [None])
        if names == [None]:
            names = list(self._fw.filter_names)

        results = []
        await self._enter_sky_flat_position(location)
        try:
            for i, filter_name in enumerate(names):
                if self.stop_requested:
                    break
                if on_filter_start is not None:
                    on_filter_start(filter_name, i + 1, len(names))
                if self._fw is not None and filter_name:
                    await self._fw.move_to(self._fw.filter_names.index(filter_name))
                result = await self.run_sky_flats(
                    filter_name or "", count, max_well_depth,
                    measure=measure, exposure_s=exposure_s, exposure_increment_s=exposure_increment_s,
                    target_fraction=target_fraction, adu_tolerance=adu_tolerance,
                    on_frame_done=on_frame_done, _skip_twilight_check=True,
                )
                results.append(result)
        finally:
            await self._leave_sky_flat_position()
        return results

    async def run_sky_flats(
        self,
        filter_name: str,
        count: int,
        max_well_depth: int,
        location=None,
        measure: str = "Average",
        exposure_s: float | None = None,
        exposure_increment_s: float = 0.1,
        target_fraction: float = 0.5,
        adu_tolerance: float = 0.10,
        on_frame_done=None,
        _skip_twilight_check: bool = False,
    ) -> CalibrationResult:
        """Capture *count* sky flats in *filter_name* (CAL-070): take an
        exposure of the twilight sky, measure its average/median ADU
        (*measure*), and adjust the exposure time to bring that reading to
        *target_fraction* (50% by default) of *max_well_depth* — the value
        set on Equipment > Camera's Max Well Depth field. The same
        convergence loop covers both the initial calibration (an explicit
        *exposure_s* still gets checked and nudged, not just an omitted one)
        and every later frame: twilight sky brightness keeps changing, so
        each of the *count* frames is measured and retaken, adjusting
        exposure again, until it lands within *adu_tolerance* (10%) of the
        target before moving on to the next one — "after each flat adjust
        the exposure and retake if not within 10%", as specified.

        Checks the local twilight window itself (needs *location*, an
        :class:`~galileo.planning.visibility.ObservingLocation`) unless
        *_skip_twilight_check* is set — the normal path,
        :meth:`run_sky_flats_all_filters`, already checked it once and also
        did the mount slew/tracking-off bracket, so a filter-by-filter call
        from there only needs to run the exposure convergence and capture."""
        if not _skip_twilight_check:
            self._require_twilight(location)
        target_adu = max_well_depth * target_fraction
        exposure = exposure_s if exposure_s is not None else exposure_increment_s

        frames_captured = 0
        for i in range(count):
            if self.stop_requested:
                break
            converged = await self._converge_sky_flat_exposure(
                exposure, target_adu, measure, adu_tolerance, exposure_increment_s,
            )
            if converged is None:      # stopped mid-convergence, before any frame landed
                break
            exposure, data = converged
            path = self._save_frame(data, "flat", filter_name, i + 1, exposure)
            frames_captured += 1
            if path is not None:
                self._register_with_library(path)
            if on_frame_done is not None:
                on_frame_done(filter_name, i + 1, count)

        return CalibrationResult(frames_captured=frames_captured, final_exposure_s=exposure, filter_name=filter_name)

    async def _converge_sky_flat_exposure(
        self, exposure: float, target_adu: float, measure: str, tolerance: float, increment_s: float,
    ):
        """One sky flat: expose, measure, and — while the reading is outside
        *tolerance* of *target_adu* — adjust *exposure* by at least
        *increment_s* and retake, up to a bounded number of attempts.
        Returns ``(exposure_used, frame_data)`` for the frame that finally
        landed within tolerance, or ``None`` if ``stop_requested`` was set
        before a frame within tolerance was captured — checked between
        exposures, same as the frame-level Stop check, never mid-exposure."""
        for _ in range(_SKY_FLAT_MAX_ATTEMPTS):
            if self.stop_requested:
                return None
            await self._camera.start_exposure(duration=exposure, frame_type="Flat Field", binning=1)
            data = await self._camera.get_image_array()
            measured = _mean_adu(data) if measure == "Average" else _median_adu(data)
            if target_adu and abs(measured - target_adu) / target_adu <= tolerance:
                return exposure, data
            exposure = _adjust_sky_flat_exposure(exposure, measured, target_adu, increment_s)
            if not (_SKY_FLAT_MIN_EXPOSURE_S <= exposure <= _SKY_FLAT_MAX_EXPOSURE_S):
                raise FlatCalibrationError(
                    f"Sky Flats: target ADU {target_adu:.0f} not reachable within the "
                    f"{_SKY_FLAT_MIN_EXPOSURE_S:g}s–{_SKY_FLAT_MAX_EXPOSURE_S:g}s exposure range."
                )
        raise FlatCalibrationError(
            f"Sky Flats: target ADU {target_adu:.0f} not reached after {_SKY_FLAT_MAX_ATTEMPTS} attempts."
        )

    def _require_twilight(self, location) -> None:
        from galileo.planning.visibility import is_twilight
        if location is None or not is_twilight(location):
            raise OutsideTwilightError(
                "Sky Flats only works during local dawn or dusk twilight — the sky is either too "
                "bright (still daylight) or too dark (full night) right now."
            )

    async def _enter_sky_flat_position(self, location) -> None:
        """Slew to the Sky Flats vantage point (East, high altitude, away from bright
        stars) and turn tracking off, so any star in frame trails into a faint streak
        rather than staying a sharp point (CAL-070)."""
        if self._mount is None:
            return
        from galileo.planning.visibility import altaz_to_radec_deg
        radec = altaz_to_radec_deg(SKY_FLAT_ALTITUDE_DEG, SKY_FLAT_AZIMUTH_DEG, location) if location else None
        if radec is not None:
            await self._mount.slew_to_coordinates(radec[0], radec[1])
        await self._mount.set_tracking(False)

    async def _leave_sky_flat_position(self) -> None:
        """Restore tracking once the Sky Flats run ends, successfully or not."""
        if self._mount is None:
            return
        try:
            await self._mount.set_tracking(True)
        except Exception:
            logger.exception("Could not restore mount tracking after Sky Flats")

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

    def _save_frame(self, data, frame_type: str, filter_name: str, idx: int, exp: float) -> Path | None:
        """Write *data* as a FITS calibration frame; returns the path written, or
        ``None`` on failure (logged, not raised — a failed save shouldn't abort
        the rest of a capture run)."""
        try:
            import datetime
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
            # Required by the Library's ingest validator (galileo.library.core.file_processing) —
            # without it, register_capture() rejects the frame outright.
            hdr["DATE-OBS"] = datetime.datetime.now(datetime.UTC).isoformat()
            fits.PrimaryHDU(data, header=hdr).writeto(path, overwrite=True)
            return path
        except Exception:
            logger.exception("Failed to save calibration frame")
            return None

    def _register_with_library(self, path: Path) -> None:
        """Catalog a Sky Flats frame into the Library (CAL-070): moves it out of
        the scratch output folder into the repository, the same way a manual
        Imaging-tab capture is filed (``LibraryRegistrar.register_capture``).
        Logged, not raised, on failure — a frame that couldn't be filed is just
        left where :meth:`_save_frame` wrote it, rather than losing the run."""
        try:
            from galileo.library.registrar import LibraryRegistrar
            if LibraryRegistrar().register_capture(path) is None:
                logger.warning("Sky Flats frame was not added to the Library: %s", path)
        except Exception:
            logger.exception("Could not register Sky Flats frame with the Library: %s", path)


def _mean_adu(data) -> float:
    try:
        import numpy as np
        return float(np.mean(data))
    except Exception:
        return 0.0


def _median_adu(data) -> float:
    try:
        import numpy as np
        return float(np.median(data))
    except Exception:
        return 0.0


def _adjust_sky_flat_exposure(current: float, measured_adu: float, target_adu: float, increment_s: float) -> float:
    """Move *current* toward producing *target_adu*, for the Sky Flats convergence
    loop (CAL-070). ADU is roughly proportional to exposure time for an unsaturated
    sky background, so a ratio-based step reaches the target in one or two attempts
    for a typical miss — but that ratio collapses toward zero right as the reading
    approaches (or starts at/below) zero, which would stall the search, so the step
    never moves by less than one *increment_s* (the dialog's Exposure Increment
    field) in the needed direction."""
    if measured_adu <= 0:
        return current + increment_s
    ratio_step = current * (target_adu / measured_adu) - current
    if abs(ratio_step) < increment_s:
        ratio_step = increment_s if target_adu > measured_adu else -increment_s
    return max(current + ratio_step, _SKY_FLAT_MIN_EXPOSURE_S)
