# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Map a connected INDI power device onto a :class:`~galileo.core.switches.SwitchPanel`.

Two mappers share one output type and one write path (SDD §4.2a):

* the **standard mapper** reads INDI's power interface (``POWER_CHANNELS``, ``USB_PORTS``,
  ``DEW_CHANNELS``/``DEW_DUTY_CYCLES``, ``VARIABLE_CHANNELS``/``VARIABLE_VOLTAGES`` and friends), whose
  names are identical across vendors, so Pegasus and Terrans boxes need no per-vendor code (EQP-SW-030/040);
* the **profile mapper** applies a :class:`~galileo.core.switches.SwitchProfile` a plugin registered, for a
  driver that does not use the standard interface (EQP-SW-080).

Everything here is a pure function over a ``{property name: IndiProperty}`` snapshot, so it is tested against
recorded property sets with no server. Nothing is cached: the panel is rebuilt from the live property cache on
every refresh, which is what makes dynamically defined/deleted properties (EQP-SW-120) and "state shown is the
driver's, never the last command" (EQP-SW-050) hold.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from galileo.adapters.indi_client import IndiProperty
from galileo.core.devices import AuxElement, AuxProperty, AuxPropertyGroup
from galileo.core.switches import (
    DUTY_MAX,
    KIND_ACTION,
    KIND_DEW,
    KIND_TOGGLE,
    KIND_VALUE,
    KIND_VARIABLE,
    ProfileChannel,
    SwitchChannel,
    SwitchGroup,
    SwitchPanel,
    SwitchProfile,
    SwitchSensor,
    resolve_profile,
)
from galileo.exceptions import DevicePropertyError

Props = dict[str, IndiProperty]

# Properties that mark a device as using INDI's standard power interface.
_STANDARD_MARKERS = (
    ("POWER_CHANNELS", "switch"), ("USB_PORTS", "switch"), ("DEW_CHANNELS", "switch"),
    ("VARIABLE_CHANNELS", "switch"), ("AUTO_DEW_CONTROL", "switch"), ("DEW_DUTY_CYCLES", "number"),
    ("POWER_SENSORS", "number"),
)
_DEFAULT_DEW_SCALE = 100.0


@dataclass
class Target:
    """How to write one channel: which property elements, and the native scale of its duty."""
    kind: str
    switch: tuple[str, str] | None = None
    number: tuple[str, str] | None = None
    scale_max: float = _DEFAULT_DEW_SCALE      # the driver's full-scale duty
    on_via_duty: bool = False
    action: bool = False


@dataclass
class Mapped:
    panel: SwitchPanel
    targets: dict[str, Target]


# ---------------------------------------------------------------------------
# Reading the snapshot
# ---------------------------------------------------------------------------

def snapshot(client: Any, device: str) -> Props:
    """The device's current properties by name, from the client's live cache."""
    return {p.name: p for p in client.device_properties(device)}


def _kind_defined(props: Props, name: str, kind: str) -> IndiProperty | None:
    prop = props.get(name)
    return prop if prop is not None and prop.kind == kind else None


def _number(props: Props, ref: tuple[str, str] | None) -> float | None:
    if ref is None:
        return None
    prop = props.get(ref[0])
    value = prop.value(ref[1]) if prop is not None else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _switch(props: Props, ref: tuple[str, str] | None) -> bool | None:
    if ref is None:
        return None
    prop = props.get(ref[0])
    value = prop.value(ref[1]) if prop is not None else None
    return bool(value) if value is not None else None


def _labels(props: Props, name: str) -> dict[str, str]:
    prop = _kind_defined(props, name, "text")
    return {n: str(el.value) for n, el in prop.elements.items() if el.value} if prop is not None else {}


def _suffix(element: str) -> str:
    """``POWER_CHANNEL_3`` -> ``3``; an element with no trailing number keeps its own name."""
    match = re.search(r"(\d+)$", element)
    return match.group(1) if match else element.lower()


def has_standard_properties(props: Props) -> bool:
    return any(_kind_defined(props, name, kind) is not None for name, kind in _STANDARD_MARKERS)


# ---------------------------------------------------------------------------
# The standard mapper (EQP-SW-030, EQP-SW-040, EQP-SW-060)
# ---------------------------------------------------------------------------

