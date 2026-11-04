# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""One ordered feed of everything a front end wants to hear about (CSURF-260).

State changes, lease changes and the bus events that matter to an operator (device connection, operation
progress) are merged into a single sequence with a monotonic id. A reader asks for "everything after id N" and may
wait for news, so a front end that talks request/response (a Connect Link route, a long poll) needs no per-reader
queue on the engine. The feed keeps only the most recent entries; a reader that fell too far behind is told so
(``gap``) and takes a fresh state snapshot instead of silently missing changes. Nothing here blocks a publisher.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections import deque
from collections.abc import Callable
from typing import Any

from galileo.bus import DeviceConnectedEvent, DeviceDisconnectedEvent, DeviceErrorEvent, Event, EventBus
from galileo.control_surface.events import OperationFinished, OperationProgress, OperationStarted
from galileo.control_surface.lease import LeaseBroker
from galileo.control_surface.state import ObservableState

logger = logging.getLogger(__name__)

FEED_EVENTS: tuple[type[Event], ...] = (
    DeviceConnectedEvent, DeviceDisconnectedEvent, DeviceErrorEvent,
    OperationStarted, OperationProgress, OperationFinished,
)
DEFAULT_CAPACITY = 2000


class EventFeed:
    def __init__(self, *, state: ObservableState, leases: LeaseBroker, bus: EventBus,
                 pier_ids: Callable[[], list[str]], capacity: int = DEFAULT_CAPACITY,
                 events: tuple[type[Event], ...] = FEED_EVENTS) -> None:
        self._cond = threading.Condition()
        self._entries: deque[dict[str, Any]] = deque(maxlen=max(10, capacity))
        self._last = 0
        self._closed = False
        self._undo: list[Callable[[], None]] = []
        for et in events:
            bus.subscribe(et, self._on_bus)
            self._undo.append(lambda et=et: bus.unsubscribe(et, self._on_bus))
        leases.add_listener(self._on_lease)
        self._undo.append(lambda: leases.remove_listener(self._on_lease))
        for pier in pier_ids():
            _seq, _values, unsub = state.subscribe(pier, self._on_state)
            self._undo.append(unsub)

    # -- writing -------------------------------------------------------------------------------------
    def _append(self, entry: dict[str, Any]) -> None:
        with self._cond:
            if self._closed:
                return
            self._last += 1
            entry["id"] = self._last
            self._entries.append(entry)
            self._cond.notify_all()

    def _on_bus(self, event: Event) -> None:
        self._append({"type": "event", "name": type(event).__name__, "source": event.source,
                      "payload": dict(event.payload)})

    def _on_lease(self, pier: str, previous: str, holder: str, reason: str) -> None:
        self._append({"type": "lease", "pier": pier, "previous": previous, "holder": holder, "reason": reason})

    def _on_state(self, pier: str, seq: int, key: str, value: Any) -> None:
        self._append({"type": "state", "pier": pier, "seq": seq, "key": key, "value": value})

    # -- reading -------------------------------------------------------------------------------------
    @property
    def last_id(self) -> int:
        with self._cond:
            return self._last

    def read(self, after: int = 0, timeout: float = 0.0, limit: int = 500) -> dict[str, Any]:
        """Entries with an id above ``after``, waiting up to ``timeout`` seconds if there are none yet.

        ``gap`` is true when entries between ``after`` and the oldest one kept have been dropped; the reader then
        re-reads state rather than trust its picture. ``last`` is the id to pass next time, whether or not anything
        came back. ``closed`` means the feed has ended.
        """
        with self._cond:
            if not self._has_news(after) and not self._closed and timeout > 0:
                self._cond.wait_for(lambda: self._has_news(after) or self._closed, timeout)
            entries = self._entries
            oldest = entries[0]["id"] if entries else self._last + 1
            gap = after + 1 < oldest and self._last > after
            picked = [dict(e) for e in entries if e["id"] > after][:max(1, limit)]
            return {"entries": picked, "last": picked[-1]["id"] if picked else after, "gap": gap,
                    "closed": self._closed}

    def _has_news(self, after: int) -> bool:
        return self._last > after

    def close(self) -> None:
        """Stop listening to the sources and wake every waiting reader."""
        for undo in self._undo:
            with contextlib.suppress(Exception):
                undo()
        self._undo.clear()
        with self._cond:
            self._closed = True
            self._cond.notify_all()


__all__ = ["DEFAULT_CAPACITY", "FEED_EVENTS", "EventFeed"]
