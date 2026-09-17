"""Full variable-star analysis service (VST-AN-010 … VST-AN-090)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

# Re-exported so callers can do ``from galileo.vstarget.analysis import Foo``
from galileo.vstarget.analysis.exposure import ExposureTimeCalculator  # noqa: F401
from galileo.vstarget.analysis.finder_chart import FinderChartRenderer  # noqa: F401
from galileo.vstarget.analysis.photometry import (  # noqa: F401
    AperturePhotometryEngine,
    PhotometryResult,
    StandardFieldObservation,
)
from galileo.vstarget.analysis.sftp_downloader import SftpImageRetriever  # noqa: F401
from galileo.vstarget.planning.models import TransformationCoefficients  # noqa: F401

logger = logging.getLogger(__name__)


class VariableStarAnalysis:
    """Coordinates plate-solve, stack, photometry, transform, and report generation."""

    def __init__(self) -> None:
        from galileo.vstarget.analysis.photometry import AperturePhotometryEngine
        self._photometry = AperturePhotometryEngine()
        self._solver = None
        self._comparison_stars: list[dict] = []
        self._transformation_coefficients = None

    # --- Image retrieval (VST-AN-010) ------------------------------------

    # SftpImageRetriever is in galileo.vstarget.analysis.sftp_downloader

    # --- Plate solving (VST-AN-020) --------------------------------------

    async def solve_image(self, fits_path: "Path | str"):
        from galileo.vstarget.analysis.platesolve import solve_fits
        if self._solver is not None:
            return await self._solver.solve(fits_path)
        return await solve_fits(fits_path)

    # --- Stacking (VST-AN-030) -------------------------------------------

    async def stack(self, frames: "list[Path]", output_path: "Path | str") -> Path:
        from galileo.vstarget.analysis.stack import stack_frames
        return await stack_frames(frames, output_path)

    # --- Photometry (VST-AN-040) -----------------------------------------

    async def run_photometry(
        self,
        image_path: "Path | str",
        target: dict,
        filter_band: str = "V",
    ):
        from astropy.io import fits
        from astropy.wcs import WCS
        from galileo.vstarget.analysis.photometry import PhotometryResult

        try:
            import numpy as np
            with fits.open(str(image_path)) as hdul:
                data = hdul[0].data.astype(np.float64)
                hdr = hdul[0].header
                wcs = WCS(hdr)

            # Convert target RA/Dec to pixel
            target_ra = target.get("ra", target.get("ra_deg", 0))
            target_dec = target.get("dec", target.get("dec_deg", 0))

            try:
                px, py = wcs.all_world2pix(target_ra, target_dec, 0)
            except Exception:
                px, py = data.shape[1] / 2, data.shape[0] / 2

            target_flux, target_err = self._photometry.measure_star(data, float(px), float(py))

            comp_fluxes, comp_mags = [], []
            for comp in self._comparison_stars:
                try:
                    cx, cy = wcs.all_world2pix(comp["ra"], comp["dec"], 0)
                except Exception:
                    continue
                f, _ = self._photometry.measure_star(data, float(cx), float(cy))
                comp_fluxes.append(f)
                comp_mags.append(float(comp[f"mag_{filter_band.lower()}"]))

            mag, uncertainty = self._photometry.differential_magnitude(
                target_flux, comp_fluxes, comp_mags
            )

            import datetime
            from astropy.time import Time
            jd = float(Time(hdr.get("DATE-OBS", "2026-01-01"), format="isot").jd)

            return PhotometryResult(
                target=target.get("name", ""),
                jd=jd,
                magnitude=mag,
                uncertainty=uncertainty,
                filter_band=filter_band,
                comp_star=self._comparison_stars[0]["label"] if self._comparison_stars else "",
            )
        except Exception as exc:
            logger.exception("Photometry failed: %s", exc)
            from galileo.vstarget.analysis.photometry import PhotometryResult
            return PhotometryResult(target=target.get("name", ""), jd=0, magnitude=99, uncertainty=99, filter_band=filter_band)

    # --- AAVSO report (VST-AN-050) ---------------------------------------

    def export_aavso_report(self, measurements: list, output_path: "Path | str") -> None:
        from galileo.vstarget.analysis.report import save_aavso_report
        save_aavso_report(measurements, output_path)

    # --- Transformation coefficients (VST-AN-060, VST-AN-070) ----------

    async def compute_transformation_coefficients(self, observations: list):
        from galileo.vstarget.analysis.transform_generator import compute_transformation_coefficients
        return compute_transformation_coefficients(observations)

    def apply_transformation(self, result):
        from galileo.vstarget.analysis.transform_apply import apply_transformation
        return apply_transformation(result, self._transformation_coefficients)
