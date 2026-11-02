# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Listener lifecycle (LINK-010, LINK-040, LINK-270).

The listener runs only while at least one route is registered: the first registration starts it
(and the mDNS advertisement), removing the last stops both. ``disable()`` stops everything at the
owner's request regardless of routes, leaving no listener, advertisement or open stream behind.
"""

from __future__ import annotations

import asyncio
import logging

from galileo.connect_link.discovery import Discovery
from galileo.connect_link.handshake import PROTOCOL_VERSION
from galileo.connect_link.server import DEFAULT_PORT, LinkServer

logger = logging.getLogger(__name__)


class LinkService:
    def __init__(
        self, server: LinkServer, discovery: Discovery | None = None, *, node_id: str = "",
        display_name: str = "Galileo", role: str = "", host: str | None = None, port: int = DEFAULT_PORT,
        advertise: bool = True,
    ) -> None:
        self.server, self.discovery = server, discovery or Discovery()
        self._node_id, self._name, self._role = node_id, display_name, role
        self._host, self._port, self._advertise = host, port, advertise
        self._disabled = False
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        server.routes.on_change(self._routes_changed)

    # -- driven by the route registry ---------------------------------------------------
    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """The loop listener changes run on; registrations from other threads are marshalled to it."""
        self._loop = loop

    def _routes_changed(self, count: int) -> None:
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return                                   # no loop yet: call reconcile() once there is one
        loop.call_soon_threadsafe(lambda: self._spawn(self.reconcile()))

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def reconcile(self) -> None:
        """Bring the listener in line with the routes and the owner's enable switch."""
        async with self._lock:
            want = bool(len(self.server.routes)) and not self._disabled
            if want and not self.server.running:
                try:
                    await self.server.start(self._host, self._port)
                except Exception:
                    logger.exception("Connect Link could not start")
                    return
                if self._advertise:
                    self.discovery.start(self._name, self._node_id, self.server.host, self.server.port,
                                         PROTOCOL_VERSION, self._role)
            elif not want and self.server.running:
                self.discovery.stop()
                await self.server.stop()

    async def disable(self) -> None:
        """The owner switched Connect Link off (LINK-270)."""
        self._disabled = True
        await self.reconcile()

    async def enable(self) -> None:
        self._disabled = False
        await self.reconcile()

    async def shutdown(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        async with self._lock:
            self.discovery.stop()
            await self.server.stop()
