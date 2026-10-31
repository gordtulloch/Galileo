# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""PLUG — Plugin Framework (TC-PLUG-010 … TC-PLUG-170)."""

import io
from pathlib import Path
import zipfile
from unittest.mock import MagicMock, patch

import pytest


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
    pytest.importorskip("galileo.plugins")

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
def test_tc_plug_020_register_session_block_or_ui_panel(plugin_manager):
    """PLUG-020: Plugin can register new session block types or UI panel."""
    exec_mod = pytest.importorskip("galileo.session_exec")
    pytest.importorskip("galileo.plugins")

    class MyInstruction:
        async def execute(self, ctx): pass

    ctx = plugin_manager.create_context()
    ctx.register_instruction_type(MyInstruction)

    registry = exec_mod.BlockRegistry.instance()
    assert MyInstruction in registry.available_blocks()


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
def test_tc_plug_060_installed_plugin_enable_disable(plugin_manager):
    """PLUG-060: Installed plugin is active when enabled and fully inert when disabled."""
    plugins = pytest.importorskip("galileo.plugins")

    class FirstPartyPlugin(plugins.PluginBase):
        name = "FirstPartyPlugin"
        version = "1.0.0"
        api_version = "1"
        panel_level = "primary"
        panel_label = "First Party"

        def activate(self, ctx): pass
        def deactivate(self): pass

    plugin_manager.load(FirstPartyPlugin)
    assert plugin_manager.is_active("FirstPartyPlugin")
    assert any(p.label == "First Party" for p in plugin_manager.get_ui_registry().get_primary_panels())

    plugin_manager.disable("FirstPartyPlugin")
    assert not plugin_manager.is_active("FirstPartyPlugin")
    assert plugin_manager.get_ui_panels("FirstPartyPlugin") == []

    plugin_manager.enable("FirstPartyPlugin")
    assert plugin_manager.is_active("FirstPartyPlugin")


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


# ---------------------------------------------------------------------------
# Helpers shared by PLUG-090 … PLUG-120 tests
# ---------------------------------------------------------------------------

MINIMAL_TOML = """\
name        = "TestPlugin"
version     = "1.0.0"
api_min     = "1"
api_max     = "1"
author      = "Test Author"
description = "A minimal test plugin"
tier        = "third_party"
entry_point = "TestPlugin"
"""

INCOMPATIBLE_TOML = """\
name        = "BadVersionPlugin"
version     = "1.0.0"
api_min     = "99"
api_max     = "99"
author      = "Test Author"
description = "Requires a future API version"
tier        = "third_party"
"""

MISSING_FIELD_TOML = """\
name        = "MissingFields"
version     = "1.0.0"
"""


