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

from galileo.connect_link import handshake
from galileo.connect_link.audit import AuditLog
from galileo.connect_link.certs import CertificateStore
from galileo.connect_link.events import EventHub
from galileo.connect_link.pairing import PairingError, PairingService, PendingListFull, RateLimited
from galileo.connect_link.peers import DelegationError, Peer, PeerStore
from galileo.connect_link.routes import RouteRegistry
from galileo.connect_link.transfer import TransferError, TransferStore

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = handshake.PROTOCOL_VERSION
DEFAULT_PORT = 8765
API = "/connect/v1"
ACTING_CLIENT_HEADER = "X-Galileo-Acting-Client"
_PEER = web.RequestKey("link_peer", Peer)
_ACTOR = web.RequestKey("link_audit_actor", tuple)


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
        routes: RouteRegistry | None = None, events: EventHub | None = None,
        transfers: TransferStore | None = None,
    ) -> None:
        self._peers, self._pairing, self._certs, self._audit = peers, pairing, certs, audit
        self.routes = routes if routes is not None else RouteRegistry()
        self.handshake_extensions = handshake.HandshakeExtensions()
        self.events = events if events is not None else EventHub()
        self.transfers = transfers if transfers is not None else TransferStore()
        peers.on_peer_ended(self.events.close_peer)              # revoked/deleted: streams close at once
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
        app.router.add_get(f"{API}/handshake", self._handshake)
        app.router.add_get(f"{API}/events", self._events)
        app.router.add_post(f"{API}/transfer", self._transfer_begin)
        app.router.add_put(f"{API}/transfer/{{tid}}/chunk/{{n}}", self._transfer_chunk)
        app.router.add_post(f"{API}/transfer/{{tid}}/complete", self._transfer_complete)
        app.router.add_get(f"{API}/objects/{{sha}}", self._object_info)
        app.router.add_get(f"{API}/objects/{{sha}}/chunk/{{n}}", self._object_chunk)
        app.router.add_route("*", "/{tail:.*}", self._plugin_route)       # reached only past the gate
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
        self.events.close_all()
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
        actor, carrier = request.get(_ACTOR, (peer.peer_id, ""))
        self._audit.write(actor, peer.plugin, f"{request.method} {path}", "ok", carrier=carrier)
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

    async def _handshake(self, request: web.Request) -> web.Response:
        """Our versions plus plugin extensions; if the caller sends its own (``?protocol=&schema=``)
        the verdict is included so a person can be told what to do (LINK-080)."""
        ours = handshake.local_info()
        body: dict[str, object] = {**ours, "plugins": self.handshake_extensions.payload()}
        q = request.query
        if "protocol" in q or "schema" in q:
            v = handshake.check(ours, dict(q))
            body["compatibility"] = {"ok": v.ok, "restricted": v.restricted, "message": v.message}
        return web.json_response(body)

    async def _plugin_route(self, request: web.Request) -> web.StreamResponse:
        """Plugin routes (LINK-050, LINK-090). The gate has already authenticated the caller."""
        carrier: Peer = request[_PEER]
        route = self.routes.find(request.method, request.path)
        if route is None:
            return web.json_response({"error": "not found"}, status=404)
        label = f"{request.method} {request.path}"
        principal = carrier
        acting = request.headers.get(ACTING_CLIENT_HEADER, "")
        if carrier.plugin != route.plugin:
            return web.json_response({"error": "forbidden"}, status=403)       # never another plugin's route
        if acting:
            try:
                principal = self._peers.resolve_client(carrier, acting)
            except DelegationError as exc:
                self._audit.write(acting, route.plugin, label, "denied", str(exc), carrier=carrier.peer_id)
                return web.json_response({"error": "forbidden"}, status=403)
        if route.permission not in principal.permissions:
            self._audit.write(principal.peer_id, route.plugin, label, "denied", f"needs {route.permission}",
                              carrier=carrier.peer_id if principal is not carrier else "")
            return web.json_response({"error": "forbidden"}, status=403)
        if principal is not carrier:
            request[_ACTOR] = (principal.peer_id, carrier.peer_id)
        return await route.handler(request, principal)

    def remove_plugin(self, plugin: str) -> None:
        """A plugin was disabled or removed: its routes, streams and handshake addition go (LINK-050/060)."""
        self.routes.unregister_plugin(plugin)
        self.events.close_plugin(plugin)
        self.handshake_extensions.unregister(plugin)

    # -- event stream (LINK-060) ---------------------------------------------------------
    async def _events(self, request: web.Request) -> web.StreamResponse:
        peer: Peer = request[_PEER]
        try:
            last = int(request.query["last_id"]) if "last_id" in request.query else None
        except ValueError:
            return web.json_response({"error": "bad request"}, status=400)
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        sub = self.events.subscribe(peer, last)
        try:
            while (msg := await sub.next()) is not None:
                await ws.send_json(msg)
        finally:
            self.events.unsubscribe(sub)
            if not ws.closed:
                await ws.close(code=4001 if sub.close_reason in ("peer ended", "plugin disabled") else 1000,
                               message=sub.close_reason.encode()[:100])
        return ws

    # -- transfer (LINK-070) -------------------------------------------------------------
    @staticmethod
    def _need(request: web.Request, permission: str) -> Peer | None:
        peer: Peer = request[_PEER]
        return peer if permission in peer.permissions else None

    @staticmethod
    def _transfer_error(exc: TransferError) -> web.Response:
        body: dict[str, object] = {"error": str(exc)}
        if exc.next_chunk is not None:
            body["next_chunk"] = exc.next_chunk
        return web.json_response(body, status=exc.status)

    async def _transfer_begin(self, request: web.Request) -> web.Response:
        peer = self._need(request, "data.push")
        if peer is None:
            return web.json_response({"error": "forbidden"}, status=403)
        try:
            b = await request.json()
            st = self.transfers.begin(peer.peer_id, str(b.get("name", ""))[:200], int(b["size"]),
                                      str(b["sha256"]).lower(), int(b.get("chunk_size", 1 << 20)))
        except TransferError as exc:
            return self._transfer_error(exc)
        except Exception:
            return web.json_response({"error": "bad request"}, status=400)
        return web.json_response({"transfer_id": st.transfer_id, "state": st.state,
                                  "next_chunk": st.next_chunk, "chunk_size": st.chunk_size})

    async def _transfer_chunk(self, request: web.Request) -> web.Response:
        peer = self._need(request, "data.push")
        if peer is None:
            return web.json_response({"error": "forbidden"}, status=403)
        try:
            data = await request.read()
            nxt = await self.transfers.put_chunk(peer.peer_id, request.match_info["tid"],
                                                 int(request.match_info["n"]), data,
                                                 request.headers.get("X-Chunk-SHA256", ""))
        except TransferError as exc:
            return self._transfer_error(exc)
        except ValueError:
            return web.json_response({"error": "bad request"}, status=400)
        return web.json_response({"next_chunk": nxt})

    async def _transfer_complete(self, request: web.Request) -> web.Response:
        peer = self._need(request, "data.push")
        if peer is None:
            return web.json_response({"error": "forbidden"}, status=403)
        try:
            st = await self.transfers.complete(peer.peer_id, request.match_info["tid"])
        except TransferError as exc:
            return self._transfer_error(exc)
        return web.json_response({"state": st.state, "sha256": st.sha256})

    async def _object_info(self, request: web.Request) -> web.Response:
        if self._need(request, "data.pull") is None:
            return web.json_response({"error": "forbidden"}, status=403)
        try:
            obj = self.transfers.info(request.match_info["sha"])
        except TransferError as exc:
            return self._transfer_error(exc)
        return web.json_response({"sha256": obj.sha256, "size": obj.size})

    async def _object_chunk(self, request: web.Request) -> web.Response:
        if self._need(request, "data.pull") is None:
            return web.json_response({"error": "forbidden"}, status=403)
        try:
            data, digest = await self.transfers.read_chunk(
                request.match_info["sha"], int(request.match_info["n"]),
                int(request.query.get("chunk_size", 1 << 20)))
        except TransferError as exc:
            return self._transfer_error(exc)
        except ValueError:
            return web.json_response({"error": "bad request"}, status=400)
        return web.Response(body=data, content_type="application/octet-stream",
                            headers={"X-Chunk-SHA256": digest})


__all__ = ["ACTING_CLIENT_HEADER", "API","DEFAULT_PORT", "PROTOCOL_VERSION", "LinkServer", "default_bind_host"]
