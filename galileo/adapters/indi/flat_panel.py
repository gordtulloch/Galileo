# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""INDI adapter(s) for flat panel devices."""

from __future__ import annotations

from galileo.adapters.indi._base import IndiAdapter
from galileo.core.devices import DeviceCategory


class IndiFlatPanelAdapter(IndiAdapter):
    """Flat panel: a dust cap (``CAP_PARK``) and/or light box
    (``FLAT_LIGHT_CONTROL`` / ``FLAT_LIGHT_INTENSITY``)."""

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.FLAT_PANEL, host, port, **kwargs)
        self.cover_state = "Closed"
        self.brightness = 0
        self.is_light_on = False

    async def open_cover(self) -> None:
        self._log_interaction("open_cover")
        self._set_sw("CAP_PARK", {"UNPARK": True, "PARK": False})
        self.cover_state = "Open"

    async def close_cover(self) -> None:
        self._log_interaction("close_cover")
        self._set_sw("CAP_PARK", {"PARK": True, "UNPARK": False})
        self.cover_state = "Closed"

    async def light_on(self) -> None:
        self._log_interaction("light_on")
        self._set_sw("FLAT_LIGHT_CONTROL", {"FLAT_LIGHT_ON": True, "FLAT_LIGHT_OFF": False})
        self.is_light_on = True

    async def light_off(self) -> None:
        self._log_interaction("light_off")
        self._set_sw("FLAT_LIGHT_CONTROL", {"FLAT_LIGHT_ON": False, "FLAT_LIGHT_OFF": True})
        self.is_light_on = False

    async def set_brightness(self, level: int) -> None:
        self._log_interaction("set_brightness", level=level)
        self._set_num("FLAT_LIGHT_INTENSITY", {"FLAT_LIGHT_INTENSITY_VALUE": level})
        self.brightness = level

    async def get_status(self) -> dict:
        """Live status from ``CAP_PARK`` (cover), ``FLAT_LIGHT_CONTROL``
        (light on/off) and ``FLAT_LIGHT_INTENSITY`` (brightness) — each read
        defensively, since a dust-cap-only or light-only panel won't have
        every property."""
        parked = self._sw("CAP_PARK", "PARK")
        if parked is not None:
            self.cover_state = "Closed" if parked else "Open"
        light_on = self._sw("FLAT_LIGHT_CONTROL", "FLAT_LIGHT_ON")
        if light_on is not None:
            self.is_light_on = light_on
        brightness = self._num("FLAT_LIGHT_INTENSITY", "FLAT_LIGHT_INTENSITY_VALUE")
        if brightness is not None:
            self.brightness = brightness
        return {
            **self._driver_info(),
            "cover_state": self.cover_state,
            "is_light_on": self.is_light_on,
            "brightness": self.brightness,
            "cover_supported": self._has("CAP_PARK"),
            "light_supported": self._has("FLAT_LIGHT_CONTROL"),
        }
