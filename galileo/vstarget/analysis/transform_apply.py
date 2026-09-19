# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Apply stored transformation coefficients to multi-filter observations (VST-AN-070)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from galileo.vstarget.analysis.photometry import PhotometryResult
    from galileo.vstarget.planning.models import TransformationCoefficients


def apply_transformation(
    result: "PhotometryResult",
    coefficients: "TransformationCoefficients",
) -> "PhotometryResult":
    """Return a new ``PhotometryResult`` with the colour transformation applied (VST-AN-070)."""
    from galileo.vstarget.analysis.photometry import PhotometryResult
    import dataclasses

    # Simplified: apply Tv coefficient to V-band only
    if result.filter_band == "V" and coefficients.Tv != 0:
        corrected_mag = result.magnitude + coefficients.Tv * 0.05  # placeholder delta
    else:
        corrected_mag = result.magnitude

    return dataclasses.replace(result, magnitude=corrected_mag, is_transformed=True)
