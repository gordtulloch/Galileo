# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LAN discovery (LINK-040).

While the listener runs the node advertises ``_galileo-link._tcp`` by mDNS carrying only its display
name, node id, port, protocol version and role hint — never a secret, and nothing that lets a
bystander pair (pairing still needs the owner's approval). Other nodes' advertisements can be
browsed, and a host and port can be entered by hand.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_galileo-link._tcp.local."
_HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$|^[0-9A-Fa-f:]+$")
_MAX_TXT = 200


class DiscoveryError(ValueError):
    """A manual address or advertisement Connect Link will not use."""


@dataclass(frozen=True)
class DiscoveredNode:
    name: str
    node_id: str
    host: str
    port: int
    protocol: int
    role: str = ""


class DiscoveryBackend(Protocol):
    """The mDNS operations Discovery needs (``zeroconf`` in production, a fake in tests)."""

    async def register(self, info: Any) -> None: ...
    async def unregister(self, info: Any) -> None: ...
    async def browse(self, listen_for: float) -> list[Any]: ...
    async def close(self) -> None: ...


class ZeroconfBackend:
    def __init__(self) -> None:
        from zeroconf import InterfaceChoice
        from zeroconf.asyncio import AsyncZeroconf
        try:
            self._zc = AsyncZeroconf()
        except OSError as exc:
            # Binding every interface can fail with "address in use" (seen on a Mac): one working interface
            # is still better than none, which would leave peers typing the address.
            logger.info("mDNS could not use every network interface (%s); using the default one", exc)
            self._zc = AsyncZeroconf(interfaces=InterfaceChoice.Default)

    async def register(self, info: Any) -> None:
        await self._zc.async_register_service(info)

    async def unregister(self, info: Any) -> None:
        await self._zc.async_unregister_service(info)

    async def browse(self, listen_for: float) -> list[Any]:
        from zeroconf import ServiceStateChange
        from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo

        names: set[str] = set()

        def on_change(*, name: str, state_change: ServiceStateChange, **_: Any) -> None:
            if state_change is not ServiceStateChange.Removed:
                names.add(name)

        browser = AsyncServiceBrowser(self._zc.zeroconf, SERVICE_TYPE, handlers=[on_change])
        try:
            await asyncio.sleep(listen_for)
        finally:
            await browser.async_cancel()
        found = []
        for name in sorted(names):
            info = AsyncServiceInfo(SERVICE_TYPE, name)
            if await info.async_request(self._zc.zeroconf, 1500):
                found.append(info)
        return found

    async def close(self) -> None:
        await self._zc.async_close()


def _clean(text: str) -> str:
    return text.encode("utf-8")[:_MAX_TXT].decode("utf-8", "ignore")


def manual_address(host: str, port: int) -> DiscoveredNode:
    """A node entered by hand: host name or IP and port, validated but not contacted."""
    host = host.strip()
    if "://" in host or "/" in host or not _HOST.match(host):
        raise DiscoveryError("enter a host name or IP address, without a scheme or path")
    if not 0 < int(port) < 65536:
        raise DiscoveryError("port must be 1-65535")
    return DiscoveredNode(name=host, node_id="", host=host, port=int(port), protocol=0)


def parse_service(info: Any) -> DiscoveredNode | None:
    """A browsed service as a node, or None when it is malformed."""
    try:
        props = {k.decode() if isinstance(k, bytes) else k: (v or b"").decode("utf-8", "replace")
                 for k, v in info.properties.items()}
        addresses = info.parsed_addresses()
        node_id = props["node"]
        if not addresses or not node_id or not info.port:
            return None
        return DiscoveredNode(props.get("name", node_id), node_id, addresses[0], int(info.port),
                              int(props.get("proto", "0")), props.get("role", ""))
    except (KeyError, ValueError, AttributeError):
        return None


class Discovery:
    def __init__(self, node_id: str, display_name: str, role_hint: str = "",
                 backend: DiscoveryBackend | None = None) -> None:
        self._node_id = node_id
        self._name = display_name
        self._role = role_hint
        self._backend = backend
        self._info: Any = None

    @property
    def advertising(self) -> bool:
        return self._info is not None

    def _backend_or_default(self) -> DiscoveryBackend:
        if self._backend is None:
            self._backend = ZeroconfBackend()
        return self._backend

    def _service_info(self, host: str, port: int, protocol: int) -> Any:
        from zeroconf import ServiceInfo
        props = {"name": _clean(self._name), "node": _clean(self._node_id), "proto": str(protocol),
                 "role": _clean(self._role)}
        return ServiceInfo(
            SERVICE_TYPE, f"{self._node_id[:60]}.{SERVICE_TYPE}", port=port, properties=props,
            addresses=[socket.inet_aton(host)])

    async def advertise(self, host: str, port: int, protocol: int) -> None:
        if self._info is not None:
            return
        info = self._service_info(host, port, protocol)
        await self._backend_or_default().register(info)
        self._info = info

    async def withdraw(self) -> None:
        info, self._info = self._info, None
        if info is not None:
            await self._backend_or_default().unregister(info)

    async def browse(self, listen_for: float = 3.0) -> list[DiscoveredNode]:
        """Other nodes currently advertising (this node is left out)."""
        found = (parse_service(i) for i in await self._backend_or_default().browse(listen_for))
        return [n for n in found if n is not None and n.node_id != self._node_id]

    async def close(self) -> None:
        await self.withdraw()
        if self._backend is not None:
            await self._backend.close()
            self._backend = None


__all__ = ["SERVICE_TYPE", "DiscoveredNode", "Discovery", "DiscoveryBackend", "DiscoveryError",
           "ZeroconfBackend", "manual_address", "parse_service"]
