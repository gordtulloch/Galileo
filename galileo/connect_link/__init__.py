# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Connect Link — the node-to-node / app / browser link service (SDD §4.28, LINK-*).

This package holds the transport-independent core first: permissions, the peer store and the
audit log. The listener, pairing, dispatcher and gateway are layered on these.
"""

from galileo.connect_link.audit import AuditEvent, AuditLog
from galileo.connect_link.peers import DelegationError, Peer, PeerError, PeerStore
from galileo.connect_link.permissions import (
    PAIRED_PERMISSIONS,
    PERMISSION_OUTREACH_VIEW,
    GrantError,
    validate_grant,
)

__all__ = [
    "PAIRED_PERMISSIONS", "PERMISSION_OUTREACH_VIEW", "AuditEvent", "AuditLog", "DelegationError",
    "GrantError", "Peer", "PeerError", "PeerStore", "validate_grant",
]
