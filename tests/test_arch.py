# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""ARCH — Protocol & Device Abstraction Layer (TC-ARCH-010 … TC-ARCH-080)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# TC-ARCH-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-ARCH-010")
@pytest.mark.priority("MVP")
def test_tc_arch_010_device_abstraction_per_category():
    """ARCH-010: Device-abstraction interface defined per category, independently by INDI and Alpaca backends."""
    devices = pytest.importorskip("galileo.core.devices")
    indi = pytest.importorskip("galileo.adapters.indi")
    alpaca = pytest.importorskip("galileo.adapters.alpaca")

    required = {"connect", "disconnect", "is_connected", "get_capabilities", "get_properties"}
    for category in devices.DeviceCategory:
        for mod, label in [(indi, "INDI"), (alpaca, "Alpaca")]:
            cls = mod.get_adapter_class(category)
            missing = required - set(dir(cls))
            assert not missing, f"{label} adapter for {category} missing: {missing}"


# ---------------------------------------------------------------------------
# TC-ARCH-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-ARCH-020")
@pytest.mark.priority("MVP")
def test_tc_arch_020_mixed_indi_alpaca_in_one_profile(minimal_profile):
    """ARCH-020: Each device may independently use INDI or Alpaca within a single equipment profile."""
    devices = pytest.importorskip("galileo.core.devices")
    pool = devices.DevicePool()
    indi = pytest.importorskip("galileo.adapters.indi")
    alpaca = pytest.importorskip("galileo.adapters.alpaca")

    cam = indi.IndiAdapter(device_type=devices.DeviceCategory.CAMERA, host="localhost", port=7624)
    foc = alpaca.AlpacaAdapter(device_type=devices.DeviceCategory.FOCUSER, host="localhost", port=11111)
    pool.register(cam)
    pool.register(foc)

    assert pool.get(devices.DeviceCategory.CAMERA).backend == "indi"
    assert pool.get(devices.DeviceCategory.FOCUSER).backend == "alpaca"


# ---------------------------------------------------------------------------
# TC-ARCH-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-ARCH-030")
@pytest.mark.priority("MVP")
def test_tc_arch_030_capability_query_limits_ui(mock_indi_camera):
    """ARCH-030: Query device advertised capabilities and expose only the corresponding controls."""
    devices = pytest.importorskip("galileo.core.devices")
    caps = devices.DeviceCapabilities.from_backend(mock_indi_camera)
    assert caps.has_cooler is True
    assert caps.can_bin is True

    # A device without a cooler reports that via capabilities
    no_cooler = MagicMock()
    no_cooler.capabilities = MagicMock(has_cooler=False)
    caps2 = devices.DeviceCapabilities.from_backend(no_cooler)
    assert caps2.has_cooler is False


# ---------------------------------------------------------------------------
# TC-ARCH-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-ARCH-040")
@pytest.mark.priority("MVP")
async def test_tc_arch_040_disconnect_detected_in_bounded_time(mock_indi_camera, event_bus):
    """ARCH-040: Detect and surface a device disconnect within a bounded time without crashing."""
    devices = pytest.importorskip("galileo.core.devices")
    monitor = devices.ConnectionMonitor(mock_indi_camera, event_bus=event_bus, poll_interval_s=0.05)

    mock_indi_camera.is_connected = False  # simulate disconnect
    await monitor.check_once()

    event_bus.publish.assert_called_once()
    call_args = event_bus.publish.call_args
    assert "disconnect" in str(call_args).lower()


# ---------------------------------------------------------------------------
# TC-ARCH-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-ARCH-050")
@pytest.mark.priority("P2")
async def test_tc_arch_050_alpaca_udp_discovery():
    """ARCH-050: Alpaca UDP discovery populates the connect dialog with discovered devices."""
    alpaca = pytest.importorskip("galileo.adapters.alpaca")
    discovery = alpaca.AlpacaDiscovery()

    fake_response = [
        {"AlpacaPort": 11111, "ServerName": "TestAlpaca1"},
        {"AlpacaPort": 11112, "ServerName": "TestAlpaca2"},
    ]
    discovery._raw_discover = AsyncMock(return_value=fake_response)
    results = await discovery.discover(timeout_s=0.1)
    assert len(results) == 2
    assert results[0]["AlpacaPort"] == 11111