def _make_plugin_zip(toml_content: str, include_package: bool = True) -> bytes:
    """Build an in-memory ZIP containing plugin.toml and optionally a stub package.

    The stub package is a top-level ``TestPlugin`` module (not nested under
    ``galileo.plugins``) to avoid namespace-package conflicts with the main
    installed ``galileo`` package during tests.  ``MINIMAL_TOML`` sets
    ``entry_point = "TestPlugin"`` to match.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.toml", toml_content)
        if include_package:
            # A PluginBase subclass the loader will discover.
            zf.writestr(
                "TestPlugin/__init__.py",
                "from galileo.plugins import PluginBase\n"
                "class TestPlugin(PluginBase):\n"
                "    name = 'TestPlugin'\n"
                "    version = '1.0.0'\n"
                "    api_version = '1'\n"
                "    def activate(self, ctx): pass\n"
                "    def deactivate(self): pass\n",
            )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# TC-PLUG-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-090")
@pytest.mark.priority("MVP")
def test_tc_plug_090_install_from_valid_zip(tmp_path):
    """PLUG-090: Install plugin from valid local ZIP; plugin appears in installed list."""
    plugins = pytest.importorskip("galileo.plugins")

    zip_bytes = _make_plugin_zip(MINIMAL_TOML)
    zip_file = tmp_path / "testplugin.zip"
    zip_file.write_bytes(zip_bytes)

    with patch("galileo.platform.get_plugins_dir", return_value=tmp_path / "plugins"):
        mgr = plugins.PluginManager()
        record = mgr.install(zip_file)

    assert record.manifest.name == "TestPlugin"
    assert record.manifest.version == "1.0.0"
    assert (tmp_path / "plugins" / "TestPlugin-1.0.0").is_dir()


@pytest.mark.requirement("TC-PLUG-090")
@pytest.mark.priority("MVP")
def test_tc_plug_090_install_missing_manifest_raises(tmp_path):
    """PLUG-090 error path: ZIP without plugin.toml raises PluginInstallError; no files left."""
    plugins = pytest.importorskip("galileo.plugins")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.txt", "no manifest here")
    zip_file = tmp_path / "bad.zip"
    zip_file.write_bytes(buf.getvalue())

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
        mgr = plugins.PluginManager()
        with pytest.raises(plugins.PluginInstallError, match=r"plugin.toml"):
            mgr.install(zip_file)

    # Nothing should have been extracted.
    assert list(plugins_dir.iterdir()) == []


@pytest.mark.requirement("TC-PLUG-090")
@pytest.mark.priority("MVP")
def test_tc_plug_090_install_missing_required_manifest_field_raises(tmp_path):
    """PLUG-090 error path: manifest with missing required fields raises PluginInstallError."""
    plugins = pytest.importorskip("galileo.plugins")

    zip_bytes = _make_plugin_zip(MISSING_FIELD_TOML)
    zip_file = tmp_path / "bad.zip"
    zip_file.write_bytes(zip_bytes)

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
        mgr = plugins.PluginManager()
        with pytest.raises(plugins.PluginInstallError):
            mgr.install(zip_file)

    assert list(plugins_dir.iterdir()) == []


@pytest.mark.requirement("TC-PLUG-090")
@pytest.mark.priority("MVP")
def test_tc_plug_090_install_incompatible_api_version_raises(tmp_path):
    """PLUG-090 / PLUG-050: Incompatible API version raises PluginInstallError; no files left."""
    plugins = pytest.importorskip("galileo.plugins")

    zip_bytes = _make_plugin_zip(INCOMPATIBLE_TOML)
    zip_file = tmp_path / "bad.zip"
    zip_file.write_bytes(zip_bytes)

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
        mgr = plugins.PluginManager()
        with pytest.raises(plugins.PluginInstallError, match="API"):
            mgr.install(zip_file)

    assert list(plugins_dir.iterdir()) == []


@pytest.mark.requirement("TC-PLUG-090")
@pytest.mark.priority("MVP")
def test_tc_plug_090_install_corrupt_zip_raises(tmp_path):
    """PLUG-090 error path: corrupt archive raises PluginInstallError."""
    plugins = pytest.importorskip("galileo.plugins")

    zip_file = tmp_path / "corrupt.zip"
    zip_file.write_bytes(b"this is not a zip file at all")

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
        mgr = plugins.PluginManager()
        with pytest.raises(plugins.PluginInstallError):
            mgr.install(zip_file)

    assert list(plugins_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# TC-PLUG-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-100")
@pytest.mark.priority("MVP")
def test_tc_plug_100_marketplace_fetch_json_array():
    """PLUG-100: Marketplace fetch parses the plugins.json array from the Galileo-Plugins repo."""
    marketplace = pytest.importorskip("galileo.plugins.marketplace")

    index = [
        {"name": "vstarget", "description": "Variable Stars", "version": "1.0.0",
         "tier": "first_party", "author": "Gord Tulloch",
         "download_url": "https://example.com/vstarget-1.0.0.zip"}
    ]

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=index)

    with patch("requests.get", return_value=mock_resp):
        client = marketplace.MarketplaceClient()
        entries, error = client.fetch()

    assert error == ""
    assert len(entries) == 1
    assert entries[0].name == "vstarget"
    assert entries[0].version == "1.0.0"
    assert entries[0].tier == "first_party"
    assert entries[0].download_url == "https://example.com/vstarget-1.0.0.zip"


@pytest.mark.requirement("TC-PLUG-100")
@pytest.mark.priority("MVP")
def test_tc_plug_100_marketplace_fetch_malformed_index_graceful():
    """PLUG-100: A non-array index (repository format changed) returns empty list + error string."""
    marketplace = pytest.importorskip("galileo.plugins.marketplace")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"not": "an array"})

    with patch("requests.get", return_value=mock_resp):
        client = marketplace.MarketplaceClient()
        entries, error = client.fetch()

    assert entries == []
    assert error != ""


@pytest.mark.requirement("TC-PLUG-100")
@pytest.mark.priority("MVP")
def test_tc_plug_100_marketplace_fetch_skips_malformed_entries():
    """PLUG-100: Entries missing required fields (name/download_url) are skipped, not fatal."""
    marketplace = pytest.importorskip("galileo.plugins.marketplace")

    index = [
        {"description": "missing name and download_url"},
        {"name": "ok-plugin", "download_url": "https://example.com/ok-plugin-1.0.0.zip"},
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=index)

    with patch("requests.get", return_value=mock_resp):
        client = marketplace.MarketplaceClient()
        entries, error = client.fetch()

    assert error == ""
    assert len(entries) == 1
    assert entries[0].name == "ok-plugin"


@pytest.mark.requirement("TC-PLUG-100")
@pytest.mark.priority("MVP")
def test_tc_plug_100_marketplace_fetch_network_failure_graceful():
    """PLUG-100: Network failure returns empty list + error string; no exception propagated."""
    marketplace = pytest.importorskip("galileo.plugins.marketplace")

    with patch("requests.get", side_effect=ConnectionError("network down")):
        client = marketplace.MarketplaceClient()
        entries, error = client.fetch()

    assert entries == []
    assert "network down" in error or len(error) > 0


@pytest.mark.requirement("TC-PLUG-100")
@pytest.mark.priority("MVP")
def test_tc_plug_100_marketplace_fetch_uses_cache_on_second_call():
    """PLUG-100: Second call within session returns cached result; no second HTTP request."""
    marketplace = pytest.importorskip("galileo.plugins.marketplace")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=[
        {"name": "X", "description": "", "version": "1", "tier": "third_party",
         "author": "", "download_url": "http://x.com/x.zip"},
    ])

    with patch("requests.get", return_value=mock_resp) as mock_get:
        client = marketplace.MarketplaceClient()
        client.fetch()
        client.fetch()   # second call — should NOT issue another HTTP request

    assert mock_get.call_count == 1


@pytest.mark.requirement("TC-PLUG-100")
@pytest.mark.priority("MVP")
def test_tc_plug_100_marketplace_refresh_clears_cache():
    """PLUG-100: refresh() forces a new HTTP request."""
    marketplace = pytest.importorskip("galileo.plugins.marketplace")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=[])

    with patch("requests.get", return_value=mock_resp) as mock_get:
        client = marketplace.MarketplaceClient()
        client.fetch()
        client.refresh()

    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# TC-PLUG-110
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-110")
@pytest.mark.priority("MVP")
def test_tc_plug_110_marketplace_download_and_install(tmp_path):
    """PLUG-110: Marketplace download + install pipeline installs the plugin."""
    plugins = pytest.importorskip("galileo.plugins")
    marketplace = pytest.importorskip("galileo.plugins.marketplace")

    zip_bytes = _make_plugin_zip(MINIMAL_TOML)
    entry = marketplace.MarketplaceEntry(
        name="TestPlugin",
        description="Test",
        version="1.0.0",
        tier="third_party",
        author="Tester",
        download_url="https://example.com/testplugin-1.0.0.zip",
    )

    download_dest = tmp_path / "testplugin-1.0.0.zip"
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    # Simulate download by patching requests.get to return the zip bytes.
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {"content-length": str(len(zip_bytes))}
    mock_resp.iter_content = MagicMock(return_value=[zip_bytes])
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("requests.get", return_value=mock_resp):
        client = marketplace.MarketplaceClient()
        ok = client.download(entry, str(download_dest))

    assert ok
    assert download_dest.exists()

    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
        mgr = plugins.PluginManager()
        record = mgr.install(download_dest)

    assert record.manifest.name == "TestPlugin"


# ---------------------------------------------------------------------------
# TC-PLUG-120
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLUG-120")
@pytest.mark.priority("MVP")
def test_tc_plug_120_remove_plugin_fully(tmp_path):
    """PLUG-120: Remove plugin — disabled immediately, files gone when full removal succeeds."""
    plugins = pytest.importorskip("galileo.plugins")

    zip_bytes = _make_plugin_zip(MINIMAL_TOML)
    zip_file = tmp_path / "testplugin.zip"
    zip_file.write_bytes(zip_bytes)

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
        mgr = plugins.PluginManager()
        mgr.install(zip_file)
        assert mgr.is_loaded("TestPlugin")

        fully_removed = mgr.remove("TestPlugin")

    assert fully_removed
    assert not mgr.is_loaded("TestPlugin")
    assert not mgr.is_active("TestPlugin")
    # Install directory should be gone.
    assert not (plugins_dir / "TestPlugin-1.0.0").exists()


@pytest.mark.requirement("TC-PLUG-120")
@pytest.mark.priority("MVP")
def test_tc_plug_120_remove_nonexistent_plugin_is_noop():
    """PLUG-120: Removing a plugin that is not installed is a graceful no-op."""
    plugins = pytest.importorskip("galileo.plugins")
    mgr = plugins.PluginManager()
    result = mgr.remove("DoesNotExist")
    assert result is True   # reports success — nothing to do


MULTI_PANEL_TOML = """\
name        = "multipanel"
version     = "1.0.0"
api_min     = "1"
api_max     = "1"
author      = "Test Author"
description = "A plugin whose manifest name differs from its class names"
tier        = "first_party"
entry_point = "multipanel"
"""


def _make_multi_panel_zip() -> bytes:
    """A plugin shaped like VSTarget: a manifest name ("multipanel") that matches
    neither of its two panel-providing class names ("PanelAPlugin"/"PanelBPlugin")."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.toml", MULTI_PANEL_TOML)
        zf.writestr(
            "multipanel/__init__.py",
            "from galileo.plugins import PluginBase\n"
            "class PanelAPlugin(PluginBase):\n"
            "    name = 'PanelAPlugin'\n"
            "    version = '1.0.0'\n"
            "    api_version = '1'\n"
            "    panel_level = 'primary'\n"
            "    panel_label = 'Panel A'\n"
            "    def activate(self, ctx): pass\n"
            "    def deactivate(self): pass\n"
            "class PanelBPlugin(PluginBase):\n"
            "    name = 'PanelBPlugin'\n"
            "    version = '1.0.0'\n"
            "    api_version = '1'\n"
            "    panel_level = 'secondary'\n"
            "    panel_label = 'Panel B'\n"
            "    def activate(self, ctx): pass\n"
            "    def deactivate(self): pass\n",
        )
    return buf.getvalue()


