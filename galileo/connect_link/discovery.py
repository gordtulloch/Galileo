# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LAN discovery by mDNS (LINK-040).

While the listener runs the node advertises ``_galileo-link._tcp`` carrying only its display name,
node id, port, protocol version and role hint — never a secret — and can browse for other nodes.
``zeroconf`` is imported lazily and every failure is contained: discovery is a convenience, and a
client can always connect to a manually entered host and port.
"""

from __future__ import annotations

import logging
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_galileo-link._tcp.local."


@dataclass(frozen=True)
class DiscoveredNode:
    name: str
    node_id: str
    host: str
    port: int
    protocol: int
    role: str


def advert_properties(node_id: str, protocol: int, role: str = "") -> dict[str, str]:
    """The TXT record: no secret ever goes in it (the display name is the service name)."""
    return {"node_id": node_id, "protocol": str(protocol), "role": role}


def _label(name: str) -> str:
    return re.sub(r"[^\w .-]", "", name).strip()[:60] or "Galileo"


def node_from_service(name: str, addresses: list[str], port: int, props: dict[bytes, bytes | None]) -> DiscoveredNode | None:
    """A browsed service as a node, or ``None`` if it is not a usable Galileo advertisement."""
    def get(key: str) -> str:
        v = props.get(key.encode())
        return v.decode("utf-8", "replace") if v else ""
    if not addresses or not port:
        return None
    try:
        protocol = int(get("protocol"))
    except ValueError:
        return None
    suffix = "." + SERVICE_TYPE
    return DiscoveredNode(name.removesuffix(suffix), get("node_id"),
                          addresses[0], port, protocol, get("role"))


class Discovery:
    def __init__(self, zeroconf_factory: Callable[[], Any] | None = None,
                 browser_factory: Callable[..., Any] | None = None) -> None:
        self._factory, self._browser_factory = zeroconf_factory, browser_factory
        self._zc: Any = None
        self._info: Any = None
        self._browser: Any = None
        self.found: dict[str, DiscoveredNode] = {}

    @property
    def advertising(self) -> bool:
        return self._info is not None

    def _zeroconf(self) -> Any:
        if self._zc is None:
            if self._factory is not None:
                self._zc = self._factory()
            else:
                from zeroconf import Zeroconf
                self._zc = Zeroconf()
        return self._zc

    def start(self, display_name: str, node_id: str, host: str, port: int, protocol: int, role: str = "") -> bool:
        """Advertise the node and start browsing; ``False`` (logged) if mDNS is unavailable."""
        if self._info is not None:
            return True
        try:
            from zeroconf import ServiceBrowser, ServiceInfo
            zc = self._zeroconf()
            label = _label(display_name)
            self._info = ServiceInfo(
                SERVICE_TYPE, f"{label}.{SERVICE_TYPE}", port=port,
                addresses=[socket.inet_aton(host)], properties=advert_properties(node_id, protocol, role),
            )
            zc.register_service(self._info)
            self._browser = (self._browser_factory or ServiceBrowser)(zc, SERVICE_TYPE, handlers=[self._on_change])
            return True
        except Exception:
            logger.warning("Connect Link discovery unavailable", exc_info=True)
            self._info = None
            self._close_zc()
            return False

    def _on_change(self, zeroconf: Any, service_type: str, name: str, state_change: Any) -> None:
        from zeroconf import ServiceStateChange
        try:
            if state_change is ServiceStateChange.Removed:
                self.found.pop(name, None)
                return
            info = zeroconf.get_service_info(service_type, name, 2000)
            if info is None:
                return
            node = node_from_service(name, info.parsed_addresses(), info.port or 0, info.properties)
            if node is not None and node.node_id != (self._info.properties.get(b"node_id", b"").decode() if self._info else ""):
                self.found[name] = node
        except Exception:
            logger.debug("discovery handler failed", exc_info=True)

    def nodes(self) -> list[DiscoveredNode]:
        return sorted(self.found.values(), key=lambda n: n.name.lower())

    def stop(self) -> None:
        """Withdraw the advertisement and stop browsing (the listener stopped)."""
        try:
            if self._browser is not None:
                self._browser.cancel()
            if self._zc is not None and self._info is not None:
                self._zc.unregister_service(self._info)
        except Exception:
            logger.debug("discovery stop failed", exc_info=True)
        finally:
            self._browser, self._info = None, None
            self.found.clear()
            self._close_zc()

    def _close_zc(self) -> None:
        zc, self._zc = self._zc, None
        if zc is not None:
            try:
                zc.close()
            except Exception:
                logger.debug("zeroconf close failed", exc_info=True)
