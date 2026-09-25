# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Apply stored transformation coefficients to multi-filter observations (VST-AN-070)."""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from galileo.plugins.vstarget.analysis.photometry import PhotometryResult
    from galileo.plugins.vstarget.planning.models import TransformationCoefficients


def apply_transformation(
    results: list[PhotometryResult],
    coefficients: TransformationCoefficients,
) -> list[PhotometryResult]:
    """Return *results* (one same-epoch measurement per filter, for one target) with the AAVSO
    colour transformation applied (VST-AN-070).

    The standard-magnitude correction for a filter needs a colour index, which in turn needs a
    second filter's measurement of the same target at the same epoch — a single filter's magnitude
    carries no colour information on its own. So this takes the whole set of same-epoch, same-target
    ``PhotometryResult``s (one per filter) rather than one at a time, and corrects whichever filters
    have a usable companion:

    - B/V pair -> instrumental colour index ``(b - v)``, scaled by ``Tbv`` to a standard ``(B-V)``,
      then ``V' = v + Tv * (B-V)`` and ``B' = V' + (B-V)``.
    - V/R pair (used only when there is no B) -> instrumental ``(v - r)`` scaled by ``Tvr``, then
      ``V' = v + Tr * (V-R)`` and ``R' = V' - (V-R)``.

    A filter with no usable companion (e.g. a lone V with neither B nor R alongside it) is returned
    unchanged, with ``is_transformed`` left ``False`` rather than claiming a correction that was
    never actually computed.
    """
    from galileo.plugins.vstarget.analysis.photometry import PhotometryResult  # noqa: F401 (for typing clarity)

    by_filter = {r.filter_band: r for r in results}
    corrected: dict[str, PhotometryResult] = {}

    b, v, r = by_filter.get("B"), by_filter.get("V"), by_filter.get("R")

    if b is not None and v is not None:
        bv_inst = b.magnitude - v.magnitude
        bv_std = coefficients.Tbv * bv_inst
        v_mag = v.magnitude + coefficients.Tv * bv_std
        corrected["V"] = dataclasses.replace(v, magnitude=v_mag, is_transformed=True)
        corrected["B"] = dataclasses.replace(b, magnitude=v_mag + bv_std, is_transformed=True)
    elif v is not None and r is not None:
        vr_inst = v.magnitude - r.magnitude
        vr_std = coefficients.Tvr * vr_inst
        v_mag = v.magnitude + coefficients.Tr * vr_std
        corrected["V"] = dataclasses.replace(v, magnitude=v_mag, is_transformed=True)
        corrected["R"] = dataclasses.replace(r, magnitude=v_mag - vr_std, is_transformed=True)

    return [corrected.get(result.filter_band, result) for result in results]