@pytest.mark.requirement("TC-PLUG-120")
@pytest.mark.priority("MVP")
def test_tc_plug_120_remove_unloads_panels_when_manifest_name_differs(tmp_path):
    """PLUG-120: Removing a plugin unloads every class it registered and drops their
    UI panels, even when the manifest name matches none of those class names.

    Regression: remove() used to unload by manifest name only, so a plugin like
    VSTarget (manifest "vstarget"; classes "VSTPlugin"/"VSTAnalysisPlugin") was
    never really unloaded and its nav entries survived the uninstall.
    """
    plugins = pytest.importorskip("galileo.plugins")

    zip_file = tmp_path / "multipanel.zip"
    zip_file.write_bytes(_make_multi_panel_zip())

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
        mgr = plugins.PluginManager()
        mgr.install(zip_file)

        assert mgr.is_loaded("PanelAPlugin")
        assert mgr.is_loaded("PanelBPlugin")
        registry = mgr.get_ui_registry()
        assert {p.label for p in registry.get_primary_panels()} == {"Panel A"}
        assert {p.label for p in registry.get_secondary_panels()} == {"Panel B"}
        # The section ids the nav needs in order to hide the buttons.
        assert set(mgr.get_panel_section_ids("multipanel")) == {"PanelAPlugin", "PanelBPlugin"}

        fully_removed = mgr.remove("multipanel")

    assert fully_removed
    assert not mgr.is_loaded("PanelAPlugin")
    assert not mgr.is_loaded("PanelBPlugin")
    assert not mgr.is_active("PanelAPlugin")
    assert not mgr.is_active("PanelBPlugin")
    assert registry.get_primary_panels() == []
    assert registry.get_secondary_panels() == []
    assert mgr.get_panel_section_ids("multipanel") == []


