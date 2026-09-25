# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Device abstraction layer — ports and adapters core (ARCH-010 … ARCH-080).

This module defines the abstract device interfaces ("ports") that all device
backends must implement, plus the DevicePool registry that holds live device
connections per Pier.  No INDI, Alpaca, or Qt dependency lives here.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from enum import Enum
from typing import TYPE_CHECKING, Protocol, cast

from galileo.core.capabilities import ConnectionState, DeviceCapabilities
from galileo.core.monitor import ConnectionMonitor as ConnectionMonitor  # re-exported so importers find it here

if TYPE_CHECKING:
    from galileo.bus import EventBus

logger = logging.getLogger(__name__)

# Concurrency model identifier (SDD §2.3); the executor itself is galileo.core.compute.
CONCURRENCY_MODEL = "ProcessPoolExecutor"


class DeviceCategory(str, Enum):
    """Supported device categories, one per hardware type."""
    CAMERA = "Camera"
    MOUNT = "Mount"
    FILTER_WHEEL = "FilterWheel"
    FOCUSER = "Focuser"
    ROTATOR = "Rotator"
    GUIDER = "Guider"
    SWITCH = "Switch"
    FLAT_PANEL = "FlatPanel"
    WEATHER_STATION = "WeatherStation"
    DOME = "Dome"
    SAFETY_MONITOR = "SafetyMonitor"


class DeviceBackend(ABC):
    """Abstract base class (port) for all device backends.

    Every INDI, Alpaca, or plugin adapter for a specific device category
    must subclass this and implement the four abstract methods.
    """

    # Registry: DeviceCategory → list[type[DeviceBackend]]
    registered_backends: dict[DeviceCategory, list[type[DeviceBackend]]] = defaultdict(list)

    backend: str = "unknown"  # overridden by each concrete adapter class
    device_type: str  # every concrete adapter sets this in __init__ (its DeviceCategory.value)

    @abstractmethod
    async def connect(self) -> None:
        """Open the connection to the device."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection to the device."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True when the device is currently connected."""

    @abstractmethod
    def get_capabilities(self) -> DeviceCapabilities:
        """Return the device's advertised capabilities."""

    def get_properties(self) -> dict:
        """Return the device's current raw properties as a flat dict."""
        return {}

    async def set_property(self, name: str, value: object) -> None:
        """Set a raw device property by name."""

    async def get_driver_info(self) -> dict[str, str | None]:
        """Identify the driver behind this device, for the Equipment pages'
        "Driver info" / "Driver version" display.

        Returns ``name``, ``description``, ``driver_info`` and
        ``driver_version`` (each ``None`` if the driver doesn't report it).
        Both real transports allow this *before* the device is connected
        (ASCOM's ``DriverInfo``/``DriverVersion`` and INDI's ``DRIVER_INFO``
        are readable while disconnected), so a page can show it as soon as
        a device is picked from a scan. Backends that cannot report driver
        details return an empty dict.
        """
        return {}


# ---------------------------------------------------------------------------
# Category-specific backend protocols
#
# Every concrete adapter (galileo.adapters.indi / .alpaca / a plugin) implements
# far more than the four DeviceBackend abstract methods — the category-specific
# surface (start_exposure, slew_to_coordinates, move_to_angle, ...) that its
# *Controller counterpart below actually drives. DeviceBackend itself can't
# declare those, since they differ per category; these Protocols let each
# *Controller narrow its self._backend to what it actually calls, via cast(),
# without weakening DeviceBackend's own shared abstract interface.
# ---------------------------------------------------------------------------

class _CameraBackend(Protocol):
    async def start_exposure(self, *, duration: float, gain: int, offset: int,
                              binning: int, frame_type: str) -> None: ...
    async def abort_exposure(self) -> None: ...
    async def set_temperature(self, temp_c: float) -> None: ...
    def get_temperature(self) -> float: ...
    def get_cooler_power(self) -> float: ...
    async def warm_up(self) -> None: ...


