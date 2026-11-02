# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Observable state per Pier (CSURF-060).

Services ``publish(pier, key, value)`` fragments such as ``mount.position``; a subscriber gets a
snapshot and then every change tagged with the Pier's next sequence number, so a gap is detectable and
a fresh snapshot can be requested. A failing subscriber is dropped from the call, never from the
service (ARCH-060).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# callback(pier, seq, key, value)
Listener = Callable[[str, int, str, Any], None]


class ObservableState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, dict[str, Any]] = {}
        self._seq: dict[str, int] = {}
        self._subs: dict[str, list[Listener]] = {}

    def publish(self, pier: str, key: str, value: Any) -> int:
        """Record a change and tell subscribers; returns its sequence number. An unchanged value is
        not republished."""
        with self._lock:
            current = self._values.setdefault(pier, {})
            if key in current and current[key] == value:
                return self._seq.get(pier, 0)
            current[key] = value
            seq = self._seq[pier] = self._seq.get(pier, 0) + 1
            listeners = list(self._subs.get(pier, ()))
        for listener in listeners:
            try:
                listener(pier, seq, key, value)
            except Exception:
                logger.exception("state subscriber failed")
        return seq

    def snapshot(self, pier: str) -> tuple[int, dict[str, Any]]:
        """``(sequence, values)`` — deltas after this have a higher sequence."""
        with self._lock:
            return self._seq.get(pier, 0), dict(self._values.get(pier, {}))

    def read(self, pier: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(pier, {}).get(key, default)

    def subscribe(self, pier: str, listener: Listener) -> tuple[int, dict[str, Any], Callable[[], None]]:
        """Snapshot plus an ``unsubscribe`` callable. The listener is registered under the same lock
        as the snapshot is taken, so no change falls between them."""
        with self._lock:
            self._subs.setdefault(pier, []).append(listener)
            seq, values = self._seq.get(pier, 0), dict(self._values.get(pier, {}))

        def unsubscribe() -> None:
            with self._lock:
                subs = self._subs.get(pier, [])
                if listener in subs:
                    subs.remove(listener)
        return seq, values, unsubscribe

    def clear_pier(self, pier: str) -> None:
        with self._lock:
            self._values.pop(pier, None)
            self._subs.pop(pier, None)


__all__ = ["Listener", "ObservableState"]
