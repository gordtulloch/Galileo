# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The request pipeline (LINK-230): the one path from a Connect Link route to a domain service.

Every operation request — from a paired client, a relayed spoke request or an outreach guest — passes,
in order: identify, authorise, validate, lease, confirm, idempotency, dispatch (under a load governor)
and audit. The audit record is written in a ``finally`` so refusals and errors are recorded too. The
pipeline returns a typed :class:`~galileo.control_surface.Outcome` and never swallows or overrides a
refusal made by a safety service.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from galileo.connect_link.audit import AuditLog
from galileo.core.ratelimit import RateLimiter
from galileo.control_surface import LeaseBroker, Outcome, Registry
from galileo.control_surface.registry import CLASSES

logger = logging.getLogger(__name__)

PERMISSION_GUEST = "outreach.view"
# Scheduling classes, highest first (LINK-230): emergency, a running session, interactive work,
# previews and sky data, transfers.
CLASS_EMERGENCY, CLASS_SESSION, CLASS_INTERACTIVE, CLASS_PREVIEW, CLASS_BULK = range(5)


@dataclass(frozen=True)
class GatewayRequest:
    client_id: str                          # the acting client (a browser, an app, a guest slot)
    name: str
    pier: str
    args: dict[str, Any] = field(default_factory=dict)
    plugin: str = ""
    kind: str = "peer"                      # "peer" or "guest"
    permissions: frozenset[str] = frozenset()
    carrier: str = ""                       # the peer carrying a delegated or relayed request
    idempotency_key: str = ""
    confirm_token: str = ""
    source: str = ""

    @property
    def holder(self) -> str:
        """The identity under which the client holds a lease."""
        return f"{self.plugin}:{self.client_id}" if self.plugin else self.client_id


class LoadGovernor:
    """Strict class order under load: a lower class is turned away first. Slots are reserved for the
    higher classes, so previews and transfers can never take the capacity a session or an emergency needs."""

    RESERVE = (0, 1, 2, 4, 6)

    def __init__(self, capacity: int = 8, session_busy: Callable[[], bool] | None = None) -> None:
        self._capacity = capacity
        self._busy = session_busy or (lambda: False)
        self._in_flight = 0
        self._lock = threading.Lock()

    def admit(self, cls: int) -> str:
        """Empty string when admitted, else the reason to give the client."""
        if cls == CLASS_EMERGENCY:
            with self._lock:
                self._in_flight += 1
            return ""
        if cls >= CLASS_PREVIEW and self._busy():
            return "yielding to the running session"
        with self._lock:
            if self._in_flight >= self._capacity - self.RESERVE[cls]:
                return "the node is busy with higher-priority work"
            self._in_flight += 1
        return ""

    def done(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)


