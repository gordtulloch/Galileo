# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Alpaca adapter(s): focuser."""

from __future__ import annotations

import logging

from galileo.adapters.alpaca._base import AlpacaAdapter
from galileo.core.devices import DeviceCategory
from galileo.focuser_settings import FocuserSettings, clamp_position

logger = logging.getLogger(__name__)


class AlpacaFocuserAdapter(AlpacaAdapter):
    """Focuser via the ASCOM Alpaca ``IFocuserV3`` interface.

    ``MaxStep`` (the device's valid travel range, consumed by
    ``FocuserController``'s EQP-FOC-030 clamp) and ``Absolute`` (whether
    ``Move`` takes an absolute position or a relative step count) are
    read from the real device on connect rather than assumed — a physical
    focuser such as a Seestar's Alpaca bridge may be relative-only, and its
    range is device-specific, not a fixed simulator constant.
    """

    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.FOCUSER, host, port, **kwargs)
        self.position = 0
        self.temperature = 15.0
        self.is_moving = False
        self.max_step: int | None = None
        self.max_increment: int | None = None
        self.absolute: bool | None = None
        self.travel_min: int | None = None
        self.travel_max: int | None = None

    def configure(self, settings: FocuserSettings) -> None:
        """Apply the saved travel guard-rails (EQP-FOC-050). An ASCOM focuser is always Absolute:
        it has no timed-move equivalent, so its operating mode is not applied."""
        self.travel_min, self.travel_max = settings.travel_min, settings.travel_max

    def _guard(self, target: int) -> int:
        limited = clamp_position(target, self.travel_min, self.travel_max)
        if limited != target:
            logger.warning(
                "Alpaca focuser %s: move to %d is beyond the set travel limits (%s..%s); limiting to %d.",
                self.base_url, target, self.travel_min, self.travel_max, limited,
            )
        return limited

    async def connect(self) -> None:
        await super().connect()
        try:
            self.absolute = bool(await self._get("absolute"))
        except Exception:
            logger.exception("Could not read Absolute from %s", self.base_url)
        try:
            self.max_step = int(await self._get("maxstep"))
        except Exception:
            logger.exception("Could not read MaxStep from %s", self.base_url)
        try:
            self.max_increment = int(await self._get("maxincrement"))
        except Exception:
            logger.exception("Could not read MaxIncrement from %s", self.base_url)
        try:
            self.position = int(await self._get("position"))
        except Exception:
            logger.exception("Could not read initial Position from %s", self.base_url)
        try:
            self.temperature = float(await self._get("temperature"))
        except Exception:
            logger.debug("Temperature not available from %s", self.base_url)

    async def move_to(self, position: int) -> None:
        position = self._guard(position)
        await self._put("move", Position=position)
        try:
            self.position = int(await self._get("position"))
        except Exception:
            logger.exception("Could not read back Position from %s after move", self.base_url)
            self.position = position
        try:
            self.is_moving = bool(await self._get("ismoving"))
        except Exception:
            logger.debug("IsMoving not available from %s", self.base_url)

    async def move_by(self, steps: int) -> None:
        steps = self._guard(self.position + steps) - self.position
        if self.absolute is False:
            # Relative-only focuser: Move's Position argument *is* the step
            # delta, so send it directly rather than computing (and
            # asserting) an absolute target it doesn't support.
            await self._put("move", Position=steps)
            try:
                self.position = int(await self._get("position"))
            except Exception:
                logger.exception("Could not read back Position from %s after move", self.base_url)
                self.position += steps
        else:
            await self.move_to(self.position + steps)

    async def set_temp_comp(self, enabled: bool) -> None:
        await self._put("tempcomp", TempComp=enabled)

    async def get_status(self) -> dict:
        """Live-query this focuser's status from the standard ASCOM
        ``IFocuserV3`` properties — the Focuser page's per-panel status
        display (Is Moving, Max Increment, Max Step, Position, Temp Comp,
        Temperature). ASCOM has no standard "is settling" property, so that
        field is always reported ``False`` here. Successful reads also
        refresh this adapter's own cached ``position``/``max_step``/
        ``max_increment`` (used by ``FocuserController``'s clamp), so they
        stay current even if the initial ``connect()``-time fetch failed
        transiently."""
        status: dict[str, bool | int | float | None] = {
            "is_moving": None, "is_settling": False, "max_increment": None,
            "max_step": None, "position": None, "temp_comp": None, "temperature": None,
        }
        try:
            status["is_moving"] = bool(await self._get("ismoving"))
            self.is_moving = status["is_moving"]
        except Exception:
            logger.exception("Could not read IsMoving from %s", self.base_url)
        try:
            status["position"] = int(await self._get("position"))
            self.position = status["position"]
        except Exception:
            logger.exception("Could not read Position from %s", self.base_url)
        try:
            status["max_increment"] = int(await self._get("maxincrement"))
            self.max_increment = status["max_increment"]
        except Exception:
            logger.exception("Could not read MaxIncrement from %s", self.base_url)
        try:
            status["max_step"] = int(await self._get("maxstep"))
            self.max_step = status["max_step"]
        except Exception:
            logger.exception("Could not read MaxStep from %s", self.base_url)
        try:
            status["temp_comp"] = bool(await self._get("tempcomp"))
        except Exception:
            # TempComp is only present when TempCompAvailable is True.
            logger.debug("TempComp not available from %s", self.base_url)
        try:
            status["temperature"] = float(await self._get("temperature"))
            self.temperature = status["temperature"]
        except Exception:
            logger.debug("Temperature not available from %s", self.base_url)
        return status
