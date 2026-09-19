# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""PLUG — Plugin Framework (TC-PLUG-010 … TC-PLUG-080)."""

import pytest
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def plugin_manager():
    plugins = pytest.importorskip("galileo.plugins")
    return plugins.PluginManager()


@pytest.fixture
def minimal_plugin():
    """A minimal valid third-party plugin definition."""
    plugins = pytest.importorskip("galileo.plugins")

    class MinimalPlugin(plugins.PluginBase):
        name = "MinimalPlugin"
        version = "1.0.0"
        api_version = "1"

        def activate(self, ctx): pass
        def deactivate(self): pass

    return MinimalPlugin


# ---------------------------------------------------------------------------
# TC-PLUG-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-010")
@pytest.mark.priority("MVP")
def test_tc_plug_010_register_new_device_backend(plugin_manager):
    """PLUG-010: Exposed API allows a plugin to register a new device backend implementing ARCH-010 abstraction."""
    devices = pytest.importorskip("galileo.core.devices")
    plugins = pytest.importorskip("galileo.plugins")

    class MyAdapter(devices.DeviceBackend):
        backend = "custom_test"
        async def connect(self): pass
        async def disconnect(self): pass
        @property
        def is_connected(self): return True
        def get_capabilities(self): return devices.DeviceCapabilities()
        def get_properties(self): return {}

    ctx = plugin_manager.create_context()
    ctx.register_device_backend(devices.DeviceCategory.CAMERA, MyAdapter)
    registered = devices.DeviceBackend.registered_backends.get(devices.DeviceCategory.CAMERA, [])
    assert MyAdapter in registered


# ---------------------------------------------------------------------------
# TC-PLUG-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-020")
@pytest.mark.priority("MVP")
def test_tc_plug_020_register_sequencer_instruction_or_ui_panel(plugin_manager):
    """PLUG-020: Plugin can register new sequencer instruction/condition/trigger or UI panel."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    plugins = pytest.importorskip("galileo.plugins")

    class MyInstruction(seq_mod.BaseInstruction):
        label = "PluginInstruction"
        async def execute(self, ctx): pass

    ctx = plugin_manager.create_context()
    ctx.register_instruction_type(MyInstruction)

    registry = seq_mod.InstructionRegistry.instance()
    assert MyInstruction in registry.available_instructions()


# ---------------------------------------------------------------------------
# TC-PLUG-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-030")
@pytest.mark.priority("P2")
def test_tc_plug_030_in_app_plugin_manager_ui():
    """PLUG-030: In-app plugin manager to browse, install, update, and remove third-party plugins."""
    plugins = pytest.importorskip("galileo.plugins")
    mgr = plugins.PluginManager()
    assert hasattr(mgr, "list_available")
    assert hasattr(mgr, "install")
    assert hasattr(mgr, "update")
    assert hasattr(mgr, "remove")


# ---------------------------------------------------------------------------
# TC-PLUG-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-040")
@pytest.mark.priority("MVP")
def test_tc_plug_040_load_unload_without_rebuild_failure_isolated(plugin_manager, minimal_plugin):
    """PLUG-040: Load/unload plugins without a full rebuild; isolate plugin failure from crashing core."""
    plugin_manager.load(minimal_plugin)
    assert plugin_manager.is_loaded("MinimalPlugin")

    plugin_manager.unload("MinimalPlugin")
    assert not plugin_manager.is_loaded("MinimalPlugin")

    # A crashing plugin must not propagate to the core
    plugins = pytest.importorskip("galileo.plugins")

    class CrashingPlugin(plugins.PluginBase):
        name = "CrashingPlugin"
        version = "0.1"
        api_version = "1"

        def activate(self, ctx):
            raise RuntimeError("Plugin crash")

        def deactivate(self): pass

    plugin_manager.load(CrashingPlugin)  # must not raise
    assert not plugin_manager.is_loaded("CrashingPlugin") or plugin_manager.is_faulted("CrashingPlugin")


# ---------------------------------------------------------------------------
# TC-PLUG-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-050")
@pytest.mark.priority("MVP")
def test_tc_plug_050_version_check_on_load(plugin_manager):
    """PLUG-050: Version-check plugin against running app's plugin API version; warn on incompatibility."""
    plugins = pytest.importorskip("galileo.plugins")

    class IncompatiblePlugin(plugins.PluginBase):
        name = "OldPlugin"
        version = "1.0.0"
        api_version = "999"  # incompatible future version

        def activate(self, ctx): pass
        def deactivate(self): pass

    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        plugin_manager.load(IncompatiblePlugin)
        assert any(issubclass(warning.category, plugins.PluginApiVersionWarning) for warning in w)


# ---------------------------------------------------------------------------
# TC-PLUG-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-060")
@pytest.mark.priority("MVP")
def test_tc_plug_060_preloaded_first_party_plugins_independently_disableable(plugin_manager):
    """PLUG-060: First-party pre-loaded plugins independently enable/disable; disabled ones are fully inert."""
    plugins = pytest.importorskip("galileo.plugins")
    plugin_manager.initialize_preloaded()

    # VST plugin (pre-loaded)
    assert plugin_manager.is_loaded("VSTPlugin")

    plugin_manager.disable("VSTPlugin")
    assert not plugin_manager.is_active("VSTPlugin")
    assert plugin_manager.get_ui_panels("VSTPlugin") == []

    plugin_manager.enable("VSTPlugin")
    assert plugin_manager.is_active("VSTPlugin")


# ---------------------------------------------------------------------------
# TC-PLUG-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-070")
@pytest.mark.priority("MVP")
def test_tc_plug_070_ui_panel_at_primary_or_secondary_level(plugin_manager):
    """PLUG-070: Plugin registered UI panel insertable at primary (top-level) or secondary (nested) navigation level."""
    plugins = pytest.importorskip("galileo.plugins")

    class TopLevelPlugin(plugins.PluginBase):
        name = "TopLevelPlugin"
        version = "1.0"
        api_version = "1"
        panel_level = "primary"
        panel_label = "My Panel"

        def activate(self, ctx): pass
        def deactivate(self): pass

    plugin_manager.load(TopLevelPlugin)
    ui_registry = plugin_manager.get_ui_registry()
    primary_panels = ui_registry.get_primary_panels()
    assert any(p.label == "My Panel" for p in primary_panels)


# ---------------------------------------------------------------------------
# TC-PLUG-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-080")
@pytest.mark.priority("MVP")
def test_tc_plug_080_plugin_context_api_for_core_services(plugin_manager):
    """PLUG-080: PluginContext exposes documented API for a plugin to invoke granted core services."""
    plugins = pytest.importorskip("galileo.plugins")
    ctx = plugin_manager.create_context(granted_services={"scheduler": MagicMock()})

    assert hasattr(ctx, "get_service")
    scheduler = ctx.get_service("scheduler")
    assert scheduler is not None

    # Accessing a service not in the grant list must raise
    with pytest.raises(plugins.ServiceAccessDenied):
        ctx.get_service("library")
