# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Connection health monitor for device backends (ARCH-040)."""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from galileo.bus import EventBus
    from galileo.core.devices import DeviceBackend

logger = logging.getLogger(__name__)


class ConnectionMonitor:
    """Polls a single device backend and publishes a disconnect/error event
    when it notices the connection has dropped (ARCH-040).

    Used by the equipment layer to satisfy the "bounded time" requirement:
    ``poll_interval_s`` controls how quickly a dropout is detected.
    """

    def __init__(
        self,
        backend: "DeviceBackend",
        event_bus: "EventBus | None" = None,
        poll_interval_s: float = 5.0,
        timeout_s: float = 30.0,
    ) -> None:
        self._backend = backend
        self._event_bus = event_bus
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def check_once(self) -> None:
        """Perform a single connectivity check and publish events as needed."""
        from galileo.bus import DeviceDisconnectedEvent, DeviceErrorEvent

        name = getattr(self._backend, "name", "unknown")
        getter = self._backend.get_properties
        try:
            async with asyncio.timeout(self.timeout_s):
                if asyncio.iscoroutinefunction(getter):
                    await getter()
                else:
                    await asyncio.to_thread(getter)
        except asyncio.TimeoutError:
            logger.warning("Device %r timed out during health check", name)
            if self._event_bus:
                self._event_bus.publish(
                    DeviceErrorEvent(
                        source=name,
                        timestamp=datetime.datetime.utcnow().isoformat(),
                        error="timeout",
                    )
                )
            return
        except Exception as exc:
            logger.warning("Device %r raised %r during health check", name, exc)
            if self._event_bus:
                self._event_bus.publish(
                    DeviceErrorEvent(
                        source=name,
                        timestamp=datetime.datetime.utcnow().isoformat(),
                        error=str(exc),
                    )
                )
            return

        if not self._backend.is_connected:
            if self._event_bus:
                self._event_bus.publish(
                    DeviceDisconnectedEvent(
                        source=name,
                        timestamp=datetime.datetime.utcnow().isoformat(),
                    )
                )

    async def _run_loop(self) -> None:
        while self._running:
            await self.check_once()
            await asyncio.sleep(self.poll_interval_s)

    def start(self) -> None:
        """Start the background polling loop."""
        self._running = True
        self._task = asyncio.ensure_future(self._run_loop())

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
