# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Connect Link — the node-to-node / app / browser link service (SDD §4.28, LINK-*).

This package holds the transport-independent core first: permissions, the peer store and the
audit log. The listener, pairing, dispatcher and gateway are layered on these.
"""

from galileo.connect_link.audit import AuditEvent, AuditLog
from galileo.connect_link.discovery import DiscoveredNode, Discovery, DiscoveryError, manual_address
from galileo.connect_link.handshake import Handshake, HandshakeResult, Versions
from galileo.connect_link.peers import DelegationError, Peer, PeerError, PeerStore
from galileo.connect_link.permissions import (
    PAIRED_PERMISSIONS,
    PERMISSION_OUTREACH_VIEW,
    GrantError,
    validate_grant,
)
from galileo.connect_link.routes import Route, RouteError, RouteRegistry
from galileo.connect_link.stream import StreamHub
from galileo.connect_link.transfer import TransferClient, TransferError, TransferService

__all__ = [
    "PAIRED_PERMISSIONS", "PERMISSION_OUTREACH_VIEW", "AuditEvent", "AuditLog", "DelegationError", "DiscoveredNode", "Discovery", "DiscoveryError",
    "GrantError", "Handshake", "HandshakeResult", "Peer", "PeerError", "PeerStore", "Route", "RouteError",
    "RouteRegistry", "StreamHub", "TransferClient", "TransferError", "TransferService", "Versions", "manual_address", "validate_grant",
]
