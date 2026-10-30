# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Plugin framework — loading, versioning, ZIP install, remove, and context (PLUG-010 … PLUG-120)."""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import logging
import shutil
import sys
import warnings
import zipfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CURRENT_API_VERSION = "1"

# Where a plugin's panel appears, declared with ``PluginBase.panel_level`` (PLUG-070, PLUG-130):
#   "science"            -- an item in the Science section's secondary menu ("primary" and
#                           "secondary" are older spellings of the same place and still work)
#   "equipment:<cat>"    -- a panel on one Equipment device page, e.g. "equipment:switch"
#   "top"                -- its own top-level icon in the left sidebar
LEVEL_TOP = "top"
LEVEL_SCIENCE = "science"
_SCIENCE_LEVELS = ("science", "primary", "secondary")

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
    def from_toml_text(cls, text: str) -> PluginManifest:
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
        return ep or f"galileo.plugins.{self.name}"


@dataclass
class PluginRecord:
    """A discovered, possibly-loaded installed plugin."""
    manifest: PluginManifest
    install_dir: Path
    enabled: bool = True
    loaded: bool = False
    faulted: bool = False
    loaded_names: list[str] = field(default_factory=list)
    help_dir: Path | None = None


def version_key(version: str) -> tuple[int, ...]:
    """Sortable form of a dotted version string (``"1.10.2"`` > ``"1.9"``); non-numeric parts
    such as a ``-beta`` suffix are ignored, and an unparseable string sorts lowest."""
    import re
    return tuple(int(n) for n in re.findall(r"\d+", version.split("-")[0].split("+")[0]))


def is_newer_version(available: str, installed: str) -> bool:
    """Whether *available* is a later release than *installed* (PLUG-190)."""
    if not available or not installed:
        return False
    return version_key(available) > version_key(installed)


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
    # Label of an optional dockable pane (PLUG-140); "" means the plugin has none.
    dock_label: str = ""
    # Label of an optional page under Options (PLUG-170); "" means the plugin has none.
    options_label: str = ""
    # Label of a view the plugin can publish on the Dashboard (OBS-150); "" means it has none.
    # The user switches it on with the "Publish on Dashboard" box Galileo adds to the plugin's
    # Options page.
    dashboard_label: str = ""

    @abstractmethod
    def activate(self, ctx: PluginContext) -> None:
        """Called when the plugin is enabled."""

    @abstractmethod
    def deactivate(self) -> None:
        """Called when the plugin is disabled."""

    def on_enabled_changed(self, enabled: bool) -> None:
        """Called when the user enables or disables the plugin while it stays loaded, so it can
        stop (or resume) any background work (PLUG-060: a disabled plugin is inert)."""
        return None

    def build_page(self) -> Any:
        """Return a QWidget for this plugin's main panel, or None for a placeholder."""
        return None

    def panel_icon_painter(self) -> Callable[[Any, Any], None] | None:
        """For a ``panel_level = "top"`` plugin: a ``draw(painter, rect)`` callable that paints the
        sidebar icon with the pen the painter already carries (PLUG-130), or ``None`` for the
        generic plugin icon."""
        return None

    def build_options_page(self) -> Any:
        """Return a QWidget for the plugin's page under Options (PLUG-170), or ``None``. Only asked
        when :attr:`options_label` is set."""
        return None

    def build_dock_widget(self) -> Any:
        """Return a QWidget for the plugin's dockable pane (PLUG-140), or ``None``. Only asked when
        :attr:`dock_label` is set."""
        return None

    def build_dashboard_widget(self) -> Any:
        """Return a QWidget to show above the Pier timelines on the Dashboard (OBS-150), or ``None``.
        Only asked when :attr:`dashboard_label` is set and the user ticked "Publish on Dashboard".
        The widget is given whatever space the Dashboard has left, so it should scale to fit (an
        animation or live image) and stop any timers while hidden."""
        return None

    def dock_initially_visible(self) -> bool:
        """Whether the dock pane is open when Galileo starts."""
        return False

    def on_dock_visibility_changed(self, visible: bool) -> None:
        """Called when the user opens or closes the dock pane (e.g. with its close button), so the
        plugin can remember the choice."""
        return None


