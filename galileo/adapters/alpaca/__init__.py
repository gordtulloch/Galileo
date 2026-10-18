# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""ASCOM Alpaca adapter (galileo.adapters.alpaca).

Communicates with Alpaca devices via HTTP/REST per the ASCOM Alpaca
specification, including UDP discovery.  Uses ``httpx`` where available
for async HTTP; falls back to ``urllib`` for minimal dependency footprint.

The package splits the adapters by device category (one module each, on top of the shared
:class:`~galileo.adapters.alpaca._base.AlpacaAdapter`); everything is re-exported here so
``from galileo.adapters.alpaca import AlpacaCameraAdapter`` keeps working.
"""

from __future__ import annotations

from galileo.adapters.alpaca._base import (
    _ALPACA_WIRE_TYPE,
    _MDNS_TIMEOUT_MS,
    _TRANSPORT_ERRORS,
    AlpacaAdapter,
    resolve_mdns_host_sync,
)
from galileo.adapters.alpaca.camera import AlpacaCameraAdapter
from galileo.adapters.alpaca.discovery import _ALPACA_DISCOVERY_MSG, _ALPACA_DISCOVERY_PORT, AlpacaDiscovery
from galileo.adapters.alpaca.dome import AlpacaDomeAdapter
from galileo.adapters.alpaca.filter_wheel import AlpacaFWAdapter
from galileo.adapters.alpaca.focuser import AlpacaFocuserAdapter
from galileo.adapters.alpaca.misc import (
    AlpacaFlatPanelAdapter,
    AlpacaGuiderAdapter,
    AlpacaSafetyMonitorAdapter,
    AlpacaWeatherAdapter,
)
from galileo.adapters.alpaca.mount import AlpacaMountAdapter
from galileo.adapters.alpaca.rotator import AlpacaRotatorAdapter
from galileo.adapters.alpaca.switch import AlpacaAuxAdapter, AlpacaSwitchAdapter, _is_boolean_switch_range
from galileo.core.devices import DeviceBackend, DeviceCategory

__all__ = [
    '_ALPACA_DISCOVERY_MSG',
    '_ALPACA_DISCOVERY_PORT',
    '_ALPACA_WIRE_TYPE',
    '_MDNS_TIMEOUT_MS',
    '_TRANSPORT_ERRORS',
    'AlpacaAdapter',
    'AlpacaAuxAdapter',
    'AlpacaCameraAdapter',
    'AlpacaDiscovery',
    'AlpacaDomeAdapter',
    'AlpacaFWAdapter',
    'AlpacaFlatPanelAdapter',
    'AlpacaFocuserAdapter',
    'AlpacaGuiderAdapter',
    'AlpacaMountAdapter',
    'AlpacaRotatorAdapter',
    'AlpacaSafetyMonitorAdapter',
    'AlpacaSwitchAdapter',
    'AlpacaWeatherAdapter',
    '_is_boolean_switch_range',
    'get_adapter_class',
    'resolve_mdns_host_sync',
]


def get_adapter_class(category: DeviceCategory) -> type[DeviceBackend]:
    """Return the Alpaca adapter class for *category*."""
    _MAP = {
        DeviceCategory.CAMERA: AlpacaCameraAdapter,
        DeviceCategory.MOUNT: AlpacaMountAdapter,
        DeviceCategory.FILTER_WHEEL: AlpacaFWAdapter,
        DeviceCategory.FOCUSER: AlpacaFocuserAdapter,
        DeviceCategory.ROTATOR: AlpacaRotatorAdapter,
        DeviceCategory.DOME: AlpacaDomeAdapter,
        DeviceCategory.SAFETY_MONITOR: AlpacaSafetyMonitorAdapter,
        DeviceCategory.SWITCH: AlpacaSwitchAdapter,
        DeviceCategory.WEATHER_STATION: AlpacaWeatherAdapter,
        DeviceCategory.GUIDER: AlpacaGuiderAdapter,
        DeviceCategory.FLAT_PANEL: AlpacaFlatPanelAdapter,
        DeviceCategory.AUX: AlpacaAuxAdapter,
    }
    cls = _MAP.get(category)
    if cls is None:
        raise ValueError(f"No Alpaca adapter for category {category!r}")
    return cls
