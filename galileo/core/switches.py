# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Switch panel model and switch profiles (EQP-SW-020 … EQP-SW-140, PLUG-210).

A *switch panel* is the structured, transport-neutral view of a power box or
relay board: groups of labelled channels (toggles, dew heaters, regulated
outputs, generic values), read-only readings, and any driver properties the
mapping did not claim. The INDI and Alpaca adapters build one from their own
protocols; the Equipment > Switches page renders it without knowing which.

A *switch profile* is declarative data a plugin registers so core can map a
driver that does not follow INDI's standard power interface (the Wanderer Astro
boxes, for one). It names INDI properties as plain strings but contains no INDI
code, so this module keeps the domain core free of adapter imports.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from galileo.core.devices import AuxPropertyGroup

logger = logging.getLogger(__name__)

# Channel kinds a panel can carry.
KIND_TOGGLE = "toggle"      # on/off
KIND_DEW = "dew"            # heater: on/off plus a 0-100 % duty
KIND_VARIABLE = "variable"  # regulated output: on/off plus a voltage
KIND_VALUE = "value"        # a number whose meaning the device does not declare (no unit, no scale)
KIND_ACTION = "action"      # a momentary button (power-cycle all)
CHANNEL_KINDS = (KIND_TOGGLE, KIND_DEW, KIND_VARIABLE, KIND_VALUE, KIND_ACTION)

DUTY_MAX = 100.0            # the one scale a dew duty is presented on (EQP-SW-060)


@dataclass
class SwitchChannel:
    """One controllable (or display-only) output of a switch device."""
    id: str                         # stable across refreshes; what ``set_switch``/``set_channel`` address
    label: str
    kind: str = KIND_TOGGLE
    on: bool | None = None          # None: unknown
    switchable: bool = True         # False: shown, but the hardware cannot switch it (no toggle)
    writable: bool = True           # False: the driver defines it read-only
    available: bool = True          # False: an optional driver property is absent, so the control is disabled
    duty: float | None = None       # dew: 0-100 %
    volts: float | None = None      # variable: the set voltage
    value: float | None = None      # value: the raw number
    min: float | None = None
    max: float | None = None
    step: float | None = None
    current_a: float | None = None
    state: str = "Idle"             # the driver's property state: Idle | Ok | Busy | Alert
    note: str = ""


@dataclass
class SwitchSensor:
    """A read-only reading (voltage, current, temperature, ...). ``value`` is None for "no reading"."""
    id: str
    label: str
    value: float | None = None
    unit: str = ""


@dataclass
class SwitchGroup:
    name: str
    channels: list[SwitchChannel] = field(default_factory=list)


@dataclass
class SwitchPanel:
    """Everything the Switches page shows for one connected device."""
    groups: list[SwitchGroup] = field(default_factory=list)
    sensors: list[SwitchSensor] = field(default_factory=list)
    other: list[AuxPropertyGroup] = field(default_factory=list)   # properties no mapping claimed (EQP-SW-070)
    recognised: bool = True
    profile: str = ""               # the profile applied, if any
    message: str = ""               # why the panel is degraded or empty

    def channels(self) -> list[SwitchChannel]:
        return [c for g in self.groups for c in g.channels]

    def channel(self, channel_id: str) -> SwitchChannel | None:
        return next((c for c in self.channels() if c.id == channel_id), None)


@dataclass
class FlatSwitch:
    """The flat view of a toggle channel that ``SwitchController.list_switches`` returns (EQP-SW-100):
    ``name`` is the stable channel id, ``state`` the on/off state, ``is_analog`` False for a toggle."""
    name: str
    state: bool | None
    is_analog: bool = False
    label: str = ""


def flat_switches(panel: SwitchPanel) -> list[FlatSwitch]:
    """Every switchable channel of *panel* as a :class:`FlatSwitch` — toggles, heaters and regulated
    outputs (on/off); display-only channels, actions and generic values are not switches."""
    return [
        FlatSwitch(name=c.id, state=c.on, is_analog=False, label=c.label)
        for c in panel.channels()
        if c.switchable and c.kind in (KIND_TOGGLE, KIND_DEW, KIND_VARIABLE)
    ]


# ---------------------------------------------------------------------------
# Switch profiles (EQP-SW-080)
# ---------------------------------------------------------------------------

PropertyRef = tuple[str, str]       # (INDI property name, element name)


@dataclass(frozen=True)
class ProfileChannel:
    """How one channel maps onto a driver's properties."""
    id: str
    label: str
    group: str
    kind: str = KIND_TOGGLE
    switch: PropertyRef | None = None       # the on/off element
    number: PropertyRef | None = None       # a dew duty, a voltage or a generic value
    native_max: float | None = None         # the driver's full-scale duty (e.g. 255); dew only
    on_via_duty: bool = False               # no switch element: on = duty above zero, off writes zero
    display_only: bool = False              # no property at all: shown, never switchable
    always_on: bool = False                 # display-only, wired straight to the supply
    current: PropertyRef | None = None      # the property element that measures this channel's current
    optional: bool = False                  # the driver defines the property only in some states


@dataclass(frozen=True)
class ProfileSensor:
    id: str
    label: str
    unit: str
    ref: PropertyRef
    no_reading: tuple[float, ...] = ()      # values the driver reports for "absent" (e.g. -127 for a missing probe)


