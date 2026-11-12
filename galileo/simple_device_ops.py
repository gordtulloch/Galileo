# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""What the Filter Wheel, Flat Panel and Aux pages do to their devices and how they describe them, with no screen
(EQP-FW, EQP-FLAT, EQP-AUX).

These three pages are small enough to share a module. Each has an ``*Ops`` class (commands against whichever
adapter it is given, reporting an :class:`~galileo.device_ops.Outcome`) and a ``describe_status`` that turns an
adapter's status dictionary into what the page shows.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from galileo.device_ops import FAILED, NOT_CONNECTED, OK, DeviceOps, Outcome

logger = logging.getLogger(__name__)


# -- filter wheel --------------------------------------------------------------------------------------------------
class FilterWheelOps(DeviceOps):
    def move_to(self, index: int) -> Outcome:
        return self._call("change filter", lambda a: a.move_to(index), "Filter change failed — see log.",
                          f" (index={index})")


@dataclass(frozen=True)
class FilterWheelView:
    name: str = "—"
    description: str = "—"
    driver_info: str = "—"
    driver_version: str = "—"
    filter_names: list[str] = field(default_factory=list)
    position: int | None = None              # None when the wheel does not say or it is out of range
    current_filter: str | None = None


def describe_filter_wheel(status: dict) -> FilterWheelView:
    names = list(status.get("filter_names") or [])
    position = status.get("position")
    in_range = position is not None and 0 <= position < len(names)
    return FilterWheelView(
        name=status.get("name") or "—", description=status.get("description") or "—",
        driver_info=status.get("driver_info") or "—", driver_version=status.get("driver_version") or "—",
        filter_names=names, position=position if in_range else None,
        current_filter=names[position] if in_range else None)


# -- flat panel ------------------------------------------------------------------------------------------------------
class FlatPanelOps(DeviceOps):
    def run(self, method: str, *args: Any, action: str) -> Outcome:
        return self._call(f"run flat panel {action}", lambda a: getattr(a, method)(*args),
                          f"Flat panel {action} failed — see log.")


@dataclass(frozen=True)
class FlatPanelView:
    connected: bool = False
    cover: str = "—"
    light: str = "—"
    brightness: int | None = None


def describe_flat_panel(status: dict) -> FlatPanelView:
    cover_state, light_on, brightness = status.get("cover_state"), status.get("is_light_on"), status.get("brightness")
    return FlatPanelView(
        connected=bool(status),
        cover="Parked" if cover_state == "Closed" else "Unparked" if cover_state == "Open" else "—",
        light="On" if light_on else "Off" if light_on is not None else "—",
        brightness=None if brightness is None else int(brightness))


# -- aux -------------------------------------------------------------------------------------------------------------
class AuxOps(DeviceOps):
    def write_property(self, name: str, values: dict) -> Outcome:
        adapter = self._get()
        if adapter is None:
            return Outcome(False, NOT_CONNECTED)
        from galileo.core.devices import AuxController
        try:
            asyncio.run(AuxController(adapter).write_property(name, values))
        except Exception:
            logger.exception("Aux: writing %s failed", name)
            return Outcome(False, FAILED, f"Could not set {name} — see log.")
        logger.info("Aux: set %s = %s", name, values)
        return OK

    def read_groups(self) -> list | None:
        """The device's property groups, or ``None`` when nothing is connected or they cannot be read."""
        adapter = self._get()
        if adapter is None:
            return None
        from galileo.core.devices import AuxController
        try:
            return asyncio.run(AuxController(adapter).get_property_groups())
        except Exception:
            logger.exception("Aux: could not refresh control panel")
            return None


class AuxServerOps(DeviceOps):
    """Commands against a server-level INDI panel (:class:`galileo.core.devices.AuxServerPanel`, EQP-AUX-020)."""

    def write_property(self, device: str, name: str, values: dict) -> Outcome:
        panel = self._get()
        if panel is None:
            return Outcome(False, NOT_CONNECTED)
        try:
            asyncio.run(panel.write_property(device, name, values))
        except Exception:
            logger.exception("Aux: writing %s.%s failed", device, name)
            return Outcome(False, FAILED, f"Could not set {device} {name} — see log.")
        logger.info("Aux: set %s.%s = %s", device, name, values)
        return OK

    def read_devices(self) -> dict[str, list] | None:
        """Every device's property groups, or ``None`` when not connected or unreadable."""
        panel = self._get()
        if panel is None:
            return None
        try:
            return asyncio.run(panel.get_all_property_groups())
        except Exception:
            logger.exception("Aux: could not refresh the INDI server panel")
            return None


def aux_needs_rebuild(shown_names: set[str], groups: list, have_tabs: bool) -> bool:
    """Whether the property tabs must be rebuilt (the device's set of properties changed) rather than refreshed."""
    return not have_tabs or shown_names != {p.name for g in groups for p in g.properties}


__all__ = ["AuxOps", "AuxServerOps", "FilterWheelOps", "FilterWheelView", "FlatPanelOps", "FlatPanelView", "aux_needs_rebuild",
           "describe_filter_wheel", "describe_flat_panel"]