# ---------------------------------------------------------------------------
# Plugin context (PLUG-080)
# ---------------------------------------------------------------------------

class PluginSettings:
    """A plugin's own slice of Galileo's configuration store (PLUG-150).

    Values are JSON-serialisable and live in the shared database under the namespace
    ``plugin.<plugin name>`` -- plugins do not keep config files or ``QSettings`` of their own.
    Like :mod:`galileo.settings_store`, reads fall back to the default and writes are logged and
    dropped when the database is unavailable; neither raises."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace

    def get(self, key: str, default: Any = None) -> Any:
        from galileo import settings_store
        return settings_store.get_setting(self.namespace, key, default)

    def all(self) -> dict[str, Any]:
        from galileo import settings_store
        return settings_store.get_namespace(self.namespace)

    def set(self, key: str, value: Any) -> bool:
        from galileo import settings_store
        return settings_store.set_setting(self.namespace, key, value)

    def update(self, values: dict[str, Any]) -> bool:
        from galileo import settings_store
        return settings_store.set_namespace(self.namespace, values)


PUBLISH_ON_DASHBOARD_KEY = "publish_on_dashboard"


def is_published_on_dashboard(plugin: PluginBase) -> bool:
    """Whether the user ticked "Publish on Dashboard" on *plugin*'s Options page (OBS-150)."""
    if not getattr(plugin, "dashboard_label", ""):
        return False
    return bool(PluginSettings(f"plugin.{plugin.name}").get(PUBLISH_ON_DASHBOARD_KEY, False))


def set_published_on_dashboard(plugin: PluginBase, published: bool) -> None:
    PluginSettings(f"plugin.{plugin.name}").set(PUBLISH_ON_DASHBOARD_KEY, bool(published))