@pytest.mark.requirement("TC-PLUG-120")
@pytest.mark.priority("MVP")
def test_tc_plug_120_remove_deferred_writes_marker(tmp_path):
    """PLUG-120: When files can't be deleted, a .pending_removal marker is written."""
    plugins = pytest.importorskip("galileo.plugins")

    zip_bytes = _make_plugin_zip(MINIMAL_TOML)
    zip_file = tmp_path / "testplugin.zip"
    zip_file.write_bytes(zip_bytes)

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
        mgr = plugins.PluginManager()
        mgr.install(zip_file)

        # Simulate OSError on rmtree (files in use on Windows).
        with patch("shutil.rmtree", side_effect=OSError("file in use")):
            result = mgr.remove("TestPlugin")

    assert result is False   # deferred removal needed
    marker = plugins_dir / "TestPlugin-1.0.0" / plugins._PENDING_REMOVAL_MARKER
    assert marker.exists()


# ---------------------------------------------------------------------------
# TC-PLUG-070 (placement) / TC-PLUG-130 / TC-PLUG-140 / TC-PLUG-150 / TC-PLUG-160
# ---------------------------------------------------------------------------

def _panel_plugin(plugins, plugin_name, level, label="Panel"):
    class _P(plugins.PluginBase):
        name = plugin_name
        version = "1.0"
        api_version = "1"
        panel_level = level
        panel_label = label

        def activate(self, ctx): pass
        def deactivate(self): pass

    return _P


@pytest.mark.requirement("TC-PLUG-070")
@pytest.mark.priority("MVP")
def test_tc_plug_070_plugin_declares_its_menu_location(plugin_manager):
    """PLUG-070: a plugin declares where its panel sits -- Science, one Equipment device page, or a
    top-level sidebar entry -- and the registry sorts panels by that declaration."""
    plugins = pytest.importorskip("galileo.plugins")
    plugin_manager.load(_panel_plugin(plugins, "SciPlugin", "science", "Sci"))
    plugin_manager.load(_panel_plugin(plugins, "LegacySciPlugin", "primary", "Legacy"))
    plugin_manager.load(_panel_plugin(plugins, "EquipPlugin", "equipment:switch", "Relay"))
    plugin_manager.load(_panel_plugin(plugins, "TopPlugin", "top", "Top"))

    registry = plugin_manager.get_ui_registry()
    assert {p.label for p in registry.get_science_panels()} == {"Sci", "Legacy"}
    assert [p.label for p in registry.get_equipment_panels("switch")] == ["Relay"]
    assert [p.label for p in registry.get_top_level_panels()] == ["Top"]
    assert registry.get_equipment_panels("camera") == []


def _make_window(tmp_path, monkeypatch, plugin_classes):
    """An offscreen AppWindow whose plugin manager loads *plugin_classes* instead of scanning disk."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    plugins = pytest.importorskip("galileo.plugins")

    def _init(self):
        for cls in plugin_classes:
            self.load(cls)

    monkeypatch.setattr(plugins.PluginManager, "initialize_from_disk", _init)
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import init_db
    init_db(tmp_path / "plug.db")
    from galileo.ui.app_window import AppWindow
    return AppWindow()


@pytest.mark.requirement("TC-PLUG-130")
@pytest.mark.priority("MVP")
def test_tc_plug_130_top_level_plugin_gets_a_sidebar_section_with_its_icon(tmp_path, monkeypatch):
    """PLUG-130: a plugin with panel_level 'top' gets its own sidebar entry, built from its
    build_page(), using the icon it paints (or the generic plugin icon)."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6 import QtWidgets
    plugins = pytest.importorskip("galileo.plugins")
    from galileo.library.database import db
    from galileo.ui import icons

    drawn = []

    class TopPlugin(plugins.PluginBase):
        name = "TopPlugin"
        version = "1.0"
        api_version = "1"
        panel_level = "top"
        panel_label = "Top Thing"

        def activate(self, ctx): pass
        def deactivate(self): pass
        def build_page(self):
            return QtWidgets.QLabel("top page")
        def panel_icon_painter(self):
            return lambda painter, rect: drawn.append(rect)

    class PlainTopPlugin(TopPlugin):
        name = "PlainTopPlugin"
        panel_label = "Plain Top"
        def panel_icon_painter(self):
            return None

    win = _make_window(tmp_path, monkeypatch, [TopPlugin, PlainTopPlugin])
    try:
        nav = win._primary_nav
        assert "plugin.TopPlugin" in nav._buttons
        assert nav._buttons["plugin.TopPlugin"].text().replace("\n", " ") == "Top Thing"
        assert "plugin.PlainTopPlugin" in nav._buttons
        assert "plugin.TopPlugin" in icons.ICONS and drawn      # its own painter was used
        assert "plugin.PlainTopPlugin" not in icons.ICONS       # fell back to the generic icon
        nav._buttons["plugin.TopPlugin"].click()
        assert win._current_primary_section == "plugin.TopPlugin"
    finally:
        icons.ICONS.pop("plugin.TopPlugin", None)
        win._window.close()
        db.close()


