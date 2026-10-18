# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""INDI adapter(s) for rotator devices."""

from __future__ import annotations

from galileo.adapters import indi_client as ic
from galileo.adapters.indi._base import IndiAdapter
from galileo.core.devices import DeviceCategory


class IndiRotatorAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.ROTATOR, host, port, **kwargs)
        self.mechanical_angle = 0.0
        self.sky_angle = 0.0

    async def move_to_angle(self, angle: float) -> None:
        self._log_interaction("move_to_angle", angle=angle)
        self._set_num("ABS_ROTATOR_ANGLE", {"ANGLE": angle})
        self.mechanical_angle = angle

    async def halt(self) -> None:
        self._log_interaction("halt")
        self._set_sw("ROTATOR_ABORT_MOTION", {"ABORT": True})

    async def set_reverse(self, reverse: bool) -> None:
        self._log_interaction("set_reverse", reverse=reverse)
        self._set_sw("ROTATOR_REVERSE", {"INDI_ENABLED": reverse, "INDI_DISABLED": not reverse})

    async def sync_position(self, angle: float) -> None:
        """Declare the rotator's current physical position to be *angle*
        (``sync_position(0)`` = "set current position as zero")."""
        self._log_interaction("sync_position", angle=angle)
        prop = "SYNC_ROTATOR_ANGLE" if self._has("SYNC_ROTATOR_ANGLE") else "SYNC_ROTATOR"
        self._set_num(prop, {"ANGLE": angle})
        self.mechanical_angle = self.sky_angle = angle

    async def set_backlash(self, steps: float) -> None:
        """Set backlash compensation (a step count; ``0`` disables it). Only
        drivers implementing ``INDI::RotatorInterface``'s backlash properties
        have it — others raise ``DevicePropertyError``."""
        self._log_interaction("set_backlash", steps=steps)
        self._require("ROTATOR_BACKLASH_STEPS")
        if self._has("ROTATOR_BACKLASH_TOGGLE"):
            self._set_sw("ROTATOR_BACKLASH_TOGGLE", {"INDI_ENABLED": steps > 0, "INDI_DISABLED": steps <= 0})
        self._set_num("ROTATOR_BACKLASH_STEPS", {"ROTATOR_BACKLASH_VALUE": steps})

    async def get_status(self) -> dict:
        """Live rotator status. INDI reports a single angle (moved with
        ``ABS_ROTATOR_ANGLE``, redefined with a sync), so mechanical and sky
        position are the same value here."""
        angle = self._num("ABS_ROTATOR_ANGLE", "ANGLE")
        if angle is not None:
            self.mechanical_angle = self.sky_angle = angle
        limit = self._client.get_property(self.device_name, "ABS_ROTATOR_ANGLE") if self._client else None
        el = limit.elements.get("ANGLE") if limit else None
        return {
            **self._driver_info(),
            "position": angle,
            "mechanical_position": angle,
            "is_moving": (self._state("ABS_ROTATOR_ANGLE") == ic.BUSY) if angle is not None else None,
            "reverse": self._sw("ROTATOR_REVERSE", "INDI_ENABLED"),
            "backlash": self._num("ROTATOR_BACKLASH_STEPS", "ROTATOR_BACKLASH_VALUE"),
            "backlash_supported": self._has("ROTATOR_BACKLASH_STEPS"),
            "can_sync": self._has("SYNC_ROTATOR_ANGLE") or self._has("SYNC_ROTATOR"),
            "max_angle": el.max if el is not None else None,
        }
