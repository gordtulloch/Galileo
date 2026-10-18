# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Alpaca adapter(s): dome."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from galileo.adapters.alpaca._base import AlpacaAdapter
from galileo.core.devices import DeviceCategory

logger = logging.getLogger(__name__)


class AlpacaDomeAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.DOME, host, port, **kwargs)
        self.azimuth = 0.0
        self.shutter_state = "Closed"
        self.is_at_park = True

    async def slew_to_azimuth(self, azimuth: float) -> None:
        await self._put("slewtoazimuth", Azimuth=azimuth)
        self.azimuth = azimuth

    async def open_shutter(self) -> None:
        await self._put("openshutter")
        self.shutter_state = "Open"

    async def close_shutter(self) -> None:
        await self._put("closeshutter")
        self.shutter_state = "Closed"

    async def park(self) -> None:
        await self._put("park")
        self.is_at_park = True

    async def unpark(self) -> None:
        # ASCOM IDome has no Unpark: a dome leaves park on its next slew, so
        # there is nothing to send — just clear the cached flag until
        # get_status() reads AtPark back.
        self.is_at_park = False

    async def abort_slew(self) -> None:
        await self._put("abortslew")

    _SHUTTER_STATE: ClassVar = {0: "Open", 1: "Closed", 2: "Opening", 3: "Closing", 4: "Error"}

    async def get_status(self) -> dict:
        """Live status: ``ShutterStatus``, ``Azimuth`` and ``AtPark``, each
        read defensively (a dome may not implement all three)."""
        status: dict[str, Any] = dict(await self.get_driver_info())
        try:
            raw_shutter = await self._get("shutterstatus")
            if raw_shutter is not None:
                self.shutter_state = self._SHUTTER_STATE.get(int(raw_shutter), "Unknown")
        except Exception:
            logger.exception("Could not read ShutterStatus from %s", self.base_url)
        try:
            raw_az = await self._get("azimuth")
            if raw_az is not None:
                self.azimuth = float(raw_az)
        except Exception:
            logger.exception("Could not read Azimuth from %s", self.base_url)
        try:
            raw_park = await self._get("atpark")
            if raw_park is not None:
                self.is_at_park = bool(raw_park)
        except Exception:
            logger.exception("Could not read AtPark from %s", self.base_url)
        status.update(shutter_state=self.shutter_state, azimuth=self.azimuth, is_at_park=self.is_at_park)
        return status
