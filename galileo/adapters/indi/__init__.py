"""INDI protocol adapter (galileo.adapters.indi).

Talks to an INDI server through the native protocol client in
:mod:`galileo.adapters.indi_client` (XML over TCP, no C extension, so it also
works on Windows where ``pyindi-client`` cannot be built). Each adapter
targets one named INDI device on a server and translates Galileo's device
port methods into that device's standard INDI properties
(``CCD_EXPOSURE``, ``EQUATORIAL_EOD_COORD``, ``ABS_FOCUS_POSITION``, ...).

The package splits the adapters by device category (one module each, on top of the shared
:class:`~galileo.adapters.indi._base.IndiAdapter`); everything is re-exported here so
``from galileo.adapters.indi import IndiCameraAdapter`` keeps working.
"""

from __future__ import annotations

from galileo.adapters.indi._base import _INTERFACE_MASK, IndiAdapter
from galileo.adapters.indi.camera import IndiCameraAdapter, IndiCameraSimulator
from galileo.adapters.indi.dome import IndiDomeAdapter
from galileo.adapters.indi.filter_wheel import IndiFWAdapter
from galileo.adapters.indi.flat_panel import IndiFlatPanelAdapter
from galileo.adapters.indi.focuser import IndiFocuserAdapter
from galileo.adapters.indi.misc import IndiAuxAdapter, IndiGuiderAdapter, IndiSafetyMonitorAdapter, IndiSwitchAdapter
from galileo.adapters.indi.mount import IndiMountAdapter
from galileo.adapters.indi.rotator import IndiRotatorAdapter
from galileo.adapters.indi.weather import IndiWeatherAdapter
from galileo.core.devices import DeviceBackend, DeviceCategory

__all__ = [
    "_INTERFACE_MASK",
    "IndiAdapter",
    "IndiAuxAdapter",
    "IndiCameraAdapter",
    "IndiCameraSimulator",
    "IndiDomeAdapter",
    "IndiFWAdapter",
    "IndiFlatPanelAdapter",
    "IndiFocuserAdapter",
    "IndiGuiderAdapter",
    "IndiMountAdapter",
    "IndiRotatorAdapter",
    "IndiSafetyMonitorAdapter",
    "IndiSwitchAdapter",
    "IndiWeatherAdapter",
    "get_adapter_class",
]


def get_adapter_class(category: DeviceCategory) -> type[DeviceBackend]:
    """Return the INDI adapter class for *category*."""
    _MAP = {
        DeviceCategory.CAMERA: IndiCameraAdapter,
        DeviceCategory.MOUNT: IndiMountAdapter,
        DeviceCategory.FILTER_WHEEL: IndiFWAdapter,
        DeviceCategory.FOCUSER: IndiFocuserAdapter,
        DeviceCategory.ROTATOR: IndiRotatorAdapter,
        DeviceCategory.FLAT_PANEL: IndiFlatPanelAdapter,
        DeviceCategory.WEATHER_STATION: IndiWeatherAdapter,
        DeviceCategory.DOME: IndiDomeAdapter,
        DeviceCategory.SAFETY_MONITOR: IndiSafetyMonitorAdapter,
        DeviceCategory.GUIDER: IndiGuiderAdapter,
        DeviceCategory.SWITCH: IndiSwitchAdapter,
        DeviceCategory.AUX: IndiAuxAdapter,
    }
    cls = _MAP.get(category)
    if cls is None:
        raise ValueError(f"No INDI adapter for category {category!r}")
    return cls
