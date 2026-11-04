# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The engine's local channel (HEAD-080, HEAD-180): how a desktop on the same computer reaches a running engine.

It is a small HTTP service for the machine's own user, not a network service. On POSIX it listens on a Unix
domain socket in a directory only the engine's user can enter; where that is unavailable (Windows) it listens on
a loopback port. Either way a random token, written to the engine's info file (readable only by its user), must
accompany every request except ``hello``, so another user on the same computer cannot use it. There is no pairing
step: the caller is the operating-system user, and every operation is made as the principal ``desktop``.

Operations pass the same ``Gateway`` pipeline (``LINK-230``) as any client, so the lease, confirmation, safety
refusal and audit are identical; the channel adds only transport, the version check on attach and an event stream
(state changes, lease changes, session and device events) that an attached desktop mirrors.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from galileo.bus import (
    DeviceConnectedEvent,
    DeviceDisconnectedEvent,
    DeviceErrorEvent,
    Event,
    EventBus,
)
from galileo.connect_link.gateway import Gateway, GatewayRequest
from galileo.control_surface import DESKTOP, LeaseBroker, ObservableState, Registry

logger = logging.getLogger(__name__)

PROTOCOL = "1"
API = "/engine/v1"
TOKEN_HEADER = "X-Engine-Token"                                    # noqa: S105 - a header name
DESKTOP_PERMISSIONS = frozenset({"view", "control"})               # Operator rights; never a config class

FORWARDED_EVENTS: tuple[type[Event], ...] = (DeviceConnectedEvent, DeviceDisconnectedEvent, DeviceErrorEvent)


