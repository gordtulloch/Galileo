# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Version handshake (LINK-080).

Both sides exchange the Galileo version, plugin-API version, schema (migration) level and Connect
Link protocol version; a plugin may add its own payload (for example capability limits).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1


def schema_level() -> int:
    """Number of the newest applied migration (0 if none or no database)."""
    try:
        from galileo.library.database import get_migration_status
        current = get_migration_status()["current"]
        return int(str(current).split("_", 1)[0]) if current != "none" else 0
    except Exception:
        return 0


def local_info() -> dict[str, Any]:
    from galileo import __version__
    from galileo.plugins import _CURRENT_API_VERSION
    return {"galileo": __version__, "plugin_api": _CURRENT_API_VERSION,
            "schema": schema_level(), "protocol": PROTOCOL_VERSION}


@dataclass(frozen=True)
class Compatibility:
    ok: bool                 # the exchange may proceed
    restricted: bool         # ...but not for data that depends on the schema
    message: str             # readable by a person


def check(local: dict[str, Any], remote: dict[str, Any]) -> Compatibility:
    """Judge a remote's handshake against ours: a protocol mismatch refuses, a schema mismatch
    restricts (schema-dependent data is not exchanged), anything else is fine."""
    try:
        rp, lp = int(remote["protocol"]), int(local["protocol"])
    except (KeyError, TypeError, ValueError):
        return Compatibility(False, False, "The other side did not report a Connect Link version.")
    if rp != lp:
        newer = "newer" if rp > lp else "older"
        return Compatibility(False, False, f"The other side runs a {newer} Connect Link protocol "
                             f"({rp}, this node {lp}); update Galileo on whichever is older.")
    try:
        rs, ls = int(remote["schema"]), int(local["schema"])
    except (KeyError, TypeError, ValueError):
        return Compatibility(False, False, "The other side did not report its database version.")
    if rs != ls:
        return Compatibility(True, True, f"The database versions differ (other {rs}, this node {ls}); "
                             "settings and data that depend on it will not be exchanged until both match.")
    return Compatibility(True, False, "Compatible.")


class HandshakeExtensions:
    """Per-plugin additions to the handshake payload."""

    def __init__(self) -> None:
        self._providers: dict[str, Callable[[], dict[str, Any]]] = {}

    def register(self, plugin: str, provider: Callable[[], dict[str, Any]]) -> None:
        self._providers[plugin] = provider

    def unregister(self, plugin: str) -> None:
        self._providers.pop(plugin, None)

    def payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, fn in list(self._providers.items()):
            try:
                out[name] = fn()
            except Exception:                                   # a bad extension never breaks the handshake
                logger.exception("handshake extension %s failed", name)
                out[name] = {}
        return out
