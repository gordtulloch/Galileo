# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Plugin framework — loading, versioning, and context (PLUG-010 … PLUG-080)."""

from __future__ import annotations

import importlib
import logging
import warnings
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

_CURRENT_API_VERSION = "1"


class PluginApiVersionWarning(UserWarning):
    """Raised when a plugin declares an incompatible API version."""


class ServiceAccessDenied(Exception):
    """Plugin attempted to access a service it was not granted."""


# ---------------------------------------------------------------------------
# Plugin base class
# ---------------------------------------------------------------------------

class PluginBase(ABC):
    """Every plugin must subclass ``PluginBase`` and declare metadata."""
    name: str = ""
    version: str = "0.0.0"
    api_version: str = "1"
    panel_level: str = "secondary"
    panel_label: str = ""

    @abstractmethod
    def activate(self, ctx: "PluginContext") -> None:
        """Called when the plugin is enabled."""

    @abstractmethod
    def deactivate(self) -> None:
        """Called when the plugin is disabled."""


# ---------------------------------------------------------------------------
# Plugin context (PLUG-080)
# ---------------------------------------------------------------------------

class PluginContext:
    """Provides a controlled API surface for a plugin to call core services."""

    def __init__(self, granted_services: dict[str, Any] | None = None) -> None:
        self._services = granted_services or {}

    def get_service(self, name: str) -> Any:
        if name not in self._services:
            raise ServiceAccessDenied(f"Plugin has not been granted access to service {name!r}")
        return self._services[name]

    def register_device_backend(self, category, adapter_cls) -> None:
        """Register a new device backend for *category* (PLUG-010, ARCH-070)."""
        from galileo.core.devices import DeviceBackend
        DeviceBackend.registered_backends[category].append(adapter_cls)

    def register_instruction_type(self, instruction_cls) -> None:
        """Register a new sequencer instruction type (PLUG-020, SEQ-ADV-070)."""
        from galileo.sequencer.advanced import InstructionRegistry
        InstructionRegistry.instance().register(instruction_cls)


# ---------------------------------------------------------------------------
# UI panel registry
# ---------------------------------------------------------------------------

class UiPanel:
    def __init__(self, label: str, level: str, plugin: PluginBase) -> None:
        self.label = label
        self.level = level
        self.plugin = plugin


class UiRegistry:
    def __init__(self) -> None:
        self._panels: list[UiPanel] = []

    def register(self, panel: UiPanel) -> None:
        self._panels.append(panel)

    def get_primary_panels(self) -> list[UiPanel]:
        return [p for p in self._panels if p.level == "primary"]

    def get_secondary_panels(self) -> list[UiPanel]:
        return [p for p in self._panels if p.level == "secondary"]


# ---------------------------------------------------------------------------
# Plugin manager
# ---------------------------------------------------------------------------

class PluginManager:
    """Discovers, loads, enables, and disables plugins (PLUG-030 … PLUG-080)."""

    def __init__(self) -> None:
        self._loaded: dict[str, PluginBase] = {}
        self._active: dict[str, bool] = {}
        self._faulted: set[str] = set()
        self._ui_registry = UiRegistry()

    def create_context(self, granted_services: dict | None = None) -> PluginContext:
        return PluginContext(granted_services=granted_services)

    # --- Introspection ---------------------------------------------------

    def list_available(self) -> list[str]:
        """Return names of plugins available in the configured repository."""
        return []

    def is_loaded(self, name: str) -> bool:
        return name in self._loaded

    def is_active(self, name: str) -> bool:
        return self._active.get(name, False)

    def is_faulted(self, name: str) -> bool:
        return name in self._faulted

    # --- Load / unload ---------------------------------------------------

    def load(self, plugin_cls: type[PluginBase]) -> None:
        """Instantiate and activate *plugin_cls*; isolates exceptions (PLUG-040)."""
        # Version check (PLUG-050)
        if plugin_cls.api_version != _CURRENT_API_VERSION:
            warnings.warn(
                f"Plugin {plugin_cls.name!r} declares API version {plugin_cls.api_version!r}; "
                f"current is {_CURRENT_API_VERSION!r}",
                PluginApiVersionWarning,
                stacklevel=2,
            )

        try:
            instance = plugin_cls()
            ctx = self.create_context()
            instance.activate(ctx)
            self._loaded[plugin_cls.name] = instance
            self._active[plugin_cls.name] = True

            # Register UI panel if declared (PLUG-070)
            if getattr(plugin_cls, "panel_label", ""):
                panel = UiPanel(
                    label=plugin_cls.panel_label,
                    level=getattr(plugin_cls, "panel_level", "secondary"),
                    plugin=instance,
                )
                self._ui_registry.register(panel)

        except Exception:
            logger.exception("Plugin %r failed to activate; marking faulted", plugin_cls.name)
            self._faulted.add(plugin_cls.name)

    def unload(self, name: str) -> None:
        plugin = self._loaded.pop(name, None)
        if plugin:
            try:
                plugin.deactivate()
            except Exception:
                logger.exception("Plugin %r raised during deactivation", name)
        self._active.pop(name, None)

    def enable(self, name: str) -> None:
        if name in self._loaded:
            self._active[name] = True

    def disable(self, name: str) -> None:
        self._active[name] = False

    def get_ui_panels(self, name: str) -> list:
        if not self.is_active(name):
            return []
        plugin = self._loaded.get(name)
        if plugin is None:
            return []
        return [p for p in self._ui_registry._panels if p.plugin is plugin]

    def get_ui_registry(self) -> UiRegistry:
        return self._ui_registry

    # --- Install / remove (PLUG-030) ------------------------------------

    def install(self, package_name: str) -> None:
        raise NotImplementedError("Plugin marketplace not yet implemented")

    def update(self, plugin_name: str) -> None:
        raise NotImplementedError("Plugin marketplace not yet implemented")

    def remove(self, plugin_name: str) -> None:
        self.unload(plugin_name)

    # --- First-party pre-loaded plugins (PLUG-060) ----------------------

    def initialize_preloaded(self) -> None:
        """Load the first-party bundled plugins."""
        from galileo.plugins.vstarget import VSTPlugin, VSTAnalysisPlugin
        self.load(VSTPlugin)
        self.load(VSTAnalysisPlugin)