@pytest.mark.requirement("TC-PLUG-140")
@pytest.mark.priority("MVP")
def test_tc_plug_140_dock_pane_is_created_toggled_and_reported(tmp_path, monkeypatch):
    """PLUG-140: a plugin with a dock_label gets a QDockWidget in the main window, initially
    visible as it asks, controllable via ctx.set_dock_visible, and told when the user closes it."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6 import QtWidgets
    plugins = pytest.importorskip("galileo.plugins")
    from galileo.library.database import db

    seen = []
    ctx_holder = {}

    class DockPlugin(plugins.PluginBase):
        name = "DockPlugin"
        version = "1.0"
        api_version = "1"
        dock_label = "My Dock"

        def activate(self, ctx):
            ctx_holder["ctx"] = ctx
        def deactivate(self): pass
        def build_dock_widget(self):
            return QtWidgets.QLabel("dock content")
        def dock_initially_visible(self):
            return True
        def on_dock_visibility_changed(self, visible):
            seen.append(visible)

    win = _make_window(tmp_path, monkeypatch, [DockPlugin])
    try:
        win._window.show()
        dock = win._plugin_docks["DockPlugin"]
        assert dock.windowTitle() == "My Dock"
        assert dock.isVisible()
        ctx_holder["ctx"].set_dock_visible(False)
        assert not dock.isVisible()
        ctx_holder["ctx"].set_dock_visible(True)
        assert dock.isVisible()
        dock.close()                        # the user's close button
        assert seen[-1] is False
        dock.setVisible(True)
        assert seen[-1] is True
        win._window.close()                 # closing the app is not the user closing the pane
        assert seen[-1] is True
    finally:
        win._window.close()
        db.close()


@pytest.mark.requirement("TC-PLUG-140")
@pytest.mark.priority("MVP")
def test_tc_plug_140_set_dock_visible_is_a_noop_before_the_window_exists(plugin_manager):
    """PLUG-140: asking for the dock before the main window exists does nothing and does not raise."""
    ctx = plugin_manager.create_context(plugin_name="Early")
    ctx.set_dock_visible(True)


@pytest.mark.requirement("TC-PLUG-150")
@pytest.mark.priority("MVP")
def test_tc_plug_150_plugin_settings_live_in_the_database_under_its_own_namespace(tmp_path):
    """PLUG-150: ctx.settings() reads and writes the shared settings store, namespaced per plugin;
    one plugin cannot see or clobber another's values."""
    plugins = pytest.importorskip("galileo.plugins")
    from galileo.library.database import db, init_db
    init_db(tmp_path / "plug_settings.db")
    try:
        mgr = plugins.PluginManager()
        a = mgr.create_context(plugin_name="PluginA").settings()
        b = mgr.create_context(plugin_name="PluginB").settings()
        assert a.get("url", "default") == "default"
        assert a.set("url", "http://a") is True
        assert a.update({"count": 5, "flag": True}) is True
        assert a.all() == {"url": "http://a", "count": 5, "flag": True}
        assert b.all() == {}
        assert a.namespace == "plugin.PluginA"
    finally:
        db.close()


@pytest.mark.requirement("TC-PLUG-150")
@pytest.mark.priority("MVP")
def test_tc_plug_150_settings_without_a_database_fall_back_to_defaults():
    """PLUG-150: with no database initialised, reads return the default and writes do not raise."""
    plugins = pytest.importorskip("galileo.plugins")
    from galileo.library.models.base import db
    if db.database is not None:
        pytest.skip("a database is already initialised in this process")
    s = plugins.PluginContext(plugin_name="NoDb").settings()
    assert s.get("x", 7) == 7
    assert s.all() == {}
    s.set("x", 1)       # must not raise


@pytest.mark.requirement("TC-PLUG-160")
@pytest.mark.priority("MVP")
def test_tc_plug_160_site_location_comes_from_the_host_and_survives_a_bad_provider(plugin_manager):
    """PLUG-160: ctx.site_location() returns what the main window's provider reports; None when
    there is no provider or it fails."""
    ctx = plugin_manager.create_context(plugin_name="SitePlugin")
    assert ctx.site_location() is None

    site = object()
    plugin_manager.site_provider = lambda: site
    assert ctx.site_location() is site

    def _boom():
        raise RuntimeError("no observatory")
    plugin_manager.site_provider = _boom
    assert ctx.site_location() is None


@pytest.mark.requirement("TC-PLUG-060")
@pytest.mark.priority("MVP")
def test_tc_plug_060_disable_by_manifest_name_notifies_the_plugin(tmp_path):
    """PLUG-060: Options > Plugins toggles by manifest name; disabling it must reach the loaded
    class so it can stop its background work (and enabling restarts it)."""
    plugins = pytest.importorskip("galileo.plugins")
    events = []

    class WorkerPlugin(plugins.PluginBase):
        name = "WorkerPlugin"
        version = "1.0"
        api_version = "1"
        def activate(self, ctx): pass
        def deactivate(self): pass
        def on_enabled_changed(self, enabled):
            events.append(enabled)

    mgr = plugins.PluginManager()
    mgr.load(WorkerPlugin)
    manifest = plugins.PluginManifest("workerpkg", "1.0", "1", "1", "me", "d", "first_party")
    mgr._records["workerpkg"] = plugins.PluginRecord(manifest, tmp_path, loaded_names=["WorkerPlugin"])

    mgr.set_enabled("workerpkg", False)
    assert events == [False] and not mgr.is_active("WorkerPlugin")
    mgr.set_enabled("workerpkg", True)
    assert events == [False, True] and mgr.is_active("WorkerPlugin")


