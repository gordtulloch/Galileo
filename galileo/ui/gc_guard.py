# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Keep the cyclic garbage collector from running Qt destructors on a worker thread.

PySide6 deadlocks when the collector, running on a *non-GUI* thread, destroys a ``QObject`` that is part of
a reference cycle: the destructor holds a Qt-internal lock while it waits for the GIL, and the GUI thread
holds the GIL while it waits for that same lock (typically in a widget constructor). Worker threads that
allocate heavily (parsing a large catalog, say) are exactly what triggers a collection, so they pause the
collector for the duration of the load. Reference counting still frees everything that is not in a cycle,
and the collector resumes as soon as the last paused worker finishes.
"""

from __future__ import annotations

import contextlib
import gc
import threading

_lock = threading.Lock()
_paused = 0
_was_enabled = False


@contextlib.contextmanager
def gc_paused():
    """Disable the cyclic collector while a worker thread does allocation-heavy work."""
    global _paused, _was_enabled
    with _lock:
        if _paused == 0:
            _was_enabled = gc.isenabled()
            gc.disable()
        _paused += 1
    try:
        yield
    finally:
        with _lock:
            _paused -= 1
            if _paused == 0 and _was_enabled:
                gc.enable()
