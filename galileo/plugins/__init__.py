# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Plugin framework — loading, versioning, ZIP install, remove, and context (PLUG-010 … PLUG-120)."""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import shutil
import sys
import warnings
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CURRENT_API_VERSION = "1"

# Name of the JSON file written to a plugin's installed directory to record
# its pending-removal state across restarts.
_PENDING_REMOVAL_MARKER = ".pending_removal"


class PluginApiVersionWarning(UserWarning):
    """Raised when a plugin declares an incompatible API version."""


class ServiceAccessDenied(Exception):
    """Plugin attempted to access a service it was not granted."""


class PluginInstallError(Exception):
    """Raised when a plugin ZIP fails validation or installation."""


# ---------------------------------------------------------------------------
# Plugin manifest
# ---------------------------------------------------------------------------

@dataclass
class PluginManifest:
    """Parsed contents of a plugin's ``plugin.toml`` manifest."""
    name: str
    version: str
    api_min: str
    api_max: str
    author: str
    description: str
    tier: str                          # "first_party" | "third_party"
    nav_level: str = "secondary"       # "primary" | "secondary"
    entry_point: str = ""              # defaults to galileo.plugins.<name> if empty

    @classmethod
    def from_toml_text(cls, text: str) -> "PluginManifest":
        """Parse a ``plugin.toml`` string.  Uses the stdlib ``tomllib`` on
        Python 3.11+ (Galileo's floor — PSD §7) so no extra dependency."""
        import tomllib  # stdlib since 3.11
        data = tomllib.loads(text)
        required = ("name", "version", "api_min", "api_max", "author", "description", "tier")
        missing = [k for k in required if k not in data]
        if missing:
            raise PluginInstallError(f"plugin.toml missing required fields: {missing}")
        return cls(
            name=data["name"],
            version=data["version"],
            api_min=data["api_min"],
            api_max=data["api_max"],
            author=data["author"],
            description=data["description"],
            tier=data["tier"],
            nav_level=data.get("nav_level", "secondary"),
            entry_point=data.get("entry_point", ""),
        )

    @property
    def resolved_entry_point(self) -> str:
        ep = self.entry_point.strip()
        return ep if ep else f"galileo.plugins.{self.name}"


