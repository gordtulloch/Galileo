# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Master relay (LINK-220).

A Master presents the Piers of every paired spoke, with its own, as one list and relays operations,
state, events and previews for a spoke's Pier over Connect Link, forwarding the originating client's
identity so the spoke audits it. Nothing here is specific to a front end: a plugin consumes
:class:`MasterRelay` through the :class:`RelayPort` shape.

* A spoke is reachable only under a grant made *on the spoke* (a peer holding ``control`` or ``view``,
  never ``config.*``); the Master only learns what the spoke's own answer says.
* The lease of a spoke's Pier lives on the spoke (LEASE-070): the request is forwarded with the client's
  identity and the spoke's gateway applies its own lease check. The Master keeps no copy of truth.
* An unreachable spoke is reported with the time last heard; operations to it are refused with that
  reason; the next successful contact re-attaches it with no re-pairing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from galileo.connect_link.gateway import Gateway, GatewayRequest
from galileo.control_surface import ObservableState, Outcome

logger = logging.getLogger(__name__)

SEP = "~"                      # a qualified Pier reference is "<node_id>~<pier>"; a bare one is local
LOCAL = ""


def qualify(node_id: str, pier: str) -> str:
    return f"{node_id}{SEP}{pier}" if node_id else pier


def split_ref(ref: str) -> tuple[str, str]:
    node, sep, pier = ref.partition(SEP)
    return (node, pier) if sep else (LOCAL, ref)


@dataclass(frozen=True)
class PierEntry:
    ref: str                       # what a client passes back as ``pier``
    node_id: str
    node_name: str
    pier: str
    local: bool
    reachable: bool = True
    view_only: bool = False
    last_heard: float | None = None


class RelayPort(Protocol):
    """What a front-end plugin may rely on."""

    async def piers(self) -> list[PierEntry]: ...
    async def invoke(self, req: GatewayRequest) -> Outcome: ...
    async def state(self, ref: str) -> dict[str, Any]: ...
    async def preview(self, ref: str, params: dict[str, Any]) -> bytes | None: ...


class SpokeLink(Protocol):
    """The Master's connection to one paired spoke."""

    async def whoami(self) -> dict[str, Any]: ...
    async def piers(self) -> list[str]: ...
    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def state(self, pier: str) -> dict[str, Any]: ...
    async def preview(self, pier: str, params: dict[str, Any]) -> bytes | None: ...
    async def stream(self, sink: Callable[[dict[str, Any]], None]) -> None: ...


_LINK_ERRORS = (OSError, TimeoutError, asyncio.TimeoutError, ConnectionError)


def _stamp(t: float | None) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%H:%M:%S UTC") if t else "never"


@dataclass
class _Spoke:
    node_id: str
    name: str
    link: SpokeLink
    grant: str = ""                                # "control", "view" or "" (no grant)
    piers: tuple[str, ...] = ()
    reachable: bool = False
    last_heard: float | None = None


