"""Aperture photometry engine (adapted from VSTarget analysis/photometry.py)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PhotometryResult:
    """Result from one aperture photometry run."""
    target: str
    jd: float
    magnitude: float
    uncertainty: float
    filter_band: str
    comp_star: str = ""
    check_star: str = ""
    is_transformed: bool = False


@dataclass
class StandardFieldObservation:
    """One standard-field observation for transformation coefficient calculation."""
    star: str
    b_mag: float
    v_mag: float
    r_mag: float
    b_inst: float
    v_inst: float
    r_inst: float


class AperturePhotometryEngine:
    """Performs aperture photometry against AAVSO VSP comparison stars (VST-AN-040)."""

    def __init__(
        self,
        aperture_radius: float = 8.0,
        annulus_inner: float = 12.0,
        annulus_outer: float = 20.0,
    ) -> None:
        self.aperture_radius = aperture_radius
        self.annulus_inner = annulus_inner
        self.annulus_outer = annulus_outer

    def measure_star(self, image_data, x: float, y: float) -> tuple[float, float]:
        """Return (flux, flux_error) for a star at pixel (*x*, *y*)."""
        try:
            import numpy as np
            from photutils.aperture import CircularAperture, CircularAnnulus, aperture_photometry

            aperture = CircularAperture((x, y), r=self.aperture_radius)
            annulus = CircularAnnulus((x, y), r_in=self.annulus_inner, r_out=self.annulus_outer)
            ann_stats = aperture_photometry(image_data, annulus)
            sky_per_px = float(ann_stats["aperture_sum"][0]) / annulus.area
            sky_total = sky_per_px * aperture.area
            phot = aperture_photometry(image_data, aperture)
            flux = float(phot["aperture_sum"][0]) - sky_total
            flux_error = float(np.sqrt(max(flux, 1)))
            return flux, flux_error
        except Exception as exc:
            logger.debug("Photometry error: %s", exc)
            return 0.0, 1.0

    def differential_magnitude(
        self,
        target_flux: float,
        comp_fluxes: list[float],
        comp_mags: list[float],
    ) -> tuple[float, float]:
        """Ensemble linear-regression differential photometry (VST-AN-040)."""
        try:
            import numpy as np
            if not comp_fluxes:
                return 99.0, 99.0
            comp_inst_mags = [-2.5 * np.log10(f + 1e-9) for f in comp_fluxes]
            target_inst = -2.5 * np.log10(target_flux + 1e-9)
            coeffs = np.polyfit(comp_inst_mags, comp_mags, 1)
            mag = float(np.polyval(coeffs, target_inst))
            uncertainty = float(np.std(np.array(comp_mags) - np.polyval(coeffs, comp_inst_mags)))
            return mag, max(uncertainty, 0.001)
        except Exception:
            return 99.0, 99.0