class _MountBackend(Protocol):
    async def slew_to_coordinates(self, *, ra: float, dec: float) -> None: ...
    async def abort_slew(self) -> None: ...
    async def park(self) -> None: ...
    async def unpark(self) -> None: ...
    async def set_tracking(self, *, enabled: bool) -> None: ...
    async def set_tracking_rate(self, *, ra_rate_arcsec_s: float, dec_rate_arcsec_s: float) -> None: ...
    async def sync_to_coordinates(self, *, ra: float, dec: float) -> None: ...


class _FilterWheelBackend(Protocol):
    filter_names: list[str]
    async def move_to(self, position: int) -> None: ...


class _FocuserBackend(Protocol):
    position: int
    temperature: float
    async def move_to(self, position: int) -> None: ...
    async def move_by(self, steps: int) -> None: ...


class _RotatorBackend(Protocol):
    async def move_to_angle(self, angle: float) -> None: ...


class _FlatPanelBackend(Protocol):
    async def open_cover(self) -> None: ...
    async def close_cover(self) -> None: ...
    async def set_brightness(self, level: int) -> None: ...


class _WeatherBackend(Protocol):
    async def poll(self) -> None: ...


class _DomeBackend(Protocol):
    async def slew_to_azimuth(self, azimuth: float) -> None: ...
    async def open_shutter(self) -> None: ...
    async def close_shutter(self) -> None: ...
    async def park(self) -> None: ...


class _SafetyMonitorBackend(Protocol):
    is_safe: bool
    async def poll(self) -> None: ...


class _SwitchBackend(Protocol):
    async def set_switch(self, name: str, value: object) -> None: ...


# ---------------------------------------------------------------------------
# Device pool
# ---------------------------------------------------------------------------

class DevicePool:
    """Container for all device backend instances belonging to one Pier.

    Satisfies ARCH-080 (one pool per Pier) and ARCH-060 (fault isolation).
    """

    def __init__(self, pier_name: str = "default", event_bus: EventBus | None = None) -> None:
        self.pier_name = pier_name
        self._event_bus = event_bus
        self._devices: dict[str, DeviceBackend] = {}

    def register(self, backend: DeviceBackend) -> None:
        """Add *backend* to this pool, keyed on its ``device_type``."""
        self._devices[backend.device_type] = backend

    def get(self, category: str | DeviceCategory) -> DeviceBackend | None:
        """Return the device for *category*, or ``None`` if not registered."""
        key = category.value if isinstance(category, DeviceCategory) else str(category)
        return self._devices.get(key)

    def get_properties(self, device_name: str) -> dict:
        """Return properties for the named device; returns {} on error (ARCH-060)."""
        device = self._devices.get(device_name)
        if device is None:
            for candidate in self._devices.values():
                if getattr(candidate, "name", None) == device_name:
                    device = candidate
                    break
        if device is None:
            return {}
        try:
            return device.get_properties()
        except Exception:
            logger.exception("Error reading properties from device %r", device_name)
            return {}

    def poll_all(self) -> None:
        """Refresh all devices; a failing device does not block others (ARCH-060)."""
        for name, device in list(self._devices.items()):
            try:
                device.get_properties()
            except Exception:
                logger.exception("Device %r raised an exception during poll; skipping", name)

    async def connect_all(self) -> None:
        """Connect all registered devices concurrently."""
        await asyncio.gather(
            *(dev.connect() for dev in self._devices.values()),
            return_exceptions=True,
        )


# ---------------------------------------------------------------------------
# Device controller (thin wrapper over a backend)
# ---------------------------------------------------------------------------

