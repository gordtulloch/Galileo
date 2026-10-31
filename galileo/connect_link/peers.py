# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Connect Link peer store (LINK-030, LINK-090, LINK-260).

A peer's token is ``<peer_id>.<secret>``: the id finds the row, the secret is checked against a
salted HMAC-SHA-256 hash and is never stored. The secret is 256 random bits, so a fast keyed hash is
sufficient (a slow password KDF would only add latency to every request).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from galileo.connect_link.permissions import validate_grant


class PeerError(Exception):
    """A peer operation that cannot be done (unknown plugin, unknown peer, ...)."""


class DelegationError(PeerError):
    """A request naming an acting client that Connect Link refuses to act for (LINK-090)."""


@dataclass(frozen=True)
class Peer:
    peer_id: str
    plugin: str
    name: str
    kind: str
    platform: str
    is_service: bool
    permissions: frozenset[str]
    cert_fingerprint: str
    created_at: float
    expires_at: float | None
    revoked_at: float | None
    last_contact: float | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def active(self, now: float) -> bool:
        return self.revoked_at is None and (self.expires_at is None or now < self.expires_at)


def _hash(salt: str, secret: str) -> str:
    return hmac.new(bytes.fromhex(salt), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def _peer(r) -> Peer:
    return Peer(
        peer_id=r.peer_id, plugin=r.plugin, name=r.name, kind=r.kind, platform=r.platform,
        is_service=bool(r.is_service), permissions=frozenset(json.loads(r.permissions or "[]")),
        cert_fingerprint=r.cert_fingerprint, created_at=r.created_at, expires_at=r.expires_at,
        revoked_at=r.revoked_at, last_contact=r.last_contact, metadata=json.loads(r.metadata or "{}"),
    )


class PeerStore:
    """Peers in ``link_peers``. A plugin declares which permissions it may grant before it pairs."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._declared: dict[str, frozenset[str]] = {}

    # -- plugin declarations -------------------------------------------------
    def declare_plugin(self, plugin: str, permissions: Iterable[str]) -> None:
        """Record the permissions *plugin* may grant (LINK-030); later calls replace earlier ones."""
        self._declared[plugin] = frozenset(permissions)

    def _model(self):
        from galileo.library.models.base import db
        from galileo.library.models.link import LinkPeerRecord
        if db.database is None:
            raise PeerError("no database is open")
        db.connect(reuse_if_open=True)
        return LinkPeerRecord

    # -- creation ------------------------------------------------------------
    def create_peer(
        self, plugin: str, name: str, permissions: Iterable[str], *, kind: str = "", platform: str = "",
        cert_fingerprint: str = "", is_service: bool = False, expires_at: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Peer, str]:
        """Create a peer; returns it with its token, the only time the token exists in the clear."""
        if plugin not in self._declared:
            raise PeerError(f"plugin {plugin!r} has not declared its permissions")
        granted = validate_grant(permissions, self._declared[plugin], is_service=is_service)
        model = self._model()
        peer_id = uuid.uuid4().hex
        salt = secrets.token_hex(16)
        secret = secrets.token_urlsafe(32)
        row = model.create(
            peer_id=peer_id, plugin=plugin, name=name, kind=kind, platform=platform,
            is_service=int(is_service), permissions=json.dumps(sorted(granted)), token_salt=salt,
            token_hash=_hash(salt, secret), cert_fingerprint=cert_fingerprint,
            metadata=json.dumps(metadata or {}), created_at=self._clock(), expires_at=expires_at,
        )
        return _peer(row), f"{peer_id}.{secret}"

    # -- lookup --------------------------------------------------------------
    def get(self, peer_id: str) -> Peer | None:
        row = self._model().get_or_none(self._model().peer_id == peer_id)
        return _peer(row) if row else None

    def list(self, plugin: str = "") -> list[Peer]:
        model = self._model()
        q = model.select().order_by(model.created_at)
        if plugin:
            q = q.where(model.plugin == plugin)
        return [_peer(r) for r in q]

    def authenticate(self, token: str) -> Peer | None:
        """The active peer a token belongs to, or ``None`` (unknown, wrong, revoked or expired)."""
        peer_id, sep, secret = (token or "").partition(".")
        if not sep or not secret:
            return None
        model = self._model()
        row = model.get_or_none(model.peer_id == peer_id)
        if row is None:
            return None
        if not hmac.compare_digest(_hash(row.token_salt, secret), row.token_hash):
            return None
        peer = _peer(row)
        return peer if peer.active(self._clock()) else None

    def touch(self, peer_id: str) -> None:
        model = self._model()
        model.update(last_contact=self._clock()).where(model.peer_id == peer_id).execute()

    # -- change --------------------------------------------------------------
    def set_permissions(self, peer_id: str, permissions: Iterable[str]) -> Peer:
        peer = self._require(peer_id)
        granted = validate_grant(permissions, self._declared.get(peer.plugin, ()), is_service=peer.is_service)
        model = self._model()
        model.update(permissions=json.dumps(sorted(granted))).where(model.peer_id == peer_id).execute()
        return self._require(peer_id)

    def set_metadata(self, peer_id: str, metadata: dict[str, Any]) -> Peer:
        """Replace the plugin's own per-peer record; it is deleted with the peer."""
        self._require(peer_id)
        model = self._model()
        model.update(metadata=json.dumps(metadata)).where(model.peer_id == peer_id).execute()
        return self._require(peer_id)

    def revoke(self, peer_id: str) -> Peer:
        """Revoke at once: the token stops working on its next request."""
        self._require(peer_id)
        model = self._model()
        model.update(revoked_at=self._clock()).where(model.peer_id == peer_id).execute()
        return self._require(peer_id)

    def delete(self, peer_id: str) -> bool:
        model = self._model()
        return model.delete().where(model.peer_id == peer_id).execute() > 0

    def delete_plugin_peers(self, plugin: str) -> int:
        model = self._model()
        return model.delete().where(model.plugin == plugin).execute()

    def _require(self, peer_id: str) -> Peer:
        peer = self.get(peer_id)
        if peer is None:
            raise PeerError(f"unknown peer {peer_id!r}")
        return peer

    # -- delegation (LINK-090) ----------------------------------------------
    def resolve_client(self, carrier: Peer, client_id: str) -> Peer:
        """The client a service credential may act for, with the **client's** own scopes.

        Refused unless *carrier* is a service credential and the client is known, active, not itself
        a service and belongs to the carrier's plugin.
        """
        if not carrier.is_service:
            raise DelegationError("only a service credential may act on behalf of a client")
        client = self.get(client_id)
        if client is None or client.is_service:
            raise DelegationError("unknown client")
        if client.plugin != carrier.plugin:
            raise DelegationError("client belongs to another plugin")
        if not client.active(self._clock()):
            raise DelegationError("client is revoked or expired")
        return client
