# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Remembered Planning options (Options > Planning), kept in ``planning.json`` in the config folder."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    # Refuse slews into the horizon obstructions drawn on the Star Atlas.
    "block_obstructed_slews": False,
}


def _path():
    from galileo.platform import get_config_dir
    return get_config_dir() / "planning.json"


def load_planning_settings() -> dict[str, Any]:
    """The saved options, with a default for anything missing or unreadable."""
    settings = dict(DEFAULTS)
    try:
        raw = json.loads(_path().read_text("utf-8"))
    except FileNotFoundError:
        return settings
    except Exception:
        logger.exception("Could not read the saved Planning options")
        return settings
    if isinstance(raw, dict):
        for key, default in DEFAULTS.items():
            if isinstance(raw.get(key), type(default)):
                settings[key] = raw[key]
    return settings


def save_planning_settings(settings: dict[str, Any]) -> None:
    data = {key: settings.get(key, default) for key, default in DEFAULTS.items()}
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Could not save the Planning options")