# ---------------------------------------------------------------------------
# TC-ARCH-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-ARCH-060")
@pytest.mark.priority("MVP")
async def test_tc_arch_060_misbehaving_device_isolated(event_bus):
    """ARCH-060: A misbehaving device connection does not block or degrade other connected devices."""
    devices = pytest.importorskip("galileo.core.devices")
    pool = devices.DevicePool(event_bus=event_bus)

    bad_cam = MagicMock(name="BadCamera")
    bad_cam.device_type = "Camera"
    bad_cam.name = "BadCamera"
    bad_cam.is_connected = True
    bad_cam.get_properties = MagicMock(side_effect=RuntimeError("driver crash"))

    good_foc = MagicMock(name="GoodFocuser")
    good_foc.device_type = "Focuser"
    good_foc.name = "GoodFocuser"
    good_foc.is_connected = True
    good_foc.get_properties = MagicMock(return_value={"position": 5000})

    pool.register(bad_cam)
    pool.register(good_foc)

    # Polling the bad device must not raise; good device still accessible
    pool.poll_all()
    props = pool.get_properties("GoodFocuser")
    assert props["position"] == 5000


# ---------------------------------------------------------------------------
# TC-ARCH-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-ARCH-070")
@pytest.mark.priority("P2")
def test_tc_arch_070_plugin_registers_device_backend():
    """ARCH-070: The device-abstraction layer is the sole integration point plugins use for new device backends."""
    devices = pytest.importorskip("galileo.core.devices")
    plugins = pytest.importorskip("galileo.plugins")

    class MyCustomAdapter(devices.DeviceBackend):
        backend = "custom"

        async def connect(self): pass
        async def disconnect(self): pass
        @property
        def is_connected(self): return True
        def get_capabilities(self): return devices.DeviceCapabilities()
        def get_properties(self): return {}

    ctx = plugins.PluginContext.__new__(plugins.PluginContext)
    ctx.register_device_backend(devices.DeviceCategory.CAMERA, MyCustomAdapter)
    registered = devices.DeviceBackend.registered_backends.get(devices.DeviceCategory.CAMERA, [])
    assert MyCustomAdapter in registered


# ---------------------------------------------------------------------------
# TC-ARCH-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-ARCH-080")
@pytest.mark.priority("MVP")
def test_tc_arch_080_multiple_device_pools_per_pier():
    """ARCH-080: Multiple concurrently addressable device pools (one per Pier) for multi-mount support."""
    devices = pytest.importorskip("galileo.core.devices")
    pool1 = devices.DevicePool(pier_name="Pier-1")
    pool2 = devices.DevicePool(pier_name="Pier-2")

    assert pool1.pier_name == "Pier-1"
    assert pool2.pier_name == "Pier-2"
    assert pool1 is not pool2

    cam1 = MagicMock(name="Cam1", device_type="Camera")
    cam2 = MagicMock(name="Cam2", device_type="Camera")
    pool1.register(cam1)
    pool2.register(cam2)

    assert pool1.get("Camera") is cam1
    assert pool2.get("Camera") is cam2


# ---------------------------------------------------------------------------
# TC-ARCH-090 — configuration lives in the shared database
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-ARCH-090")
@pytest.mark.priority("MVP")
def test_tc_arch_090_settings_store_round_trips_namespaces_and_scopes(settings_db):
    """ARCH-090: configuration is stored in the shared database through one settings store, per namespace, key and scope."""
    from galileo import settings_store as store
    assert store.available()
    assert store.get_setting("demo", "a", "dflt") == "dflt"
    assert store.set_setting("demo", "a", {"x": [1, 2]})
    assert store.set_setting("demo", "a", {"x": [3]})                    # overwrite, not duplicate
    assert store.get_setting("demo", "a") == {"x": [3]}
    store.set_setting("demo", "a", "pier-specific", scope="Pier A")
    assert store.get_setting("demo", "a") == {"x": [3]}
    assert store.get_namespace("demo", scope="Pier A") == {"a": "pier-specific"}
    store.set_namespace("demo", {"b": 1}, replace=True)
    assert store.get_namespace("demo") == {"b": 1}
    store.delete_setting("demo", "b")
    assert store.get_namespace("demo") == {}


@pytest.mark.requirement("TC-ARCH-090")
@pytest.mark.priority("MVP")
def test_tc_arch_090_settings_fall_back_to_defaults_without_a_database():
    """ARCH-090: with no database available, reads return defaults and writes are dropped instead of raising (early start-up, the watchdog)."""
    from galileo import settings_store as store
    from galileo.watchdog_settings import DEFAULTS, load_watchdog_settings, save_watchdog_settings
    assert not store.available()
    assert store.get_setting("demo", "a", 5) == 5
    assert store.set_setting("demo", "a", 1) is False
    save_watchdog_settings({"enabled": False, "timeout_s": 60})          # must not raise
    assert load_watchdog_settings() == DEFAULTS


