# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""INDI adapter(s) for focuser devices."""

from __future__ import annotations

import logging
from collections.abc import Callable

from galileo.adapters import indi_client as ic
from galileo.adapters.indi._base import IndiAdapter
from galileo.core.devices import DeviceCategory
from galileo.exceptions import DevicePropertyError
from galileo.focuser_settings import (
    MODE_ABSOLUTE, MODE_PULSE, PULSE_MIN_MS, PULSE_RANGE_MAX, FocuserSettings, clamp_position,
)

logger = logging.getLogger(__name__)


class IndiFocuserAdapter(IndiAdapter):
    """Focuser via ``INDI::Focuser``: absolute moves use ``ABS_FOCUS_POSITION``;
    relative-only drivers use ``REL_FOCUS_POSITION`` + ``FOCUS_MOTION``.

    In *Pulse* mode (``configure``) the focuser is driven by ``FOCUS_TIMER`` alone — run the motor
    for N ms in the ``FOCUS_MOTION`` direction. The driver reports no position, so this adapter keeps
    a virtual one on ``0..PULSE_RANGE_MAX`` (1 unit = 1 ms), advanced by each completed pulse, and
    tells ``position_listener`` after every change so it can be retained across restarts.
    """

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.FOCUSER, host, port, **kwargs)
        self.position = 0
        self.temperature = 15.0
        self.is_moving = False
        self.is_settling = False
        self.max_increment: int | None = None
        self.max_step: int | None = None
        self.absolute: bool | None = None
        self.temp_comp = False
        self.mode = MODE_ABSOLUTE
        self.travel_min: int | None = None
        self.travel_max: int | None = None
        self.position_listener: Callable[[int], None] | None = None

    @property
    def pulse(self) -> bool:
        return self.mode == MODE_PULSE

    def configure(self, settings: FocuserSettings) -> None:
        """Apply the saved operating mode, retained position and travel limits (EQP-FOC-040/050)."""
        self.mode = settings.mode
        self.travel_min, self.travel_max = settings.travel_min, settings.travel_max
        if self.pulse:
            self.position = settings.start_position()
            self.max_step = PULSE_RANGE_MAX
            self.max_increment = None

    def set_position(self, position: int) -> None:
        """Tell a pulse focuser where it really is (the user's "this is the middle" calibration)."""
        self.position = int(position)
        self._notify_position()

    def _notify_position(self) -> None:
        if self.pulse and self.position_listener is not None:
            try:
                self.position_listener(self.position)
            except Exception:
                logger.exception("Focuser position listener failed")

    def _on_connected(self) -> None:
        if self.pulse and not self._has("FOCUS_TIMER"):
            logger.warning(
                "INDI focuser %r is set to Pulse mode but its driver has no FOCUS_TIMER property.",
                self.device_name,
            )
        self._refresh()

    def _refresh(self) -> None:
        self.absolute = self._has("ABS_FOCUS_POSITION")
        if not self.pulse:
            self._refresh_position()
        temp = self._num("FOCUS_TEMPERATURE", "TEMPERATURE")
        if temp is not None:
            self.temperature = temp

    def _refresh_position(self) -> None:
        absolute = self._client.get_property(self.device_name, "ABS_FOCUS_POSITION") if self._client else None
        relative = self._client.get_property(self.device_name, "REL_FOCUS_POSITION") if self._client else None
        if absolute is not None:
            el = absolute.elements.get("FOCUS_ABSOLUTE_POSITION")
            if el is not None:
                if el.value is not None:
                    self.position = int(el.value)
                if el.max is not None:
                    self.max_step = int(el.max)
        if relative is not None:
            el = relative.elements.get("FOCUS_RELATIVE_POSITION")
            if el is not None and el.max is not None:
                self.max_increment = int(el.max)

    def _temp_comp_property(self) -> ic.IndiProperty | None:
        # INDI has no standard temperature-compensation property; drivers that
        # support it (MoonLite, Pegasus, ...) each name it differently.
        return self._client.find_property(
            self.device_name, lambda p: p.kind == "switch" and "COMPENS" in p.name.upper(),
        ) if self._client else None

    def _travel(self) -> tuple[int | None, int | None]:
        """The user's travel guard-rails, held inside the pulse axis when in Pulse mode."""
        if self.pulse:
            return max(self.travel_min or 0, 0), min(self.travel_max or PULSE_RANGE_MAX, PULSE_RANGE_MAX)
        return self.travel_min, self.travel_max

    def _guard(self, target: int) -> int:
        low, high = self._travel()
        limited = clamp_position(target, low, high)
        if limited != target:
            logger.warning(
                "INDI focuser %r: move to %d is beyond the set travel limits (%s..%s); limiting to %d.",
                self.device_name, target, low, high, limited,
            )
        return limited

    async def move_to(self, position: int) -> None:
        self._log_interaction("move_to", position=position, from_position=self.position)
        position = self._guard(position)
        if self.pulse:
            await self._pulse_by(position - self.position)
        elif self._has("ABS_FOCUS_POSITION"):
            self._set_num("ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": position})
            self.position = position
        elif self._has("REL_FOCUS_POSITION"):
            self._move_relative(position - self.position)
        else:
            self._raise_no_motion_property()

    async def move_by(self, steps: int) -> None:
        self._log_interaction("move_by", steps=steps)
        steps = self._guard(self.position + steps) - self.position
        if self.pulse:
            await self._pulse_by(steps)
        elif self._has("REL_FOCUS_POSITION"):
            self._move_relative(steps)
        elif self._has("ABS_FOCUS_POSITION"):
            target = self.position + steps
            self._set_num("ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": target})
            self.position = target
        else:
            self._raise_no_motion_property()

    def _move_relative(self, steps: int) -> None:
        self._select("FOCUS_MOTION", "FOCUS_OUTWARD" if steps >= 0 else "FOCUS_INWARD")
        self._set_num("REL_FOCUS_POSITION", {"FOCUS_RELATIVE_POSITION": abs(steps)})
        self.position += steps

    async def _pulse_by(self, steps: int) -> None:
        """Run the motor for ``abs(steps)`` ms (outward if positive) and, once the driver reports the
        pulse finished, advance the virtual position by it."""
        if not self._has("FOCUS_TIMER"):
            raise DevicePropertyError(
                f"INDI focuser {self.device_name!r} has no FOCUS_TIMER property, so it cannot be driven "
                "in Pulse mode — set the focuser's mode to Absolute."
            )
        ms = abs(steps)
        if ms == 0:
            return
        if ms < PULSE_MIN_MS:
            logger.warning(
                "INDI focuser %r: a %d ms pulse is below the %d ms minimum; not moving.",
                self.device_name, ms, PULSE_MIN_MS,
            )
            return
        seq0 = self._c().blob_seq(self.device_name, "FOCUS_TIMER")
        self._select("FOCUS_MOTION", "FOCUS_OUTWARD" if steps > 0 else "FOCUS_INWARD")
        self._set_num("FOCUS_TIMER", {"FOCUS_TIMER_VALUE": ms})
        self.is_moving = True
        try:
            await self._wait_not_busy("FOCUS_TIMER", ms / 1000.0 + 15.0, "focuser pulse", after_seq=seq0)
        finally:
            self.is_moving = False
        self.position += steps
        self._notify_position()

    def _raise_no_motion_property(self) -> None:
        # move_to and move_by used to call each other when neither property existed (e.g. the
        # driver's properties had not arrived yet), recursing until RecursionError.
        hint = (" It does have FOCUS_TIMER — set the focuser's mode to Pulse." if self._has("FOCUS_TIMER") else "")
        raise DevicePropertyError(
            f"INDI focuser {self.device_name!r} exposes neither ABS_FOCUS_POSITION nor "
            f"REL_FOCUS_POSITION, so it cannot be moved.{hint}"
        )

    async def set_temp_comp(self, enabled: bool) -> None:
        self._log_interaction("set_temp_comp", enabled=enabled)
        prop = self._temp_comp_property()
        if prop is None:
            raise DevicePropertyError(
                f"INDI focuser {self.device_name!r} has no temperature-compensation switch."
            )
        on = next((n for n in prop.elements if "ENABLE" in n.upper() or n.upper().endswith("_ON")), None)
        off = next((n for n in prop.elements if "DISABLE" in n.upper() or n.upper().endswith("_OFF")), None)
        if on is None:
            raise DevicePropertyError(f"Cannot interpret INDI switch {prop.name!r} as temperature compensation.")
        values = {on: enabled}
        if off is not None:
            values[off] = not enabled
        self._c().send_switch(self.device_name, prop.name, values)
        self.temp_comp = enabled

    async def get_status(self) -> dict:
        self._refresh()
        if self.pulse:
            busy = self._state("FOCUS_TIMER") == ic.BUSY
        else:
            busy = ic.BUSY in (self._state("ABS_FOCUS_POSITION"), self._state("REL_FOCUS_POSITION"))
        self.is_moving = busy
        comp = self._temp_comp_property()
        if comp is not None:
            self.temp_comp = any(el.value for n, el in comp.elements.items() if "ENABLE" in n.upper() or n.upper().endswith("_ON"))
        return {
            "is_moving": self.is_moving,
            # INDI has no "settling" state distinct from Busy.
            "is_settling": False,
            "max_increment": self.max_increment,
            "max_step": self.max_step,
            "mode": self.mode,
            "position": self.position,
            "temp_comp": self.temp_comp if comp is not None else None,
            "temperature": self._num("FOCUS_TEMPERATURE", "TEMPERATURE"),
        }