def map_standard(props: Props) -> tuple[Mapped, set[str]]:
    """Build a panel from INDI's power interface. Returns the mapping and the property names it claimed."""
    claimed: set[str] = set()
    targets: dict[str, Target] = {}
    groups: list[SwitchGroup] = []

    def currents(name: str) -> dict[str, float | None]:
        prop = _kind_defined(props, name, "number")
        if prop is None:
            return {}
        claimed.add(name)
        return {n: _number(props, (name, n)) for n in prop.elements}

    def toggle_group(title: str, switch: str, labels: str, current: str | None, prefix: str) -> None:
        sw = _kind_defined(props, switch, "switch")
        if sw is None:
            return
        claimed.update({switch, labels})
        names, amps = _labels(props, labels), currents(current) if current else {}
        channels = []
        for element, el in sw.elements.items():
            cid = f"{prefix}{_suffix(element)}"
            channels.append(SwitchChannel(
                id=cid, label=names.get(element) or el.label or element, on=bool(el.value),
                writable=sw.perm != "ro", current_a=amps.get(element), state=sw.state,
            ))
            targets[cid] = Target(kind=KIND_TOGGLE, switch=(switch, element))
        groups.append(SwitchGroup(title, channels))

    toggle_group("DC", "POWER_CHANNELS", "POWER_LABELS", "POWER_CURRENTS", "dc")
    toggle_group("USB", "USB_PORTS", "USB_LABELS", None, "usb")

    # Dew heaters: an on/off switch plus a duty, either of which a driver may omit.
    dsw = _kind_defined(props, "DEW_CHANNELS", "switch")
    dduty = _kind_defined(props, "DEW_DUTY_CYCLES", "number")
    if dsw is not None or dduty is not None:
        claimed.update({"DEW_CHANNELS", "DEW_DUTY_CYCLES", "DEW_LABELS"})
        names, amps = _labels(props, "DEW_LABELS"), currents("DEW_CURRENTS")
        base = dsw if dsw is not None else dduty
        assert base is not None
        elements = list(base.elements)
        channels = []
        for element in elements:
            cid = f"dew{_suffix(element)}"
            scale = float(dduty.elements[element].max or _DEFAULT_DEW_SCALE) if dduty and element in dduty.elements else _DEFAULT_DEW_SCALE
            raw = _number(props, ("DEW_DUTY_CYCLES", element))
            label = names.get(element) or (dsw.elements[element].label if dsw and element in dsw.elements else "") or element
            channels.append(SwitchChannel(
                id=cid, label=label, kind=KIND_DEW,
                on=_switch(props, ("DEW_CHANNELS", element)),
                duty=None if raw is None else _clamp(raw / scale * DUTY_MAX, 0.0, DUTY_MAX),
                min=0.0, max=DUTY_MAX, step=_dew_step(dduty, element, scale),
                writable=(dsw is None or dsw.perm != "ro") and (dduty is None or dduty.perm != "ro"),
                current_a=amps.get(element), state=base.state,
            ))
            targets[cid] = Target(
                kind=KIND_DEW, switch=("DEW_CHANNELS", element) if dsw is not None and element in dsw.elements else None,
                number=("DEW_DUTY_CYCLES", element) if dduty is not None and element in dduty.elements else None,
                scale_max=scale,
            )
        groups.append(SwitchGroup("Dew heaters", channels))

    toggle_group("Auto dew", "AUTO_DEW_CONTROL", "DEW_LABELS", None, "autodew")

    vsw = _kind_defined(props, "VARIABLE_CHANNELS", "switch")
    vvolts = _kind_defined(props, "VARIABLE_VOLTAGES", "number")
    if vsw is not None or vvolts is not None:
        claimed.update({"VARIABLE_CHANNELS", "VARIABLE_VOLTAGES", "VARIABLE_LABELS"})
        names = _labels(props, "VARIABLE_LABELS")
        channels = []
        vbase = vsw if vsw is not None else vvolts
        assert vbase is not None
        for element in list(vbase.elements):
            cid = f"var{_suffix(element)}"
            vel = vvolts.elements.get(element) if vvolts else None
            channels.append(SwitchChannel(
                id=cid, label=names.get(element) or (vsw.elements[element].label if vsw and element in vsw.elements else "") or element,
                kind=KIND_VARIABLE, on=_switch(props, ("VARIABLE_CHANNELS", element)),
                volts=_number(props, ("VARIABLE_VOLTAGES", element)),
                min=vel.min if vel else None, max=vel.max if vel else None, step=vel.step if vel else None,
                writable=(vsw is None or vsw.perm != "ro") and (vvolts is None or vvolts.perm != "ro"),
                state=vbase.state,
            ))
            targets[cid] = Target(
                kind=KIND_VARIABLE, switch=("VARIABLE_CHANNELS", element) if vsw is not None and element in vsw.elements else None,
                number=("VARIABLE_VOLTAGES", element) if vvolts is not None and element in vvolts.elements else None,
            )
        groups.append(SwitchGroup("Adjustable outputs", channels))

    device: list[SwitchChannel] = []
    for prop_name, element, cid, label in (
        ("LED_CONTROL", "INDI_ENABLED", "led", "LEDs"),
        ("POWER_OFF_DISCONNECT", "INDI_ENABLED", "power_off_on_disconnect", "Power off on disconnect"),
    ):
        prop = _kind_defined(props, prop_name, "switch")
        if prop is not None and element in prop.elements:
            claimed.add(prop_name)
            device.append(SwitchChannel(id=cid, label=label, on=bool(prop.elements[element].value),
                                        writable=prop.perm != "ro", state=prop.state))
            targets[cid] = Target(kind=KIND_TOGGLE, switch=(prop_name, element))
    cycle = _kind_defined(props, "POWER_CYCLE", "switch")
    if cycle is not None and cycle.elements:
        claimed.add("POWER_CYCLE")
        element = next(iter(cycle.elements))
        device.append(SwitchChannel(id="power_cycle", label="Cycle power", kind=KIND_ACTION,
                                    writable=cycle.perm != "ro", state=cycle.state))
        targets["power_cycle"] = Target(kind=KIND_ACTION, switch=("POWER_CYCLE", element), action=True)
    ovp = _kind_defined(props, "OVER_VOLTAGE_PROTECTION", "number")
    if ovp is not None and ovp.elements:
        claimed.add("OVER_VOLTAGE_PROTECTION")
        element = next(iter(ovp.elements))
        el = ovp.elements[element]
        device.append(SwitchChannel(
            id="over_voltage", label="Over-voltage limit (V)", kind=KIND_VALUE,
            value=_number(props, ("OVER_VOLTAGE_PROTECTION", element)),
            min=el.min, max=el.max, step=el.step, writable=ovp.perm != "ro", state=ovp.state,
        ))
        targets["over_voltage"] = Target(kind=KIND_VALUE, number=("OVER_VOLTAGE_PROTECTION", element))
    if device:
        groups.append(SwitchGroup("Device", device))

    sensors: list[SwitchSensor] = []
    sensor_prop = _kind_defined(props, "POWER_SENSORS", "number")
    if sensor_prop is not None:
        claimed.add("POWER_SENSORS")
        for element, label, unit in (
            ("SENSOR_VOLTAGE", "Voltage", "V"), ("SENSOR_CURRENT", "Current", "A"), ("SENSOR_POWER", "Power", "W"),
        ):
            if element in sensor_prop.elements:
                sensors.append(SwitchSensor(id=element.lower(), label=label, unit=unit,
                                            value=_number(props, ("POWER_SENSORS", element))))

    return Mapped(SwitchPanel(groups=groups, sensors=sensors), targets), claimed


