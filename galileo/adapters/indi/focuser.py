# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""INDI adapter(s) for focuser devices."""

from __future__ import annotations

from galileo.adapters import indi_client as ic
from galileo.adapters.indi._base import IndiAdapter
from galileo.core.devices import DeviceCategory
from galileo.exceptions import DevicePropertyError


class IndiFocuserAdapter(IndiAdapter):
    """Focuser via ``INDI::Focuser``: absolute moves use ``ABS_FOCUS_POSITION``;
    relative-only drivers use ``REL_FOCUS_POSITION`` + ``FOCUS_MOTION``."""

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

    def _on_connected(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self.absolute = self._has("ABS_FOCUS_POSITION")
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
        temp = self._num("FOCUS_TEMPERATURE", "TEMPERATURE")
        if temp is not None:
            self.temperature = temp

    def _temp_comp_property(self) -> ic.IndiProperty | None:
        # INDI has no standard temperature-compensation property; drivers that
        # support it (MoonLite, Pegasus, ...) each name it differently.
        return self._client.find_property(
            self.device_name, lambda p: p.kind == "switch" and "COMPENS" in p.name.upper(),
        ) if self._client else None

    async def move_to(self, position: int) -> None:
        self._log_interaction("move_to", position=position, from_position=self.position)
        if self._has("ABS_FOCUS_POSITION"):
            self._set_num("ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": position})
            self.position = position
        elif self._has("REL_FOCUS_POSITION"):
            self._move_relative(position - self.position)
        else:
            self._raise_no_motion_property()

    async def move_by(self, steps: int) -> None:
        self._log_interaction("move_by", steps=steps)
        if self._has("REL_FOCUS_POSITION"):
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

    def _raise_no_motion_property(self) -> None:
        # move_to and move_by used to call each other when neither property existed (e.g. the
        # driver's properties had not arrived yet), recursing until RecursionError.
        raise DevicePropertyError(
            f"INDI focuser {self.device_name!r} exposes neither ABS_FOCUS_POSITION nor "
            "REL_FOCUS_POSITION, so it cannot be moved."
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
            "position": self.position,
            "temp_comp": self.temp_comp if comp is not None else None,
            "temperature": self._num("FOCUS_TEMPERATURE", "TEMPERATURE"),
        }
