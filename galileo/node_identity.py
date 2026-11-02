# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""This node's identity: a random id made once and kept in the settings database.

It names the origin of records that travel between nodes (``HIST-050``) and the node in a Connect Link
advertisement. It is the one setting that is never replicated: two nodes must not share an id.
"""

from __future__ import annotations

import uuid

from galileo import settings_store

NAMESPACE = "node"
_cached: str | None = None


def get_node_id() -> str:
    """The node id, created on first use. Without a database it is fixed for this process only."""
    global _cached
    stored = settings_store.get_setting(NAMESPACE, "id", "")
    if stored:
        _cached = str(stored)
        return _cached
    if _cached is None:
        _cached = uuid.uuid4().hex
    settings_store.set_setting(NAMESPACE, "id", _cached)
    return _cached


def reset_cache() -> None:
    """Forget the in-process copy (tests, and after the database is replaced)."""
    global _cached
    _cached = None


__all__ = ["NAMESPACE", "get_node_id", "reset_cache"]
