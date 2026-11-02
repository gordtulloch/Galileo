# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Plugin route registry (LINK-050).

A plugin registers versioned routes under its own prefix (``/<plugin>/v<N>/...``), each declaring the
permission it needs. The registry is only consulted *after* the dispatcher has authenticated the
caller, so an unauthenticated caller cannot learn which routes exist.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from galileo.connect_link.permissions import PAIRED_PERMISSIONS

logger = logging.getLogger(__name__)

RESERVED_PREFIXES = frozenset({"connect"})        # core's own prefix (/connect/v1/...)
_PLUGIN = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})

Handler = Callable[..., Awaitable[Any]]


class RouteError(ValueError):
    """A route registration Connect Link refuses."""


@dataclass(frozen=True)
class Route:
    plugin: str
    method: str
    path: str
    permission: str
    handler: Handler


class RouteRegistry:
    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], Route] = {}
        self._lock = threading.Lock()
        self._listeners: list[Callable[[int], None]] = []

    def on_change(self, listener: Callable[[int], None]) -> None:
        """Call *listener* with the new route count after each change (drives start/stop, LINK-010)."""
        self._listeners.append(listener)

    def register(self, plugin: str, method: str, path: str, permission: str, handler: Handler) -> Route:
        """Register ``path`` (which must begin ``/<plugin>/v<N>/``) for *plugin*."""
        method = method.upper()
        if not _PLUGIN.match(plugin) or plugin in RESERVED_PREFIXES:
            raise RouteError(f"{plugin!r} is not a prefix a plugin may register under")
        if method not in _METHODS:
            raise RouteError(f"unsupported method {method!r}")
        if permission not in PAIRED_PERMISSIONS:
            raise RouteError(f"{permission!r} is not a permission a route can require")
        if not re.match(rf"^/{re.escape(plugin)}/v\d+(/[A-Za-z0-9_~-][A-Za-z0-9._~-]*)*/?$", path):
            raise RouteError(f"path {path!r} must be under /{plugin}/v<N>/")
        route = Route(plugin, method, path.rstrip("/"), permission, handler)
        with self._lock:
            if (method, route.path) in self._routes:
                raise RouteError(f"{method} {route.path} is already registered")
            self._routes[(method, route.path)] = route
            count = len(self._routes)
        self._notify(count)
        return route

    def unregister_plugin(self, plugin: str) -> int:
        """Drop every route of *plugin* (plugin disabled or removed); returns how many."""
        with self._lock:
            gone = [k for k, r in self._routes.items() if r.plugin == plugin]
            for k in gone:
                del self._routes[k]
            count = len(self._routes)
        if gone:
            self._notify(count)
        return len(gone)

    def find(self, method: str, path: str) -> Route | None:
        with self._lock:
            return self._routes.get((method.upper(), path.rstrip("/")))

    def __len__(self) -> int:
        with self._lock:
            return len(self._routes)

    def _notify(self, count: int) -> None:
        for fn in list(self._listeners):
            try:
                fn(count)
            except Exception:                                   # a listener never breaks registration
                logger.exception("route-change listener failed")
