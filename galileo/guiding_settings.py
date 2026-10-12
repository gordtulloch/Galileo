# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Remembered Guiding options (Options > Guiding), kept in the shared database (``app_settings``, namespace ``guiding``).

These are the dither and settle parameters sent to PHD2 (GUIDE-030): how far a dither moves the
guide star, whether it moves only in RA, and how PHD2 decides the guide star has settled again.
The PHD2 host/port are not here — they are saved per Pier from the Guiding screen.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "dither_amount_px": 3.0,
    "dither_ra_only": False,
    "settle_pixels": 1.5,
    "settle_time_s": 10.0,
    "settle_timeout_s": 100.0,
}

# key -> (minimum, maximum) for the numeric options.
RANGES: dict[str, tuple[float, float]] = {
    "dither_amount_px": (0.1, 30.0),
    "settle_pixels": (0.1, 10.0),
    "settle_time_s": (1.0, 600.0),
    "settle_timeout_s": (5.0, 3600.0),
}


NAMESPACE = "guiding"
LEGACY_FILE = "guiding.json"   # one-time import, then renamed *.migrated


def _clean(raw: Any) -> dict[str, Any]:
    settings = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return settings
    if isinstance(raw.get("dither_ra_only"), bool):
        settings["dither_ra_only"] = raw["dither_ra_only"]
    for key, (low, high) in RANGES.items():
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            settings[key] = min(high, max(low, float(value)))
    return settings


def load_guiding_settings() -> dict[str, Any]:
    """The saved options, with a default for anything missing, unreadable or out of range."""
    from galileo.settings_store import load_with_legacy
    return _clean(load_with_legacy(NAMESPACE, LEGACY_FILE))


def save_guiding_settings(settings: dict[str, Any]) -> None:
    from galileo.settings_store import set_namespace
    set_namespace(NAMESPACE, _clean(settings))