def _plain(value: Any) -> Any:
    """Something JSON can carry: primitives and containers pass, anything else becomes its text."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        import dataclasses
        return _plain(dataclasses.asdict(value))
    return str(getattr(value, "value", value))


class EngineChannel:
    def __init__(self, *, registry: Registry, leases: LeaseBroker, gateway: Gateway, state: ObservableState,
                 devices: Any, bus: EventBus, version: str, directory: Path,
                 extra_events: tuple[type[Event], ...] = (), status_extra: Callable[[], dict[str, Any]] | None = None) -> None:
        self._status_extra = status_extra
        self._registry, self._leases, self._gateway, self._state = registry, leases, gateway, state
        self._devices, self._bus, self.version = devices, bus, version
        self._dir = Path(directory)
        self._events = FORWARDED_EVENTS + extra_events
        self.token = secrets.token_urlsafe(32)
        self._runner: web.AppRunner | None = None
        self._queues: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.address = ""                                          # "unix:/path" or "http://127.0.0.1:port"
        self._unsubscribers: list[Any] = []

    # -- lifecycle -----------------------------------------------------------------------------
    async def start(self) -> dict[str, str]:
        """Start serving; returns what a client needs to attach (address and token)."""
        self._loop = asyncio.get_running_loop()
        app = web.Application(middlewares=[self._auth])
        app.router.add_get(f"{API}/hello", self._hello)
        app.router.add_get(f"{API}/piers", self._piers)
        app.router.add_get(f"{API}/status", self._status)
        app.router.add_get(f"{API}/catalogue/{{pier}}", self._catalogue)
        app.router.add_post(f"{API}/op", self._op)
        app.router.add_post(f"{API}/lease/{{action}}", self._lease)
        app.router.add_get(f"{API}/state/{{pier}}", self._snapshot)
        app.router.add_get(f"{API}/events", self._stream)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site: web.BaseSite
        if hasattr(asyncio.get_running_loop(), "create_unix_server") and sys.platform != "win32":
            self._dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self._dir, stat.S_IRWXU)                      # only the engine's user may enter
            path = self._dir / "engine.sock"
            path.unlink(missing_ok=True)
            site = web.UnixSite(self._runner, str(path))
            await site.start()
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            self.address = f"unix:{path}"
        else:
            site = web.TCPSite(self._runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            self.address = f"http://127.0.0.1:{port}"
        self._subscribe()
        return {"address": self.address, "token": self.token, "protocol": PROTOCOL}

    async def stop(self) -> None:
        for unsubscribe in self._unsubscribers:
            with contextlib.suppress(Exception):
                unsubscribe()
        self._unsubscribers.clear()
        for q in list(self._queues):
            q.put_nowait(None)                                     # end every open stream
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    # -- events out ------------------------------------------------------------------------------
    def _subscribe(self) -> None:
        for et in self._events:
            handler = self._on_bus
            self._bus.subscribe(et, handler)
            self._unsubscribers.append(lambda et=et, h=handler: self._bus.unsubscribe(et, h))
        self._leases.add_listener(self._on_lease)
        for pier in self._devices.pier_ids():
            _seq, _values, unsub = self._state.subscribe(pier, self._on_state)
            self._unsubscribers.append(unsub)

    def _emit(self, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return
        line = json.dumps(_plain(message))
        for q in list(self._queues):
            loop.call_soon_threadsafe(q.put_nowait, line)

    def _on_bus(self, event: Event) -> None:
        self._emit({"type": "event", "name": type(event).__name__, "source": event.source, "payload": event.payload})

    def _on_lease(self, pier: str, previous: str, holder: str, reason: str) -> None:
        self._emit({"type": "lease", "pier": pier, "previous": previous, "holder": holder, "reason": reason})

    def _on_state(self, pier: str, seq: int, key: str, value: Any) -> None:
        self._emit({"type": "state", "pier": pier, "seq": seq, "key": key, "value": value})

    # -- requests ------------------------------------------------------------------------------------
    @web.middleware
    async def _auth(self, request: web.Request, handler):
        if request.path != f"{API}/hello" and not secrets.compare_digest(
                request.headers.get(TOKEN_HEADER, ""), self.token):
            return web.json_response({"error": "not authorised"}, status=401)
        return await handler(request)

    async def _hello(self, request: web.Request) -> web.Response:
        """Versions and protocol, compared before anything else (HEAD-180)."""
        theirs = {"version": request.query.get("version", ""), "protocol": request.query.get("protocol", "")}
        mine = {"version": self.version, "protocol": PROTOCOL}
        if theirs != mine and (theirs["version"] or theirs["protocol"]):
            return web.json_response({
                "error": f"This engine is Galileo {self.version} (protocol {PROTOCOL}) but the desktop is "
                         f"Galileo {theirs['version'] or '?'} (protocol {theirs['protocol'] or '?'}). "
                         "Start both from the same Galileo version.", **mine}, status=409)
        return web.json_response(mine)

    async def _piers(self, request: web.Request) -> web.Response:
        return web.json_response(await self._piers_list())

    async def _piers_list(self) -> list[dict[str, Any]]:
        out = []
        for pier in self._devices.pier_ids():
            out.append({"id": pier, "name": self._devices.pier_name(pier),
                        "connected": self._devices.connected(pier), "lease": self._leases.holder(pier)})
        return out

    async def _status(self, request: web.Request) -> web.Response:
        """What a supervisor wants to know (HEAD-170): version, Piers, sessions and listeners. Read-only."""
        extra = self._status_extra() if self._status_extra else {}
        return web.json_response(_plain({"version": self.version, "protocol": PROTOCOL, "piers": await self._piers_list(),
                                         "listeners": [self.address], **extra}))

    async def _catalogue(self, request: web.Request) -> web.Response:
        return web.json_response(_plain(self._registry.catalogue(request.match_info["pier"])))

    async def _json(self, request: web.Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text=json.dumps({"error": "body must be a JSON object"}),
                                     content_type="application/json")
        return body

    async def _op(self, request: web.Request) -> web.Response:
        body = await self._json(request)
        req = GatewayRequest(
            client_id=DESKTOP, name=str(body.get("name", "")), pier=str(body.get("pier", "")),
            args=body.get("args") if isinstance(body.get("args"), dict) else {}, kind="peer",
            permissions=DESKTOP_PERMISSIONS, idempotency_key=str(body.get("idempotency_key", "")),
            confirm_token=str(body.get("confirm_token", "")), source="local channel")
        outcome = await self._gateway.handle(req)
        return web.json_response(_plain(outcome.as_dict()))

    async def _lease(self, request: web.Request) -> web.Response:
        body, action = await self._json(request), request.match_info["action"]
        pier = str(body.get("pier", ""))
        if action == "acquire":
            result = self._leases.acquire(pier, DESKTOP)
        elif action == "take":
            result = self._leases.take(pier, DESKTOP, bool(body.get("confirmed")))
        elif action == "release":
            return web.json_response({"released": self._leases.release(pier, DESKTOP), "holder": self._leases.holder(pier)})
        else:
            return web.json_response({"error": "unknown lease action"}, status=404)
        return web.json_response({"granted": result.granted, "holder": result.holder,
                                  "can_take_over": result.can_take_over, "reason": result.reason})

    async def _snapshot(self, request: web.Request) -> web.Response:
        seq, values = self._state.snapshot(request.match_info["pier"])
        return web.json_response({"seq": seq, "values": _plain(values)})

    async def _stream(self, request: web.Request) -> web.StreamResponse:
        """Newline-delimited JSON: state changes, lease changes and bus events, until either side closes."""
        resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson", "Cache-Control": "no-store"})
        await resp.prepare(request)
        queue: asyncio.Queue = asyncio.Queue()
        self._queues.add(queue)
        try:
            await resp.write(b'{"type":"ready"}\n')
            while True:
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    line = '{"type":"ping"}'                       # lets the client notice a dead engine
                if line is None:
                    break
                await resp.write(line.encode() + b"\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._queues.discard(queue)
        return resp


__all__ = ["API", "DESKTOP_PERMISSIONS", "PROTOCOL", "TOKEN_HEADER", "EngineChannel"]
