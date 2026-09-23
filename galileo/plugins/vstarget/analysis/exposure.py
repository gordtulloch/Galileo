# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Exposure-time calculator (adapted from VSTarget analysis/exposure.py)."""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


class ExposureTimeCalculator:
    """Calibrate per-telescope/filter throughput and suggest exposure times (VST-AN-080)."""

    def __init__(
        self,
        telescope_aperture_mm: float = 200.0,
        focal_length_mm: float = 1000.0,
        pixel_size_um: float = 5.86,
        qe: float = 0.7,
    ) -> None:
        self.aperture_mm = telescope_aperture_mm
        self.focal_length_mm = focal_length_mm
        self.pixel_size_um = pixel_size_um
        self.qe = qe

    def compute(
        self,
        target_magnitude: float,
        filter_band: str = "V",
        target_snr: float = 100.0,
        sky_brightness_mag_arcsec2: float = 20.0,
    ) -> float:
        """Return the required exposure time in seconds (VST-AN-080)."""
        # Simple signal-to-noise estimate:
        # S ∝ flux × aperture_area × QE × t
        # N ≈ sqrt(S + sky × aperture_px × t)
        # SNR = S / N → solve for t.

        area_cm2 = math.pi * (self.aperture_mm / 20) ** 2  # convert mm to cm
        # Star flux (photons/cm²/s) approximated from magnitude
        zp_flux = 1e6  # photons/cm²/s at mag 0 (rough V-band approximation)
        star_flux = zp_flux * 10 ** (-0.4 * target_magnitude)
        signal_rate = star_flux * area_cm2 * self.qe

        if signal_rate <= 0:
            return 3600.0

        # Approximate t for target SNR: t = (SNR² × N²) / S² — simplified
        t = (target_snr ** 2) / signal_rate
        return max(1.0, min(t, 3600.0))
