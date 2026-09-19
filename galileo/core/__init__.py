# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""galileo.core package — device abstraction layer."""

from galileo.core.capabilities import ConnectionState, DeviceCapabilities
from galileo.core.devices import (
    CONCURRENCY_MODEL,
    CameraController,
    DeviceBackend,
    DeviceCategory,
    DeviceController,
    DevicePool,
    DevicePropertyInspector,
    DomeController,
    FilterWheelController,
    FlatPanelController,
    FocuserController,
    GuiderController,
    MountController,
    RotatorController,
    SafetyMonitorController,
    SwitchController,
    WeatherController,
)
from galileo.core.monitor import ConnectionMonitor

__all__ = [
    "CONCURRENCY_MODEL",
    "CameraController",
    "ConnectionMonitor",
    "ConnectionState",
    "DeviceBackend",
    "DeviceCapabilities",
    "DeviceCategory",
    "DeviceController",
    "DevicePool",
    "DevicePropertyInspector",
    "DomeController",
    "FilterWheelController",
    "FlatPanelController",
    "FocuserController",
    "GuiderController",
    "MountController",
    "RotatorController",
    "SafetyMonitorController",
    "SwitchController",
    "WeatherController",
]
