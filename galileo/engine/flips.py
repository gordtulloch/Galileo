# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The meridian flip on the engine (CSURF-170): live state and a flip on request.

State is read, never cached: the flip settings are the Pier's saved Mount-page settings (``MountLimits``, read from
the database each time, so a change made on the desktop is seen), and the hour angle and pier side come from the
mount. What the engine does remember is whether a flip is running and how the last one ended, per Pier.

A flip is the one the Sessions screen's Meridian Flip block does: slew the mount to where it already points so it
crosses the meridian, resume tracking, and then check that it really did change side of the pier, since a mount that
stays put has not flipped. It is refused while a session runs (that session's own block does the flip and a second
slew would fight it), while the mount is parked or not tracking, and from the east side of the pier. The engine does
not flip on its own: ``due`` is reported and a person or client decides. Re-slaving a dome and restarting guiding
follow once the engine has those services.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from galileo.control_surface.flips import FlipRefused
from galileo.mount_limits import flip_phase, minutes_to_flip, pier_side_text

logger = logging.getLogger(__name__)


class EngineFlips:
    """``FlipAccess`` (``galileo.control_surface.flips``) over the device service and session runner."""

    def __init__(self, devices: Any, runner: Any) -> None:
        self._devices, self._runner = devices, runner
        self._flipping: set[str] = set()
        self._last: dict[str, dict[str, Any]] = {}

    def limits(self, pier: str) -> Any:
        from galileo.observatory import get_device_config, mount_limits_from_config
        record = self._devices.pier_record(pier)
        return mount_limits_from_config(get_device_config(record, "mount") if record is not None else None)

    def why_not(self, pier: str) -> str | None:
        mount = self._devices.controller(pier, "mount")
        if mount is None:
            return "this Pier has no mount"
        if not getattr(mount, "is_connected", True):
            return "the mount is not connected"
        if pier in self._flipping:
            return "a flip is already under way on this Pier"
        if self._runner.is_running(pier):
            return "a session is running on this Pier; its Meridian Flip block does the flip"
        return None

    async def state(self, pier: str) -> dict[str, Any]:
        out: dict[str, Any] = {"flipping": pier in self._flipping, "last": self._last.get(pier),
                               "why_not": self.why_not(pier) or ""}
        mount = self._devices.controller(pier, "mount")
        if mount is None or not getattr(mount, "is_connected", True):
            return {**out, "phase": "unavailable"}
        limits = self.limits(pier)
        status = await mount.get_status() or {}
        lst, ra = status.get("sidereal_time"), status.get("right_ascension")
        from galileo.mount_limits import hour_angle_hours
        ha = hour_angle_hours(lst, ra) if lst is not None and ra is not None else None
        side = status.get("side_of_pier")
        phase = flip_phase(limits, ha, side, tracking=bool(status.get("tracking")),
                           slewing=bool(status.get("slewing")), flipping=pier in self._flipping)
        minutes = minutes_to_flip(limits, ha, side)
        return {**out, "phase": phase, "enabled": bool(limits.flip_enabled), "limit_deg": limits.flip_ha_deg,
                "hour_angle_hours": ha, "pier_side": side, "pointing": pier_side_text(side),
                "minutes_to_flip": None if minutes is None else round(minutes, 1)}

    async def flip(self, pier: str, progress: Any) -> dict[str, Any]:
        reason = self.why_not(pier)
        if reason:
            raise FlipRefused(reason)
        mount = self._devices.controller(pier, "mount")
        status = await mount.get_status() or {}
        if not status.get("tracking") or status.get("slewing"):          # a parked mount does not track
            raise FlipRefused("the mount must be tracking, and not slewing, to flip")
        if status.get("side_of_pier") != "West":
            raise FlipRefused(f"the mount is on the {status.get('side_of_pier') or 'unknown'} side of the pier, "
                              "so there is no flip to make")
        ra_hours, dec = status.get("right_ascension"), status.get("declination")
        if ra_hours is None or dec is None:
            raise FlipRefused("the mount did not report where it points")
        self._flipping.add(pier)
        began = time.time()
        try:
            progress("flipping across the meridian")
            from galileo.meridianflip import MeridianFlipConfig, MeridianFlipService
            from galileo.tracking import resume_tracking
            service = MeridianFlipService(
                mount=mount, config=MeridianFlipConfig(post_flip_recenter=False, post_flip_restart_guiding=False))
            await service.execute_flip(target_ra=ra_hours * 15.0, target_dec=dec)
            if await resume_tracking(mount, None) is None:
                raise FlipRefused("the mount was still slewing after the wait, so tracking was left alone")
            after = await mount.get_status() or {}
            side = after.get("side_of_pier")
            if side == "West":
                raise FlipRefused("the mount stayed on the west side of the pier, so it did not flip")
            self._last[pier] = {"outcome": "done", "at": time.time(), "seconds": round(time.time() - began, 1),
                                "pier_side": side, "message": ""}
            return dict(self._last[pier])
        except Exception as exc:
            self._last[pier] = {"outcome": "failed", "at": time.time(), "seconds": round(time.time() - began, 1),
                                "pier_side": None, "message": str(exc) or type(exc).__name__}
            if not isinstance(exc, FlipRefused):
                logger.exception("Pier %s: the meridian flip failed", pier)
            raise
        finally:
            self._flipping.discard(pier)


__all__ = ["EngineFlips"]