@dataclass
class PluginRecord:
    """A discovered, possibly-loaded installed plugin."""
    manifest: PluginManifest
    install_dir: Path
    enabled: bool = True
    loaded: bool = False
    faulted: bool = False
    loaded_names: list[str] = field(default_factory=list)


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

    def build_page(self) -> Any:
        """Return a QWidget for this plugin's main panel, or None for a placeholder."""
        return None


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
    """Discovers, loads, enables, disables, installs, and removes plugins
    (PLUG-030 … PLUG-120).

    Plugins are stored as extracted directories under ``get_plugins_dir()``,
    each containing a ``plugin.toml`` manifest.  No plugin is bundled in the
    Galileo installer; all plugins — including first-party ones — are obtained
    via :meth:`install` (from a local ZIP or a marketplace download).
    """

    def __init__(self) -> None:
        self._loaded: dict[str, PluginBase] = {}
        self._active: dict[str, bool] = {}
        self._faulted: set[str] = set()
        self._records: dict[str, PluginRecord] = {}
        self._ui_registry = UiRegistry()

    def create_context(self, granted_services: dict | None = None) -> PluginContext:
        return PluginContext(granted_services=granted_services)

    # --- Introspection ---------------------------------------------------

    def list_installed(self) -> list[PluginRecord]:
        """Return records for every plugin currently installed on disk."""
        return list(self._records.values())

    def list_available(self) -> list[str]:
        """Return names of installed plugins (kept for backward compatibility)."""
        return list(self._records.keys())

    def is_loaded(self, name: str) -> bool:
        return name in self._loaded

    def is_active(self, name: str) -> bool:
        return self._active.get(name, False)

    def is_faulted(self, name: str) -> bool:
        return name in self._faulted

    # --- Startup: scan plugins_dir and load enabled plugins ---------------

    def initialize_from_disk(self) -> None:
        """Scan ``get_plugins_dir()`` for installed plugins and load the
        enabled ones.  Deferred-removal markers are processed first."""
        from galileo.platform import get_plugins_dir
        plugins_dir = get_plugins_dir()

        # Finish any deferred removals from the previous run.
        for marker in plugins_dir.glob(f"*/{_PENDING_REMOVAL_MARKER}"):
            install_dir = marker.parent
            logger.info("Completing deferred removal of plugin directory %s", install_dir)
            try:
                shutil.rmtree(install_dir)
            except OSError:
                logger.exception("Could not remove plugin directory %s", install_dir)

        # Discover and load installed plugins.
        for toml_path in sorted(plugins_dir.glob("*/plugin.toml")):
            install_dir = toml_path.parent
            try:
                manifest = PluginManifest.from_toml_text(toml_path.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("Skipping plugin in %s — bad manifest", install_dir)
                continue

            record = PluginRecord(manifest=manifest, install_dir=install_dir, enabled=True)
            self._records[manifest.name] = record
            self._load_from_record(record)

    def initialize_preloaded(self) -> None:
        """Backward-compatible entry point: scan disk (no bundled plugins)."""
        self.initialize_from_disk()

    # --- Load / unload ---------------------------------------------------

    def _load_from_record(self, record: PluginRecord) -> None:
        """Import a plugin package, discover its ``PluginBase`` subclasses,
        and activate each one."""
        install_dir = record.install_dir
        if str(install_dir) not in sys.path:
            sys.path.insert(0, str(install_dir))
        try:
            mod = importlib.import_module(record.manifest.resolved_entry_point)
        except Exception:
            logger.exception("Plugin %r failed to import", record.manifest.name)
            self._faulted.add(record.manifest.name)
            record.faulted = True
            return

        self._register_help(mod)
        for attr_name in dir(mod):
            cls = getattr(mod, attr_name)
            if (
                isinstance(cls, type)
                and issubclass(cls, PluginBase)
                and cls is not PluginBase
                and cls.name
            ):
                self.load(cls)
                if cls.name in self._loaded:
                    record.loaded_names.append(cls.name)
        record.loaded = True

    @staticmethod
    def _register_help(mod: Any) -> None:
        """Pick up a plugin's own help (HELP-060): Markdown in a ``help/`` folder beside its entry
        module, named for the screen ids its pages use (``science.<plugin name>.md``)."""
        try:
            from galileo import help as help_content
            module_file = getattr(mod, "__file__", None)
            help_dir = Path(module_file).parent / "help" if module_file else None
            if help_dir is not None and help_dir.is_dir():
                help_content.register_dir(help_dir)
        except Exception:
            logger.exception("Could not register help for plugin module %r", getattr(mod, "__name__", mod))

    def load(self, plugin_cls: type[PluginBase]) -> None:
        """Instantiate and activate *plugin_cls*; isolates exceptions (PLUG-040)."""
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
        self._ui_registry._panels = [p for p in self._ui_registry._panels if p.plugin is not plugin]

    def enable(self, name: str) -> None:
        if name in self._loaded:
            self._active[name] = True
        if name in self._records:
            self._records[name].enabled = True

    def disable(self, name: str) -> None:
        self._active[name] = False
        if name in self._records:
            self._records[name].enabled = False

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable an installed plugin by name."""
        if enabled:
            self.enable(name)
        else:
            self.disable(name)

    def get_ui_panels(self, name: str) -> list:
        if not self.is_active(name):
            return []
        plugin = self._loaded.get(name)
        if plugin is None:
            return []
        return [p for p in self._ui_registry._panels if p.plugin is plugin]

    def get_ui_registry(self) -> UiRegistry:
        return self._ui_registry

    # --- Install (PLUG-090 / PLUG-110) ------------------------------------

    def install(self, zip_path: str | Path) -> PluginRecord:
        """Install a plugin from a local ZIP file (PLUG-090).

        Validates the ZIP, checks API compatibility, extracts to
        ``get_plugins_dir()/<name>-<version>/``, then loads the plugin.
        Rolls back (removes the extracted directory) on any failure.

        Returns the new :class:`PluginRecord` on success.
        Raises :class:`PluginInstallError` on any validation or load failure.
        """
        from galileo.platform import get_plugins_dir

        zip_path = Path(zip_path)
        if not zip_path.exists():
            raise PluginInstallError(f"ZIP file not found: {zip_path}")

        # --- 1. Validate archive and manifest ---
        try:
            zf = zipfile.ZipFile(zip_path, "r")
        except zipfile.BadZipFile as exc:
            raise PluginInstallError(f"Not a valid ZIP file: {exc}") from exc

        with zf:
            names = zf.namelist()
            toml_candidates = [n for n in names if n == "plugin.toml" or n.endswith("/plugin.toml")]
            if not toml_candidates:
                raise PluginInstallError("ZIP does not contain plugin.toml")
            # Prefer root-level manifest.
            toml_member = next((n for n in toml_candidates if "/" not in n), toml_candidates[0])
            try:
                toml_text = zf.read(toml_member).decode("utf-8")
            except Exception as exc:
                raise PluginInstallError(f"Cannot read plugin.toml: {exc}") from exc

            manifest = PluginManifest.from_toml_text(toml_text)

            # --- 2. Version-check (PLUG-050) ---
            try:
                api_min = int(manifest.api_min)
                api_max = int(manifest.api_max)
                current = int(_CURRENT_API_VERSION)
            except ValueError:
                # Non-integer versions: fall back to string equality
                api_min = api_max = current = 0
                if manifest.api_min != _CURRENT_API_VERSION:
                    raise PluginInstallError(
                        f"Plugin {manifest.name!r} requires API {manifest.api_min}–{manifest.api_max}; "
                        f"running API {_CURRENT_API_VERSION}"
                    )
            else:
                if not (api_min <= current <= api_max):
                    raise PluginInstallError(
                        f"Plugin {manifest.name!r} requires API {manifest.api_min}–{manifest.api_max}; "
                        f"running API {_CURRENT_API_VERSION}"
                    )

            # --- 3. Extract ---
            plugins_dir = get_plugins_dir()
            install_dir = plugins_dir / f"{manifest.name}-{manifest.version}"
            if install_dir.exists():
                shutil.rmtree(install_dir)
            install_dir.mkdir(parents=True)
            try:
                zf.extractall(install_dir)
            except Exception as exc:
                shutil.rmtree(install_dir, ignore_errors=True)
                raise PluginInstallError(f"Extraction failed: {exc}") from exc

        # --- 4. Load ---
        record = PluginRecord(manifest=manifest, install_dir=install_dir, enabled=True)
        self._records[manifest.name] = record
        try:
            self._load_from_record(record)
        except Exception as exc:
            shutil.rmtree(install_dir, ignore_errors=True)
            self._records.pop(manifest.name, None)
            raise PluginInstallError(f"Plugin loaded but raised during activation: {exc}") from exc

        if record.faulted:
            shutil.rmtree(install_dir, ignore_errors=True)
            self._records.pop(manifest.name, None)
            raise PluginInstallError(
                f"Plugin {manifest.name!r} faulted during activation; installation rolled back"
            )

        logger.info("Installed plugin %r v%s to %s", manifest.name, manifest.version, install_dir)
        return record

    # --- Remove (PLUG-120) ------------------------------------------------

    def get_panel_section_ids(self, manifest_name: str) -> list[str]:
        """Return the plugin class names loaded for *manifest_name*, used to
        remove their nav buttons when the plugin is uninstalled."""
        record = self._records.get(manifest_name)
        return list(record.loaded_names) if record else []

    def remove(self, plugin_name: str) -> bool:
        """Uninstall an installed plugin (PLUG-120).

        Disables and unloads the plugin immediately.  If the installed
        directory can be deleted right away, it is.  Otherwise a
        ``.pending_removal`` marker is written and the caller should prompt
        the user to restart so :meth:`initialize_from_disk` can finish the
        cleanup.

        Returns ``True`` if fully removed, ``False`` if a restart is needed.
        """
        # Unload all class instances loaded from this manifest record — the
        # registry key is the class name (e.g. "VSTPlugin"), not the manifest
        # name (e.g. "vstarget"), so unloading by manifest name alone misses them.
        record = self._records.get(plugin_name)
        for cls_name in (record.loaded_names if record else [plugin_name]):
            self.unload(cls_name)
        record = self._records.pop(plugin_name, None)
        if record is None:
            return True

        install_dir = record.install_dir
        try:
            shutil.rmtree(install_dir)
            logger.info("Removed plugin %r from %s", plugin_name, install_dir)
            return True
        except OSError:
            # Files in use (e.g. the loaded .pyd/.so is memory-mapped on Windows).
            marker = install_dir / _PENDING_REMOVAL_MARKER
            try:
                marker.write_text("pending", encoding="utf-8")
            except OSError:
                logger.exception("Could not write removal marker for %s", install_dir)
            logger.info("Plugin %r marked for deferred removal; restart required", plugin_name)
            return False

    # --- Deprecated: update stub -----------------------------------------

    def update(self, plugin_name: str) -> None:
        """Update a plugin by re-installing from the marketplace.
        (Stub — callers should download the new ZIP and call install().)"""
        raise NotImplementedError("Call install() with the updated ZIP path")
