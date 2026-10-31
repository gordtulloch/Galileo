# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""INDI adapter(s) for misc devices."""

from __future__ import annotations

import asyncio
from typing import Any

from galileo.adapters import indi_client as ic
from galileo.adapters.indi import switch_map
from galileo.adapters.indi._base import IndiAdapter
from galileo.core.devices import (
    AuxElement,
    AuxProperty,
    AuxPropertyGroup,
    DeviceCategory,
    SwitchPanel,
    SwitchProfileRegistry,
)
from galileo.core.switches import KIND_DEW, KIND_VARIABLE, flat_switches
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
    """A power box or relay board behind an INDI driver (EQP-SW-010, EQP-SW-020 … EQP-SW-070, EQP-SW-120).

    The panel is rebuilt from the live property cache on every call, never remembered, so what it shows is
    always the driver's own state and a property the driver defines or withdraws mid-session is picked up
    (see :mod:`galileo.adapters.indi.switch_map`). A device that follows INDI's power interface needs no
    configuration; one that does not is mapped by a plugin-registered profile."""

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.SWITCH, host, port, **kwargs)

    # -- discovery ---------------------------------------------------------

    async def list_available_devices(self, category: DeviceCategory) -> list[str]:
        """The usual Switch scan (power / output / aux interfaces) plus any device whose name a registered
        profile claims, so a driver that sets none of those interface bits is still offered (EQP-SW-020)."""
        names = await super().list_available_devices(category)
        claimed = SwitchProfileRegistry.claimed_device_names()
        if not claimed:
            return names
        extra = await asyncio.to_thread(self._claimed_devices_sync, claimed)
        return names + [n for n in extra if n not in names]

    def _claimed_devices_sync(self, claimed: set[str]) -> list[str]:
        client = ic.acquire_client(self.host, self.port)
        try:
            return [d for d in client.device_names() if d in claimed]
        finally:
            ic.release_client(client)

    # -- the panel ---------------------------------------------------------

    def _mapped(self) -> switch_map.Mapped:
        return switch_map.build_panel(self.device_name, switch_map.snapshot(self._c(), self.device_name))

    async def get_panel(self) -> SwitchPanel:
        return await asyncio.to_thread(lambda: self._mapped().panel)

    @property
    def switches(self) -> list:
        """The flat view (EQP-SW-100): every switchable channel, addressed by its stable id."""
        if not self.is_connected:
            return []
        return flat_switches(self._mapped().panel)

    # -- writes ------------------------------------------------------------

    async def set_channel(
        self, channel_id: str, *, on: bool | None = None, duty: float | None = None,
        volts: float | None = None, value: float | None = None,
    ) -> None:
        self._log_interaction("set_channel", channel=channel_id, on=on, duty=duty, volts=volts, value=value)
        await asyncio.to_thread(self._set_channel_sync, channel_id, on, duty, volts, value)

    def _set_channel_sync(self, channel_id: str, on, duty, volts, value) -> None:
        client = self._c()
        props = switch_map.snapshot(client, self.device_name)
        mapped = switch_map.build_panel(self.device_name, props)
        switch_map.apply_write(client, self.device_name, mapped, props, channel_id,
                               on=on, duty=duty, volts=volts, value=value)

    async def write_property(self, name: str, values: dict[str, Any]) -> None:
        """Write an unclaimed driver property from the panel's "Other" group (EQP-SW-070), exactly as the
        Aux page would: by the property's kind in the live cache."""
        self._log_interaction("write_property", name=name, values=values)
        await asyncio.to_thread(self._write_property_sync, name, values)

    def _write_property_sync(self, name: str, values: dict[str, Any]) -> None:
        client = self._c()
        prop = client.get_property(self.device_name, name)
        if prop is None:
            raise DevicePropertyError(f"INDI property {name!r} is not defined on {self.device_name!r}.")
        if prop.perm == "ro":
            raise DevicePropertyError(f"INDI property {name!r} on {self.device_name!r} is read-only.")
        if prop.kind == "number":
            client.send_number(self.device_name, name, {k: float(v) for k, v in values.items()})
        elif prop.kind == "switch":
            client.send_switch(self.device_name, name, {k: bool(v) for k, v in values.items()})
        elif prop.kind == "text":
            client.send_text(self.device_name, name, {k: str(v) for k, v in values.items()})
        else:
            raise DevicePropertyError(f"INDI property {name!r} ({prop.kind}) is not writable from the Switches page.")

    async def set_switch(self, name: str, value) -> None:
        """Flat write by channel id (EQP-SW-100): a bool switches the channel, a number sets its level
        (duty for a heater, volts for a regulated output, the raw value otherwise)."""
        if isinstance(value, bool):
            await self.set_channel(name, on=value)
            return
        panel = await self.get_panel()
        channel = panel.channel(name)
        if channel is None:
            raise DevicePropertyError(f"INDI device {self.device_name!r} has no switch channel {name!r}.")
        level = float(value)
        if channel.kind == KIND_DEW:
            await self.set_channel(name, duty=level)
        elif channel.kind == KIND_VARIABLE:
            await self.set_channel(name, volts=level)
        else:
            await self.set_channel(name, value=level)


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
