# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""A token-bucket rate limiter per client, shared by the Connect Link gateway (LINK-230) and sky
streaming (SKYSTR-070)."""

from __future__ import annotations

import threading
from collections.abc import Callable


class RateLimiter:
    """``capacity`` requests in a burst per client, refilled at ``per_s`` a second."""

    def __init__(self, clock: Callable[[], float], capacity: int = 30, per_s: float = 10.0) -> None:
        self._clock, self._cap, self._rate = clock, float(capacity), per_s
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, client: str) -> bool:
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get(client, (self._cap, now))
            tokens = min(self._cap, tokens + (now - last) * self._rate)
            if tokens < 1:
                self._buckets[client] = (tokens, now)
                return False
            self._buckets[client] = (tokens - 1, now)
            if len(self._buckets) > 4096:                       # forget idle clients
                for k in [k for k, (_, t) in self._buckets.items() if now - t > 600]:
                    del self._buckets[k]
            return True


__all__ = ["RateLimiter"]