class MasterRelay:
    def __init__(self, local: Gateway, local_piers: Callable[[], list[str]], *,
                 node_name: str = "This node", clock: Callable[[], float] = time.time,
                 local_state: ObservableState | None = None,
                 local_preview: Callable[[str, dict[str, Any]], Awaitable[bytes | None]] | None = None) -> None:
        self._local, self._local_piers, self._node_name, self._clock = local, local_piers, node_name, clock
        self._state = local_state
        self._local_preview = local_preview
        self._spokes: dict[str, _Spoke] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # -- spokes ------------------------------------------------------------------------
    async def add_spoke(self, node_id: str, name: str, link: SpokeLink) -> _Spoke:
        spoke = self._spokes[node_id] = _Spoke(node_id, name, link)
        await self.refresh(node_id)
        return spoke

    def remove_spoke(self, node_id: str) -> None:
        self._spokes.pop(node_id, None)
        task = self._tasks.pop(node_id, None)
        if task:
            task.cancel()

    async def refresh(self, node_id: str) -> bool:
        """Ask the spoke what it granted us and which Piers it has; ``True`` when it answered. A spoke
        that has withdrawn the grant answers 401/403, which arrives here as an error."""
        spoke = self._spokes[node_id]
        try:
            who = await spoke.link.whoami()
            piers = await spoke.link.piers()
        except _LINK_ERRORS:
            spoke.reachable = False
            return False
        perms = set(who.get("permissions", ()))
        spoke.grant = "control" if "control" in perms else "view" if "view" in perms else ""
        spoke.piers = tuple(piers)
        self._heard(spoke)
        return True

    def _heard(self, spoke: _Spoke) -> None:
        spoke.reachable, spoke.last_heard = True, self._clock()

    def _lost(self, spoke: _Spoke) -> Outcome:
        spoke.reachable = False
        return Outcome("unreachable", f"{spoke.name} is unreachable; last heard {_stamp(spoke.last_heard)}")

    # -- the one list ------------------------------------------------------------------
    async def piers(self) -> list[PierEntry]:
        out = [PierEntry(p, LOCAL, self._node_name, p, True, last_heard=self._clock()) for p in self._local_piers()]
        for s in self._spokes.values():
            if s.grant:
                out += [PierEntry(qualify(s.node_id, p), s.node_id, s.name, p, False, s.reachable,
                                  s.grant == "view", s.last_heard) for p in s.piers]
        return out

    def spoke_status(self) -> list[dict[str, Any]]:
        """Every paired spoke, including one that has granted nothing — shown as such, not hidden."""
        return [{"node_id": s.node_id, "name": s.name, "grant": s.grant or "none", "reachable": s.reachable,
                 "last_heard": s.last_heard} for s in self._spokes.values()]

    # -- operations --------------------------------------------------------------------
    async def invoke(self, req: GatewayRequest) -> Outcome:
        """Run a request on this node or forward it to the spoke that owns the Pier. A forwarded
        request is audited here too, as well as on the spoke. The caller has authorised its own client
        (its role); the spoke enforces what this Master was granted and the lease."""
        node, pier = split_ref(req.pier)
        if node == LOCAL:
            return await self._local.handle(req)
        outcome = await self._forward(req, node, pier)
        self._local.record(req, outcome, "relay")
        return outcome

    async def _forward(self, req: GatewayRequest, node: str, pier: str) -> Outcome:
        if not req.client_id or not req.name:
            return Outcome("refused", "the request does not say who is asking")
        spoke = self._spokes.get(node)
        if spoke is None or (spoke.reachable and pier not in spoke.piers):
            return Outcome("unavailable", "no such Pier")
        if not spoke.grant:
            return Outcome("refused", f"{spoke.name} has not granted access")
        payload = {"client_id": req.client_id, "name": req.name, "pier": pier, "args": req.args,
                   "idempotency_key": req.idempotency_key, "confirm_token": req.confirm_token,
                   "source": req.source}
        try:
            reply = await spoke.link.invoke(payload)
        except _LINK_ERRORS:
            return self._lost(spoke)
        self._heard(spoke)
        return Outcome(**{k: v for k, v in reply.items() if k in Outcome.__dataclass_fields__})

    async def state(self, ref: str) -> dict[str, Any]:
        node, pier = split_ref(ref)
        if node == LOCAL:
            seq, values = self._state.snapshot(pier) if self._state else (0, {})
            return {"seq": seq, "values": values, "reachable": True}
        spoke = self._spokes.get(node)
        if spoke is None or not spoke.grant:
            return {"seq": 0, "values": {}, "reachable": False, "reason": "not available"}
        try:
            snap = await spoke.link.state(pier)
        except _LINK_ERRORS:
            self._lost(spoke)
            return {"seq": 0, "values": {}, "reachable": False,
                    "reason": f"{spoke.name} is unreachable; last heard {_stamp(spoke.last_heard)}"}
        self._heard(spoke)
        return {**snap, "reachable": True}

    async def preview(self, ref: str, params: dict[str, Any]) -> bytes | None:
        """Previews are rendered on the owning node and relayed (LINK-220)."""
        node, pier = split_ref(ref)
        if node == LOCAL:
            return await self._local_preview(pier, params) if self._local_preview else None
        spoke = self._spokes.get(node)
        if spoke is None or not spoke.grant:
            return None
        try:
            data = await spoke.link.preview(pier, params)
        except _LINK_ERRORS:
            self._lost(spoke)
            return None
        self._heard(spoke)
        return data

    # -- events ------------------------------------------------------------------------
    def attach_events(self, node_id: str, sink: Callable[[str, dict[str, Any]], None],
                      retry_s: float = 5.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        """Relay a spoke's event stream to ``sink(node_id, message)``; reconnects by itself, without
        re-pairing, whenever the spoke comes back."""
        spoke = self._spokes[node_id]

        def deliver(message: dict[str, Any]) -> None:
            self._heard(spoke)
            sink(node_id, message)

        async def run() -> None:
            while True:
                try:
                    await spoke.link.stream(deliver)
                except _LINK_ERRORS:
                    self._lost(spoke)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("relayed event sink failed")
                await sleep(retry_s)

        self._tasks[node_id] = asyncio.create_task(run())

    async def close(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()


class HttpSpokeLink:
    """A :class:`SpokeLink` over Connect Link: an ``aiohttp`` session pinned to the spoke's certificate,
    carrying the Master's token for that spoke. ``base`` is ``https://host:port/connect/v1``."""

    def __init__(self, session: Any, base: str, headers: dict[str, str]) -> None:
        self._s, self._base, self._h = session, base.rstrip("/"), headers

    async def _json(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        async with self._s.request(method, self._base + path, headers=self._h, **kw) as r:
            if r.status in (401, 403):
                raise ConnectionError("the spoke has withdrawn access")
            r.raise_for_status()
            return dict(await r.json())

    async def whoami(self) -> dict[str, Any]:
        return await self._json("GET", "/whoami")

    async def piers(self) -> list[str]:
        return list((await self._json("GET", "/relay/piers")).get("piers", []))

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._json("POST", "/relay/invoke", json=payload)

    async def state(self, pier: str) -> dict[str, Any]:
        return await self._json("GET", f"/relay/state/{pier}")

    async def preview(self, pier: str, params: dict[str, Any]) -> bytes | None:
        async with self._s.post(f"{self._base}/relay/preview/{pier}", json=params, headers=self._h) as r:
            if r.status == 404:
                return None
            r.raise_for_status()
            return bytes(await r.read())

    async def stream(self, sink: Callable[[dict[str, Any]], None]) -> None:
        async with self._s.ws_connect(self._base + "/stream", headers=self._h) as ws:
            async for msg in ws:
                if msg.type == 1:                                  # aiohttp.WSMsgType.TEXT
                    sink(msg.json())


class SpokeEndpoints:
    """The spoke's side: what a Master's service peer may call. The request is run through *this* node's
    gateway with the forwarded client as actor and the Master's peer as carrier (LINK-220, LINK-090)."""

    def __init__(self, gateway: Gateway, piers: Callable[[], list[str]], state: ObservableState | None = None,
                 preview: Callable[[str, dict[str, Any]], Awaitable[bytes | None]] | None = None) -> None:
        self._gateway, self._piers, self._state, self._preview = gateway, piers, state, preview

    def list_piers(self) -> list[str]:
        return self._piers()

    async def invoke(self, peer: Any, body: dict[str, Any]) -> dict[str, Any]:
        try:
            client, name, pier = str(body["client_id"]), str(body["name"]), str(body["pier"])
            args = body.get("args") or {}
            if not isinstance(args, dict):
                raise TypeError("args")
        except (KeyError, TypeError):
            return Outcome("invalid", "malformed relay request").as_dict()
        req = GatewayRequest(
            client_id=client, name=name, pier=pier, args=args, plugin=peer.plugin, kind="peer",
            permissions=frozenset(peer.permissions), carrier=peer.peer_id,
            idempotency_key=str(body.get("idempotency_key", "")), confirm_token=str(body.get("confirm_token", "")),
            source=str(body.get("source", "")))
        return (await self._gateway.handle(req)).as_dict()

    def snapshot(self, pier: str) -> dict[str, Any]:
        seq, values = self._state.snapshot(pier) if self._state else (0, {})
        return {"seq": seq, "values": values}

    async def preview(self, pier: str, params: dict[str, Any]) -> bytes | None:
        return await self._preview(pier, params) if self._preview else None


__all__ = ["LOCAL", "SEP", "HttpSpokeLink", "MasterRelay", "PierEntry", "RelayPort", "SpokeEndpoints", "SpokeLink",
           "qualify", "split_ref"]