class DeviceController:
    """Wraps a *DeviceBackend* with error handling and event publication."""

    def __init__(self, backend: DeviceBackend, event_bus: EventBus | None = None) -> None:
        self._backend = backend
        self._event_bus = event_bus

    @property
    def is_connected(self) -> bool:
        return self._backend.is_connected

    def connection_state(self) -> ConnectionState:
        if getattr(self._backend, "has_error", False):
            return ConnectionState.ERROR
        if self._backend.is_connected:
            return ConnectionState.CONNECTED
        return ConnectionState.DISCONNECTED

    def get_properties(self) -> dict:
        raw = self._backend.get_properties()
        return raw if isinstance(raw, dict) else {}

    def set_property(self, name: str, value: object) -> None:
        # Call synchronously if the backend's set_property is not a coroutine
        import asyncio
        import inspect
        result = self._backend.set_property(name, value)
        if inspect.isawaitable(result):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(result)
                else:
                    loop.run_until_complete(result)
            except RuntimeError:
                pass  # no event loop — best-effort

    async def connect(self) -> None:
        from galileo.bus import DeviceConnectedEvent, DeviceErrorEvent
        import datetime
        try:
            await self._backend.connect()
            if self._event_bus:
                self._event_bus.publish(
                    DeviceConnectedEvent(
                        source=getattr(self._backend, "name", ""),
                        timestamp=datetime.datetime.utcnow().isoformat(),
                    )
                )
        except Exception as exc:
            if self._event_bus:
                self._event_bus.publish(
                    DeviceErrorEvent(
                        source=getattr(self._backend, "name", ""),
                        timestamp=datetime.datetime.utcnow().isoformat(),
                        error=str(exc),
                    )
                )
            raise

    async def disconnect(self) -> None:
        await self._backend.disconnect()


# ---------------------------------------------------------------------------
# Property inspector
# ---------------------------------------------------------------------------

class DevicePropertyInspector:
    """Exposes all raw device properties for diagnostic/expert use (EQP-060)."""

    def __init__(self, backend: DeviceBackend) -> None:
        self._backend = backend

    def get_all_raw_properties(self) -> dict:
        return self._backend.get_properties()


# ---------------------------------------------------------------------------
# Specialised controllers (thin layer over DeviceController)
# ---------------------------------------------------------------------------

class CameraController(DeviceController):
    """Controls a camera device (EQP-CAM-010 … EQP-CAM-040)."""

    async def start_exposure(self, duration: float, gain: int = 0, offset: int = 0,
                              binning: int = 1, frame_type: str = "Light") -> None:
        await cast(_CameraBackend, self._backend).start_exposure(
            duration=duration, gain=gain, offset=offset,
            binning=binning, frame_type=frame_type,
        )

    async def abort_exposure(self) -> None:
        await cast(_CameraBackend, self._backend).abort_exposure()

    async def get_image_array(self):
        return await self._backend.get_image_array()

    async def set_target_temperature(self, temp_c: float) -> None:
        await cast(_CameraBackend, self._backend).set_temperature(temp_c)

    def get_temperature(self) -> float:
        return cast(_CameraBackend, self._backend).get_temperature()

    def get_cooler_power(self) -> float:
        return cast(_CameraBackend, self._backend).get_cooler_power()

    async def warm_up(self) -> None:
        await cast(_CameraBackend, self._backend).warm_up()


class MountController(DeviceController):
    """Controls a mount device (EQP-MNT-010 … EQP-MNT-040)."""

    def get_status(self) -> dict:
        b = self._backend
        return {
            "ra": getattr(b, "ra", None),
            "dec": getattr(b, "dec", None),
            "altitude": getattr(b, "altitude", None),
            "azimuth": getattr(b, "azimuth", None),
            "pier_side": getattr(b, "pier_side", None),
            "is_tracking": getattr(b, "is_tracking", None),
            "is_slewing": getattr(b, "is_slewing", None),
        }

    async def slew_to_coordinates(self, ra: float, dec: float) -> None:
        await cast(_MountBackend, self._backend).slew_to_coordinates(ra=ra, dec=dec)

    async def abort_slew(self) -> None:
        await cast(_MountBackend, self._backend).abort_slew()

    async def park(self) -> None:
        await cast(_MountBackend, self._backend).park()

    async def unpark(self) -> None:
        await cast(_MountBackend, self._backend).unpark()

    async def set_tracking(self, enabled: bool) -> None:
        await cast(_MountBackend, self._backend).set_tracking(enabled=enabled)

    async def set_tracking_rate(self, ra_rate_arcsec_s: float, dec_rate_arcsec_s: float) -> None:
        await cast(_MountBackend, self._backend).set_tracking_rate(
            ra_rate_arcsec_s=ra_rate_arcsec_s,
            dec_rate_arcsec_s=dec_rate_arcsec_s,
        )

    async def sync_to_coordinates(self, ra: float, dec: float) -> None:
        await cast(_MountBackend, self._backend).sync_to_coordinates(ra=ra, dec=dec)


