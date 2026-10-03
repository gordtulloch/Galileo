# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""PLUG — Plugin Framework (TC-PLUG-010 … TC-PLUG-120)."""

import io
import json
import zipfile
from pathlib import Path
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
        with pytest.raises(plugins.PluginInstallError, match="plugin.toml"):
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
def test_tc_plug_100_marketplace_fetch_json_embed():
    """PLUG-100: Marketplace fetch parses JSON embed in the page."""
    marketplace = pytest.importorskip("galileo.plugins.marketplace")

    html = """
    <html><body>
    <script type="application/json" id="galileo-plugins">
    [
      {"name": "vstarget", "description": "Variable Stars", "version": "1.0.0",
       "tier": "first_party", "author": "Gord Tulloch",
       "download_url": "https://example.com/vstarget-1.0.0.zip"}
    ]
    </script>
    </body></html>
    """

    import requests
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = html

    with patch("requests.get", return_value=mock_resp):
        client = marketplace.MarketplaceClient()
        entries, error = client.fetch()

    assert error == ""
    assert len(entries) == 1
    assert entries[0].name == "vstarget"
    assert entries[0].version == "1.0.0"
    assert entries[0].tier == "first_party"


@pytest.mark.requirement("TC-PLUG-100")
@pytest.mark.priority("MVP")
def test_tc_plug_100_marketplace_fetch_html_fallback():
    """PLUG-100: Marketplace fetch falls back to HTML scraping when no JSON embed."""
    marketplace = pytest.importorskip("galileo.plugins.marketplace")

    html = """
    <html><body>
    <section id="plugins">
      <a href="/downloads/myplugin-1.2.0.zip">My Plugin 1.2.0</a>
    </section>
    </body></html>
    """

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = html

    with patch("requests.get", return_value=mock_resp):
        client = marketplace.MarketplaceClient()
        entries, error = client.fetch()

    assert error == ""
    assert len(entries) == 1
    assert "myplugin" in entries[0].name.lower()
    assert entries[0].download_url.endswith(".zip")


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

    html = '<script type="application/json" id="galileo-plugins">[{"name":"X","description":"","version":"1","tier":"third_party","author":"","download_url":"http://x.com/x.zip"}]</script>'
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = html

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

    html = '<script type="application/json" id="galileo-plugins">[]</script>'
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = html

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
