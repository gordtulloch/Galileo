# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Pairing with approval (LINK-020).

A peer asks to pair; the request is held, with a short confirmation code shown both to the peer and
beside the request on this node, until a person approves or rejects it. On approval the peer
collects its token exactly once. Requests expire, are rate-limited per source address, and are
refused when the pending list is full.
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from galileo.connect_link.peers import Peer, PeerStore

DEFAULT_EXPIRY_S = 300.0
DEFAULT_MAX_PENDING = 20
DEFAULT_RATE_LIMIT = (5, 60.0)       # requests per source address, per window (seconds)


class PairingError(Exception):
    """Base for refused pairing operations."""


class RateLimited(PairingError):
    pass


class PendingListFull(PairingError):
    pass


class UnknownPairing(PairingError):
    pass


@dataclass
class PairingRequest:
    request_id: str
    code: str
    plugin: str
    name: str
    kind: str
    platform: str
    source: str
    created_at: float
    expires_at: float
    state: str = "pending"          # pending | approved | rejected
    token: str | None = None        # held after approval until collected, once
    peer_id: str = ""


class PairingService:
    def __init__(
        self, peers: PeerStore, clock: Callable[[], float] = time.time, *, expiry_s: float = DEFAULT_EXPIRY_S,
        max_pending: int = DEFAULT_MAX_PENDING, rate_limit: tuple[int, float] = DEFAULT_RATE_LIMIT,
    ) -> None:
        self._peers = peers
        self._clock = clock
        self.expiry_s = expiry_s
        self.max_pending = max_pending
        self._rate = rate_limit
        self._requests: dict[str, PairingRequest] = {}
        self._by_source: dict[str, deque[float]] = {}

    def _sweep(self) -> None:
        now = self._clock()
        for rid in [r for r, p in self._requests.items() if now >= p.expires_at]:
            del self._requests[rid]

    def request(self, plugin: str, name: str, kind: str, platform: str, source: str) -> PairingRequest:
        self._sweep()
        now = self._clock()
        hits = self._by_source.setdefault(source, deque())
        window = self._rate[1]
        while hits and now - hits[0] >= window:
            hits.popleft()
        if len(hits) >= self._rate[0]:
            raise RateLimited("too many pairing requests from this address")
        if sum(1 for p in self._requests.values() if p.state == "pending") >= self.max_pending:
            raise PendingListFull("too many pairing requests are waiting")
        hits.append(now)
        req = PairingRequest(
            request_id=uuid.uuid4().hex, code=f"{secrets.randbelow(10**6):06d}", plugin=plugin,
            name=name, kind=kind, platform=platform, source=source, created_at=now,
            expires_at=now + self.expiry_s,
        )
        self._requests[req.request_id] = req
        return req

    def pending(self) -> list[PairingRequest]:
        """What the owner sees beside each confirmation code."""
        self._sweep()
        return [p for p in self._requests.values() if p.state == "pending"]

    def _get(self, request_id: str) -> PairingRequest:
        self._sweep()
        req = self._requests.get(request_id)
        if req is None:
            raise UnknownPairing(request_id)
        return req

    def approve(
        self, request_id: str, permissions: Iterable[str], *, cert_fingerprint: str = "",
        expires_at: float | None = None,
    ) -> Peer:
        req = self._get(request_id)
        if req.state != "pending":
            raise UnknownPairing(f"request is {req.state}")
        peer, token = self._peers.create_peer(
            req.plugin, req.name, permissions, kind=req.kind, platform=req.platform,
            cert_fingerprint=cert_fingerprint, expires_at=expires_at,
        )
        req.state, req.token, req.peer_id = "approved", token, peer.peer_id
        req.expires_at = self._clock() + self.expiry_s      # time left to collect the token
        return peer

    def reject(self, request_id: str) -> None:
        self._get(request_id).state = "rejected"

    def poll(self, request_id: str) -> tuple[str, str | None]:
        """What the requesting peer sees: ``(state, token)``. The token is returned once, then gone.
        An unknown or expired request is ``("expired", None)``."""
        try:
            req = self._get(request_id)
        except UnknownPairing:
            return "expired", None
        if req.state == "approved":
            token, req.token = req.token, None
            if token is None:
                return "collected", None
            return "approved", token
        return req.state, None