def _dew_step(duty_prop: IndiProperty | None, element: str, scale: float) -> float | None:
    """The driver's duty step re-expressed on the 0-100 scale."""
    if duty_prop is None or element not in duty_prop.elements:
        return None
    step = duty_prop.elements[element].step
    return None if not step else step / scale * DUTY_MAX


# ---------------------------------------------------------------------------
# The profile mapper (EQP-SW-080, EQP-SW-060)
# ---------------------------------------------------------------------------

def map_profile(props: Props, profile: SwitchProfile) -> tuple[Mapped, set[str]]:
    """Apply *profile* to the device's properties. A property the driver does not currently define leaves
    that channel present but disabled (``available`` False) instead of failing (EQP-SW-120)."""
    claimed: set[str] = set()
    targets: dict[str, Target] = {}
    grouped: dict[str, list[SwitchChannel]] = {}

    for ch in profile.channels:
        for ref in (ch.switch, ch.number, ch.current):
            if ref is not None:
                claimed.add(ref[0])
        grouped.setdefault(ch.group, []).append(_profile_channel(props, ch))
        if not ch.display_only:
            targets[ch.id] = Target(
                kind=ch.kind, switch=ch.switch, number=ch.number, on_via_duty=ch.on_via_duty,
                scale_max=ch.native_max or _element_max(props, ch.number) or _DEFAULT_DEW_SCALE,
                action=ch.kind == KIND_ACTION,
            )

    sensors: list[SwitchSensor] = []
    for s in profile.sensors:
        claimed.add(s.ref[0])
        prop = props.get(s.ref[0])
        if prop is None or s.ref[1] not in prop.elements:
            continue
        value = _number(props, s.ref)
        if value is not None and value in s.no_reading:
            value = None
        sensors.append(SwitchSensor(id=s.id, label=s.label, unit=s.unit, value=value))

    panel = SwitchPanel(groups=[SwitchGroup(g, chs) for g, chs in grouped.items()], sensors=sensors, profile=profile.name)
    return Mapped(panel, targets), claimed


