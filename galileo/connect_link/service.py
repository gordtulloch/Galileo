# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Connect Link service: settings, plugin-driven start and stop, and disable (LINK-260, LINK-270).

``ConnectLinkService`` composes the listener, pairing, peers, audit, transfer and discovery and is the
one thing the application starts. Its settings live in the shared database (namespace ``connect_link``);
its keys and the outreach passphrase live in the secret store. The listener runs only while it is enabled
*and* at least one plugin uses it, and stops with the last one; disabling closes the listener, ends every
stream, stops the advertisement and leaves no listener or worker, with the pairings kept so that
enabling it again needs no re-pairing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from galileo import settings_store
from galileo.connect_link.audit import AuditLog
from galileo.connect_link.certs import CertificateStore
from galileo.connect_link.discovery import Discovery
from galileo.connect_link.outreach import OutreachFacility
from galileo.connect_link.outreach_feed import OutreachFeed, pier_display_names
from galileo.connect_link.pairing import PairingService
from galileo.connect_link.peers import PeerStore
from galileo.connect_link.relay import SpokeEndpoints
from galileo.connect_link.secrets_store import KeyringSecretStore, SecretStore
from galileo.connect_link.server import DEFAULT_PORT, LinkServer
from galileo.connect_link.transfer import TransferService

logger = logging.getLogger(__name__)

NAMESPACE = "connect_link"
PRUNE_INTERVAL_S = 24 * 3600.0
MIN_PORT, MAX_PORT = 1024, 65535


class SettingsError(ValueError):
    """A Connect Link setting that is out of range."""


@dataclass(frozen=True)
class LinkSettings:
    enabled: bool = False
    port: int = DEFAULT_PORT
    pairing_expiry_s: int = 300
    audit_retention_days: int = 90
    advertise: bool = True
    bind_host: str = ""                       # empty = the node's LAN address, never the wildcard (LINK-010)

    @classmethod
    def load(cls) -> LinkSettings:
        raw = settings_store.get_namespace(NAMESPACE)
        d = cls()
        try:
            return cls(
                enabled=bool(raw.get("enabled", d.enabled)), port=int(raw.get("port", d.port)),
                pairing_expiry_s=int(raw.get("pairing_expiry_s", d.pairing_expiry_s)),
                audit_retention_days=int(raw.get("audit_retention_days", d.audit_retention_days)),
                advertise=bool(raw.get("advertise", d.advertise)), bind_host=str(raw.get("bind_host", d.bind_host)))
        except (TypeError, ValueError):
            logger.warning("Connect Link settings are unreadable; using the defaults")
            return d

    def validate(self) -> None:
        if not MIN_PORT <= self.port <= MAX_PORT:
            raise SettingsError(f"the port must be between {MIN_PORT} and {MAX_PORT}")
        if not 30 <= self.pairing_expiry_s <= 3600:
            raise SettingsError("pairing requests must last between 30 seconds and an hour")
        if not 1 <= self.audit_retention_days <= 3650:
            raise SettingsError("keep the audit log for between 1 and 3650 days")
        if self.bind_host in ("0.0.0.0", "::"):  # noqa: S104 - this is the check that refuses it
            raise SettingsError("listening on every interface is not allowed; leave it blank for the LAN address")

    def save(self) -> None:
        self.validate()
        settings_store.set_namespace(NAMESPACE, {
            "enabled": self.enabled, "port": self.port, "pairing_expiry_s": self.pairing_expiry_s,
            "audit_retention_days": self.audit_retention_days, "advertise": self.advertise,
            "bind_host": self.bind_host})


