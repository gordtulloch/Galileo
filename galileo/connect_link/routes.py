# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Plugin-registered routes (LINK-050).

A plugin registers versioned request/response routes under its own prefix
(``/<plugin>/v<n>/...``), each declaring the permission it needs. The registry only answers "which
route is this and what does it need"; authentication, the permission check and the audit record
happen in the server's gate and dispatcher *before* a lookup, so an unauthenticated caller learns
nothing about which routes exist.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from galileo.connect_link.permissions import PAIRED_PERMISSIONS

CORE_PREFIX = "connect"
_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_VERSIONED = re.compile(r"^/(?P<plugin>[^/]+)/v(?P<version>[1-9][0-9]*)(?P<rest>/.*)?$")
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})

# ``handler(peer, request) -> web.Response | dict | list`` — typed loosely so the registry has no
# dependency on the transport.
Handler = Callable[[Any, Any], Awaitable[Any]]


class RouteError(ValueError):
    """A route registration Connect Link refuses."""


@dataclass(frozen=True)
class Route:
    plugin: str
    method: str
    path: str
    permission: str
    handler: Handler


def plugin_prefix(plugin: str) -> str:
    """The URL segment a plugin owns: its name, lower-cased."""
    return plugin.strip().lower()


class RouteRegistry:
    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], Route] = {}

    def register(self, plugin: str, method: str, path: str, permission: str, handler: Handler) -> Route:
        prefix = plugin_prefix(plugin)
        if not _NAME.match(prefix) or prefix == CORE_PREFIX:
            raise RouteError(f"{plugin!r} cannot register routes")
        method = method.upper()
        if method not in METHODS:
            raise RouteError(f"unsupported method {method!r}")
        if permission not in PAIRED_PERMISSIONS:
            raise RouteError(f"unknown permission {permission!r}")
        m = _VERSIONED.match(path)
        if m is None or m["plugin"] != prefix:
            raise RouteError(f"{path!r} is not under /{prefix}/v<n>/")
        if ".." in path or "//" in path:
            raise RouteError(f"{path!r} is not a clean path")
        key = (method, path)
        existing = self._routes.get(key)
        if existing is not None:
            raise RouteError(f"{method} {path} is already registered")
        route = Route(prefix, method, path, permission, handler)
        self._routes[key] = route
        return route

    def unregister_plugin(self, plugin: str) -> int:
        """Remove every route a plugin registered (disable / remove). Returns how many."""
        prefix = plugin_prefix(plugin)
        gone = [k for k, r in self._routes.items() if r.plugin == prefix]
        for k in gone:
            del self._routes[k]
        return len(gone)

    def find(self, method: str, path: str) -> Route | None:
        return self._routes.get((method.upper(), path))

    def routes(self, plugin: str = "") -> list[Route]:
        prefix = plugin_prefix(plugin)
        return [r for r in self._routes.values() if not prefix or r.plugin == prefix]

    def __len__(self) -> int:
        return len(self._routes)


__all__ = ["CORE_PREFIX", "Handler", "Route", "RouteError", "RouteRegistry", "plugin_prefix"]
