# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""What the Dome page does to a dome and how it describes one, with no screen (EQP-DOME, DOME-010).

* :class:`DomeOps` runs a dome command against the adapter it is given and returns an
  :class:`~galileo.device_ops.Outcome`.
* :func:`describe_status` turns an adapter's status dictionary into what the panel shows.
* :func:`sync_to_mount` and :func:`slave_step` drive a :class:`~galileo.dome.DomeService`.
* :func:`slave_status_text` says what the slaving is doing.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from galileo.device_ops import FAILED, OK, DeviceOps, Outcome

logger = logging.getLogger(__name__)


class DomeOps(DeviceOps):
    def run(self, method: str, *args: Any, action: str) -> Outcome:
        """Run ``adapter.<method>(*args)``; ``failed`` carries the status-bar text."""
        outcome = self._call(f"run dome {action}", lambda a: getattr(a, method)(*args),
                             f"Dome {action} failed — see log.")
        return outcome


@dataclass(frozen=True)
class DomeView:
    connected: bool = False                 # an empty status means not connected
    shutter: str = "—"
    azimuth: str = "—"
    parked: bool = False
    at_park: bool | None = None             # None when the dome does not say
    park_button: str = "Park"
    park_chip: str = "—"


def describe_status(status: dict) -> DomeView:
    azimuth, at_park = status.get("azimuth"), status.get("is_at_park")
    return DomeView(
        connected=bool(status), shutter=status.get("shutter_state") or "—",
        azimuth="—" if azimuth is None else f"{azimuth:.1f}°", parked=bool(at_park), at_park=at_park,
        park_button="Unpark" if at_park else "Park",
        park_chip="—" if at_park is None else ("Parked" if at_park else "Unparked"))


def sync_to_mount(service: Any) -> Outcome:
    """Move the dome to where the mount points, now."""
    try:
        asyncio.run(service.sync_to_mount(force=True))
    except Exception:
        logger.exception("Dome sync to mount failed")
        return Outcome(False, FAILED, "Dome sync failed — see log.")
    return OK


def slave_step(service: Any) -> bool:
    """One slaving step (follow the mount); ``False`` when it failed, which is logged and does not stop the slaving."""
    try:
        asyncio.run(service.track_mount())
    except Exception:
        logger.exception("Dome slaving step failed")
        return False
    return True


def slave_status_text(service: Any) -> str:
    if service is None:
        return "—"
    if not service.slaving_enabled:
        return "Slaving off"
    if not service.ready:
        return "Waiting for a connected mount"
    if service.last_slaved_azimuth is None:
        return "Slaving on — waiting for the mount to track"
    return f"Slaving on — followed mount to {service.last_slaved_azimuth:.1f}°"


__all__ = ["DomeOps", "DomeView", "describe_status", "slave_status_text", "slave_step", "sync_to_mount"]