class ConnectLinkService:
    def __init__(
        self, *, node_id: str, node_name: str = "Galileo", secrets: SecretStore | None = None,
        clock: Callable[[], float] = time.time, transfer_root: Path | None = None,
        session_busy: Callable[[], bool] | None = None, role_hint: str = "", discovery: Discovery | None = None,
    ) -> None:
        self._clock, self._node_id, self._session_busy = clock, node_id, session_busy
        self.peers = PeerStore(clock)
        self.audit = AuditLog(clock)
        self.certs = CertificateStore(secrets or KeyringSecretStore(), node_name)
        self.pairing = PairingService(self.peers, clock)
        self._transfer_root = transfer_root
        self.discovery = discovery if discovery is not None else Discovery(node_id, node_name, role_hint)
        self.server: LinkServer | None = None
        # The outreach event facility (LINK-100): off until the owner opens an event, and ended with the link.
        self.outreach = OutreachFacility(self.audit, clock=clock, link_available=lambda: self.running,
                                         pier_names=pier_display_names)
        self.outreach_feed = OutreachFeed(self.outreach, session_busy=session_busy)
        self.outreach._render = self.outreach_feed.render
        self.spoke: SpokeEndpoints | None = None
        self._users: set[str] = set()
        # Plugins hand over a function that puts their routes (and handshake additions) on a LinkServer.
        # The server is created afresh each time the listener starts, so it is run again for each one.
        self._installers: dict[str, Callable[[LinkServer], None]] = {}
        self._installed_on: dict[str, LinkServer] = {}
        self._prune: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    # -- state ---------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.server is not None and self.server.running

    @property
    def users(self) -> frozenset[str]:
        return frozenset(self._users)

    def settings(self) -> LinkSettings:
        return LinkSettings.load()

    def fingerprint(self) -> str:
        return self.certs.fingerprint()

    # -- plugins that use Connect Link -------------------------------------------------------
    async def acquire(self, plugin: str, permissions: Iterable[str] = (),
                      install: Callable[[LinkServer], None] | None = None) -> None:
        """A plugin starts using Connect Link, declaring the permissions it may grant to peers it pairs;
        the first plugin starts the listener (if enabled). *install*, if given, registers the plugin's
        routes on the listener's server: now if it is running, and again after every restart (LINK-050)."""
        name = plugin.strip().lower()
        if permissions:
            self.peers.declare_plugin(name, permissions)
        if install is not None:
            self._installers[name] = install
        self._users.add(name)
        await self.reconcile()
        self._install_routes()

    def _install_routes(self) -> None:
        server = self.server
        if server is None:
            return
        for name, install in list(self._installers.items()):
            if self._installed_on.get(name) is server or name not in self._users:
                continue
            try:
                install(server)
            except Exception:                         # one plugin's bad routes never stop the listener
                logger.exception("Could not register the routes of plugin %s", name)
            self._installed_on[name] = server

    async def release(self, plugin: str) -> None:
        """A plugin stops using it; the route table and streams of that plugin go, and the last one to
        leave stops the listener."""
        name = plugin.strip().lower()
        self._users.discard(name)
        self._installers.pop(name, None)
        self._installed_on.pop(name, None)
        if self.server is not None:
            self.server.disable_plugin(name)
        await self.reconcile()

    # -- start, stop, disable ------------------------------------------------------------------
    async def reconcile(self) -> None:
        """Make the listener match the settings and the plugins in use."""
        async with self._lock:
            wanted = self.settings().enabled and bool(self._users)
            if wanted and not self.running:
                await self._start()
            elif not wanted and self.running:
                await self._stop()

    async def set_enabled(self, enabled: bool) -> None:
        settings_store.set_setting(NAMESPACE, "enabled", bool(enabled))
        await self.reconcile()

    async def apply_settings(self, new: LinkSettings) -> None:
        """Save changed settings and restart the listener if one of them needs it."""
        old = self.settings()
        new.save()
        self.pairing.expiry_s = new.pairing_expiry_s
        restart = self.running and (new.port, new.bind_host, new.advertise) != (old.port, old.bind_host, old.advertise)
        if restart:
            async with self._lock:
                await self._stop()
        await self.reconcile()

    async def shutdown(self) -> None:
        """Stop everything (application exit). Pairings stay."""
        async with self._lock:
            await self._stop()
        await self.discovery.close()

    async def _start(self) -> None:
        s = self.settings()
        self.pairing.expiry_s = s.pairing_expiry_s
        transfers = TransferService(self._transfer_root, busy=self._session_busy) if self._transfer_root else None
        server = LinkServer(self.peers, self.pairing, self.certs, self.audit, transfers=transfers,
                            discovery=self.discovery if s.advertise else None, spoke=self.spoke)
        await server.start(s.bind_host or None, s.port)
        self.server = server
        self._install_routes()
        self._prune = asyncio.create_task(self._prune_daily())
        logger.info("Connect Link started for %s", ", ".join(sorted(self._users)) or "no plugin")

    # -- outreach events (LINK-100, LINK-190) -----------------------------------------------------------
    async def open_event(self, owner: str, duration_min: int | None = None) -> None:
        """Open an outreach event; raises ``OutreachError`` with the reason if it cannot open."""
        self.outreach.open(owner, duration_min)
        self.outreach_feed.attach(asyncio.get_running_loop())
        self.outreach.start_timer()

    async def close_event(self, by: str = "owner") -> None:
        await self._end_event(by, "ended")

    async def _end_event(self, by: str, reason: str) -> None:
        self.outreach.close(by, reason)
        self.outreach_feed.detach()
        await self.outreach.stop_timer()

    async def _stop(self) -> None:
        if self.outreach.is_open:                              # disabling Connect Link ends the event (LINK-100)
            await self._end_event("system", "connect link stopped")
        prune, self._prune = self._prune, None
        if prune is not None:
            prune.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await prune
        server, self.server = self.server, None
        if server is not None:
            await server.stop()                    # closes streams and withdraws the advertisement
            logger.info("Connect Link stopped")

    async def _prune_daily(self) -> None:
        while True:
            try:
                self.audit.prune()
            except Exception:
                logger.exception("Could not prune the Connect Link audit log")
            await asyncio.sleep(PRUNE_INTERVAL_S)


__all__ = ["MAX_PORT", "MIN_PORT", "NAMESPACE", "ConnectLinkService", "LinkSettings", "SettingsError"]
