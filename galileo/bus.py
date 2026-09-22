# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Lightweight in-process publish/subscribe event bus.

The bus is the sole cross-module communication mechanism between the
sequencer, device layer, and safety/notification modules (SDD §2.3).
Qt-based code should bridge onto this bus using ``Qt.QueuedConnection``
rather than calling it directly from non-Qt threads.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class Event:
    """Base class for all bus events."""

    def __init__(self, source: str = "", **payload: Any) -> None:
        self.source = source
        self.payload = payload

    def __repr__(self) -> str:
        return f"{type(self).__name__}(source={self.source!r}, payload={self.payload})"

    def __getattr__(self, name: str):
        # Falls back to the payload dict so e.g. DeviceErrorEvent(recoverable=True)
        # is readable as both event.payload["recoverable"] and event.recoverable.
        try:
            return self.payload[name]
        except KeyError:
            raise AttributeError(name) from None


# --- Domain event types ---------------------------------------------------

class DeviceConnectedEvent(Event):
    timestamp: str

class DeviceDisconnectedEvent(Event):
    timestamp: str

class DeviceErrorEvent(Event):
    timestamp: str

class SafetyUnsafeEvent(Event):
    explanation: str

class SequenceCompleteEvent(Event):
    pass

class SequenceErrorEvent(Event):
    pass

class SequenceAbortEvent(Event):
    pass

class WeatherReadingEvent(Event):
    timestamp: str

class SolveStartedEvent(Event):
    """A plate solve began; ``fits_path`` is the frame being solved."""

class SolveCompleteEvent(Event):
    """A plate solve finished; ``fits_path`` is the frame and ``result`` its ``SolveResult``
    (success or not — see ``SolveResult.failure_reason``)."""

class CurrentObjectChangedEvent(Event):
    """A Pier's current object changed. Payload: ``pier`` (the key from
    ``galileo.current_object.pier_key``) and ``object`` (a ``CurrentObject``,
    or ``None`` when it was cleared)."""

class FocusStartedEvent(Event):
    """An autofocus run began. Payload: ``positions`` (the planned sweep),
    ``initial_position``, ``step_size``, ``num_points``."""

class FocusFrameEvent(Event):
    """One autofocus exposure was measured. Payload: ``position``, ``frame``
    (the raw array), ``hfr``, ``fwhm``, ``star_count`` and ``confirm`` (True
    for the post-move confirmation exposure taken at the computed best
    position, False for a sweep sample)."""

class FocusCompleteEvent(Event):
    """An autofocus run ended, however it ended. Payload: ``result`` (an
    ``AutofocusResult``)."""


# --- Bus implementation ---------------------------------------------------

class EventBus:
    """Thread-safe publish/subscribe event bus.

    Handlers are called synchronously in the thread that calls ``publish``.
    Qt UI code must post to the Qt event loop via ``QMetaObject.invokeMethod``
    or a ``Qt.QueuedConnection`` signal before calling ``publish``.
    """

    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[[Event], None]]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Callable[[Event], None]) -> None:
        """Register *handler* to be called when *event_type* is published."""
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: Callable[[Event], None]) -> None:
        """Remove *handler* for *event_type*; silently ignores unknown handlers."""
        try:
            self._handlers[event_type].remove(handler)
        except ValueError:
            pass

    def publish(self, event: Event) -> None:
        """Publish *event* to all registered handlers for its type."""
        for handler in list(self._handlers.get(type(event), [])):
            try:
                handler(event)
            except Exception:
                logger.exception("Event handler raised an exception for %r", event)


# Module-level default bus (singleton)
_default_bus: EventBus | None = None


def get_bus() -> EventBus:
    """Return the process-wide default event bus."""
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus
