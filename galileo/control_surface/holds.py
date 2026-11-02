# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Held motion with a deadman (CSURF-400 to CSURF-420, LEASE-080).

Motion that lasts only while a button is held (a manual slew, jog or focuser move) is started as a
*hold*. The holder must send ``beat`` regularly; when the beat stops, the holder disconnects, the
lease changes hands, the pairing is revoked, the originating plugin is disabled or a safety stop
occurs, the service's own ``stop`` is called. ``check`` is the watchdog step and ``run`` drives it.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_BEAT_S = 0.25
DEFAULT_DEADMAN_S = 0.6
MAX_STOP_DELAY_S = 1.0


class HoldError(ValueError):
    """A hold the manager refuses."""


def validate_timing(beat_s: float, deadman_s: float) -> None:
    """The deadman must exceed twice the beat interval, and motion must stop within a second (CSURF-410)."""
    if beat_s <= 0:
        raise HoldError("the keep-alive interval must be positive")
    if deadman_s <= 2 * beat_s:
        raise HoldError("the deadman timeout must exceed twice the keep-alive interval")
    if deadman_s + beat_s / 2 > MAX_STOP_DELAY_S:
        raise HoldError("motion must stop within one second of the last keep-alive")


@dataclass
class _Hold:
    hold_id: str
    pier: str
    holder: str
    origin: str
    stop: Callable[[], None]
    last_beat: float


class HoldManager:
    def __init__(self, clock: Callable[[], float] = time.monotonic, beat_s: float = DEFAULT_BEAT_S,
                 deadman_s: float = DEFAULT_DEADMAN_S) -> None:
        validate_timing(beat_s, deadman_s)
        self._clock, self.beat_s, self.deadman_s = clock, beat_s, deadman_s
        self._lock = threading.Lock()
        self._holds: dict[str, _Hold] = {}

    def start(self, pier: str, holder: str, stop: Callable[[], None], origin: str = "") -> str:
        """Begin a hold; ``stop`` is the service's own stop. One hold per Pier at a time."""
        with self._lock:
            if any(h.pier == pier for h in self._holds.values()):
                raise HoldError("a hold is already active on this Pier")
            hold_id = uuid.uuid4().hex
            self._holds[hold_id] = _Hold(hold_id, pier, holder, origin, stop, self._clock())
            return hold_id

    def beat(self, hold_id: str, holder: str) -> bool:
        with self._lock:
            hold = self._holds.get(hold_id)
            if hold is None or hold.holder != holder:
                return False
            hold.last_beat = self._clock()
            return True

    def active(self, pier: str = "") -> list[str]:
        with self._lock:
            return [h.hold_id for h in self._holds.values() if not pier or h.pier == pier]

    # -- stopping ------------------------------------------------------------------------
    def stop(self, hold_id: str, holder: str | None = None, reason: str = "stopped") -> bool:
        with self._lock:
            hold = self._holds.get(hold_id)
            if hold is None or (holder is not None and hold.holder != holder):
                return False
            del self._holds[hold_id]
        self._halt(hold, reason)
        return True

    def _stop_where(self, match: Callable[[_Hold], bool], reason: str) -> int:
        with self._lock:
            doomed = [h for h in self._holds.values() if match(h)]
            for h in doomed:
                del self._holds[h.hold_id]
        for h in doomed:
            self._halt(h, reason)
        return len(doomed)

    @staticmethod
    def _halt(hold: _Hold, reason: str) -> None:
        try:
            hold.stop()
        except Exception:               # a stop that fails is logged loudly; the others still run
            logger.exception("could not stop held motion on %s (%s)", hold.pier, reason)

    def check(self) -> int:
        """Stop every hold whose keep-alive has lapsed; returns how many."""
        now = self._clock()
        return self._stop_where(lambda h: now - h.last_beat >= self.deadman_s, "deadman")

    def cancel_holder(self, holder: str, reason: str = "disconnected") -> int:
        return self._stop_where(lambda h: h.holder == holder, reason)

    def cancel_pier(self, pier: str, reason: str = "lease changed") -> int:
        return self._stop_where(lambda h: h.pier == pier, reason)

    def cancel_origin(self, origin: str, reason: str = "plugin disabled") -> int:
        return self._stop_where(lambda h: bool(origin) and h.origin == origin, reason)

    def cancel_all(self, reason: str = "safety stop") -> int:
        return self._stop_where(lambda h: True, reason)

    def on_lease_changed(self, pier: str, previous: str, holder: str, reason: str) -> None:
        """Lease listener (LEASE-080): taking or losing the lease stops the previous holder's motion."""
        if previous and previous != holder:
            self._stop_where(lambda h: h.pier == pier and h.holder == previous, f"lease {reason}")

    async def run(self, interval: float | None = None) -> None:
        """Watchdog loop; cancel the task to stop it. Starts only when something needs holds."""
        step = interval or self.beat_s / 2
        while True:
            await asyncio.sleep(step)
            self.check()


__all__ = ["DEFAULT_BEAT_S", "DEFAULT_DEADMAN_S", "HoldError", "HoldManager", "validate_timing"]