class PluginContext:
    """Provides a controlled API surface for a plugin to call core services."""

    def __init__(
        self,
        granted_services: dict[str, Any] | None = None,
        plugin_name: str = "",
        host: PluginManager | None = None,
    ) -> None:
        self._services = granted_services or {}
        self._plugin_name = plugin_name
        self._host = host

    def get_service(self, name: str) -> Any:
        if name not in self._services:
            raise ServiceAccessDenied(f"Plugin has not been granted access to service {name!r}")
        return self._services[name]

    def settings(self) -> PluginSettings:
        """This plugin's configuration, stored in the shared database (PLUG-150)."""
        return PluginSettings(f"plugin.{self._plugin_name or 'unnamed'}")

    def site_location(self) -> Any:
        """The selected Observatory's ``galileo.planning.visibility.ObservingLocation``, or ``None``
        when none is selected or it has no latitude/longitude yet (PLUG-160)."""
        provider = getattr(self._host, "site_provider", None)
        if provider is None:
            return None
        try:
            return provider()
        except Exception:
            logger.exception("Site-location provider failed")
            return None

    def set_dock_visible(self, visible: bool) -> None:
        """Show or hide this plugin's dock pane (PLUG-140). A no-op until the main window exists."""
        controller = getattr(self._host, "dock_controller", None)
        if controller is not None:
            controller(self._plugin_name, visible)

    def register_device_backend(self, category, adapter_cls) -> None:
        """Register a new device backend for *category* (PLUG-010, ARCH-070)."""
        from galileo.core.devices import DeviceBackend
        DeviceBackend.registered_backends[category].append(adapter_cls)

    def register_switch_profile(self, profile) -> bool:
        """Register a declarative switch profile (PLUG-210, EQP-SW-080): how a driver that does not use INDI's
        power interface maps onto the Switches page. The plugin holds no INDI connection and writes no device
        code; core applies the profile. A malformed profile is rejected with a logged reason and ``False``
        returned — it never raises into the plugin and never affects another profile. While the registering
        plugin is disabled its profiles are not offered (PLUG-060); unloading it drops them (PLUG-120)."""
        from galileo.core.switches import SwitchProfileRegistry
        try:
            profile.validate()
        except (AttributeError, TypeError, ValueError) as exc:
            logger.error("Plugin %r: switch profile rejected: %s", self._plugin_name or "unnamed", exc)  # noqa: TRY400 -- an expected, reportable rejection: the reason is the whole story, a traceback would only bury it
            return False
        owner, host = self._plugin_name, self._host
        probe = (lambda: host.is_active(owner)) if host is not None and owner else None
        SwitchProfileRegistry.register(profile, owner=owner, is_active=probe)
        return True

    def register_instruction_type(self, instruction_cls) -> None:
        """Register a new session block type (PLUG-020, SES-340)."""
        from galileo.session_exec import BlockRegistry
        BlockRegistry.instance().register(instruction_cls)


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
        self._dock_plugins: list[PluginBase] = []
        self._options_plugins: list[PluginBase] = []
        self._dashboard_plugins: list[PluginBase] = []

    def register(self, panel: UiPanel) -> None:
        self._panels.append(panel)

    def register_dock(self, plugin: PluginBase) -> None:
        self._dock_plugins.append(plugin)

    def register_options(self, plugin: PluginBase) -> None:
        self._options_plugins.append(plugin)

    def register_dashboard(self, plugin: PluginBase) -> None:
        self._dashboard_plugins.append(plugin)

    def get_dashboard_plugins(self) -> list[PluginBase]:
        """Loaded plugins that can publish a view on the Dashboard (OBS-150)."""
        return list(self._dashboard_plugins)

    def get_options_plugins(self) -> list[PluginBase]:
        """Loaded plugins that offer a page under Options (PLUG-170)."""
        return list(self._options_plugins)

    def get_primary_panels(self) -> list[UiPanel]:
        return [p for p in self._panels if p.level == "primary"]

    def get_top_level_panels(self) -> list[UiPanel]:
        """Panels that get their own icon in the left sidebar (``panel_level = "top"``, PLUG-130)."""
        return [p for p in self._panels if p.level == LEVEL_TOP]

    def get_science_panels(self) -> list[UiPanel]:
        """Panels that sit in the Science section's menu (PLUG-070)."""
        return [p for p in self._panels if p.level in _SCIENCE_LEVELS]

    def get_dock_plugins(self) -> list[PluginBase]:
        """Loaded plugins that offer a dockable pane (PLUG-140)."""
        return list(self._dock_plugins)

    def get_secondary_panels(self) -> list[UiPanel]:
        return [p for p in self._panels if p.level == "secondary"]

    def get_equipment_panels(self, category: str) -> list[UiPanel]:
        """Panels a plugin contributes to one Equipment page, declared with
        ``panel_level = "equipment:<category id>"`` (e.g. ``"equipment:switch"``)."""
        return [p for p in self._panels if p.level == f"equipment:{category}"]


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
        # Set by the main window once it exists; plugins reach them through PluginContext.
        self.site_provider: Callable[[], Any] | None = None
        self.dock_controller: Callable[[str, bool], None] | None = None
        self._listeners: list[Callable[[], None]] = []

    def add_change_listener(self, listener: Callable[[], None]) -> None:
        """Call *listener* (no arguments) after a plugin is installed, updated or removed, so the
        window can bring its menus, sidebar and panes in line without a restart (PLUG-190)."""
        self._listeners.append(listener)

    def _notify_changed(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:
                logger.exception("Plugin change listener failed")

    def installed_version(self, name: str) -> str:
        """The installed version of manifest *name*, or ``""`` when it is not installed."""
        record = self._records.get(name)
        return record.manifest.version if record else ""

    def update_available(self, name: str, available_version: str) -> bool:
        """Whether *available_version* (e.g. the marketplace's) is newer than what is installed."""
        return is_newer_version(available_version, self.installed_version(name))

    def create_context(self, granted_services: dict | None = None, plugin_name: str = "") -> PluginContext:
        return PluginContext(granted_services=granted_services, plugin_name=plugin_name, host=self)

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

        # Discover installed plugins.  Should an update have left an older version's directory
        # behind (it was in use when the update ran), only the newest one of each is loaded.
        newest: dict[str, tuple[PluginManifest, Path]] = {}
        for toml_path in sorted(plugins_dir.glob("*/plugin.toml")):
            install_dir = toml_path.parent
            if (install_dir / _PENDING_REMOVAL_MARKER).exists():
                continue
            try:
                manifest = PluginManifest.from_toml_text(toml_path.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("Skipping plugin in %s — bad manifest", install_dir)
                continue
            current = newest.get(manifest.name)
            if current is None:
                newest[manifest.name] = (manifest, install_dir)
            elif is_newer_version(manifest.version, current[0].version):
                shutil.rmtree(current[1], ignore_errors=True)
                newest[manifest.name] = (manifest, install_dir)
            else:
                shutil.rmtree(install_dir, ignore_errors=True)

        for manifest, install_dir in newest.values():
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

        record.help_dir = self._register_help(mod)
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
    def _register_help(mod: Any) -> Path | None:
        """Pick up a plugin's own help (HELP-060): Markdown in a ``help/`` folder beside its entry
        module, named for the screen ids its pages use (``science.<plugin name>.md``)."""
        try:
            from galileo import help as help_content
            module_file = getattr(mod, "__file__", None)
            help_dir = Path(module_file).parent / "help" if module_file else None
            if help_dir is not None and help_dir.is_dir():
                help_content.register_dir(help_dir)
                return help_dir
        except Exception:
            logger.exception("Could not register help for plugin module %r", getattr(mod, "__name__", mod))
        return None

    def _unload_record(self, record: PluginRecord) -> None:
        """Deactivate every class loaded from *record* and forget its code, so a different version
        of the same plugin can be imported afresh in the running process (PLUG-190): its modules
        leave ``sys.modules``, its folder leaves ``sys.path`` and its help is unregistered."""
        for cls_name in (record.loaded_names or [record.manifest.name]):
            self.unload(cls_name)
            self._faulted.discard(cls_name)
        self._faulted.discard(record.manifest.name)
        record.loaded_names = []
        record.loaded = False
        record.faulted = False

        root = record.install_dir
        for mod_name, mod in list(sys.modules.items()):
            locations = [getattr(mod, "__file__", None)]
            with contextlib.suppress(Exception):   # a namespace package's __path__ may not iterate
                locations.extend(getattr(mod, "__path__", None) or [])
            if any(loc and self._is_under(Path(loc), root) for loc in locations):
                del sys.modules[mod_name]
        with contextlib.suppress(ValueError):
            sys.path.remove(str(root))
        importlib.invalidate_caches()

        if record.help_dir is not None:
            from galileo import help as help_content
            help_content.unregister_dir(record.help_dir)
            record.help_dir = None

    @staticmethod
    def _is_under(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            return False

    @staticmethod
    def _delete_dir_or_mark(install_dir: Path) -> bool:
        """Delete *install_dir*; if its files are in use, leave a removal marker for the next start."""
        try:
            shutil.rmtree(install_dir)
            return True
        except OSError:
            try:
                (install_dir / _PENDING_REMOVAL_MARKER).write_text("pending", encoding="utf-8")
            except OSError:
                logger.exception("Could not write removal marker for %s", install_dir)
            return False

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
            ctx = self.create_context(plugin_name=plugin_cls.name)
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
            if getattr(plugin_cls, "dock_label", ""):
                self._ui_registry.register_dock(instance)
            if getattr(plugin_cls, "options_label", ""):
                self._ui_registry.register_options(instance)
            if getattr(plugin_cls, "dashboard_label", ""):
                self._ui_registry.register_dashboard(instance)
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
        from galileo.core.switches import SwitchProfileRegistry
        SwitchProfileRegistry.unregister_owner(name)
        self._ui_registry._panels = [p for p in self._ui_registry._panels if p.plugin is not plugin]
        self._ui_registry._dock_plugins = [p for p in self._ui_registry._dock_plugins if p is not plugin]
        self._ui_registry._options_plugins = [p for p in self._ui_registry._options_plugins if p is not plugin]
        self._ui_registry._dashboard_plugins = [p for p in self._ui_registry._dashboard_plugins if p is not plugin]

    def _class_names(self, name: str) -> list[str]:
        """The loaded plugin class names behind *name*, which is either a class name or the
        manifest name Options > Plugins uses (one manifest can load several classes)."""
        record = self._records.get(name)
        return list(record.loaded_names) if record and record.loaded_names else [name]

    def enable(self, name: str) -> None:
        for cls_name in self._class_names(name):
            if cls_name in self._loaded:
                self._active[cls_name] = True
                self._notify_enabled(cls_name, True)
        if name in self._records:
            self._records[name].enabled = True

    def disable(self, name: str) -> None:
        for cls_name in self._class_names(name):
            self._active[cls_name] = False
            self._notify_enabled(cls_name, False)
        if name in self._records:
            self._records[name].enabled = False

    def _notify_enabled(self, name: str, enabled: bool) -> None:
        plugin = self._loaded.get(name)
        if plugin is None:
            return
        try:
            plugin.on_enabled_changed(enabled)
        except Exception:
            logger.exception("Plugin %r raised in on_enabled_changed", name)

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
            except ValueError as exc:
                # Non-integer versions: fall back to string equality
                api_min = api_max = current = 0
                if manifest.api_min != _CURRENT_API_VERSION:
                    raise PluginInstallError(
                        f"Plugin {manifest.name!r} requires API {manifest.api_min}–{manifest.api_max}; "
                        f"running API {_CURRENT_API_VERSION}"
                    ) from exc
            else:
                if not (api_min <= current <= api_max):
                    raise PluginInstallError(
                        f"Plugin {manifest.name!r} requires API {manifest.api_min}–{manifest.api_max}; "
                        f"running API {_CURRENT_API_VERSION}"
                    )

            # --- 3. Retire the version being replaced, if any (PLUG-190) ---
            # Its code is unloaded now so the new version can be imported under the same module
            # names; its folder is kept until the new one has loaded, to fall back on.
            plugins_dir = get_plugins_dir()
            install_dir = plugins_dir / f"{manifest.name}-{manifest.version}"
            previous = self._records.get(manifest.name)
            if previous is not None:
                self._unload_record(previous)
            was_enabled = previous.enabled if previous is not None else True
            replaced_in_place = previous is not None and previous.install_dir == install_dir

            # --- 4. Extract ---
            if install_dir.exists():
                shutil.rmtree(install_dir)
            install_dir.mkdir(parents=True)
            try:
                zf.extractall(install_dir)
            except Exception as exc:
                shutil.rmtree(install_dir, ignore_errors=True)
                self._restore(previous, replaced_in_place)
                raise PluginInstallError(f"Extraction failed: {exc}") from exc

        # --- 5. Load ---
        record = PluginRecord(manifest=manifest, install_dir=install_dir, enabled=True)
        self._records[manifest.name] = record
        failure = ""
        try:
            self._load_from_record(record)
        except Exception as exc:
            failure = f"Plugin loaded but raised during activation: {exc}"
        if not failure and record.faulted:
            failure = f"Plugin {manifest.name!r} faulted during activation; installation rolled back"
        if failure:
            self._unload_record(record)
            shutil.rmtree(install_dir, ignore_errors=True)
            self._records.pop(manifest.name, None)
            self._restore(previous, replaced_in_place)
            raise PluginInstallError(failure)

        if not was_enabled:
            self.disable(manifest.name)
        if previous is not None and not replaced_in_place:
            self._delete_dir_or_mark(previous.install_dir)

        logger.info("Installed plugin %r v%s to %s", manifest.name, manifest.version, install_dir)
        self._notify_changed()
        return record

    def _restore(self, previous: PluginRecord | None, replaced_in_place: bool) -> None:
        """Bring back the version an install was replacing after the install failed."""
        if previous is None or replaced_in_place or not previous.install_dir.exists():
            return
        self._records[previous.manifest.name] = previous
        self._load_from_record(previous)

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
        if record is None:
            self.unload(plugin_name)
            return True
        self._unload_record(record)
        self._records.pop(plugin_name, None)

        removed = self._delete_dir_or_mark(record.install_dir)
        if removed:
            logger.info("Removed plugin %r from %s", plugin_name, record.install_dir)
        else:
            # Files in use (e.g. the loaded .pyd/.so is memory-mapped on Windows).
            logger.info("Plugin %r marked for deferred removal; restart required", plugin_name)
        self._notify_changed()
        return removed

    # --- Update (PLUG-190) -------------------------------------------------

    def update(self, zip_path: str | Path) -> PluginRecord:
        """Replace an installed plugin with the version in *zip_path* without restarting: the old
        version is unloaded, the new one imported and activated, and listeners told. Same as
        :meth:`install`, which already handles a plugin that is installed; kept as the named
        entry point the Options > Plugins **Update** button uses."""
        return self.install(zip_path)