def _element_max(props: Props, ref: tuple[str, str] | None) -> float | None:
    prop = props.get(ref[0]) if ref else None
    el = prop.elements.get(ref[1]) if prop is not None and ref else None
    return float(el.max) if el is not None and el.max else None


def _profile_channel(props: Props, ch: ProfileChannel) -> SwitchChannel:
    out = SwitchChannel(id=ch.id, label=ch.label, kind=ch.kind)
    if ch.current is not None:
        out.current_a = _number(props, ch.current)
    if ch.display_only:
        out.switchable = False
        out.writable = False
        out.on = True if ch.always_on else None
        return out

    sw = props.get(ch.switch[0]) if ch.switch else None
    num = props.get(ch.number[0]) if ch.number else None
    sw_ok = sw is not None and ch.switch is not None and ch.switch[1] in sw.elements
    num_ok = num is not None and ch.number is not None and ch.number[1] in num.elements
    missing = []
    if ch.switch and not sw_ok and not ch.on_via_duty:
        missing.append(ch.switch[0])
    if ch.number and not num_ok:
        missing.append(ch.number[0])
    if missing:
        out.available = False
        out.note = f"{', '.join(missing)} is not defined by the driver right now" + (" (optional)" if ch.optional else "")

    if sw_ok and ch.switch is not None:
        out.on = _switch(props, ch.switch)
        out.writable = sw.perm != "ro" if sw is not None else True
        out.state = sw.state if sw is not None else out.state
    if num_ok and ch.number is not None and num is not None:
        raw = _number(props, ch.number)
        el = num.elements[ch.number[1]]
        out.writable = out.writable and num.perm != "ro"
        out.state = num.state
        if ch.kind == KIND_DEW:
            scale = ch.native_max or (float(el.max) if el.max else _DEFAULT_DEW_SCALE)
            out.duty = None if raw is None else _clamp(raw / scale * DUTY_MAX, 0.0, DUTY_MAX)
            out.min, out.max = 0.0, DUTY_MAX
            out.step = None if not el.step else el.step / scale * DUTY_MAX
            if ch.on_via_duty and raw is not None:
                out.on = raw > 0
        elif ch.kind == KIND_VARIABLE:
            out.volts, out.min, out.max, out.step = raw, el.min, el.max, el.step
        else:
            out.value, out.min, out.max, out.step = raw, el.min, el.max, el.step
    return out


# ---------------------------------------------------------------------------
# Top level: pick the mapper, add the "Other" group
# ---------------------------------------------------------------------------

def build_panel(device: str, props: Props) -> Mapped:
    """The panel for *device*: its profile if its property signature matches one (never by name alone),
    else INDI's standard power interface, else an unrecognised panel that still lists every property."""
    defined = {(p.name, p.kind) for p in props.values()}
    resolution = resolve_profile(device, defined)
    if resolution.profile is not None:
        mapped, claimed = map_profile(props, resolution.profile)
    elif resolution.ambiguous:
        mapped, claimed = Mapped(SwitchPanel(
            recognised=False,
            message=f"{device!r} matches more than one switch profile ({', '.join(resolution.ambiguous)}); "
                    "its controls are listed below as the driver defines them.",
        ), {}), set()
    elif has_standard_properties(props):
        mapped, claimed = map_standard(props)
    else:
        mapped, claimed = Mapped(SwitchPanel(
            recognised=False,
            message=f"{device!r} is not recognised as a power device: it does not use INDI's power interface "
                    "and no installed switch profile matches its properties. Its controls are listed below "
                    "as the driver defines them.",
        ), {}), set()
    mapped.panel.other = aux_groups([p for n, p in props.items() if n not in claimed])
    return mapped


