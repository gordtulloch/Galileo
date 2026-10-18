# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Alpaca adapter(s): safety-monitor, weather, guider and flat-panel."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from galileo.adapters.alpaca._base import AlpacaAdapter
from galileo.core.devices import DeviceCategory

logger = logging.getLogger(__name__)


class AlpacaSafetyMonitorAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.SAFETY_MONITOR, host, port, **kwargs)
        self.is_safe = True
        self.explanation = ""
        self.tier = 1

    async def poll(self) -> None:
        value = await self._get("issafe")
        self.is_safe = True if value is None else bool(value)


class AlpacaWeatherAdapter(AlpacaAdapter):
    """Weather station via ASCOM ``ObservingConditions``. Any property the
    driver doesn't implement comes back as the ASCOM "not implemented" error,
    which ``_get`` already turns into ``None`` (EQP-WX-010/EQP-WX-020) —
    this attribute is then simply left at its last value."""

    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.WEATHER_STATION, host, port, **kwargs)
        self.cloud_cover = 0.0
        self.wind_speed = 0.0
        self.wind_gust = 0.0
        self.humidity = 50.0
        self.temperature = 15.0
        self.dew_point = 0.0
        self.pressure = 1013.0
        self.rain_rate = 0.0
        self.is_safe = True

    async def poll(self) -> None:
        for attr, prop in (
            ("cloud_cover", "cloudcover"), ("humidity", "humidity"),
            ("temperature", "temperature"), ("dew_point", "dewpoint"),
            ("pressure", "pressure"), ("wind_speed", "windspeed"),
            ("wind_gust", "windgust"), ("rain_rate", "rainrate"),
        ):
            value = await self._get(prop)
            if value is not None:
                setattr(self, attr, float(value))


class AlpacaGuiderAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.GUIDER, host, port, **kwargs)


class AlpacaFlatPanelAdapter(AlpacaAdapter):
    # ASCOM ICoverCalibratorV1's CoverState/CalibratorState are integer enums
    # on the wire — normalized to strings here, same convention as
    # AlpacaMountAdapter's SideOfPier/EquatorialSystem.
    _COVER_STATE: ClassVar = {0: "NotPresent", 1: "Closed", 2: "Moving", 3: "Open", 4: "Unknown"}
    _CALIBRATOR_STATE: ClassVar = {0: "NotPresent", 1: "Off", 2: "NotReady", 3: "Ready", 4: "Unknown", 5: "Error"}

    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.FLAT_PANEL, host, port, **kwargs)
        self.cover_state = "Closed"
        self.brightness = 0
        self.is_light_on = False

    async def open_cover(self) -> None:
        await self._put("opencover")
        self.cover_state = "Open"

    async def close_cover(self) -> None:
        await self._put("closecover")
        self.cover_state = "Closed"

    async def light_on(self) -> None:
        """``ICoverCalibratorV1.CalibratorOn`` at the panel's current brightness."""
        await self._put("calibratoron", Brightness=self.brightness)
        self.is_light_on = True

    async def light_off(self) -> None:
        await self._put("calibratoroff")
        self.is_light_on = False

    async def set_brightness(self, level: int) -> None:
        await self._put("brightness", Brightness=level)
        self.brightness = level

    async def get_status(self) -> dict:
        """Live status: ``CoverState``/``CalibratorState`` (both read
        defensively — a cover-only or calibrator-only panel lacks one side)
        plus ``Brightness``."""
        status: dict[str, Any] = dict(await self.get_driver_info())
        try:
            raw_cover = await self._get("coverstate")
            if raw_cover is not None:
                self.cover_state = self._COVER_STATE.get(int(raw_cover), "Unknown")
        except Exception:
            logger.exception("Could not read CoverState from %s", self.base_url)
        try:
            raw_cal = await self._get("calibratorstate")
            if raw_cal is not None:
                self.is_light_on = self._CALIBRATOR_STATE.get(int(raw_cal)) in ("Ready", "NotReady")
        except Exception:
            logger.exception("Could not read CalibratorState from %s", self.base_url)
        try:
            raw_brightness = await self._get("brightness")
            if raw_brightness is not None:
                self.brightness = int(raw_brightness)
        except Exception:
            logger.exception("Could not read Brightness from %s", self.base_url)
        status.update(cover_state=self.cover_state, is_light_on=self.is_light_on, brightness=self.brightness)
        return status