@pytest.mark.requirement("TC-ARCH-090")
@pytest.mark.priority("MVP")
def test_tc_arch_090_legacy_json_is_imported_once_and_renamed(settings_db, tmp_path):
    """ARCH-090: an old settings JSON file is imported into the database once and renamed *.migrated, never deleted."""
    from galileo import settings_store as store
    legacy = tmp_path / "old.json"
    legacy.write_text('{"k": 1, "j": [true]}', encoding="utf-8")
    assert store.import_legacy_json("legacy_demo", legacy) == {"k": 1, "j": [True]}
    assert not legacy.exists() and (tmp_path / "old.json.migrated").exists()
    legacy.write_text('{"k": 99}', encoding="utf-8")                      # a second file never overwrites the database
    assert store.import_legacy_json("legacy_demo", legacy)["k"] == 1


@pytest.mark.requirement("TC-ARCH-090")
@pytest.mark.priority("MVP")
def test_tc_arch_090_library_settings_live_in_the_database_without_passwords(settings_db, config_folder, monkeypatch):
    """ARCH-090: the Options > Library settings are stored in the database, an old library.ini is imported once, and no password is stored."""
    import galileo.library.config as library_config
    config_dir = config_folder
    ini = config_dir / "library.ini"
    ini.write_text("[DEFAULT]\nrepo = /data/repo\nitelescope_password = hunter2\nsftp_password = pw\n", encoding="utf-8")
    saved = []
    monkeypatch.setattr(library_config, "set_itelescope_password", saved.append)   # no real keychain
    assert library_config.get_repository_path() == "/data/repo"
    assert saved == ["hunter2"] and not ini.exists() and (config_dir / "library.ini.migrated").exists()

    from galileo.settings_store import get_namespace
    config = library_config.load_config()
    config.set("DEFAULT", "source", "/data/in")
    config.set("DEFAULT", "sftp_password", "nope")
    library_config.save_config(config)
    stored = get_namespace("library")
    assert stored["repo"] == "/data/repo" and stored["source"] == "/data/in"
    assert not any("password" in key for key in stored)


@pytest.mark.requirement("TC-ARCH-090")
@pytest.mark.priority("MVP")
def test_tc_arch_090_equipment_profiles_live_in_the_database(settings_db, tmp_path, minimal_profile):
    """ARCH-090: equipment profiles and the last-used name are database rows; old *.gpf files are imported once and renamed."""
    import json
    from galileo.equipment.profiles import ProfileManager
    legacy = tmp_path / "profiles"
    legacy.mkdir()
    (legacy / "Old.gpf").write_text(json.dumps(dict(minimal_profile, name="Old")), encoding="utf-8")
    (legacy / ".last_used").write_text("Old", encoding="utf-8")
    mgr = ProfileManager(storage_dir=legacy)
    assert (legacy / "Old.gpf.migrated").exists() and not (legacy / "Old.gpf").exists()
    mgr.save(minimal_profile)
    fresh = ProfileManager(storage_dir=tmp_path / "elsewhere")             # nothing in memory: reads the database
    assert set(fresh.list_names()) == {"Old", "TestSetup"}
    assert fresh.get("TestSetup").piers[0].optical_trains[0].name == "MainScope"
    assert fresh.get_last_used_name() == "Old"
    fresh.delete("Old")
    assert not ProfileManager(storage_dir=tmp_path / "x").exists("Old")


@pytest.mark.requirement("TC-ARCH-090")
@pytest.mark.priority("MVP")
def test_tc_arch_090_migration_028_survives_fake_replay(tmp_path):
    """ARCH-090: the app_settings migration is idempotent and survives peewee-migrate's fake replay."""
    import importlib
    from unittest.mock import MagicMock
    mod = importlib.import_module("galileo.library.migrations.028_add_app_settings")
    migrator = MagicMock()
    mod.migrate(migrator, MagicMock(), fake=True)
    mod.migrate(migrator, MagicMock(), fake=True)
    statements = " ".join(str(c.args[0]) for c in migrator.sql.call_args_list)
    assert "CREATE TABLE IF NOT EXISTS app_settings" in statements and "CREATE UNIQUE INDEX IF NOT EXISTS" in statements

    from galileo.library.database import db, get_migration_status, init_db
    init_db(tmp_path / "twice.db")
    try:
        init_db(tmp_path / "twice.db")                                      # re-running migrations is a no-op
        assert db.table_exists("app_settings")
        assert not get_migration_status()["undone"]
    finally:
        db.close()
