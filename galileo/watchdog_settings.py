# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Saved settings for the crash/hang watchdog (SAFE-060): whether it is armed and its timeout."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {"enabled": True, "timeout_s": 300.0}
MIN_TIMEOUT_S = 10.0
MAX_TIMEOUT_S = 3600.0


NAMESPACE = "watchdog"
LEGACY_FILE = "watchdog.json"   # one-time import, then renamed *.migrated


def load_watchdog_settings() -> dict[str, Any]:
    """The saved settings, with a default for anything missing, unreadable or out of range.

    Safe to call before the database is up (it returns the defaults) and never raises."""
    from galileo.settings_store import load_with_legacy
    settings = dict(DEFAULTS)
    raw = load_with_legacy(NAMESPACE, LEGACY_FILE)
    if isinstance(raw.get("enabled"), bool):
        settings["enabled"] = raw["enabled"]
    timeout = raw.get("timeout_s")
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
        settings["timeout_s"] = min(MAX_TIMEOUT_S, max(MIN_TIMEOUT_S, float(timeout)))
    return settings


def save_watchdog_settings(settings: dict[str, Any]) -> None:
    """Save the options (clamping the timeout); they take effect the next time Galileo starts."""
    from galileo.settings_store import set_namespace
    timeout = settings.get("timeout_s", DEFAULTS["timeout_s"])
    set_namespace(NAMESPACE, {
        "enabled": bool(settings.get("enabled", DEFAULTS["enabled"])),
        "timeout_s": min(MAX_TIMEOUT_S, max(MIN_TIMEOUT_S, float(timeout))),
    })
