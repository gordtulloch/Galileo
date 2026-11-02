# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Connect Link listener (LINK-010, LINK-020; ADR-LINK-006, ADR-LINK-007).

An ``aiohttp`` application on the asyncio loop. Every request passes one middleware before any
route is consulted: the only paths answered without a valid token are *request pairing* and *poll
pairing*; anything else without a token gets the same bare 401 whether or not the path exists, so an
unauthenticated caller learns nothing about which routes there are.
"""

from __future__ import annotations

import hashlib
import logging
import socket

from aiohttp import web

from galileo.connect_link.audit import AuditLog
from galileo.connect_link.certs import CertificateStore
from galileo.connect_link.discovery import Discovery
from galileo.connect_link.handshake import Handshake, Versions, schema_level
from galileo.connect_link.pairing import PairingError, PairingService, PendingListFull, RateLimited
from galileo.connect_link.peers import Peer, PeerStore
from galileo.connect_link.relay import SpokeEndpoints
from galileo.connect_link.routes import RouteRegistry
from galileo.connect_link.stream import StreamHub
from galileo.connect_link.transfer import MAX_CHUNK, TransferError, TransferService

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


def default_versions() -> Versions:
    """This node's versions for the handshake (LINK-080), read from the running application."""
    from galileo import __version__
    from galileo.library.database import get_migration_status
    from galileo.plugins import _CURRENT_API_VERSION
    return Versions(__version__, _CURRENT_API_VERSION, schema_level(get_migration_status()["current"]),
                    PROTOCOL_VERSION)


def _unauthorised() -> web.Response:
    return web.json_response({"error": "unauthorised"}, status=401)