@pytest.mark.requirement("TC-PLUG-170")
@pytest.mark.priority("MVP")
def test_tc_plug_170_plugin_options_page_appears_under_options(tmp_path, monkeypatch):
    """PLUG-170: a plugin with options_label gets an item under Options whose page comes from its
    build_options_page(); a page that fails to build becomes a placeholder, not a startup failure."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6 import QtWidgets
    plugins = pytest.importorskip("galileo.plugins")

    class OptPlugin(plugins.PluginBase):
        name = "OptPlugin"
        version = "1.0"
        api_version = "1"
        options_label = "Opt Thing"

        def activate(self, ctx): pass
        def deactivate(self): pass
        def build_options_page(self):
            return QtWidgets.QLabel("opt page")

    class BrokenOptPlugin(OptPlugin):
        name = "BrokenOptPlugin"
        options_label = "Broken Thing"

        def build_options_page(self):
            raise RuntimeError("boom")

    win = _make_window(tmp_path, monkeypatch, [OptPlugin, BrokenOptPlugin])
    try:
        registry = win._plugin_manager.get_ui_registry()
        assert [p.options_label for p in registry.get_options_plugins()] == ["Opt Thing", "Broken Thing"]
        texts = {w.text() for w in win._options_page.findChildren(QtWidgets.QLabel)}
        assert "opt page" in texts
    finally:
        win._window.close()


# ---------------------------------------------------------------------------
# TC-PLUG-190 -- in-place install and update, "update available"
# ---------------------------------------------------------------------------

def _versioned_zip(version: str, label: str = "Live Panel", broken: bool = False) -> bytes:
    """A plugin package whose code reports *version*, so a test can tell which one is loaded."""
    toml = (
        'name = "livepanel"\n'
        f'version = "{version}"\n'
        'api_min = "1"\napi_max = "1"\nauthor = "T"\ndescription = "d"\n'
        'tier = "third_party"\nentry_point = "livepanel"\n'
    )
    body = (
        "from galileo.plugins import PluginBase\n"
        f"CODE_VERSION = {version!r}\n"
        "class LivePlugin(PluginBase):\n"
        "    name = 'LivePlugin'\n"
        f"    version = {version!r}\n"
        "    api_version = '1'\n"
        "    panel_level = 'science'\n"
        f"    panel_label = {label!r}\n"
        "    def activate(self, ctx): pass\n"
        "    def deactivate(self): pass\n"
    )
    if broken:
        body += "raise RuntimeError('boom')\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.toml", toml)
        zf.writestr("livepanel/__init__.py", body)
    return buf.getvalue()


@pytest.mark.requirement("TC-PLUG-190")
@pytest.mark.priority("MVP")
def test_tc_plug_190_version_comparison_decides_whether_an_update_is_available():
    """PLUG-190: a marketplace version counts as an update only when it is later than the installed
    one, comparing numerically (1.10 is later than 1.9) and never flagging an unknown version."""
    plugins = pytest.importorskip("galileo.plugins")
    assert plugins.is_newer_version("1.10.0", "1.9.3")
    assert plugins.is_newer_version("2.0", "1.99.99")
    assert not plugins.is_newer_version("1.0.0", "1.0.0")
    assert not plugins.is_newer_version("0.9", "1.0")
    assert not plugins.is_newer_version("", "1.0")
    assert not plugins.is_newer_version("1.1", "")


@pytest.mark.requirement("TC-PLUG-190")
@pytest.mark.priority("MVP")
def test_tc_plug_190_update_replaces_the_running_code_without_a_restart(tmp_path):
    """PLUG-190: installing a newer version of a loaded plugin unloads the old code, imports the
    new in the same process, drops the old folder, keeps one panel, and tells the listeners."""
    import sys
    plugins = pytest.importorskip("galileo.plugins")
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    v1, v2 = tmp_path / "v1.zip", tmp_path / "v2.zip"
    v1.write_bytes(_versioned_zip("1.0.0", "Old Label"))
    v2.write_bytes(_versioned_zip("2.0.0", "New Label"))

    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
        mgr = plugins.PluginManager()
        changes = []
        mgr.add_change_listener(lambda: changes.append(mgr.installed_version("livepanel")))
        mgr.install(v1)
        assert sys.modules["livepanel"].CODE_VERSION == "1.0.0"
        assert mgr.update_available("livepanel", "2.0.0")
        assert not mgr.update_available("livepanel", "1.0.0")

        mgr.update(v2)

    try:
        assert sys.modules["livepanel"].CODE_VERSION == "2.0.0"
        assert mgr.installed_version("livepanel") == "2.0.0"
        assert not mgr.update_available("livepanel", "2.0.0")
        assert [p.label for p in mgr.get_ui_registry().get_science_panels()] == ["New Label"]
        assert not (plugins_dir / "livepanel-1.0.0").exists()
        assert (plugins_dir / "livepanel-2.0.0").exists()
        assert str(plugins_dir / "livepanel-1.0.0") not in sys.path
        assert changes == ["1.0.0", "2.0.0"]
    finally:
        mgr.remove("livepanel")


@pytest.mark.requirement("TC-PLUG-190")
@pytest.mark.priority("MVP")
def test_tc_plug_190_failed_update_keeps_the_working_version(tmp_path):
    """PLUG-190: an update whose code fails to load is rolled back and the version that was
    running is loaded again, files and panel intact."""
    import sys
    plugins = pytest.importorskip("galileo.plugins")
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    good, bad = tmp_path / "good.zip", tmp_path / "bad.zip"
    good.write_bytes(_versioned_zip("1.0.0"))
    bad.write_bytes(_versioned_zip("2.0.0", broken=True))

    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
        mgr = plugins.PluginManager()
        mgr.install(good)
        with pytest.raises(plugins.PluginInstallError):
            mgr.update(bad)

    try:
        assert mgr.installed_version("livepanel") == "1.0.0"
        assert mgr.is_loaded("LivePlugin")
        assert sys.modules["livepanel"].CODE_VERSION == "1.0.0"
        assert (plugins_dir / "livepanel-1.0.0").exists()
        assert not (plugins_dir / "livepanel-2.0.0").exists()
        assert len(mgr.get_ui_registry().get_science_panels()) == 1
    finally:
        mgr.remove("livepanel")


@pytest.mark.requirement("TC-PLUG-190")
@pytest.mark.priority("MVP")
def test_tc_plug_190_startup_loads_only_the_newest_left_over_version(tmp_path):
    """PLUG-190: should an update have left an older version's folder behind, the next start loads
    only the newest and clears the stale one."""
    import sys
    plugins = pytest.importorskip("galileo.plugins")
    plugins_dir = tmp_path / "plugins"
    for version in ("1.0.0", "1.10.0", "1.9.0"):
        d = plugins_dir / f"livepanel-{version}"
        d.mkdir(parents=True)
        with zipfile.ZipFile(io.BytesIO(_versioned_zip(version))) as zf:
            zf.extractall(d)

    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
        mgr = plugins.PluginManager()
        mgr.initialize_from_disk()
        try:
            assert [r.manifest.version for r in mgr.list_installed()] == ["1.10.0"]
            assert sys.modules["livepanel"].CODE_VERSION == "1.10.0"
            assert sorted(p.name for p in plugins_dir.iterdir()) == ["livepanel-1.10.0"]
        finally:
            mgr.remove("livepanel")


@pytest.mark.requirement("TC-PLUG-190")
@pytest.mark.priority("MVP")
def test_tc_plug_190_window_gains_and_loses_plugin_ui_live(tmp_path, monkeypatch):
    """PLUG-190: installing, updating and removing a plugin changes the Science menu of the running
    window; nothing needs a restart."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6 import QtWidgets
    pytest.importorskip("galileo.plugins")
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    zips = {}
    for v in ("1.0.0", "2.0.0"):
        zips[v] = tmp_path / f"{v}.zip"
        zips[v].write_bytes(_versioned_zip(v, f"Panel{v}"))

    win = _make_window(tmp_path, monkeypatch, [])
    app = QtWidgets.QApplication.instance()
    try:
        with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir):
            win._plugin_manager.install(zips["1.0.0"])
            app.processEvents()
            nav = win._primary_pages["science"]._secondary_nav
            assert nav.has_item("LivePlugin")
            first_page = win._primary_pages["science"]

            win._plugin_manager.update(zips["2.0.0"])
            app.processEvents()
            assert win._primary_pages["science"] is not first_page
            nav = win._primary_pages["science"]._secondary_nav
            assert nav._buttons["LivePlugin"].text() == "Panel2.0.0"

            win._plugin_manager.remove("livepanel")
            app.processEvents()
            assert not hasattr(win._primary_pages["science"], "_secondary_nav")
    finally:
        win._window.close()


