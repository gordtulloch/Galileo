# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Run a blocking catalog query off the UI thread (concurrency model, SDD §2.3).

The Library screens read the whole catalog; on a big repository that takes long enough to freeze the
window. ``run_in_worker`` runs the query on the shared Qt thread pool and delivers the result back on
the UI thread. Widgets keep a generation counter so a result that has been superseded by a newer
request (the user changed the sort order while a load was running) is dropped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

logger = logging.getLogger(__name__)


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _Signals) -> None:
        super().__init__()
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:        # reported on the UI thread, never lost in the pool
            logger.exception("Library background query failed")
            self._signals.failed.emit(exc)
        else:
            self._signals.done.emit(result)


def run_in_worker(owner: QObject, fn: Callable[[], Any],
                  on_done: Callable[[Any], None], on_error: Callable[[Exception], None] | None = None) -> None:
    """Call *fn* on a pool thread; *on_done(result)* / *on_error(exc)* then run on the UI thread.

    *owner* parents the signal object, so the callbacks do not fire once the owning widget is
    destroyed."""
    signals = _Signals(owner)
    signals.done.connect(on_done)
    if on_error is not None:
        signals.failed.connect(on_error)
    signals.done.connect(signals.deleteLater)
    signals.failed.connect(signals.deleteLater)
    QThreadPool.globalInstance().start(_Job(fn, signals))
