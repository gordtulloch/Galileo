# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""INDI adapter(s) for dome devices."""

from __future__ import annotations

from galileo.adapters.indi._base import IndiAdapter
from galileo.core.devices import DeviceCategory


class IndiDomeAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.DOME, host, port, **kwargs)
        self.azimuth = 0.0
        self.shutter_state = "Closed"
        self.is_at_park = True

    async def slew_to_azimuth(self, azimuth: float) -> None:
        self._log_interaction("slew_to_azimuth", azimuth=azimuth)
        self._set_num("ABS_DOME_POSITION", {"DOME_ABSOLUTE_POSITION": azimuth})
        self.azimuth = azimuth

    async def open_shutter(self) -> None:
        self._log_interaction("open_shutter")
        self._set_sw("DOME_SHUTTER", {"SHUTTER_OPEN": True, "SHUTTER_CLOSE": False})
        self.shutter_state = "Open"

    async def close_shutter(self) -> None:
        self._log_interaction("close_shutter")
        self._set_sw("DOME_SHUTTER", {"SHUTTER_OPEN": False, "SHUTTER_CLOSE": True})
        self.shutter_state = "Closed"

    async def park(self) -> None:
        self._log_interaction("park")
        self._set_sw("DOME_PARK", {"PARK": True, "UNPARK": False})
        self.is_at_park = True

    async def unpark(self) -> None:
        self._log_interaction("unpark")
        self._set_sw("DOME_PARK", {"PARK": False, "UNPARK": True})
        self.is_at_park = False

    async def abort_slew(self) -> None:
        self._log_interaction("abort_slew")
        self._set_sw("DOME_ABORT_MOTION", {"ABORT": True})

    async def get_status(self) -> dict:
        """Live status from ``DOME_SHUTTER``, ``ABS_DOME_POSITION`` and
        ``DOME_PARK`` — each read defensively, since a shutter-less or
        non-absolute-positioning dome won't define every property."""
        shutter_open = self._sw("DOME_SHUTTER", "SHUTTER_OPEN")
        if shutter_open is not None:
            self.shutter_state = "Open" if shutter_open else "Closed"
        azimuth = self._num("ABS_DOME_POSITION", "DOME_ABSOLUTE_POSITION")
        if azimuth is not None:
            self.azimuth = azimuth
        parked = self._sw("DOME_PARK", "PARK")
        if parked is not None:
            self.is_at_park = parked
        return {
            **self._driver_info(),
            "shutter_state": self.shutter_state,
            "azimuth": self.azimuth,
            "is_at_park": self.is_at_park,
        }
