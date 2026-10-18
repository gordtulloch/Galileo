# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Alpaca adapter(s): filter-wheel."""

from __future__ import annotations

import logging
from typing import Any

from galileo.adapters.alpaca._base import AlpacaAdapter
from galileo.core.devices import DeviceCategory

logger = logging.getLogger(__name__)


class AlpacaFWAdapter(AlpacaAdapter):
    """Filter wheel via the ASCOM Alpaca ``IFilterWheelV2`` interface."""

    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.FILTER_WHEEL, host, port, **kwargs)
        self.filter_names: list[str] = []
        self.position = 0

    async def connect(self) -> None:
        await super().connect()
        try:
            names = await self._get("names")
            if names:
                self.filter_names = [str(n) for n in names]
        except Exception:
            logger.exception("Could not read Names from %s", self.base_url)
        try:
            position = await self._get("position")
            if position is not None:
                self.position = int(position)
        except Exception:
            logger.exception("Could not read initial Position from %s", self.base_url)

    async def move_to(self, index: int) -> None:
        await self._put("position", Position=index)
        self.position = index

    async def get_status(self) -> dict:
        """Live-query this filter wheel's status from the standard ASCOM
        ``IFilterWheelV2`` properties — the Filter Wheel page's status
        display (Name/Description/Driver info/version) and current
        selection (``Names``/``Position``, refreshing this adapter's own
        cached ``filter_names``/``position`` in case they changed on the
        device since ``connect()``). Every property is read defensively
        since not every driver implements every optional one."""
        status: dict[str, Any] = {}
        reads: list[tuple[str, str, Any]] = [
            ("name", "name", str),
            ("description", "description", str),
            ("driver_info", "driverinfo", str),
            ("driver_version", "driverversion", str),
        ]
        for key, attribute, caster in reads:
            try:
                value = await self._get(attribute)
                status[key] = caster(value) if value is not None else None
            except Exception:
                logger.exception("Could not read %s from %s", attribute, self.base_url)
                status[key] = None
        try:
            names = await self._get("names")
            if names:
                self.filter_names = [str(n) for n in names]
        except Exception:
            logger.exception("Could not read Names from %s", self.base_url)
        try:
            position = await self._get("position")
            if position is not None:
                self.position = int(position)
        except Exception:
            logger.exception("Could not read Position from %s", self.base_url)
        status["filter_names"] = list(self.filter_names)
        status["position"] = self.position
        return status
