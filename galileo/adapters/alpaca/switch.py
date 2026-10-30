# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Alpaca adapter(s): switch and auxiliary."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from galileo.adapters.alpaca._base import AlpacaAdapter
from galileo.core.devices import (
    AuxElement,
    AuxProperty,
    AuxPropertyGroup,
    DeviceCategory,
    SwitchChannel,
    SwitchGroup,
    SwitchPanel,
    SwitchSensor,
)
from galileo.core.switches import KIND_VALUE, flat_switches
from galileo.exceptions import DevicePropertyError

logger = logging.getLogger(__name__)


def _is_boolean_switch_range(min_value: Any, max_value: Any, step_value: Any) -> bool:
    """Whether an ISwitchV2 channel's declared range (``MinSwitchValue``/
    ``MaxSwitchValue``/``SwitchStep``) is really just a boolean On/Off rather
    than a variable analog value — the ASCOM spec defines a boolean switch as
    one with range 0..1 and step 1."""
    try:
        return float(min_value) == 0.0 and float(max_value) == 1.0 and float(step_value) == 1.0
    except (TypeError, ValueError):
        return False


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class _ChannelMeta:
    """What an ISwitchV2 channel declares about itself — fixed for the life of the connection."""
    index: int
    name: str
    description: str
    can_write: bool
    boolean: bool
    min: float | None
    max: float | None
    step: float | None

    @property
    def channel_id(self) -> str:
        # The index is what the device addresses; the name is appended because Alpaca does not forbid two
        # channels sharing one, and it keeps an id readable in a session (EQP-SW-100).
        return f"{self.index}:{self.name}"


_MAX_PARALLEL_REQUESTS = 4   # a small device (a Seestar's bridge, a relay board) should not be flooded