@dataclass(frozen=True)
class SwitchProfile:
    """Declarative mapping for one driver that does not use INDI's power interface (EQP-SW-080)."""
    name: str
    device_names: tuple[str, ...]
    signature: frozenset[tuple[str, str]]   # (property name, kind) pairs that must all be defined after connect
    channels: tuple[ProfileChannel, ...] = ()
    sensors: tuple[ProfileSensor, ...] = ()

    def validate(self) -> None:
        """Raise ``ValueError`` naming the first problem, so a malformed profile is rejected with a reason
        rather than breaking the panel later (PLUG-210)."""
        if not self.name or not isinstance(self.name, str):
            raise ValueError("profile has no name")
        if not self.device_names or not all(isinstance(n, str) and n for n in self.device_names):
            raise ValueError(f"profile {self.name!r} claims no device names")
        if not self.signature:
            raise ValueError(f"profile {self.name!r} has an empty signature")
        for item in self.signature:
            if not (isinstance(item, tuple) and len(item) == 2 and all(isinstance(s, str) and s for s in item)):
                raise ValueError(f"profile {self.name!r} has a malformed signature entry {item!r}")
            if item[1] not in ("text", "number", "switch", "light"):
                raise ValueError(f"profile {self.name!r} signature entry {item!r} has an unknown property kind")
        seen: set[str] = set()
        for ch in self.channels:
            if not ch.id or ch.id in seen:
                raise ValueError(f"profile {self.name!r} has a missing or duplicate channel id {ch.id!r}")
            seen.add(ch.id)
            if ch.kind not in CHANNEL_KINDS:
                raise ValueError(f"profile {self.name!r} channel {ch.id!r} has unknown kind {ch.kind!r}")
            if ch.display_only:
                if ch.switch or ch.number:
                    raise ValueError(f"profile {self.name!r} display-only channel {ch.id!r} names a property")
            elif not (ch.switch or ch.number):
                raise ValueError(f"profile {self.name!r} channel {ch.id!r} names no property")
            if ch.on_via_duty and not ch.number:
                raise ValueError(f"profile {self.name!r} channel {ch.id!r} is on-via-duty but has no number")
            if ch.native_max is not None and ch.native_max <= 0:
                raise ValueError(f"profile {self.name!r} channel {ch.id!r} has a non-positive native_max")
            for ref in (ch.switch, ch.number, ch.current):
                if ref is not None and not (len(ref) == 2 and all(isinstance(s, str) and s for s in ref)):
                    raise ValueError(f"profile {self.name!r} channel {ch.id!r} has a malformed property reference")
        for sensor in self.sensors:
            if not sensor.id or not (len(sensor.ref) == 2 and all(sensor.ref)):
                raise ValueError(f"profile {self.name!r} sensor {sensor.id!r} has a malformed property reference")

    def satisfied_by(self, defined: set[tuple[str, str]]) -> bool:
        """Whether every ``(name, kind)`` pair of the signature is among *defined*."""
        return self.signature <= defined


class SwitchProfileRegistry:
    """The profiles plugins have registered (PLUG-210). Each entry remembers its owning plugin and an
    optional liveness probe, so a disabled plugin's profiles are simply not offered (PLUG-060) and a
    removed plugin's are dropped (PLUG-120)."""

    _entries: ClassVar[list[tuple[SwitchProfile, str, Callable[[], bool] | None]]] = []
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def register(cls, profile: SwitchProfile, owner: str = "", is_active: Callable[[], bool] | None = None) -> None:
        """Add *profile* (already validated); a profile of the same name from the same owner is replaced."""
        with cls._lock:
            cls._entries[:] = [e for e in cls._entries if not (e[0].name == profile.name and e[1] == owner)]
            cls._entries.append((profile, owner, is_active))

    @classmethod
    def unregister_owner(cls, owner: str) -> None:
        with cls._lock:
            cls._entries[:] = [e for e in cls._entries if e[1] != owner]

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._entries.clear()

    @classmethod
    def profiles(cls) -> list[SwitchProfile]:
        """Every offered profile — those whose owning plugin is enabled."""
        with cls._lock:
            entries = list(cls._entries)
        out: list[SwitchProfile] = []
        for profile, owner, probe in entries:
            try:
                if probe is None or probe():
                    out.append(profile)
            except Exception:
                logger.exception("Liveness probe for switch profile %r (plugin %r) failed", profile.name, owner)
        return out

    @classmethod
    def claimed_device_names(cls) -> set[str]:
        return {name for p in cls.profiles() for name in p.device_names}

    @classmethod
    def profiles_for_name(cls, device_name: str) -> list[SwitchProfile]:
        return [p for p in cls.profiles() if device_name in p.device_names]


class ProfileResolution:
    """The outcome of matching a connected device to a profile (EQP-SW-080)."""

    __slots__ = ("ambiguous", "profile")

    def __init__(self, profile: SwitchProfile | None = None, ambiguous: list[str] | None = None) -> None:
        self.profile = profile
        self.ambiguous = ambiguous or []


def resolve_profile(device_name: str, defined: set[tuple[str, str]]) -> ProfileResolution:
    """Pick the profile for *device_name* by property signature, never by name alone: among the profiles
    claiming the name whose full signature is defined on the device, the one with the largest signature
    wins. No match gives an empty resolution; a tie between profiles is reported rather than guessed."""
    satisfied = [p for p in SwitchProfileRegistry.profiles_for_name(device_name) if p.satisfied_by(defined)]
    if not satisfied:
        return ProfileResolution()
    best = max(len(p.signature) for p in satisfied)
    top = [p for p in satisfied if len(p.signature) == best]
    if len(top) > 1:
        return ProfileResolution(ambiguous=[p.name for p in top])
    return ProfileResolution(profile=top[0])