class Gateway:
    def __init__(
        self, registry: Registry, leases: LeaseBroker, audit: AuditLog, *,
        clock: Callable[[], float] = time.time, guest_allowlist: Iterable[str] = (),
        governor: LoadGovernor | None = None, limiter: RateLimiter | None = None,
        confirm_ttl_s: float = 60.0, idempotency_ttl_s: float = 600.0,
    ) -> None:
        registry.verify()                                       # CSURF-020: no config entry, ever
        self._registry, self._leases, self._audit, self._clock = registry, leases, audit, clock
        self._guest = frozenset(guest_allowlist)
        self._governor = governor or LoadGovernor()
        self._limiter = limiter or RateLimiter(clock)
        self._confirm_ttl, self._idem_ttl = confirm_ttl_s, idempotency_ttl_s
        self._tokens: dict[str, tuple[str, str, float]] = {}    # token -> (client, fingerprint, expiry)
        self._results: dict[tuple[str, str], tuple[float, str, Outcome]] = {}
        self._lock = threading.Lock()

    # -- the pipeline ----------------------------------------------------------------------
    async def handle(self, req: GatewayRequest) -> Outcome:
        outcome = Outcome("unavailable", "the request could not be processed")
        cls = ""
        try:
            outcome, cls = await self._pipeline(req)
        except Exception:
            logger.exception("Connect Link gateway failed")
        finally:
            self.record(req, outcome, cls)
        return outcome

    async def _pipeline(self, req: GatewayRequest) -> tuple[Outcome, str]:
        # 1. identify
        if not req.client_id or not req.name:
            return Outcome("refused", "the request does not say who is asking"), ""
        spec = self._registry.spec(req.name)
        cls = spec.permission_class if spec else ""
        if cls != "emergency" and not self._limiter.allow(req.client_id):
            return Outcome("busy", "too many requests; slow down"), cls
        # 2. authorise
        denied = self._authorise(req, cls)
        if denied:
            return Outcome("refused", denied), cls
        # 3. validate against the catalogue (an unknown name is "unavailable")
        prepared = self._registry.prepare(req.name, req.args, req.pier)
        if isinstance(prepared, Outcome):
            return prepared, cls
        spec = prepared.spec
        # 4. lease
        if spec.needs_lease and cls != "emergency":
            holder = self._leases.holder(req.pier)
            if holder != req.holder:
                who = holder or "nobody"
                return Outcome("refused", f"you do not hold the control lease for this Pier ({who} does)"
                               if holder else "take the control lease for this Pier first"), cls
        # 5/6. idempotency lookup precedes the confirm check so a retried confirmed request is not
        # asked to confirm twice
        fingerprint = json.dumps([req.name, req.pier, prepared.args], sort_keys=True, default=str)
        if req.idempotency_key:
            cached = self._cached(req, fingerprint)
            if cached is not None:
                return cached, cls
        if cls == "confirm":
            asked = self._confirm(req, fingerprint)
            if asked is not None:
                return asked, cls
        # 7. dispatch under the governor
        reason = self._governor.admit(self._class_of(spec.name, cls))
        if reason:
            return Outcome("busy", reason), cls
        try:
            outcome = await self._registry.run(prepared, req.pier, req.holder)
        finally:
            self._governor.done()
        if spec.needs_lease:
            self._leases.touch(req.pier, req.holder)
        if req.idempotency_key and outcome.status != "busy":
            with self._lock:
                self._results[(req.client_id, req.idempotency_key)] = (
                    self._clock() + self._idem_ttl, fingerprint, outcome)
        return outcome, cls

    # -- stages ----------------------------------------------------------------------------
    def _authorise(self, req: GatewayRequest, cls: str) -> str:
        if req.kind == "guest":
            if PERMISSION_GUEST not in req.permissions:
                return "guests may not use this"
            if req.name not in self._guest or cls != "read":
                return "this is not available to guests"
            return ""
        if cls not in CLASSES:
            return ""                                           # unknown name: validate says unavailable
        need = {"read": ("view", "control")}.get(cls, ("control",))
        if not req.permissions.intersection(need):
            return f"this needs the {need[0]} permission"
        return ""

    @staticmethod
    def _class_of(name: str, cls: str) -> int:
        if cls == "emergency":
            return CLASS_EMERGENCY
        if name.startswith("session."):
            return CLASS_SESSION
        if name.startswith(("preview.", "sky.")):
            return CLASS_PREVIEW
        if name.startswith("transfer."):
            return CLASS_BULK
        return CLASS_INTERACTIVE

    def _cached(self, req: GatewayRequest, fingerprint: str) -> Outcome | None:
        now = self._clock()
        with self._lock:
            for key in [k for k, v in self._results.items() if v[0] <= now]:
                del self._results[key]
            hit = self._results.get((req.client_id, req.idempotency_key))
        if hit is None:
            return None
        if hit[1] != fingerprint:
            return Outcome("invalid", "this idempotency key was used for a different request",
                           path="idempotency_key")
        return hit[2]

    def _confirm(self, req: GatewayRequest, fingerprint: str) -> Outcome | None:
        """None when the request carries a valid, unused confirmation; otherwise the outcome to return."""
        now = self._clock()
        with self._lock:
            for t in [t for t, v in self._tokens.items() if v[2] <= now]:
                del self._tokens[t]
            entry = self._tokens.get(req.confirm_token) if req.confirm_token else None
            if entry is not None and entry[0] == req.client_id and entry[1] == fingerprint:
                del self._tokens[req.confirm_token]           # single use; a wrong presenter cannot burn it
                return None
            token = secrets.token_urlsafe(16)
            self._tokens[token] = (req.client_id, fingerprint, now + self._confirm_ttl)
        reason = "confirmation required" if not req.confirm_token else "that confirmation is not valid; confirm again"
        return Outcome("refused", reason, confirm_token=token)

    # -- audit -----------------------------------------------------------------------------
    def record(self, req: GatewayRequest, outcome: Outcome, cls: str) -> None:
        """Write the audit event for a request (also used by the relay for requests it forwards)."""
        fields: dict[str, Any] = {"pier": req.pier, "class": cls}
        if outcome.correlation_id:
            fields["correlation_id"] = outcome.correlation_id
        if req.source:
            fields["source"] = req.source
        actor = "guest" if req.kind == "guest" else req.client_id        # a guest identifier is never stored
        self._audit.write(actor, req.plugin, f"op {req.name}", outcome.status, outcome.reason,
                          carrier=req.carrier, fields=fields)

    def catalogue(self, req: GatewayRequest) -> dict[str, Any]:
        """The catalogue as this client may use it (a guest sees only the guest allowlist)."""
        cat = self._registry.catalogue(req.pier)
        if req.kind == "guest":
            cat["operations"] = [o for o in cat["operations"] if o["name"] in self._guest]
        return cat


__all__ = ["CLASS_BULK", "CLASS_EMERGENCY", "CLASS_INTERACTIVE", "CLASS_PREVIEW", "CLASS_SESSION",
           "PERMISSION_GUEST", "Gateway", "GatewayRequest", "LoadGovernor", "RateLimiter"]
