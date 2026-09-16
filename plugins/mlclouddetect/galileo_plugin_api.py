"""Local stub of the Galileo plugin API surface.

Mirrors the interfaces described in docs/SDD.md:
- Section 4.1 (galileo.core.devices — device ports, DeviceCapabilities)
- Section 4.20 (galileo.plugins — PluginContext, plugin manifest)

This stub exists only because the `galileo` package has no implementation
yet (the project is at the SRS/SDD stage). Once galileo.core.devices and
galileo.plugins exist as real code, replace the imports in this plugin with:

    from galileo.core.devices import SafetyMonitorPort, DeviceCapabilities, DeviceStatus
    from galileo.plugins import PluginContext, PluginManifest

and delete this file.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeviceCapabilities:
    can_report_safety: bool = False
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DeviceStatus:
    connected: bool
    safe: bool
    detail: str = ""


class SafetyMonitorPort(ABC):
    """Port interface for a safety-monitor device or plugin-provided equivalent."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def capabilities(self) -> DeviceCapabilities: ...

    @property
    @abstractmethod
    def is_safe(self) -> bool: ...

    @property
    @abstractmethod
    def status(self) -> DeviceStatus: ...


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    api_compat_range: str
    description: str = ""


@dataclass
class PluginContext:
    """Injected into every plugin at load time (SDD Section 6.3)."""

    log: logging.Logger
    config_dir: str