# ---------------------------------------------------------------------------
# TC-PLUG-210 — switch profile registration
# ---------------------------------------------------------------------------

def _profile(name="Box", device="Some Box"):
    from galileo.core.switches import ProfileChannel, SwitchProfile
    return SwitchProfile(
        name=name, device_names=(device,), signature=frozenset({("PROP", "switch")}),
        channels=(ProfileChannel(id="c1", label="C1", group="G", switch=("PROP", "ELEM")),),
    )


@pytest.fixture
def profile_registry():
    from galileo.core.switches import SwitchProfileRegistry
    SwitchProfileRegistry.clear()
    yield SwitchProfileRegistry
    SwitchProfileRegistry.clear()


def _profile_plugin(plugins, plugin_name, profiles):
    class ProfilePlugin(plugins.PluginBase):
        name = plugin_name
        version = "1.0.0"
        api_version = "1"
        results: list = []

        def activate(self, ctx):
            type(self).results = [ctx.register_switch_profile(p) for p in profiles]

        def deactivate(self): pass

    return ProfilePlugin


@pytest.mark.requirement("TC-PLUG-210")
@pytest.mark.priority("P2")
def test_tc_plug_210_plugin_registers_a_profile_through_the_context(plugin_manager, profile_registry):
    """PLUG-210: a plugin registers a declarative switch profile through PluginContext, holding no INDI
    connection and needing no granted service."""
    plugins = pytest.importorskip("galileo.plugins")
    cls = _profile_plugin(plugins, "ProfilePlugin", [_profile()])
    plugin_manager.load(cls)
    assert cls.results == [True]
    assert [p.name for p in profile_registry.profiles()] == ["Box"]
    assert profile_registry.claimed_device_names() == {"Some Box"}


@pytest.mark.requirement("TC-PLUG-210")
@pytest.mark.priority("P2")
def test_tc_plug_210_malformed_profile_is_rejected_with_a_reason_and_others_survive(plugin_manager, profile_registry, caplog):
    """PLUG-210: a malformed profile is refused with a logged reason, never raised into the plugin, and does
    not affect another profile or the application."""
    import logging
    plugins = pytest.importorskip("galileo.plugins")
    from galileo.core.switches import SwitchProfile
    broken = SwitchProfile(name="Broken", device_names=(), signature=frozenset({("P", "switch")}))
    cls = _profile_plugin(plugins, "MixedPlugin", [broken, _profile("Good"), object()])
    with caplog.at_level(logging.ERROR):
        plugin_manager.load(cls)
    assert cls.results == [False, True, False]                      # the bare object has no validate(): rejected too
    assert not plugin_manager.is_faulted("MixedPlugin")             # the plugin itself is fine
    assert [p.name for p in profile_registry.profiles()] == ["Good"]
    assert "claims no device names" in caplog.text


