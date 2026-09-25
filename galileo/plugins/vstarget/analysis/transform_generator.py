# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Transformation coefficient generator (adapted from VSTarget analysis/transform_generator.py)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from galileo.plugins.vstarget.planning.models import TransformationCoefficients
    from galileo.plugins.vstarget.analysis.photometry import StandardFieldObservation


def compute_transformation_coefficients(
    observations: list[StandardFieldObservation],
) -> TransformationCoefficients:
    """Least-squares fit AAVSO transformation coefficients from standard-field obs (VST-AN-060)."""
    from galileo.plugins.vstarget.planning.models import TransformationCoefficients
    try:
        import numpy as np

        b_mags = np.array([o.b_mag for o in observations])
        v_mags = np.array([o.v_mag for o in observations])
        b_inst = np.array([o.b_inst for o in observations])
        v_inst = np.array([o.v_inst for o in observations])

        bv_std = b_mags - v_mags
        bv_inst = b_inst - v_inst

        if len(bv_std) < 2:
            return TransformationCoefficients()

        Tbv_coeff = float(np.polyfit(bv_inst, bv_std, 1)[0])
        Tv_coeff = float(np.polyfit(v_inst - np.mean(v_inst), v_mags - np.mean(v_mags), 1)[0])
        return TransformationCoefficients(Tbv=Tbv_coeff, Tv=Tv_coeff)
    except Exception as exc:
        logger.debug("Transform coefficient calculation failed: %s", exc)
        return TransformationCoefficients()
