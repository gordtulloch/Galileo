# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The desktop's end of the local channel (HEAD-070, HEAD-110, HEAD-120, HEAD-180).

``EngineClient`` is what a desktop uses when another process holds the engine lock. It lists the engine's Piers,
takes and releases the control lease as ``desktop``, runs Control Surface operations, reads state and mirrors the
engine's events. If the channel is lost it says so, keeps the last values and marks them stale, and offers
``retry``; it never starts an engine itself (HEAD-120).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp

from galileo.engine.channel import API, PROTOCOL, TOKEN_HEADER

logger = logging.getLogger(__name__)


class EngineUnreachable(Exception):
    """The engine did not answer; ``EngineClient.stale`` is set."""


class EngineMismatch(Exception):
    """The engine and the desktop are different versions; the message names both (HEAD-180)."""


def find_engine(directory: Path | str | None = None) -> dict[str, Any]:
    """What the running engine wrote about its channel (address, token), or ``{}`` if none is running."""
    from galileo.engine.lock import EngineLock
    return EngineLock(directory).holder().get("channel") or {}


class EngineClient:
    def __init__(self, address: str, token: str, version: str, on_event: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.address, self._token, self.version = address, token, version
        self.on_event = on_event
        self.stale = False
        self.last_state: dict[str, dict[str, Any]] = {}            # pier -> last values, kept when the engine goes away
        self._session: aiohttp.ClientSession | None = None
        self._stream_task: asyncio.Task | None = None

    # -- connection -------------------------------------------------------------------------------
    def _base(self) -> tuple[str, aiohttp.BaseConnector | None]:
        if self.address.startswith("unix:"):
            return "http://engine", aiohttp.UnixConnector(path=self.address[5:])
        return self.address, None

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            base, connector = self._base()
            self._session = aiohttp.ClientSession(base_url=base, connector=connector,
                                                  headers={TOKEN_HEADER: self._token},
                                                  timeout=aiohttp.ClientTimeout(total=30))
        return self._session

    async def _call(self, method: str, path: str, **kw: Any) -> Any:
        session = await self._http()
        try:
            async with session.request(method, f"{API}{path}", **kw) as r:
                body = await r.json(content_type=None)
                if r.status == 409:
                    raise EngineMismatch(str(body.get("error", "versions differ")))
                if r.status >= 400:
                    raise EngineUnreachable(str(body.get("error", r.status)) if isinstance(body, dict) else str(r.status))
        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            self._set_stale(True)
            raise EngineUnreachable(f"The Galileo engine did not answer ({exc.__class__.__name__}).") from exc
        self._set_stale(False)
        return body

    def _set_stale(self, stale: bool) -> None:
        if stale != self.stale:
            self.stale = stale
            if self.on_event:
                self.on_event({"type": "stale" if stale else "fresh"})

    async def attach(self) -> dict[str, Any]:
        """Compare versions and protocol with the engine; raises ``EngineMismatch`` naming both on a difference."""
        return await self._call("GET", "/hello", params={"version": self.version, "protocol": PROTOCOL})

    async def retry(self) -> dict[str, Any]:
        """Try the engine again after it was unreachable (never starts one)."""
        if self._session is not None:
            await self._session.close()
            self._session = None
        info = await self.attach()
        await self.start_events()
        return info

    # -- the engine's data ---------------------------------------------------------------------------
    async def piers(self) -> list[dict[str, Any]]:
        return await self._call("GET", "/piers")

    async def status(self) -> dict[str, Any]:
        return await self._call("GET", "/status")

    async def catalogue(self, pier: str) -> dict[str, Any]:
        return await self._call("GET", f"/catalogue/{pier}")

    async def state(self, pier: str) -> dict[str, Any]:
        snap = await self._call("GET", f"/state/{pier}")
        self.last_state[pier] = dict(snap["values"])
        return snap

    async def invoke(self, name: str, pier: str, args: dict[str, Any] | None = None, *,
                     idempotency_key: str = "", confirm_token: str = "") -> dict[str, Any]:
        return await self._call("POST", "/op", json={"name": name, "pier": pier, "args": args or {},
                                                      "idempotency_key": idempotency_key, "confirm_token": confirm_token})

    async def acquire_lease(self, pier: str) -> dict[str, Any]:
        return await self._call("POST", "/lease/acquire", json={"pier": pier})

    async def take_lease(self, pier: str, confirmed: bool = False) -> dict[str, Any]:
        return await self._call("POST", "/lease/take", json={"pier": pier, "confirmed": confirmed})

    async def release_lease(self, pier: str) -> dict[str, Any]:
        return await self._call("POST", "/lease/release", json={"pier": pier})

    # -- events --------------------------------------------------------------------------------------------
    async def start_events(self) -> None:
        if self._stream_task is None or self._stream_task.done():
            self._stream_task = asyncio.get_running_loop().create_task(self._read_events())

    async def _read_events(self) -> None:
        session = await self._http()
        try:
            async with session.get(f"{API}/events", timeout=aiohttp.ClientTimeout(total=None, sock_read=40)) as r:
                async for raw in r.content:
                    try:
                        message = json.loads(raw)
                    except ValueError:
                        continue
                    if message.get("type") == "state":
                        self.last_state.setdefault(str(message["pier"]), {})[message["key"]] = message["value"]
                    self._set_stale(False)
                    if self.on_event and message.get("type") != "ping":
                        self.on_event(message)
        except (aiohttp.ClientError, OSError, TimeoutError):
            pass
        except asyncio.CancelledError:
            raise
        self._set_stale(True)                                      # the stream ended: the engine is gone or went quiet

    async def close(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()
            await asyncio.gather(self._stream_task, return_exceptions=True)
            self._stream_task = None
        if self._session is not None:
            await self._session.close()
            self._session = None


__all__ = ["EngineClient", "EngineMismatch", "EngineUnreachable", "find_engine"]
