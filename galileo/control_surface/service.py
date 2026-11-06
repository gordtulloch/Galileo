# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""How a plugin reaches the running engine's Control Surface (CSURF-250, LINK-230).

The engine builds the registry, the lease broker, the request pipeline and the observable state; a front-end
plugin (WebConnect, MobileConnect) has to use *those* objects, not its own, or its operations would meet a
different lease and a different catalogue from the desktop's. The engine publishes them here when its local
channel starts and withdraws them when it stops; a plugin reads them with :func:`get_control_surface`, in the
same way NodeConnect reads Connect Link with ``get_host()``. It is ``None`` while no engine is running, and a
plugin treats that as "Galileo is not ready" rather than an error.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from galileo.connect_link.gateway import Gateway
from galileo.control_surface.feed import EventFeed
from galileo.control_surface.lease import LeaseBroker
from galileo.control_surface.registry import Registry
from galileo.control_surface.state import ObservableState


@dataclass(frozen=True)
class ControlSurfaceService:
    registry: Registry
    leases: LeaseBroker
    gateway: Gateway
    state: ObservableState
    piers: Callable[[], list[dict[str, Any]]]       # id, name, connected, lease holder — one dict per local Pier
    feed: EventFeed | None = None                   # state, lease and operation events in order (CSURF-260)
    previews: Any = None                            # galileo.control_surface.frames.FramePreviews: pictures (PREV-070)


_lock = threading.Lock()
_current: ControlSurfaceService | None = None


def publish_control_surface(service: ControlSurfaceService) -> None:
    global _current
    with _lock:
        _current = service


def withdraw_control_surface() -> None:
    global _current
    with _lock:
        _current = None


def get_control_surface() -> ControlSurfaceService | None:
    with _lock:
        return _current


__all__ = ["ControlSurfaceService", "get_control_surface", "publish_control_surface", "withdraw_control_surface"]
