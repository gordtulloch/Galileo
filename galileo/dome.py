# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Dome control service (DOME-010 … DOME-030)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Slaving re-slews the dome only when it is further than this from the mount (degrees);
# stops a dome chattering on every status poll while the mount tracks.
DEFAULT_SLAVE_TOLERANCE_DEG = 2.0


def _angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two azimuths, in degrees (wraps at 360)."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


class DomeService:
    """Coordinates dome azimuth, shutter, and park with the mount (DOME-010 … DOME-030).

    One instance per Pier: it holds that Pier's dome and mount ports (never an INDI/Alpaca
    class directly) and, when given an event bus, publishes ``DeviceErrorEvent`` for a
    failed slave/shutter command so the rest of the app learns of it without a direct call.
    """

    def __init__(
        self, dome=None, mount=None, event_bus=None,
        slave_tolerance_deg: float = DEFAULT_SLAVE_TOLERANCE_DEG,
    ) -> None:
        self._dome = dome
        self._mount = mount
        self._event_bus = event_bus
        self._slaving_enabled = False
        # DOME-020 "where enabled": open/close+park with a session run, and track after a flip.
        self._sequence_sync_enabled = False
        self.slave_tolerance_deg = slave_tolerance_deg
        self.last_slaved_azimuth: float | None = None

    # --- wiring -------------------------------------------------------------

    @property
    def dome(self):
        return self._dome

    @property
    def mount(self):
        return self._mount

    def set_dome(self, dome) -> None:
        self._dome = dome

    def set_mount(self, mount) -> None:
        self._mount = mount

    @property
    def ready(self) -> bool:
        """True when both a dome and a mount are attached (slaving is possible)."""
        return self._dome is not None and self._mount is not None

    # --- settings -----------------------------------------------------------

    def set_slaving(self, enabled: bool) -> None:
        """Enable or disable azimuth slaving (DOME-010, DOME-030)."""
        self._slaving_enabled = enabled

    @property
    def slaving_enabled(self) -> bool:
        return self._slaving_enabled

    def set_sequence_sync(self, enabled: bool) -> None:
        """Enable or disable shutter/park synchronisation with session start/end (DOME-020)."""
        self._sequence_sync_enabled = enabled

    @property
    def sequence_sync_enabled(self) -> bool:
        return self._sequence_sync_enabled

    # --- status -------------------------------------------------------------

    async def get_status(self) -> dict:
        """The dome's live status plus this service's slaving flags (empty dict if no dome)."""
        if self._dome is None:
            return {}
        status = dict(await self._dome.get_status() or {})
        status["slaving_enabled"] = self._slaving_enabled
        status["sequence_sync_enabled"] = self._sequence_sync_enabled
        return status

    # --- commands -----------------------------------------------------------

    async def open_shutter(self) -> None:
        if self._dome is not None:
            await self._dome.open_shutter()

    async def close_shutter(self) -> None:
        if self._dome is not None:
            await self._dome.close_shutter()

    async def park(self) -> None:
        if self._dome is not None:
            await self._dome.park()

    async def _mount_azimuth(self) -> float | None:
        mount = self._mount
        if mount is None:
            return None
        get_status = getattr(mount, "get_status", None)
        if get_status is not None:
            try:
                azimuth = (await get_status() or {}).get("azimuth")
            except Exception:
                logger.debug("Could not read the mount's azimuth", exc_info=True)
                azimuth = None
            if isinstance(azimuth, (int, float)):
                return float(azimuth)
        azimuth = getattr(mount, "azimuth", None)
        return float(azimuth) if isinstance(azimuth, (int, float)) else None

    async def sync_to_mount(self, force: bool = False) -> None:
        """Slew dome to match the mount's current azimuth (DOME-010). A no-op while slaving
        is disabled (DOME-030) unless *force* — the explicit Dome Sync block."""
        if not (self._slaving_enabled or force):
            return
        if self._mount is None or self._dome is None:
            return
        mount_az = await self._mount_azimuth()
        if mount_az is None:
            return
        await self._dome.slew_to_azimuth(mount_az)
        self.last_slaved_azimuth = mount_az

    async def track_mount(self) -> bool:
        """One slaving step: follow the mount while it is tracking and not parked, re-slewing
        only when the dome is more than the tolerance away (DOME-010). Returns True if the
        dome was commanded. Disabled slaving (DOME-030) or a missing device does nothing."""
        if not self._slaving_enabled or not self.ready:
            return False
        try:
            status = await self._mount.get_status() or {}
        except Exception:
            logger.debug("Could not read the mount status for slaving", exc_info=True)
            return False
        if status.get("at_park") or status.get("tracking") is False or status.get("slewing"):
            return False  # parked / not tracking / mid-slew: nothing meaningful to follow yet
        azimuth = status.get("azimuth")
        if not isinstance(azimuth, (int, float)):
            return False
        azimuth = float(azimuth)
        if (self.last_slaved_azimuth is not None
                and _angle_diff(azimuth, self.last_slaved_azimuth) <= self.slave_tolerance_deg):
            return False
        try:
            await self._dome.slew_to_azimuth(azimuth)
        except Exception as exc:
            logger.exception("Dome slaving failed")
            self._publish_error(f"dome slaving failed: {exc}")
            return False
        self.last_slaved_azimuth = azimuth
        return True

    def _publish_error(self, message: str) -> None:
        if self._event_bus is None:
            return
        try:
            from galileo.bus import DeviceErrorEvent
            self._event_bus.publish(DeviceErrorEvent(source="dome", error=message))
        except Exception:
            logger.debug("Could not publish the dome error event", exc_info=True)

    # --- session / flip hooks ------------------------------------------------

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
        """Keep the shutter open during a meridian flip (DOME-020); once the mount has
        settled, re-slave the dome to its new azimuth when slaving is on."""
        self.last_slaved_azimuth = None  # force a re-slew after the flip
        if self._slaving_enabled and self.ready:
            await self.track_mount()


__all__ = ["DomeService", "DEFAULT_SLAVE_TOLERANCE_DEG"]
