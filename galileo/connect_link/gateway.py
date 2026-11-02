# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The request pipeline (LINK-230, ADR-LINK-005).

Every operation request from a paired client passes the same stages in fixed order — identify,
authorise, validate, lease, confirm, idempotency, dispatch — and is audited in a ``finally``, so
MobileConnect and WebConnect cannot differ in the safety-critical steps. The catalogue of operations,
the lease and the load signal are ports (``Protocol``s) so the pipeline is complete before the
Control Surface and lease services exist.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections import OrderedDict, defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from galileo.connect_link.audit import AuditLog
from galileo.connect_link.peers import Peer

OK, REFUSED, INVALID, UNAVAILABLE, BUSY, UNREACHABLE = (
    "ok", "refused", "invalid", "unavailable", "busy", "unreachable")

READ, OPERATE, CONFIRM, EMERGENCY, CONFIG = "read", "operate", "confirm", "emergency", "config"
_PERMISSION = {READ: "view", OPERATE: "control", CONFIRM: "control", EMERGENCY: "control"}


class CatalogueError(ValueError):
    """An operation the Control Surface catalogue must not hold."""


class SafetyRefusal(Exception):
    """Raised by a domain service that declines for safety; surfaced verbatim, never overridden."""


class Unreachable(Exception):
    """Raised by a relay when the owning node cannot be reached."""


class LeasePort(Protocol):
    def holds(self, client_id: str, pier: str) -> bool: ...


@dataclass(frozen=True)
class Result:
    outcome: str
    reason: str = ""
    data: Any = None


@dataclass(frozen=True)
class Operation:
    name: str
    op_class: str
    handler: Callable[[Peer, dict[str, Any]], Awaitable[Any]]
    validate: Callable[[dict[str, Any]], str | None] = lambda args: None      # reason, or None if valid
    needs_lease: bool | None = None                                            # default: not for read/emergency


@dataclass
class Request:
    client: Peer
    op: str
    args: dict[str, Any] = field(default_factory=dict)
    pier: str = ""
    idempotency_key: str = ""
    confirm_token: str = ""


class Catalogue:
    def __init__(self) -> None:
        self._ops: dict[str, Operation] = {}

    def register(self, op: Operation) -> None:
        if op.op_class == CONFIG or op.op_class not in _PERMISSION:
            raise CatalogueError(f"{op.name}: class {op.op_class!r} cannot be on a remote surface")
        self._ops[op.name] = op

    def get(self, name: str) -> Operation | None:
        return self._ops.get(name)


class _Confirmations:
    def __init__(self, clock: Callable[[], float], ttl: float = 30.0) -> None:
        self._clock, self._ttl = clock, ttl
        self._tokens: dict[str, tuple[str, float]] = {}

    @staticmethod
    def _bind(req: Request) -> str:
        blob = json.dumps([req.client.peer_id, req.op, req.pier, req.args], sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def issue(self, req: Request) -> str:
        now = self._clock()
        self._tokens = {t: v for t, v in self._tokens.items() if v[1] > now}
        token = secrets.token_urlsafe(16)
        self._tokens[token] = (self._bind(req), now + self._ttl)
        return token

    def redeem(self, req: Request) -> bool:
        entry = self._tokens.pop(req.confirm_token, None)           # single use
        return entry is not None and entry[1] > self._clock() and secrets.compare_digest(entry[0], self._bind(req))


class Gateway:
    def __init__(
        self, catalogue: Catalogue, audit: AuditLog, lease: LeasePort, *,
        clock: Callable[[], float] = time.monotonic, max_inflight: int = 8,
        rate: tuple[int, float] = (30, 10.0),
        idempotency_size: int = 512,
    ) -> None:
        self._cat, self._audit, self._lease, self._clock = catalogue, audit, lease, clock
        self._confirm = _Confirmations(clock)
        self._max_inflight, self._inflight = max_inflight, 0
        self._rate = rate
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._done: OrderedDict[tuple[str, str], Result] = OrderedDict()
        self._done_size = idempotency_size

    async def handle(self, req: Request) -> Result:
        result = Result(UNAVAILABLE, "internal error")
        try:
            result = await self._run(req)
            return result
        finally:                                                     # audit always, including refusal and error
            self._audit.write(req.client.peer_id, req.client.plugin, f"op:{req.op}", result.outcome,
                              result.reason, fields={"pier": req.pier})

    def _limited(self, client_id: str) -> bool:
        n, window = self._rate
        now, hits = self._clock(), self._hits[client_id]
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= n:
            return True
        hits.append(now)
        return False

    async def _run(self, req: Request) -> Result:
        # identify
        client = req.client
        if client.is_service or not client.active(time.time()):
            return Result(REFUSED, "unknown or inactive client")
        op = self._cat.get(req.op)
        if op is None:
            return Result(INVALID, "unknown operation")
        emergency = op.op_class == EMERGENCY
        # authorise
        if _PERMISSION[op.op_class] not in client.permissions:
            return Result(REFUSED, f"requires {_PERMISSION[op.op_class]}")
        if not emergency and self._limited(client.peer_id):            # emergency is never rate-limited
            return Result(BUSY, "rate limited")
        # validate
        problem = op.validate(req.args)
        if problem:
            return Result(INVALID, problem)
        # lease
        needs = op.needs_lease if op.needs_lease is not None else op.op_class in (OPERATE, CONFIRM)
        if needs and not self._lease.holds(client.peer_id, req.pier):
            return Result(REFUSED, "another controller holds the lease")
        # confirm
        if op.op_class == CONFIRM and not self._confirm.redeem(req):
            return Result(REFUSED, "confirmation required", {"confirm_token": self._confirm.issue(req)})
        # idempotency
        key = (client.peer_id, req.idempotency_key)
        if req.idempotency_key and key in self._done:
            return self._done[key]
        # dispatch, under the load governor (an emergency operation is never held back by it)
        if not emergency and self._inflight >= self._max_inflight:
            return Result(BUSY, "node is busy")
        self._inflight += 1
        try:
            data = await op.handler(client, req.args)
            result = Result(OK, "", data)
        except SafetyRefusal as exc:
            result = Result(REFUSED, str(exc))                         # verbatim, never overridden
        except Unreachable as exc:
            result = Result(UNREACHABLE, str(exc))
        except Exception as exc:                                       # BaseException is never caught
            result = Result(UNAVAILABLE, str(exc) or exc.__class__.__name__)
        finally:
            self._inflight -= 1
        if req.idempotency_key and result.outcome == OK:
            self._done[key] = result
            while len(self._done) > self._done_size:
                self._done.popitem(last=False)
        return result