def aux_groups(props: list[IndiProperty]) -> list[AuxPropertyGroup]:
    """Properties no mapping claimed, shaped for the Aux property widgets, one group per INDI group
    (EQP-SW-070). BLOBs are image/data payloads, not a control, and are skipped."""
    groups: dict[str, AuxPropertyGroup] = {}
    for prop in props:
        if prop.kind == "blob":
            continue
        name = prop.group or "Main Control"
        groups.setdefault(name, AuxPropertyGroup(name=name)).properties.append(AuxProperty(
            name=prop.name, label=prop.label or prop.name, kind=prop.kind, group=name,
            perm=prop.perm, rule=prop.rule, state=prop.state,
            elements=[AuxElement(name=el.name, label=el.label or el.name, value=el.value,
                                 min=el.min, max=el.max, step=el.step) for el in prop.elements.values()],
        ))
    return sorted(groups.values(), key=lambda g: g.name)


# ---------------------------------------------------------------------------
# Writes (EQP-SW-050, EQP-SW-060)
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _require(props: Props, ref: tuple[str, str], device: str, kind: str) -> IndiProperty:
    prop = props.get(ref[0])
    if prop is None or prop.kind != kind or ref[1] not in prop.elements:
        raise DevicePropertyError(
            f"INDI device {device!r} does not define {ref[0]}.{ref[1]} right now — its driver doesn't "
            "support this operation (or has withdrawn it for the current mode)."
        )
    if prop.perm == "ro":
        raise DevicePropertyError(f"INDI property {ref[0]!r} on {device!r} is read-only.")
    return prop


def write_switch(client: Any, device: str, props: Props, ref: tuple[str, str], on: bool) -> None:
    prop = _require(props, ref, device, "switch")
    others = [n for n in prop.elements if n != ref[1]]
    if prop.rule == "OneOfMany":
        values = {ref[1]: on, **dict.fromkeys(others, False)} if on else {ref[1]: False}
        if not on and len(others) == 1:
            values[others[0]] = True      # a two-way On/Off vector: switching one off turns the other on
    else:
        values = {ref[1]: on}
    client.send_switch(device, prop.name, values)


def write_number(client: Any, device: str, props: Props, ref: tuple[str, str], native: float) -> None:
    prop = _require(props, ref, device, "number")
    el = prop.elements[ref[1]]
    lo = el.min if el.min is not None else float("-inf")
    hi = el.max if el.max is not None else float("inf")
    client.send_number(device, prop.name, {ref[1]: _clamp(float(native), lo, hi)})


def apply_write(
    client: Any, device: str, mapped: Mapped, props: Props, channel_id: str, *,
    on: bool | None = None, duty: float | None = None, volts: float | None = None, value: float | None = None,
) -> None:
    """Send whichever of *on*, *duty*, *volts* and *value* is given to the channel's property elements."""
    target = mapped.targets.get(channel_id)
    if target is None:
        raise DevicePropertyError(f"INDI device {device!r} has no switch channel {channel_id!r}.")
    if on is None and duty is None and volts is None and value is None:
        raise DevicePropertyError(f"Nothing to set on {channel_id!r}.")

    if on is not None:
        if target.on_via_duty and target.number is not None:
            write_number(client, device, props, target.number, target.scale_max if on else 0.0)
        elif target.switch is not None:
            write_switch(client, device, props, target.switch, on)
        else:
            raise DevicePropertyError(f"{channel_id!r} on {device!r} has no on/off control.")
    if duty is not None:
        if target.kind != KIND_DEW or target.number is None:
            raise DevicePropertyError(f"{channel_id!r} on {device!r} has no duty control.")
        write_number(client, device, props, target.number, _clamp(duty, 0.0, DUTY_MAX) / DUTY_MAX * target.scale_max)
    if volts is not None:
        if target.kind != KIND_VARIABLE or target.number is None:
            raise DevicePropertyError(f"{channel_id!r} on {device!r} has no voltage control.")
        write_number(client, device, props, target.number, volts)
    if value is not None:
        if target.kind != KIND_VALUE or target.number is None:
            raise DevicePropertyError(f"{channel_id!r} on {device!r} has no numeric control.")
        write_number(client, device, props, target.number, value)
