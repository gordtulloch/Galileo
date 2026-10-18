# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Alpaca adapter(s): rotator."""

from __future__ import annotations

import logging
from typing import Any

from galileo.adapters.alpaca._base import AlpacaAdapter
from galileo.core.devices import DeviceCategory
from galileo.exceptions import DevicePropertyError

logger = logging.getLogger(__name__)


class AlpacaRotatorAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.ROTATOR, host, port, **kwargs)
        self.mechanical_angle = 0.0
        self.sky_angle = 0.0

    async def move_to_angle(self, angle: float) -> None:
        await self._put("moveabsolute", Position=angle)
        self.mechanical_angle = angle

    async def halt(self) -> None:
        await self._put("halt")

    async def set_reverse(self, reverse: bool) -> None:
        await self._put("reverse", Reverse=reverse)

    async def sync_position(self, angle: float) -> None:
        """``IRotatorV3.Sync``: declare the current sky position to be *angle*
        (``sync_position(0)`` = "set current position as zero")."""
        await self._put("sync", Position=angle)
        self.sky_angle = angle

    async def set_backlash(self, steps: float) -> None:
        raise DevicePropertyError("ASCOM Alpaca's IRotatorV3 interface has no backlash setting.")

    async def get_status(self) -> dict:
        """Live status from the standard ASCOM ``IRotatorV3`` properties:
        ``Position`` (sky, as synced) and ``MechanicalPosition`` (raw), plus
        ``IsMoving`` and ``Reverse``. Each is read defensively — a driver
        that doesn't implement one leaves that field ``None``."""
        status: dict[str, Any] = {}
        reads: list[tuple[str, str, Any]] = [
            ("name", "name", str), ("description", "description", str),
            ("driver_info", "driverinfo", str), ("driver_version", "driverversion", str),
            ("position", "position", float), ("mechanical_position", "mechanicalposition", float),
            ("is_moving", "ismoving", bool), ("reverse", "reverse", bool),
        ]
        for key, attribute, caster in reads:
            try:
                value = await self._get(attribute)
                status[key] = caster(value) if value is not None else None
            except Exception:
                logger.exception("Could not read %s from %s", attribute, self.base_url)
                status[key] = None
        status.update(backlash=None, backlash_supported=False, can_sync=True, max_angle=360.0)
        if status["position"] is not None:
            self.sky_angle = status["position"]
        if status["mechanical_position"] is not None:
            self.mechanical_angle = status["mechanical_position"]
        return status
