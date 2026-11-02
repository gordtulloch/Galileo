# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Running the Connect Link service inside the application.

The application has no long-lived asyncio loop of its own, and the listener needs one. ``LinkHost``
gives the service a private loop on a daemon thread, started only when something first needs it (the
Options page enabling Connect Link, or a plugin using it) and stopped again on shutdown, so a user who
never enables Connect Link has no thread, no loop and no socket. The synchronous methods are safe to call
from the UI thread.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import socket
import threading
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, TypeVar

from galileo.connect_link.pairing import PairingRequest
from galileo.connect_link.peers import Peer
from galileo.connect_link.service import ConnectLinkService, LinkSettings

logger = logging.getLogger(__name__)
T = TypeVar("T")
CALL_TIMEOUT_S = 20.0


class LinkHost:
    def __init__(self, service: ConnectLinkService) -> None:
        self.service = service
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- the loop thread ---------------------------------------------------------------------
    @property
    def loop_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or self._thread is None or not self._thread.is_alive():
                ready = threading.Event()
                loop = asyncio.new_event_loop()

                def run() -> None:
                    asyncio.set_event_loop(loop)
                    loop.call_soon(ready.set)
                    loop.run_forever()
                    loop.close()

                self._loop = loop
                self._thread = threading.Thread(target=run, name="connect-link", daemon=True)
                self._thread.start()
                ready.wait(5)
            return self._loop

    def call(self, coro: Awaitable[T], timeout: float = CALL_TIMEOUT_S) -> T:
        """Run a coroutine on the service's loop and wait for it (never from that loop itself)."""
        loop = self._ensure_loop()
        future: concurrent.futures.Future[T] = asyncio.run_coroutine_threadsafe(coro, loop)  # type: ignore[arg-type]
        return future.result(timeout)

    def shutdown(self) -> None:
        """Stop the service and the loop. Pairings stay."""
        if not self.loop_running:
            return
        try:
            self.call(self.service.shutdown())
        except Exception:
            logger.exception("Connect Link did not shut down cleanly")
        loop, thread = self._loop, self._thread
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(5)
        self._loop = self._thread = None

    # -- what the Options page needs ------------------------------------------------------------------
    def settings(self) -> LinkSettings:
        return self.service.settings()

    def set_enabled(self, enabled: bool) -> None:
        if enabled or self.loop_running:
            self.call(self.service.set_enabled(enabled))
        else:
            from galileo import settings_store
            from galileo.connect_link.service import NAMESPACE
            settings_store.set_setting(NAMESPACE, "enabled", False)

    def apply_settings(self, new: LinkSettings) -> None:
        if self.loop_running:
            self.call(self.service.apply_settings(new))
        else:
            new.save()
            self.service.pairing.expiry_s = new.pairing_expiry_s

    def acquire(self, plugin: str, permissions: tuple[str, ...] = ()) -> None:
        self.call(self.service.acquire(plugin, permissions))

    def release(self, plugin: str) -> None:
        if self.loop_running:
            self.call(self.service.release(plugin))

    def status(self) -> dict[str, Any]:
        s = self.service
        running = s.running and s.server is not None
        return {"enabled": s.settings().enabled, "running": running, "plugins": sorted(s.users),
                "host": s.server.host if running and s.server else "", "port": s.server.port if running and s.server else 0}

    def pending(self) -> list[PairingRequest]:
        return self.service.pairing.pending()

    def approve(self, request_id: str, permissions: list[str]) -> Peer:
        return self.service.pairing.approve(request_id, permissions, cert_fingerprint=self.service.fingerprint())

    def reject(self, request_id: str) -> None:
        self.service.pairing.reject(request_id)

    def peers(self) -> list[Peer]:
        return self.service.peers.list()

    def revoke(self, peer_id: str) -> None:
        """Revoke at once; an open stream of that peer is closed too (LINK-060)."""
        if self.service.server is not None:
            self.service.server.revoke_peer(peer_id)
        else:
            self.service.peers.revoke(peer_id)

    def delete(self, peer_id: str) -> bool:
        if self.service.server is not None:
            self.service.server.streams.close_peer(peer_id)
        return self.service.peers.delete(peer_id)

    # -- outreach events (LINK-190) -----------------------------------------------------------------------
    def open_event(self, owner: str, minutes: int | None = None) -> None:
        """Open an event; raises ``OutreachError`` saying why not."""
        self.call(self.service.open_event(owner, minutes))

    def close_event(self) -> None:
        if self.loop_running:
            self.call(self.service.close_event("owner"))

    def extend_event(self, minutes: int) -> None:
        self.service.outreach.extend(minutes)

    def eject_guests(self) -> int:
        return self.service.outreach.eject_all()

    def reissue_secret(self) -> None:
        self.service.outreach.reissue_secret()

    def event_status(self) -> dict[str, Any]:
        return self.service.outreach.status()

    def event_display(self) -> dict[str, Any]:
        return self.service.outreach.event_display()

    def fingerprint(self) -> str:
        try:
            return self.service.fingerprint()
        except Exception:
            logger.exception("Could not read the Connect Link certificate")
            return ""


_host: LinkHost | None = None
_host_lock = threading.Lock()


def get_host() -> LinkHost:
    """The application's Connect Link host, created on first use (no thread until something needs one)."""
    global _host
    with _host_lock:
        if _host is None:
            from galileo.node_identity import get_node_id
            from galileo.platform import get_data_dir
            from galileo.replication.busy import get_session_busy
            root: Path = get_data_dir() / "connect_link" / "transfer"
            _host = LinkHost(ConnectLinkService(
                node_id=get_node_id(), node_name=socket.gethostname() or "Galileo", transfer_root=root,
                session_busy=get_session_busy().is_busy))
        return _host


def shutdown_host() -> None:
    """Called at application exit."""
    with _host_lock:
        host = _host
    if host is not None:
        host.shutdown()


__all__ = ["LinkHost", "get_host", "shutdown_host"]
