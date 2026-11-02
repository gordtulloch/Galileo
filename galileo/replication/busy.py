# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Busy signal (REPL-060): is an imaging session or calibration run executing, and tell me when it ends.

The session executor and calibration runs ``acquire`` a token while they work and ``release`` it
after; a bulk apply of replicated settings asks ``is_busy()`` and otherwise waits with ``on_idle``.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)


class BusyTracker:
    def __init__(self) -> None:
        self._active: set[object] = set()
        self._waiters: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._active)

    def acquire(self, token: object) -> None:
        with self._lock:
            self._active.add(token)

    def release(self, token: object) -> None:
        with self._lock:
            self._active.discard(token)
            waiters, self._waiters = ([], self._waiters) if self._active else (self._waiters, [])
        for fn in waiters:
            try:
                fn()
            except Exception:
                logger.exception("on_idle callback raised")

    @contextlib.contextmanager
    def working(self, token: object) -> Iterator[None]:
        self.acquire(token)
        try:
            yield
        finally:
            self.release(token)

    def on_idle(self, callback: Callable[[], None]) -> None:
        """Call *callback* once, now if idle, otherwise when the last work ends."""
        with self._lock:
            if self._active:
                self._waiters.append(callback)
                return
        callback()


tracker = BusyTracker()
is_busy = tracker.is_busy
on_idle = tracker.on_idle
