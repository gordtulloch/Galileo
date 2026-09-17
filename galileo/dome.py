"""Dome control service (DOME-010 … DOME-030)."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class DomeService:
    """Coordinates dome azimuth, shutter, and park with the mount (DOME-010 … DOME-030)."""

    def __init__(self, dome=None, mount=None, event_bus=None) -> None:
        self._dome = dome
        self._mount = mount
        self._event_bus = event_bus
        self._slaving_enabled = False

    def set_slaving(self, enabled: bool) -> None:
        """Enable or disable azimuth slaving (DOME-010, DOME-030)."""
        self._slaving_enabled = enabled

    @property
    def slaving_enabled(self) -> bool:
        return self._slaving_enabled

    async def sync_to_mount(self) -> None:
        """Slew dome to match the mount's current azimuth (DOME-010)."""
        if not self._slaving_enabled:
            return
        if self._mount is None or self._dome is None:
            return
        mount_az = getattr(self._mount, "azimuth", 0.0)
        await self._dome.slew_to_azimuth(mount_az)

    async def on_sequence_start(self) -> None:
        """Open the shutter when a sequence starts (DOME-020)."""
        if self._dome:
            await self._dome.open_shutter()

    async def on_sequence_end(self) -> None:
        """Close the shutter and park the dome when a sequence ends (DOME-020)."""
        if self._dome:
            await self._dome.close_shutter()
            await self._dome.park()

    async def on_meridian_flip(self) -> None:
        """Keep the shutter open during a meridian flip (DOME-020)."""
        pass  # shutter remains open; dome slaving will track as needed
