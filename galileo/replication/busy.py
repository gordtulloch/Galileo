# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The session busy signal (REPL-060).

``is_busy()`` is true while a session or calibration run is executing; ``on_idle(callback)`` calls back
once when the last one ends (immediately when nothing is running), so a bulk apply can wait for an
imaging session to finish. The session executor wraps its run in :meth:`SessionBusy.running`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class SessionBusy:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = 0
        self._waiting: list[Callable[[], None]] = []

    def is_busy(self) -> bool:
        with self._lock:
            return self._active > 0

    @contextmanager
    def running(self) -> Iterator[None]:
        with self._lock:
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
                callbacks = self._waiting if self._active == 0 else []
                if callbacks:
                    self._waiting = []
            for callback in callbacks:
                self._call(callback)

    def on_idle(self, callback: Callable[[], None]) -> None:
        """One-shot: run ``callback`` when no session is running (now, if that is already so)."""
        with self._lock:
            if self._active > 0:
                self._waiting.append(callback)
                return
        self._call(callback)

    @staticmethod
    def _call(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            logger.exception("on_idle callback failed")


_busy = SessionBusy()


def get_session_busy() -> SessionBusy:
    """The process-wide busy signal."""
    return _busy


__all__ = ["SessionBusy", "get_session_busy"]