class FilterWheelController(DeviceController):
    """Controls a filter wheel (EQP-FW-010 … EQP-FW-020)."""

    def __init__(self, backend: DeviceBackend, event_bus=None) -> None:
        super().__init__(backend, event_bus)
        self._focus_offsets: dict[str, int] = {}

    def get_filter_names(self) -> list[str]:
        return list(cast(_FilterWheelBackend, self._backend).filter_names)

    async def move_to_filter(self, filter_name: str) -> None:
        backend = cast(_FilterWheelBackend, self._backend)
        idx = backend.filter_names.index(filter_name)
        await backend.move_to(idx)

    def set_focus_offset(self, filter_name: str, offset_steps: int) -> None:
        self._focus_offsets[filter_name] = offset_steps

    def get_focus_offset(self, filter_name: str) -> int:
        return self._focus_offsets.get(filter_name, 0)


class FocuserController(DeviceController):
    """Controls a focuser (EQP-FOC-010 … EQP-FOC-030)."""

    def __init__(self, backend: DeviceBackend, event_bus=None, backlash_steps: int = 0) -> None:
        super().__init__(backend, event_bus)
        self.backlash_steps = backlash_steps

    def get_position(self) -> int:
        return int(cast(_FocuserBackend, self._backend).position)

    def get_temperature(self) -> float:
        return float(cast(_FocuserBackend, self._backend).temperature)

    def _clamp_position(self, position: int) -> int:
        """Clamp *position* to the focuser's valid travel range, 0..MaxStep
        (EQP-FOC-030).

        A real ASCOM/Alpaca ``IFocuserV3`` driver is documented to hard-stop
        at these limits itself rather than raise, but INDI focuser drivers
        make no equivalent universal guarantee, and even where the hardware
        does protect itself, silently trusting a rejected/clamped move would
        leave this controller's cached position out of sync with reality.
        Clamping here — logged, not silent — is the one guard that applies
        the same way across both transports. ``max_step`` is read from
        whatever the connected backend reports (``None`` if the backend
        hasn't discovered it, e.g. before connecting), in which case only
        the 0 floor is enforced.
        """
        max_step = getattr(self._backend, "max_step", None)
        if not isinstance(max_step, (int, float)):
            max_step = None
        clamped = max(position, 0)
        if max_step is not None and clamped > max_step:
            clamped = int(max_step)
        if clamped != position:
            logger.warning(
                "Focuser move to %d is outside the valid travel range (0..%s); clamping to %d.",
                position, max_step, clamped,
            )
        return clamped

    async def move_to(self, position: int) -> None:
        position = self._clamp_position(position)
        backend = cast(_FocuserBackend, self._backend)
        if self.backlash_steps > 0:
            # Overshoot then return to apply backlash compensation
            overshoot = self._clamp_position(position - self.backlash_steps)
            await backend.move_to(overshoot)
        await backend.move_to(position)

    async def move_by(self, steps: int) -> None:
        current = self.get_position()
        target = self._clamp_position(current + steps)
        await cast(_FocuserBackend, self._backend).move_by(target - current)


class RotatorController(DeviceController):
    """Controls a rotator (EQP-ROT-010)."""

    def get_status(self) -> dict:
        return {
            "mechanical_angle": getattr(self._backend, "mechanical_angle", None),
            "sky_angle": getattr(self._backend, "sky_angle", None),
        }

    async def move_to_angle(self, angle: float) -> None:
        await cast(_RotatorBackend, self._backend).move_to_angle(angle)


