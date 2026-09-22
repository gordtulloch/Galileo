# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Remembered Imaging options (Options > Imaging), kept in ``imaging.json`` in the config folder."""

from __future__ import annotations

import json
import logging
from typing import Any

from galileo.metadata import BITPIX_AUTO, BITPIX_CHOICES

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    # The FITS sample format saved frames are written in (IMG-170): "auto" picks the smallest
    # portable type that fits each frame (the historical behaviour), or one of BITPIX_CHOICES'
    # other values forces every frame to that one format.
    "bitpix": BITPIX_AUTO,
}


def _path():
    from galileo.platform import get_config_dir
    return get_config_dir() / "imaging.json"


def load_imaging_settings() -> dict[str, Any]:
    """The saved options, with a default for anything missing, unreadable or no longer valid."""
    settings = dict(DEFAULTS)
    try:
        raw = json.loads(_path().read_text("utf-8"))
    except FileNotFoundError:
        return settings
    except Exception:
        logger.exception("Could not read the saved Imaging options")
        return settings
    if isinstance(raw, dict) and raw.get("bitpix") in BITPIX_CHOICES:
        settings["bitpix"] = raw["bitpix"]
    return settings


def save_imaging_settings(settings: dict[str, Any]) -> None:
    bitpix = settings.get("bitpix", BITPIX_AUTO)
    data = {"bitpix": bitpix if bitpix in BITPIX_CHOICES else BITPIX_AUTO}
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Could not save the Imaging options")
