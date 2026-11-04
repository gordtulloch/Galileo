# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The per-Pier control lease (LEASE-010 to LEASE-060, LEASE-080).

At most one holder per Pier — ``desktop`` or a remote client's id — kept in memory only, so a restart
clears it. A free Pier is granted at once; a held one is refused with the holder named and can be
*taken over* with a confirmation. The lease also lapses after an idle time and when its holder
disconnects. Every change is published on the bus and offered to registered listeners (the held-motion
manager uses one to stop the previous holder's motion).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from galileo.bus import EventBus, get_bus
from galileo.control_surface.events import LeaseChanged

logger = logging.getLogger(__name__)

DESKTOP = "desktop"
DEFAULT_IDLE_S = 600.0

# listener(pier, previous_holder, new_holder, reason)
ChangeListener = Callable[[str, str, str, str], None]


@dataclass(frozen=True)
class LeaseResult:
    granted: bool
    holder: str                 # who holds the lease after the call
    can_take_over: bool = False
    reason: str = ""


class LeaseBroker:
    def __init__(self, clock: Callable[[], float] = time.monotonic, idle_s: float = DEFAULT_IDLE_S,
                 bus: EventBus | None = None) -> None:
        self._clock = clock
        self.idle_s = idle_s
        self._bus = bus
        self._lock = threading.RLock()
        self._holders: dict[str, tuple[str, float]] = {}            # pier -> (holder, last activity)
        self._listeners: list[ChangeListener] = []

    def add_listener(self, listener: ChangeListener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: ChangeListener) -> None:
        with contextlib.suppress(ValueError):
            self._listeners.remove(listener)

    # -- queries -------------------------------------------------------------------------
    def holder(self, pier: str) -> str:
        with self._lock:
            self._expire(pier)
            entry = self._holders.get(pier)
            return entry[0] if entry else ""

    # -- changes -------------------------------------------------------------------------
    def acquire(self, pier: str, holder: str) -> LeaseResult:
        with self._lock:
            self._expire(pier)
            current = self._holders.get(pier)
            if current is None:
                self._set(pier, holder, "acquired")
                return LeaseResult(True, holder)
            if current[0] == holder:
                self._holders[pier] = (holder, self._clock())
                return LeaseResult(True, holder)
            return LeaseResult(False, current[0], can_take_over=True, reason=f"held by {current[0]}")

    def take(self, pier: str, holder: str, confirmed: bool) -> LeaseResult:
        """Take over a held lease; refused unless the requester has confirmed (LEASE-030)."""
        with self._lock:
            self._expire(pier)
            current = self._holders.get(pier)
            if current is None or current[0] == holder:
                return self.acquire(pier, holder)
            if not confirmed:
                return LeaseResult(False, current[0], can_take_over=True,
                                   reason=f"held by {current[0]}; confirm to take it over")
            self._set(pier, holder, "taken over")
            return LeaseResult(True, holder)

    def release(self, pier: str, holder: str, reason: str = "released") -> bool:
        with self._lock:
            current = self._holders.get(pier)
            if current is None or current[0] != holder:
                return False
            self._set(pier, "", reason)
            return True

    def on_disconnect(self, holder: str, reason: str = "disconnected") -> list[str]:
        """Release every Pier a disconnected or revoked holder had (LEASE-040)."""
        with self._lock:
            piers = [p for p, (h, _) in self._holders.items() if h == holder]
            for p in piers:
                self._set(p, "", reason)
            return piers

    def touch(self, pier: str, holder: str) -> None:
        """The holder did something: restart its idle timer (LEASE-040)."""
        with self._lock:
            current = self._holders.get(pier)
            if current is not None and current[0] == holder:
                self._holders[pier] = (holder, self._clock())

    def expire_idle(self) -> list[str]:
        """Release every lease idle for longer than ``idle_s``; returns the Piers freed."""
        with self._lock:
            return [p for p in list(self._holders) if self._expire(p)]

    # -- internals -----------------------------------------------------------------------
    def _expire(self, pier: str) -> bool:
        current = self._holders.get(pier)
        if current is not None and current[0] != DESKTOP and self._clock() - current[1] >= self.idle_s:
            self._set(pier, "", "idle")
            return True
        return False

    def _set(self, pier: str, holder: str, reason: str) -> None:
        previous = self._holders.get(pier, ("", 0.0))[0]
        if holder:
            self._holders[pier] = (holder, self._clock())
        else:
            self._holders.pop(pier, None)
        for listener in list(self._listeners):
            try:
                listener(pier, previous, holder, reason)
            except Exception:
                logger.exception("lease listener failed")
        try:
            (self._bus or get_bus()).publish(LeaseChanged(
                "control_surface", pier=pier, holder=holder, previous=previous, reason=reason))
        except Exception:
            logger.exception("lease event subscriber failed")


__all__ = ["DEFAULT_IDLE_S", "DESKTOP", "ChangeListener", "LeaseBroker", "LeaseResult"]
