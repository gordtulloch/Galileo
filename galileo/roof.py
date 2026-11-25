# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The interlock every automatic roof close goes through (SAFE-110), and the safety state a session thread may read.

A roof or shutter can hit a telescope that is not parked, so before closing one automatically every mount under it
is parked and **confirmed** parked. A mount that cannot be confirmed (not connected, no park status, park failed or
timed out) means the roof is not closed.

No Qt here: the executor and the watchdog use this from their own threads.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

PARK_TIMEOUT_S = 180.0   # a park is a slew; a slow mount crossing the whole sky needs minutes
PARK_POLL_S = 1.0


async def _at_park(mount: Any) -> bool:
    """True only when the mount positively says it is parked; an unreadable or absent status is not "parked"."""
    try:
        status = mount.get_status()
        if inspect.isawaitable(status):
            status = await status
        return status.get("at_park") is True
    except Exception:
        logger.debug("Could not read whether %r is parked", mount, exc_info=True)
        return False


async def park_and_confirm(mount: Any, timeout_s: float | None = None) -> bool:
    """Park *mount* (unless it already is) and wait until it reports parked. ``False`` if it never does."""
    if mount is None or getattr(mount, "is_connected", True) is False:
        return False
    timeout_s = PARK_TIMEOUT_S if timeout_s is None else timeout_s

    async def park_and_wait() -> None:
        if await _at_park(mount):
            return
        try:
            await mount.park()
        except Exception:
            logger.exception("Park failed")      # still look: it may be parked, or get there
        while not await _at_park(mount):      # noqa: ASYNC110 - polling a device; there is no event to await
            await asyncio.sleep(PARK_POLL_S)

    try:
        await asyncio.wait_for(park_and_wait(), timeout_s)
    except TimeoutError:
        logger.warning("A mount was not confirmed parked within %g s", timeout_s)
        return False
    return True


async def park_roof_mounts(mounts: Iterable[tuple[str, Any]], timeout_s: float | None = None) -> list[str]:
    """Park every ``(pier name, mount)`` under a roof at once. Returns the names of the Piers whose mount is **not**
    confirmed parked; an empty list means the roof may be closed. A ``None`` mount is configured but not connected."""
    mounts = list(mounts)
    parked = await asyncio.gather(*(park_and_confirm(mount, timeout_s) for _name, mount in mounts))
    return [name for (name, _mount), ok in zip(mounts, parked, strict=True) if not ok]


def roof_left_open_message(unconfirmed: list[str]) -> str:
    return (f"The roof was NOT closed: the mount of {', '.join(unconfirmed) or 'a Pier'} could not be confirmed "
            "parked. Close it yourself once the telescope is clear.")


class SafetySnapshot:
    """The last safety verdict and the mounts under the roof, written by the thread that owns the devices (the
    desktop's UI thread) and read by session and watchdog threads, which must not touch widgets."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._safe = True
        self._mounts: list[tuple[str, Any]] = []

    def set_safe(self, safe: bool) -> None:
        with self._lock:
            self._safe = bool(safe)

    def set_mounts(self, mounts: Iterable[tuple[str, Any]]) -> None:
        with self._lock:
            self._mounts = list(mounts)

    def is_safe(self) -> bool:
        with self._lock:
            return self._safe

    def mounts(self) -> list[tuple[str, Any]]:
        with self._lock:
            return list(self._mounts)


__all__ = ["PARK_POLL_S", "PARK_TIMEOUT_S", "SafetySnapshot", "park_and_confirm", "park_roof_mounts",
           "roof_left_open_message"]
