# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""INDI adapter(s) for weather devices."""

from __future__ import annotations

from galileo.adapters import indi_client as ic
from galileo.adapters.indi._base import IndiAdapter
from galileo.core.devices import DeviceCategory


class IndiWeatherAdapter(IndiAdapter):
    """Weather station via ``INDI::Weather`` (``WEATHER_PARAMETERS`` +
    ``WEATHER_STATUS``). INDI has no standard cloud-cover parameter."""

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.WEATHER_STATION, host, port, **kwargs)
        self.cloud_cover = 0.0
        self.wind_speed = 0.0
        self.wind_gust = 0.0
        self.humidity = 50.0
        self.temperature = 15.0
        self.dew_point = 0.0
        self.pressure = 1013.0
        self.rain_rate = 0.0
        self.rain = 0.0
        self.is_safe = True

    async def poll(self) -> None:
        # Element names cover both reference drivers EQP-WX-010/EQP-WX-020
        # target: indi-argentweather's ADS-WS1 (temperature, humidity,
        # dewpoint, barometer, wind_speed/gust, rain_hour) and indi-hydreon's
        # RG-11 (WEATHER_RAIN, a 0/1 "raining now" flag, distinct from
        # WEATHER_RAIN_HOUR's running total) — a driver missing an element
        # simply leaves that attribute at its last value (``_num`` returns
        # ``None`` for one it doesn't define).
        for attr, element in (
            ("temperature", "WEATHER_TEMPERATURE"), ("humidity", "WEATHER_HUMIDITY"),
            ("dew_point", "WEATHER_DEWPOINT"), ("pressure", "WEATHER_BAROMETER"),
            ("wind_speed", "WEATHER_WIND_SPEED"), ("wind_gust", "WEATHER_WIND_GUST"),
            ("rain_rate", "WEATHER_RAIN_HOUR"), ("rain", "WEATHER_RAIN"),
        ):
            value = self._num("WEATHER_PARAMETERS", element)
            if value is not None:
                setattr(self, attr, value)
        state = self._state("WEATHER_STATUS")
        if state is not None:
            self.is_safe = state != ic.ALERT