class FlatPanelController(DeviceController):
    """Controls a flat panel (EQP-FP-010)."""

    async def open_cover(self) -> None:
        await cast(_FlatPanelBackend, self._backend).open_cover()

    async def close_cover(self) -> None:
        await cast(_FlatPanelBackend, self._backend).close_cover()

    async def set_brightness(self, level: int) -> None:
        await cast(_FlatPanelBackend, self._backend).set_brightness(level)


class WeatherController(DeviceController):
    """Controls a weather station (EQP-WX-010)."""

    def __init__(self, backend: DeviceBackend, event_bus=None, poll_interval_s: int = 60) -> None:
        super().__init__(backend, event_bus)
        self.poll_interval_s = poll_interval_s

    async def poll(self) -> None:
        await cast(_WeatherBackend, self._backend).poll()

    def get_readings(self) -> dict:
        b = self._backend
        return {
            "cloud_cover": getattr(b, "cloud_cover", None),
            "wind_speed": getattr(b, "wind_speed", None),
            "humidity": getattr(b, "humidity", None),
            "temperature": getattr(b, "temperature", None),
            "rain_rate": getattr(b, "rain_rate", None),
        }


class DomeController(DeviceController):
    """Controls a dome device (EQP-DOME-010)."""

    async def slew_to_azimuth(self, azimuth: float) -> None:
        await cast(_DomeBackend, self._backend).slew_to_azimuth(azimuth)

    async def open_shutter(self) -> None:
        await cast(_DomeBackend, self._backend).open_shutter()

    async def close_shutter(self) -> None:
        await cast(_DomeBackend, self._backend).close_shutter()

    async def park(self) -> None:
        await cast(_DomeBackend, self._backend).park()

    def get_status(self) -> dict:
        b = self._backend
        return {
            "azimuth": getattr(b, "azimuth", None),
            "shutter_state": getattr(b, "shutter_state", None),
            "is_at_park": getattr(b, "is_at_park", None),
        }


class SafetyMonitorController(DeviceController):
    """Controls a safety monitor device (EQP-SAFE-010)."""

    def __init__(self, backend: DeviceBackend, event_bus=None) -> None:
        super().__init__(backend, event_bus)
        self._is_safe = True
        self._explanation = ""
        self.last_abort_trigger: str = ""

    @property
    def is_safe(self) -> bool:
        return self._is_safe

    @property
    def explanation(self) -> str:
        return self._explanation

    async def poll(self) -> None:
        from galileo.bus import SafetyUnsafeEvent
        import datetime

        backend = cast(_SafetyMonitorBackend, self._backend)
        await backend.poll()
        new_safe = backend.is_safe
        new_expl = getattr(self._backend, "explanation", "")

        if not new_safe and (self._is_safe or new_expl != self._explanation):
            if self._event_bus:
                self._event_bus.publish(
                    SafetyUnsafeEvent(
                        source=getattr(self._backend, "name", ""),
                        explanation=new_expl,
                        timestamp=datetime.datetime.utcnow().isoformat(),
                    )
                )
            self.last_abort_trigger = f"SafetyMonitor:{getattr(self._backend, 'name', '')}"

        self._is_safe = new_safe
        self._explanation = new_expl


class GuiderController(DeviceController):
    """Exposes guider connect/start/stop/dither (EQP-GDR-010)."""

    def __init__(self, guiding_service=None) -> None:
        self._service = guiding_service

    @property
    def is_connected(self) -> bool:
        return getattr(self._service, "is_connected", False)

    async def start_guiding(self) -> None:
        await self._service.start_guiding()

    async def stop_guiding(self) -> None:
        await self._service.stop_guiding()

    async def dither(self) -> None:
        await self._service.dither()


class SwitchController(DeviceController):
    """Controls switch/relay devices (EQP-SW-010)."""

    def list_switches(self) -> list:
        return list(getattr(self._backend, "switches", []))

    async def set_switch(self, name: str, value) -> None:
        await cast(_SwitchBackend, self._backend).set_switch(name, value)
