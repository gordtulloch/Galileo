# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Remembered Imaging options (Options > Imaging), kept in the shared database (``app_settings``, namespace ``imaging``)."""

from __future__ import annotations

import logging
from typing import Any

from galileo.metadata import BITPIX_AUTO, BITPIX_CHOICES

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    # The FITS sample format saved frames are written in (IMG-170): "auto" picks the smallest
    # portable type that fits each frame (the historical behaviour), or one of BITPIX_CHOICES'
    # other values forces every frame to that one format.
    "bitpix": BITPIX_AUTO,
    # How much neighbouring mosaic panes overlap, as a percentage of a pane (FRAME-040). Shared by
    # both Framing Assistant entry points (the Imaging tab and the Session Image block).
    "mosaic_overlap_pct": 10.0,
}

MOSAIC_OVERLAP_RANGE = (0.0, 50.0)


NAMESPACE = "imaging"
LEGACY_FILE = "imaging.json"   # one-time import, then renamed *.migrated


def load_imaging_settings() -> dict[str, Any]:
    """The saved options, with a default for anything missing, unreadable or no longer valid."""
    from galileo.settings_store import load_with_legacy
    settings = dict(DEFAULTS)
    raw = load_with_legacy(NAMESPACE, LEGACY_FILE)
    if raw.get("bitpix") in BITPIX_CHOICES:
        settings["bitpix"] = raw["bitpix"]
    overlap = raw.get("mosaic_overlap_pct")
    if isinstance(overlap, (int, float)) and not isinstance(overlap, bool)             and MOSAIC_OVERLAP_RANGE[0] <= overlap <= MOSAIC_OVERLAP_RANGE[1]:
        settings["mosaic_overlap_pct"] = float(overlap)
    return settings


def save_imaging_settings(settings: dict[str, Any]) -> None:
    from galileo.settings_store import set_namespace
    bitpix = settings.get("bitpix", BITPIX_AUTO)
    overlap = settings.get("mosaic_overlap_pct", DEFAULTS["mosaic_overlap_pct"])
    low, high = MOSAIC_OVERLAP_RANGE
    set_namespace(NAMESPACE, {
        "bitpix": bitpix if bitpix in BITPIX_CHOICES else BITPIX_AUTO,
        "mosaic_overlap_pct": float(min(max(overlap, low), high)),
    })