@pytest.mark.requirement("TC-PLUG-210")
@pytest.mark.priority("P2")
def test_tc_plug_210_profiles_of_a_disabled_plugin_are_not_offered(plugin_manager, profile_registry):
    """PLUG-210 / PLUG-060: while its plugin is disabled a profile is not offered; enabling restores it."""
    plugins = pytest.importorskip("galileo.plugins")
    plugin_manager.load(_profile_plugin(plugins, "TogglePlugin", [_profile()]))
    assert profile_registry.claimed_device_names() == {"Some Box"}
    plugin_manager.disable("TogglePlugin")
    assert profile_registry.profiles() == [] and profile_registry.claimed_device_names() == set()
    plugin_manager.enable("TogglePlugin")
    assert [p.name for p in profile_registry.profiles()] == ["Box"]


@pytest.mark.requirement("TC-PLUG-210")
@pytest.mark.priority("P2")
def test_tc_plug_210_profiles_of_an_unloaded_plugin_are_dropped_and_others_kept(plugin_manager, profile_registry):
    """PLUG-210 / PLUG-120: unloading a plugin deregisters its profiles and leaves other plugins' alone."""
    plugins = pytest.importorskip("galileo.plugins")
    plugin_manager.load(_profile_plugin(plugins, "PluginA", [_profile("A", "Box A")]))
    plugin_manager.load(_profile_plugin(plugins, "PluginB", [_profile("B", "Box B")]))
    assert profile_registry.claimed_device_names() == {"Box A", "Box B"}
    plugin_manager.unload("PluginA")
    assert profile_registry.claimed_device_names() == {"Box B"}


@pytest.mark.requirement("TC-PLUG-210")
@pytest.mark.priority("P2")
def test_tc_plug_210_registering_again_replaces_rather_than_duplicates(plugin_manager, profile_registry):
    """PLUG-210: a plugin that registers the same profile again (a reload) does not leave a duplicate."""
    plugins = pytest.importorskip("galileo.plugins")
    cls = _profile_plugin(plugins, "Reloader", [_profile(), _profile()])
    plugin_manager.load(cls)
    assert cls.results == [True, True]
    assert len(profile_registry.profiles()) == 1


# ---------------------------------------------------------------------------
# TC-PLUG-200
# ---------------------------------------------------------------------------

def _deps_zip(requires: list[str]) -> bytes:
    toml = (
        'name = "depplug"\nversion = "1.0.0"\napi_min = "1"\napi_max = "1"\n'
        'author = "t"\ndescription = "d"\ntier = "third_party"\n'
        'entry_point = "depplug"\n'
        f"requires = {requires!r}\n".replace("'", '"')
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.toml", toml)
        zf.writestr("depplug/__init__.py", "")
    return buf.getvalue()


@pytest.mark.requirement("TC-PLUG-200")
@pytest.mark.priority("MVP")
def test_tc_plug_200_requires_installed_into_the_plugins_private_folder(tmp_path):
    """PLUG-200: a plugin's declared requirements are installed into a folder private to it, on
    sys.path while it is loaded, and removed with the plugin; Galileo's environment is untouched."""
    import sys
    plugins = pytest.importorskip("galileo.plugins")
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    zip_path = tmp_path / "dep.zip"
    zip_path.write_bytes(_deps_zip(["somepkg>=1.0"]))
    calls = []

    def fake_pip(args):
        calls.append(args)
        target = args[args.index("--target") + 1]
        (Path(target) / "somepkg").mkdir(parents=True)
        return 0, ""

    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir), \
            patch("galileo.plugins._run_pip", fake_pip):
        mgr = plugins.PluginManager()
        record = mgr.install(zip_path)
        deps = record.install_dir / ".deps"
        assert calls and "somepkg>=1.0" in calls[0] and "--target" in calls[0]
        assert (deps / "somepkg").is_dir()
        assert str(deps) in sys.path
        mgr.remove("depplug")

    assert str(deps) not in sys.path
    assert not record.install_dir.exists()


@pytest.mark.requirement("TC-PLUG-200")
@pytest.mark.priority("MVP")
def test_tc_plug_200_unresolvable_requirement_fails_install_and_rolls_back(tmp_path):
    """PLUG-200: if a requirement cannot be resolved (offline included) the install fails and
    leaves nothing behind."""
    plugins = pytest.importorskip("galileo.plugins")
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    zip_path = tmp_path / "dep.zip"
    zip_path.write_bytes(_deps_zip(["nosuchpkg"]))

    with patch("galileo.platform.get_plugins_dir", return_value=plugins_dir), \
            patch("galileo.plugins._run_pip", lambda args: (1, "no network")):
        mgr = plugins.PluginManager()
        with pytest.raises(plugins.PluginInstallError, match="dependencies"):
            mgr.install(zip_path)

    assert list(plugins_dir.iterdir()) == []
    assert mgr.installed_version("depplug") == ""


@pytest.mark.requirement("TC-PLUG-200")
@pytest.mark.priority("MVP")
def test_tc_plug_200_requires_must_be_a_list_of_strings():
    """PLUG-200: a malformed ``requires`` entry is rejected when the manifest is read; a plugin
    without one installs nothing."""
    plugins = pytest.importorskip("galileo.plugins")
    base = ('name="x"\nversion="1"\napi_min="1"\napi_max="1"\nauthor="a"\n'
            'description="d"\ntier="third_party"\n')
    with pytest.raises(plugins.PluginInstallError):
        plugins.PluginManifest.from_toml_text(base + 'requires = "numpy"\n')
    assert plugins.PluginManifest.from_toml_text(base).requires == []
    calls = []
    with patch("galileo.plugins._run_pip", lambda a: calls.append(a) or (0, "")):
        plugins.install_requirements(Path("."), [])
    assert calls == []