class AlpacaSwitchAdapter(AlpacaAdapter):
    """An ASCOM Alpaca Switch device (ISwitchV2): a power box, relay board, flip mirror, ... (EQP-SW-010,
    EQP-SW-050, EQP-SW-100, EQP-SW-130, EQP-SW-140).

    ISwitchV2 is a flat list of channels with no grouping and no statement of what an analog channel *means*,
    so the panel is one group; a boolean 0..1 step-1 channel is a toggle, any other writable channel a
    generic value that carries only its declared range (no assumed unit — a wrong unit on a power control is
    worse than none), and a read-only channel a reading. The Aux page still shows the same device unchanged."""

    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.SWITCH, host, port, **kwargs)
        self._channels: list[_ChannelMeta] | None = None
        self._panel: SwitchPanel | None = None

    async def connect(self) -> None:
        await super().connect()
        self._channels = None
        try:
            await self.get_panel()      # fills the flat list, so a session can address channels at once
        except Exception:
            logger.warning("Could not read the Alpaca switch channels of %s:%s", self.host, self.port, exc_info=True)

    async def disconnect(self) -> None:
        await super().disconnect()
        self._channels = None
        self._panel = None

    # -- reading -----------------------------------------------------------

    async def _load_channels(self) -> list[_ChannelMeta]:
        count = int(await self._get("maxswitch") or 0)
        gate = asyncio.Semaphore(_MAX_PARALLEL_REQUESTS)

        async def get(attribute: str, index: int) -> Any:
            async with gate:
                return await self._get(attribute, Id=index)

        async def one(index: int) -> _ChannelMeta:
            name, description, can_write, lo, hi, step = await asyncio.gather(
                get("getswitchname", index), get("getswitchdescription", index), get("canwrite", index),
                get("minswitchvalue", index), get("maxswitchvalue", index), get("switchstep", index),
            )
            return _ChannelMeta(
                index=index, name=str(name or f"Switch {index}"), description=str(description or ""),
                can_write=bool(can_write), boolean=_is_boolean_switch_range(lo, hi, step),
                min=_as_float(lo), max=_as_float(hi), step=_as_float(step),
            )

        return list(await asyncio.gather(*(one(i) for i in range(count))))

    async def get_panel(self) -> SwitchPanel:
        if self._channels is None:
            self._channels = await self._load_channels()
        channels = self._channels
        gate = asyncio.Semaphore(_MAX_PARALLEL_REQUESTS)

        async def read(meta: _ChannelMeta) -> Any:
            async with gate:
                return await self._get("getswitch" if meta.boolean else "getswitchvalue", Id=meta.index)

        raw = await asyncio.gather(*(read(m) for m in channels))
        out: list[SwitchChannel] = []
        sensors: list[SwitchSensor] = []
        for meta, value in zip(channels, raw, strict=True):
            note = meta.description if meta.description and meta.description != meta.name else ""
            if meta.boolean:
                out.append(SwitchChannel(
                    id=meta.channel_id, label=meta.name, on=None if value is None else bool(value),
                    switchable=meta.can_write, writable=meta.can_write, note=note,
                ))
            elif meta.can_write:
                out.append(SwitchChannel(
                    id=meta.channel_id, label=meta.name, kind=KIND_VALUE, value=_as_float(value),
                    min=meta.min, max=meta.max, step=meta.step, note=note,
                ))
            else:
                sensors.append(SwitchSensor(id=meta.channel_id, label=meta.name, value=_as_float(value)))
        panel = SwitchPanel(groups=[SwitchGroup("Switches", out)] if out else [], sensors=sensors)
        self._panel = panel
        return panel

    @property
    def switches(self) -> list:
        """The flat view (EQP-SW-100), from the most recent panel read."""
        return flat_switches(self._panel) if self._panel is not None else []

    # -- writing -----------------------------------------------------------

    def _channel(self, channel_id: str) -> _ChannelMeta:
        for meta in self._channels or []:
            if meta.channel_id == channel_id:
                return meta
        raise DevicePropertyError(f"Alpaca switch device at {self.host}:{self.port} has no channel {channel_id!r}.")

    async def set_channel(
        self, channel_id: str, *, on: bool | None = None, duty: float | None = None,
        volts: float | None = None, value: float | None = None,
    ) -> None:
        if self._channels is None:
            self._channels = await self._load_channels()
        meta = self._channel(channel_id)
        if duty is not None or volts is not None:
            raise DevicePropertyError(
                f"Alpaca channel {meta.name!r} is a plain switch or value; it has no duty or voltage control."
            )
        if not meta.can_write:
            raise DevicePropertyError(f"Alpaca channel {meta.name!r} is read-only.")
        if on is not None:
            if not meta.boolean:
                raise DevicePropertyError(f"Alpaca channel {meta.name!r} is not an on/off switch; set its value.")
            await self._put("setswitch", Id=meta.index, State=on)
        elif value is not None:
            if meta.boolean:
                raise DevicePropertyError(f"Alpaca channel {meta.name!r} is an on/off switch; it has no level.")
            level = value
            if meta.min is not None:
                level = max(meta.min, level)
            if meta.max is not None:
                level = min(meta.max, level)
            await self._put("setswitchvalue", Id=meta.index, Value=level)
        else:
            raise DevicePropertyError(f"Nothing to set on Alpaca channel {meta.name!r}.")
        await self.get_panel()          # state shown is the device's, not the command we just sent

    async def set_switch(self, name: str, value) -> None:
        """Flat write (EQP-SW-100) by channel id — or by plain channel name when that is unambiguous."""
        if self._channels is None:
            self._channels = await self._load_channels()
        by_id = [m for m in self._channels if m.channel_id == name]
        matches = by_id or [m for m in self._channels if m.name == name]
        if len(matches) != 1:
            raise DevicePropertyError(
                f"Alpaca switch device at {self.host}:{self.port} has "
                f"{'no' if not matches else 'more than one'} channel named {name!r}."
            )
        target = matches[0].channel_id
        if isinstance(value, bool):
            await self.set_channel(target, on=value)
        else:
            await self.set_channel(target, value=float(value))


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
