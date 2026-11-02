# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Replication support — what a sync plugin (NodeConnect) needs from core (SDD §4.32, REPL-*).

Change tracking and tombstones (``tracking``), the replicable-table registry (``registry``), the
settings-changed event (``events``), the session busy signal (``busy``) and typed access to the
core-owned sync tables (``syncstore``). Nothing here talks to another node.
"""

from galileo.replication.busy import SessionBusy, get_session_busy
from galileo.replication.events import SettingsChanged, publish_settings_changed
from galileo.replication.registry import (
    NOT_CONFIGURATION,
    PENDING_REGISTRATION,
    RegistryError,
    ReplicableRegistry,
    ReplicableSpec,
    register_defaults,
    registry,
)
from galileo.replication.syncstore import SyncStore, SyncStorePort
from galileo.replication.tracking import NotMasterError, RevisionIssuer, apply_mode

__all__ = [
    "NOT_CONFIGURATION", "PENDING_REGISTRATION", "NotMasterError", "RegistryError", "ReplicableRegistry",
    "ReplicableSpec", "RevisionIssuer", "SessionBusy", "SettingsChanged", "SyncStore", "SyncStorePort",
    "apply_mode", "get_session_busy", "publish_settings_changed", "register_defaults", "registry",
]
