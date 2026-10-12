# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Remembered Planning options (Options > Planning), kept in the shared database (``app_settings``, namespace ``planning``)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    # Refuse slews into the horizon obstructions drawn on the Star Atlas.
    "block_obstructed_slews": False,
}


NAMESPACE = "planning"
LEGACY_FILE = "planning.json"   # one-time import, then renamed *.migrated


def load_planning_settings() -> dict[str, Any]:
    """The saved options, with a default for anything missing or unreadable."""
    from galileo.settings_store import load_with_legacy
    settings = dict(DEFAULTS)
    raw = load_with_legacy(NAMESPACE, LEGACY_FILE)
    for key, default in DEFAULTS.items():
        if isinstance(raw.get(key), type(default)):
            settings[key] = raw[key]
    return settings


def save_planning_settings(settings: dict[str, Any]) -> None:
    from galileo.settings_store import set_namespace
    set_namespace(NAMESPACE, {key: settings.get(key, default) for key, default in DEFAULTS.items()})
