# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Connect Link listener (LINK-010, LINK-020; ADR-LINK-006, ADR-LINK-007).

An ``aiohttp`` application on the asyncio loop. Every request passes one middleware before any
route is consulted: the only paths answered without a valid token are *request pairing* and *poll
pairing*; anything else without a token gets the same bare 401 whether or not the path exists, so an
unauthenticated caller learns nothing about which routes there are.
"""

from __future__ import annotations

import logging
import socket

from aiohttp import web

from galileo.connect_link.audit import AuditLog
from galileo.connect_link.certs import CertificateStore
from galileo.connect_link.pairing import PairingError, PairingService, PendingListFull, RateLimited
from galileo.connect_link.peers import Peer, PeerStore

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
DEFAULT_PORT = 8765
API = "/connect/v1"
_PEER = web.RequestKey("link_peer", Peer)


def default_bind_host() -> str:
    """The node's LAN address (never ``0.0.0.0`` unless the owner chooses it, LINK-010). Found by
    asking the OS which interface would reach the LAN; no packet is sent."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _unauthorised() -> web.Response:
    return web.json_response({"error": "unauthorised"}, status=401)


class LinkServer:
    def __init__(
        self, peers: PeerStore, pairing: PairingService, certs: CertificateStore, audit: AuditLog,
    ) -> None:
        self._peers, self._pairing, self._certs, self._audit = peers, pairing, certs, audit
        self._runner: web.AppRunner | None = None
        self.host = ""
        self.port = 0

    @property
    def running(self) -> bool:
        return self._runner is not None

    async def start(self, host: str | None = None, port: int = DEFAULT_PORT) -> None:
        if self._runner is not None:
            return
        app = web.Application(middlewares=[self._gate])
        app.router.add_post(f"{API}/pair", self._pair)
        app.router.add_get(f"{API}/pair/{{request_id}}", self._pair_poll)
        app.router.add_get(f"{API}/whoami", self._whoami)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        self.host = host or default_bind_host()
        site = web.TCPSite(runner, self.host, port, ssl_context=self._certs.ssl_context())
        try:
            await site.start()
        except Exception:
            await runner.cleanup()
            raise
        self._runner = runner
        self.port = runner.addresses[0][1] if runner.addresses else port      # the port actually bound
        logger.info("Connect Link listening on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        runner, self._runner = self._runner, None
        if runner is not None:
            await runner.cleanup()
            self.port = 0

    # -- the one gate every request passes ---------------------------------------------
    @web.middleware
    async def _gate(self, request: web.Request, handler):
        path = request.path
        if request.method == "POST" and path == f"{API}/pair":
            return await handler(request)
        if request.method == "GET" and path.startswith(f"{API}/pair/"):
            return await handler(request)
        auth = request.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        peer = self._peers.authenticate(token) if token else None
        if peer is None:
            self._audit.write("", "", f"{request.method} {path}", "denied", "no valid token",
                              fields={"source": request.remote or ""})
            return _unauthorised()
        self._peers.touch(peer.peer_id)
        request[_PEER] = peer
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            self._audit.write(peer.peer_id, peer.plugin, f"{request.method} {path}", "error", exc.reason or "")
            raise
        self._audit.write(peer.peer_id, peer.plugin, f"{request.method} {path}", "ok")
        return response

    # -- unauthenticated: request and poll pairing ---------------------------------------
    async def _pair(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            plugin, name = str(body["plugin"]), str(body["name"]).strip()
            kind, platform = str(body.get("kind", "")), str(body.get("platform", ""))
            if not name or len(name) > 80:
                raise ValueError("name")
        except Exception:
            return web.json_response({"error": "bad request"}, status=400)
        source = request.remote or ""
        try:
            req = self._pairing.request(plugin, name, kind, platform, source)
        except RateLimited:
            return web.json_response({"error": "too many requests"}, status=429)
        except PendingListFull:
            return web.json_response({"error": "busy"}, status=503)
        except PairingError:
            return web.json_response({"error": "refused"}, status=400)
        self._audit.write("", plugin, "pair.request", "pending", fields={"source": source, "name": name})
        return web.json_response({
            "request_id": req.request_id, "code": req.code, "expires_in": self._pairing.expiry_s,
            "fingerprint": self._certs.fingerprint(), "protocol": PROTOCOL_VERSION,
        }, status=202)

    async def _pair_poll(self, request: web.Request) -> web.Response:
        state, token = self._pairing.poll(request.match_info["request_id"])
        body: dict[str, object] = {"state": state}
        if token:
            body["token"] = token
        return web.json_response(body)

    # -- authenticated ------------------------------------------------------------------
    async def _whoami(self, request: web.Request) -> web.Response:
        peer: Peer = request[_PEER]
        return web.json_response({
            "peer_id": peer.peer_id, "name": peer.name, "plugin": peer.plugin,
            "permissions": sorted(peer.permissions),
        })


__all__ = ["API", "DEFAULT_PORT", "PROTOCOL_VERSION", "LinkServer", "default_bind_host"]
