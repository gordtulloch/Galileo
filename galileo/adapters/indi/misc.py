# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""INDI adapter(s) for misc devices."""

from __future__ import annotations

import asyncio
from typing import Any

from galileo.adapters import indi_client as ic
from galileo.adapters.indi._base import IndiAdapter
from galileo.core.devices import AuxElement, AuxProperty, AuxPropertyGroup, DeviceCategory
from galileo.exceptions import DevicePropertyError


class IndiSafetyMonitorAdapter(IndiAdapter):
    """INDI defines no safety-monitor device interface, so there is nothing
    to discover or read; ``poll()`` leaves the last known state unchanged."""

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.SAFETY_MONITOR, host, port, **kwargs)
        self.is_safe = True
        self.explanation = ""
        self.tier = 1

    async def poll(self) -> None:
        pass


class IndiGuiderAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.GUIDER, host, port, **kwargs)


class IndiSwitchAdapter(IndiAdapter):
    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.SWITCH, host, port, **kwargs)
        self.switches: list = []

    async def set_switch(self, name: str, value) -> None:
        self._log_interaction("set_switch", name=name, value=value)
        for sw in self.switches:
            if sw.name == name:
                sw.state = value


class IndiAuxAdapter(IndiAdapter):
    """Generic control-panel adapter for a miscellaneous INDI driver
    (EQP-AUX-010). Unlike every other category adapter, this one doesn't
    translate a fixed set of standard properties into typed port methods —
    it exposes whatever properties the connected driver defines, grouped
    exactly as the driver groups them (its own INDI tabs), for
    ``AuxController``/the Equipment > Aux page to render generically."""

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.AUX, host, port, **kwargs)

    async def list_available_devices(self, category: DeviceCategory) -> list[str]:
        """Every device the server currently has, unfiltered by
        ``DRIVER_INTERFACE`` — Aux is the deliberate catch-all for a driver
        that doesn't fit one of the other categories' guided pages, or that
        the user wants to drive directly rather than through one."""
        return await asyncio.to_thread(self._list_all_devices_sync)

    def _list_all_devices_sync(self) -> list[str]:
        client = ic.acquire_client(self.host, self.port)
        try:
            return client.device_names()
        finally:
            ic.release_client(client)

    async def get_property_groups(self) -> list[AuxPropertyGroup]:
        return await asyncio.to_thread(self._get_property_groups_sync)

    def _get_property_groups_sync(self) -> list[AuxPropertyGroup]:
        client = self._c()
        groups: dict[str, AuxPropertyGroup] = {}
        for prop in client.device_properties(self.device_name):
            if prop.kind == "blob":
                continue  # image/data payloads aren't a control-panel field
            group_name = prop.group or "Main Control"
            group = groups.setdefault(group_name, AuxPropertyGroup(name=group_name))
            group.properties.append(AuxProperty(
                name=prop.name, label=prop.label or prop.name, kind=prop.kind,
                group=group_name, perm=prop.perm, rule=prop.rule, state=prop.state,
                elements=[
                    AuxElement(name=el.name, label=el.label or el.name, value=el.value,
                               min=el.min, max=el.max, step=el.step)
                    for el in prop.elements.values()
                ],
            ))
        return list(groups.values())

    async def write_property(self, name: str, values: dict[str, Any]) -> None:
        self._log_interaction("write_property", name=name, values=values)
        await asyncio.to_thread(self._write_property_sync, name, values)

    def _write_property_sync(self, name: str, values: dict[str, Any]) -> None:
        client = self._c()
        prop = client.get_property(self.device_name, name)
        if prop is None:
            raise DevicePropertyError(f"INDI property {name!r} is not defined on {self.device_name!r}.")
        if prop.kind == "number":
            client.send_number(self.device_name, name, {k: float(v) for k, v in values.items()})
        elif prop.kind == "switch":
            client.send_switch(self.device_name, name, {k: bool(v) for k, v in values.items()})
        elif prop.kind == "text":
            client.send_text(self.device_name, name, {k: str(v) for k, v in values.items()})
        else:
            raise DevicePropertyError(f"INDI property {name!r} ({prop.kind}) is not writable from the Aux panel.")
