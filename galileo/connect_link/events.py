# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Server-push event stream (LINK-060).

A plugin publishes messages to its own stream; every connected peer of that plugin that holds the
message's permission receives them, each tagged with a per-stream sequence id. A bounded replay ring
lets a peer that reconnects with its last id catch up; if it fell off the ring (or the node
restarted) it is told to resynchronise instead. Everything here runs on the asyncio loop.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any

from galileo.connect_link.peers import Peer

DEFAULT_REPLAY = 256
DEFAULT_QUEUE = 256
RESYNC = "resync"


@dataclass(frozen=True)
class _Entry:
    id: int
    type: str
    data: Any
    permission: str

    def message(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "data": self.data}


class Subscription:
    """One connected peer's view of a plugin stream. ``next()`` returns messages, then ``None`` once
    the stream is closed (peer revoked, plugin disabled, or the peer fell too far behind)."""

    def __init__(self, peer: Peer, maxsize: int) -> None:
        self.peer = peer
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize)
        self.closed = False
        self.close_reason = ""

    def _offer(self, message: dict[str, Any]) -> bool:
        if self.closed:
            return False
        try:
            self._queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            self._close("too slow")                      # bounded memory: drop the laggard, it resyncs
            return False

    def _close(self, reason: str) -> None:
        if self.closed:
            return
        self.closed, self.close_reason = True, reason
        while True:                                       # make room for the sentinel
            try:
                self._queue.put_nowait(None)
                break
            except asyncio.QueueFull:
                self._queue.get_nowait()

    async def next(self) -> dict[str, Any] | None:
        return await self._queue.get()


class EventHub:
    def __init__(self, replay: int = DEFAULT_REPLAY, queue_size: int = DEFAULT_QUEUE) -> None:
        self._replay, self._queue_size = replay, queue_size
        self._rings: dict[str, deque[_Entry]] = {}
        self._seq: dict[str, int] = {}
        self._subs: dict[str, set[Subscription]] = {}

    def publish(self, plugin: str, type: str, data: Any = None, permission: str = "view") -> int:
        """Append a message to *plugin*'s stream and push it; returns its sequence id."""
        seq = self._seq.get(plugin, 0) + 1
        self._seq[plugin] = seq
        entry = _Entry(seq, type, data, permission)
        self._rings.setdefault(plugin, deque(maxlen=self._replay)).append(entry)
        for sub in list(self._subs.get(plugin, ())):
            if permission in sub.peer.permissions:
                sub._offer(entry.message())
        return seq

    def subscribe(self, peer: Peer, last_id: int | None = None) -> Subscription:
        """Attach *peer* to its plugin's stream, replaying what it missed after *last_id*."""
        sub = Subscription(peer, self._queue_size)
        plugin = peer.plugin
        current = self._seq.get(plugin, 0)
        if last_id is not None:
            ring = self._rings.get(plugin, deque())
            oldest = ring[0].id if ring else current + 1
            if last_id > current or last_id + 1 < oldest:
                sub._offer({"id": current, "type": RESYNC, "data": None})
            else:
                for e in ring:
                    if e.id > last_id and e.permission in peer.permissions:
                        sub._offer(e.message())
        self._subs.setdefault(plugin, set()).add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.get(sub.peer.plugin, set()).discard(sub)
        sub._close("unsubscribed")

    def close_peer(self, peer_id: str, reason: str = "peer ended") -> int:
        n = 0
        for subs in self._subs.values():
            for sub in [s for s in subs if s.peer.peer_id == peer_id]:
                subs.discard(sub)
                sub._close(reason)
                n += 1
        return n

    def close_plugin(self, plugin: str, reason: str = "plugin disabled") -> int:
        """Close every stream of *plugin* and forget its history (plugin disabled or removed)."""
        subs = self._subs.pop(plugin, set())
        for sub in subs:
            sub._close(reason)
        self._rings.pop(plugin, None)
        self._seq.pop(plugin, None)
        return len(subs)

    def close_all(self) -> None:
        for plugin in list(self._subs):
            self.close_plugin(plugin, "listener stopped")

    def count(self, plugin: str | None = None) -> int:
        if plugin is not None:
            return len(self._subs.get(plugin, ()))
        return sum(len(s) for s in self._subs.values())
