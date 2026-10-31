# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The server-push event stream (LINK-060).

One WebSocket per peer carries plugin-defined messages, each tagged with a per-stream sequence id.
Every message is also kept in a bounded replay ring, so a peer that drops and reconnects with the last
id it saw receives what it missed — or is told to resynchronise when that is no longer possible
(the ring has moved past it, or the stream was recreated, which a changing ``epoch`` reveals). A
peer too slow to keep up is disconnected rather than allowed to hold memory; it reconnects and
replays. ``publish`` and ``close_*`` must be called on the event loop that runs the listener.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web

logger = logging.getLogger(__name__)

DEFAULT_RING = 256
SEND_TIMEOUT_S = 10.0
_CLOSE = object()


@dataclass
class _Connection:
    queue: asyncio.Queue[Any]
    ws: web.WebSocketResponse


@dataclass
class _Stream:
    plugin: str
    epoch: str = field(default_factory=lambda: secrets.token_hex(8))
    seq: int = 0
    ring: deque[tuple[int, Any]] = field(default_factory=deque)
    conn: _Connection | None = None


class StreamHub:
    def __init__(self, ring_size: int = DEFAULT_RING, send_timeout: float = SEND_TIMEOUT_S) -> None:
        self._ring_size = ring_size
        self._send_timeout = send_timeout
        self._streams: dict[str, _Stream] = {}

    # -- publishing ------------------------------------------------------------------------
    def publish(self, peer_id: str, data: Any) -> int | None:
        """Queue ``data`` for one peer; returns its sequence id, or ``None`` if the peer has no stream
        (it has never connected, so there is nothing to miss)."""
        stream = self._streams.get(peer_id)
        return None if stream is None else self._append(peer_id, stream, data)

    def broadcast(self, plugin: str, data: Any) -> int:
        """Queue ``data`` for every stream of a plugin. Returns how many streams received it."""
        n = 0
        for peer_id, stream in list(self._streams.items()):
            if stream.plugin == plugin:
                self._append(peer_id, stream, data)
                n += 1
        return n

    def _append(self, peer_id: str, stream: _Stream, data: Any) -> int:
        stream.seq += 1
        stream.ring.append((stream.seq, data))
        while len(stream.ring) > self._ring_size:
            stream.ring.popleft()
        conn = stream.conn
        if conn is not None:
            self._enqueue(peer_id, stream, conn, {"seq": stream.seq, "data": data})
        return stream.seq

    def _enqueue(self, peer_id: str, stream: _Stream, conn: _Connection, msg: Any) -> None:
        try:
            conn.queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("Connect Link stream for %s cannot keep up; disconnecting it", peer_id)
            self._detach(stream, conn)

    # -- closing ---------------------------------------------------------------------------
    def close_peer(self, peer_id: str, *, forget: bool = True) -> None:
        """Close a peer's stream at once (revoked, deleted). ``forget`` also drops its replay ring."""
        stream = self._streams.get(peer_id)
        if stream is None:
            return
        if stream.conn is not None:
            self._detach(stream, stream.conn)
        if forget:
            del self._streams[peer_id]

    def close_plugin(self, plugin: str) -> int:
        gone = [p for p, s in self._streams.items() if s.plugin == plugin]
        for peer_id in gone:
            self.close_peer(peer_id)
        return len(gone)

    def close_all(self) -> None:
        for peer_id in list(self._streams):
            self.close_peer(peer_id)

    def _detach(self, stream: _Stream, conn: _Connection) -> None:
        if stream.conn is conn:
            stream.conn = None
        # Drop anything unsent and wake the writer so it closes the socket.
        while not conn.queue.empty():
            conn.queue.get_nowait()
        conn.queue.put_nowait(_CLOSE)

    def connected(self, peer_id: str) -> bool:
        stream = self._streams.get(peer_id)
        return stream is not None and stream.conn is not None

    # -- the WebSocket endpoint --------------------------------------------------------------
    async def serve(self, request: web.Request, peer_id: str, plugin: str) -> web.StreamResponse:
        ws = web.WebSocketResponse(heartbeat=20.0)
        await ws.prepare(request)
        stream = self._streams.setdefault(peer_id, _Stream(plugin))
        if stream.conn is not None:                               # a newer connection replaces the old
            self._detach(stream, stream.conn)
        conn = _Connection(asyncio.Queue(maxsize=self._ring_size + 8), ws)

        # Decide replay and attach with no await in between, so no message can fall in the gap.
        epoch, last = request.query.get("epoch", ""), request.query.get("last", "")
        if not last:
            conn.queue.put_nowait({"type": "hello", "epoch": stream.epoch, "seq": stream.seq})
        elif not _replayable(stream, epoch, last):
            conn.queue.put_nowait({"type": "resync", "epoch": stream.epoch, "seq": stream.seq})
        else:
            conn.queue.put_nowait({"type": "hello", "epoch": stream.epoch, "seq": stream.seq})
            for seq, data in stream.ring:
                if seq > int(last):
                    conn.queue.put_nowait({"seq": seq, "data": data})
        stream.conn = conn

        reader = asyncio.ensure_future(self._read(ws))
        writer = asyncio.ensure_future(self._write(conn))
        try:
            await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if stream.conn is conn:
                stream.conn = None
            for task in (reader, writer):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            if not ws.closed:
                await ws.close()
        return ws

    @staticmethod
    async def _read(ws: web.WebSocketResponse) -> None:
        async for msg in ws:                                      # the peer sends nothing we act on
            if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break

    async def _write(self, conn: _Connection) -> None:
        while True:
            msg = await conn.queue.get()
            if msg is _CLOSE:
                return
            try:
                await asyncio.wait_for(conn.ws.send_json(msg), self._send_timeout)
            except (TimeoutError, ConnectionError, RuntimeError):
                return


def _replayable(stream: _Stream, epoch: str, last: str) -> bool:
    """Can everything after ``last`` still be replayed from this stream?"""
    try:
        n = int(last)
    except ValueError:
        return False
    if epoch != stream.epoch or n < 0 or n > stream.seq:
        return False
    if n == stream.seq:
        return True
    return bool(stream.ring) and stream.ring[0][0] <= n + 1


__all__ = ["DEFAULT_RING", "StreamHub"]
