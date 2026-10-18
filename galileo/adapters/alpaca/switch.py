# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Alpaca adapter(s): switch and auxiliary."""

from __future__ import annotations

from typing import Any

from galileo.adapters.alpaca._base import AlpacaAdapter
from galileo.core.devices import AuxElement, AuxProperty, AuxPropertyGroup, DeviceCategory


class AlpacaSwitchAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.SWITCH, host, port, **kwargs)
        self.switches: list = []

    async def set_switch(self, name: str, value) -> None:
        for i, sw in enumerate(self.switches):
            if sw.name == name:
                await self._put("setswitch", Id=i, State=value)
                sw.state = value


def _is_boolean_switch_range(min_value: Any, max_value: Any, step_value: Any) -> bool:
    """Whether an ISwitchV2 channel's declared range (``MinSwitchValue``/
    ``MaxSwitchValue``/``SwitchStep``) is really just a boolean On/Off rather
    than a variable analog value — the ASCOM spec defines a boolean switch as
    one with range 0..1 and step 1."""
    try:
        return float(min_value) == 0.0 and float(max_value) == 1.0 and float(step_value) == 1.0
    except (TypeError, ValueError):
        return False


class AlpacaAuxAdapter(AlpacaAdapter):
    """Generic control-panel adapter for a miscellaneous Alpaca device
    (EQP-AUX-010). Alpaca has no cross-device-type generic property
    introspection — unlike INDI, each DeviceType's property set is a fixed,
    separately-specified interface — so this adapter is scoped to the one
    ASCOM interface meant for this purpose, ISwitchV2 (the Alpaca "Switch"
    DeviceType), which the ASCOM spec itself describes as being for
    arbitrary/auxiliary hardware (a power box, a flip mirror, a relay
    board, ...) rather than a specific instrument. Every channel becomes one
    property with one element: a boolean On/Off pair when its declared range
    is 0..1 step 1 (:func:`_is_boolean_switch_range`), or a numeric
    slider/spinbox otherwise — both in a single "Switches" group/tab, since
    ISwitchV2 has no grouping concept of its own."""

    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.AUX, host, port, **kwargs)

    async def get_property_groups(self) -> list[AuxPropertyGroup]:
        max_switch = int(await self._get("maxswitch") or 0)
        group = AuxPropertyGroup(name="Switches")
        for i in range(max_switch):
            name = str(await self._get("getswitchname", Id=i) or f"Switch {i}")
            description = await self._get("getswitchdescription", Id=i)
            can_write = bool(await self._get("canwrite", Id=i))
            min_value = await self._get("minswitchvalue", Id=i)
            max_value = await self._get("maxswitchvalue", Id=i)
            step = await self._get("switchstep", Id=i)
            if _is_boolean_switch_range(min_value, max_value, step):
                value: Any = bool(await self._get("getswitch", Id=i))
                kind = "switch"
                element = AuxElement(name=str(i), label=name, value=value)
            else:
                value = await self._get("getswitchvalue", Id=i)
                kind = "number"
                element = AuxElement(
                    name=str(i), label=name, value=value,
                    min=float(min_value) if min_value is not None else None,
                    max=float(max_value) if max_value is not None else None,
                    step=float(step) if step is not None else None,
                )
            group.properties.append(AuxProperty(
                name=str(i), label=str(description) if description else name, kind=kind,
                group="Switches", perm="rw" if can_write else "ro", elements=[element],
            ))
        return [group]

    async def write_property(self, name: str, values: dict[str, Any]) -> None:
        index = int(name)
        value = next(iter(values.values()))
        if isinstance(value, bool):
            await self._put("setswitch", Id=index, State=value)
        else:
            await self._put("setswitchvalue", Id=index, Value=float(value))