class LinkServer:
    def __init__(
        self, peers: PeerStore, pairing: PairingService, certs: CertificateStore, audit: AuditLog,
        routes: RouteRegistry | None = None, handshake: Handshake | None = None,
        streams: StreamHub | None = None, transfers: TransferService | None = None, discovery: Discovery | None = None, spoke: SpokeEndpoints | None = None,
    ) -> None:
        self._peers, self._pairing, self._certs, self._audit = peers, pairing, certs, audit
        self.transfers = transfers
        self.discovery = discovery
        self.spoke = spoke
        self.streams = streams if streams is not None else StreamHub()
        self.routes = routes if routes is not None else RouteRegistry()
        self.handshake = handshake if handshake is not None else Handshake(default_versions)
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
        app.router.add_post(f"{API}/handshake", self._handshake)
        app.router.add_get(f"{API}/stream", self._stream)
        if self.transfers is not None:                                # LINK-070
            app.router.add_get(f"{API}/transfer/{{sha}}", self._transfer_status)
            app.router.add_put(f"{API}/transfer/{{sha}}", self._transfer_put)
            app.router.add_delete(f"{API}/transfer/{{sha}}", self._transfer_abort)
            app.router.add_get(f"{API}/transfer/{{sha}}/chunk", self._transfer_get)
        if self.spoke is not None:                                    # LINK-220: this node is a spoke
            app.router.add_post(f"{API}/relay/invoke", self._relay_invoke)
            app.router.add_get(f"{API}/relay/piers", self._relay_piers)
            app.router.add_get(f"{API}/relay/state/{{pier}}", self._relay_state)
            app.router.add_post(f"{API}/relay/preview/{{pier}}", self._relay_preview)
        app.router.add_route("*", "/{tail:.*}", self._dispatch)       # plugin routes (LINK-050)
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
        if self.discovery is not None:                                # LINK-040: only while listening
            try:
                await self.discovery.advertise(self.host, self.port, PROTOCOL_VERSION)
            except Exception:
                logger.warning("Connect Link could not advertise on the LAN; peers must use the address",
                               exc_info=True)

    def revoke_peer(self, peer_id: str) -> None:
        """Revoke a peer and close its event stream at once (LINK-060)."""
        self._peers.revoke(peer_id)
        self.streams.close_peer(peer_id)

    def disable_plugin(self, plugin: str) -> None:
        """A plugin was disabled or removed: drop its routes and close its streams (LINK-050, -060)."""
        self.routes.unregister_plugin(plugin)
        self.streams.close_plugin(plugin.strip().lower())

    async def stop(self) -> None:
        self.streams.close_all()
        if self.discovery is not None:
            try:
                await self.discovery.withdraw()
            except Exception:
                logger.warning("Connect Link could not withdraw its LAN advertisement", exc_info=True)
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
            outcome = "denied" if exc.status in (401, 403) else "error"
            self._audit.write(peer.peer_id, peer.plugin, f"{request.method} {path}", outcome, exc.reason or "")
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


    async def _stream(self, request: web.Request) -> web.StreamResponse:
        peer: Peer = request[_PEER]
        return await self.streams.serve(request, peer.peer_id, peer.plugin.strip().lower())

    async def _handshake(self, request: web.Request) -> web.Response:
        peer: Peer = request[_PEER]
        try:
            theirs = await request.json()
            if not isinstance(theirs, dict):
                raise TypeError("body")
        except Exception:
            return web.json_response({"error": "bad request"}, status=400)
        return web.json_response(self.handshake.evaluate(peer.plugin, theirs).as_dict())

    # -- spoke side of the Master relay (LINK-220) ---------------------------------------
    def _spoke(self, request: web.Request) -> SpokeEndpoints:
        self._need(request, "control", "view")
        if self.spoke is None:
            raise web.HTTPNotFound(reason="no such route")
        return self.spoke

    async def _relay_invoke(self, request: web.Request) -> web.Response:
        spoke = self._spoke(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TypeError("body")
        except Exception:
            return web.json_response({"error": "bad request"}, status=400)
        return web.json_response(await spoke.invoke(request[_PEER], body))

    async def _relay_piers(self, request: web.Request) -> web.Response:
        return web.json_response({"piers": self._spoke(request).list_piers()})

    async def _relay_state(self, request: web.Request) -> web.Response:
        return web.json_response(self._spoke(request).snapshot(request.match_info["pier"]))

    async def _relay_preview(self, request: web.Request) -> web.Response:
        spoke = self._spoke(request)
        try:
            params = await request.json()
        except Exception:
            params = {}
        data = await spoke.preview(request.match_info["pier"], params if isinstance(params, dict) else {})
        if data is None:
            return web.json_response({"error": "no preview"}, status=404)
        return web.Response(body=data, content_type="application/octet-stream")

    # -- transfer (LINK-070) --------------------------------------------------------------
    @staticmethod
    def _transfer_error(exc: TransferError) -> web.Response:
        headers = {"Retry-After": str(exc.detail["retry_after"])} if "retry_after" in exc.detail else None
        return web.json_response({"error": str(exc), **exc.detail}, status=exc.status, headers=headers)

    def _xfer(self) -> TransferService:
        if self.transfers is None:
            raise web.HTTPNotFound(reason="no such route")
        return self.transfers

    @staticmethod
    def _need(request: web.Request, *permissions: str) -> None:
        peer: Peer = request[_PEER]
        if not peer.permissions.intersection(permissions):
            raise web.HTTPForbidden(reason=f"needs {' or '.join(permissions)}")

    async def _transfer_status(self, request: web.Request) -> web.Response:
        self._need(request, "data.push", "data.pull")
        try:
            return web.json_response(self._xfer().status(request.match_info["sha"]))
        except TransferError as exc:
            return self._transfer_error(exc)

    async def _transfer_put(self, request: web.Request) -> web.Response:
        self._need(request, "data.push")
        try:
            size, offset = int(request.query["size"]), int(request.query["offset"])
        except (KeyError, ValueError):
            return web.json_response({"error": "size and offset are required"}, status=400)
        if (request.content_length or 0) > MAX_CHUNK:
            return web.json_response({"error": "chunk too large"}, status=413)
        data = await request.content.read(MAX_CHUNK + 1)
        try:
            result = await self._xfer().put_chunk(
                request.match_info["sha"], size, offset, data, request.headers.get("X-Chunk-SHA256", ""))
        except TransferError as exc:
            return self._transfer_error(exc)
        return web.json_response(result)

    async def _transfer_abort(self, request: web.Request) -> web.Response:
        self._need(request, "data.push")
        self._xfer().abort(request.match_info["sha"])
        return web.json_response({"ok": True})

    async def _transfer_get(self, request: web.Request) -> web.Response:
        self._need(request, "data.pull")
        try:
            offset, length = int(request.query["offset"]), int(request.query["length"])
        except (KeyError, ValueError):
            return web.json_response({"error": "offset and length are required"}, status=400)
        try:
            data, size = await self._xfer().get_chunk(request.match_info["sha"], offset, length)
        except TransferError as exc:
            return self._transfer_error(exc)
        return web.Response(body=data, content_type="application/octet-stream", headers={
            "X-Chunk-SHA256": hashlib.sha256(data).hexdigest(), "X-Object-Size": str(size)})

    async def _dispatch(self, request: web.Request) -> web.StreamResponse:
        """Plugin routes. The caller is already authenticated; an unknown route is 404 and a missing
        permission or another plugin's route 403."""
        peer: Peer = request[_PEER]
        route = self.routes.find(request.method, request.path)
        if route is None:
            raise web.HTTPNotFound(reason="no such route")
        if route.plugin != peer.plugin or route.permission not in peer.permissions:
            raise web.HTTPForbidden(reason=f"needs {route.permission}")
        try:
            result = await route.handler(peer, request)
        except web.HTTPException:
            raise
        except Exception:
            logger.exception("Connect Link route %s %s failed", request.method, request.path)
            raise web.HTTPInternalServerError(reason="handler failed") from None
        if isinstance(result, web.StreamResponse):
            return result
        return web.json_response(result)


__all__ = ["API", "DEFAULT_PORT", "PROTOCOL_VERSION", "LinkServer", "default_bind_host", "default_versions"]
