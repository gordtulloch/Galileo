# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""PROF — Equipment Profiles / Piers (TC-PROF-010 … TC-PROF-090)."""

import pytest


# ---------------------------------------------------------------------------
# TC-PROF-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PROF-010")
@pytest.mark.priority("MVP")
def test_tc_prof_010_save_current_devices_as_named_profile(minimal_profile):
    """PROF-010: Allow saving the current device connections/settings as a named equipment profile."""
    profiles = pytest.importorskip("galileo.equipment.profiles")
    mgr = profiles.ProfileManager()
    mgr.save(minimal_profile)

    assert mgr.exists("TestSetup")


# ---------------------------------------------------------------------------
# TC-PROF-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PROF-020")
@pytest.mark.priority("MVP")
async def test_tc_prof_020_load_profile_reconnects_devices(minimal_profile):
    """PROF-020: Load a saved profile, reconnecting all devices it references."""
    profiles = pytest.importorskip("galileo.equipment.profiles")
    mgr = profiles.ProfileManager()
    mgr.save(minimal_profile)

    connect_calls = []

    async def fake_connect(device_config):
        connect_calls.append(device_config["name"])

    loaded = await mgr.load("TestSetup", connect_fn=fake_connect)
    assert loaded.name == "TestSetup"
    assert "SimCamera" in connect_calls


# ---------------------------------------------------------------------------
# TC-PROF-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PROF-030")
@pytest.mark.priority("MVP")
def test_tc_prof_030_multiple_profiles_crud(minimal_profile, tmp_path):
    """PROF-030: Create, rename, and delete multiple equipment profiles."""
    profiles = pytest.importorskip("galileo.equipment.profiles")
    mgr = profiles.ProfileManager(storage_dir=tmp_path)

    profile_a = dict(minimal_profile, name="Rig-A")
    profile_b = dict(minimal_profile, name="Rig-B")
    mgr.save(profile_a)
    mgr.save(profile_b)

    assert set(mgr.list_names()) >= {"Rig-A", "Rig-B"}

    mgr.rename("Rig-A", "Rig-Alpha")
    assert mgr.exists("Rig-Alpha")
    assert not mgr.exists("Rig-A")

    mgr.delete("Rig-B")
    assert not mgr.exists("Rig-B")


# ---------------------------------------------------------------------------
# TC-PROF-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PROF-040")
@pytest.mark.priority("MVP")
def test_tc_prof_040_persist_last_used_profile(minimal_profile, tmp_path):
    """PROF-040: Persist the last-used profile and offer to reload it on application start."""
    profiles = pytest.importorskip("galileo.equipment.profiles")
    mgr = profiles.ProfileManager(storage_dir=tmp_path)
    mgr.save(minimal_profile)
    mgr.set_last_used("TestSetup")

    # Simulate app restart with a fresh manager
    mgr2 = profiles.ProfileManager(storage_dir=tmp_path)
    assert mgr2.get_last_used_name() == "TestSetup"


# ---------------------------------------------------------------------------
# TC-PROF-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PROF-050")
@pytest.mark.priority("P2")
def test_tc_prof_050_export_import_portable_file(minimal_profile, tmp_path):
    """PROF-050: Export a profile to a portable file and import it back."""
    profiles = pytest.importorskip("galileo.equipment.profiles")
    mgr = profiles.ProfileManager(storage_dir=tmp_path / "storage")
    mgr.save(minimal_profile)

    export_dir = tmp_path / "export"
    export_dir.mkdir()
    export_path = export_dir / "TestSetup.gpf"
    mgr.export("TestSetup", export_path)
    assert export_path.exists()

    mgr.delete("TestSetup")
    assert not mgr.exists("TestSetup")

    mgr.import_profile(export_path)
    assert mgr.exists("TestSetup")


# ---------------------------------------------------------------------------
# TC-PROF-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PROF-060")
@pytest.mark.priority("MVP")
async def test_tc_prof_060_warn_on_missing_device_at_load(minimal_profile, tmp_path):
    """PROF-060: Warn rather than silently fail when a profile references an unreachable device at load time."""
    profiles = pytest.importorskip("galileo.equipment.profiles")
    mgr = profiles.ProfileManager(storage_dir=tmp_path)
    mgr.save(minimal_profile)

    async def always_unreachable(device_config):
        raise ConnectionError(f"Cannot reach {device_config['name']}")

    warnings = []
    with pytest.warns(profiles.DeviceUnreachableWarning):
        loaded = await mgr.load("TestSetup", connect_fn=always_unreachable)

    assert loaded is not None, "Load must succeed with partial connection"


# ---------------------------------------------------------------------------
# TC-PROF-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PROF-070")
@pytest.mark.priority("MVP")
def test_tc_prof_070_optical_train_definition(minimal_profile):
    """PROF-070: Organize devices into a named optical train: telescope → reducer/FW/rotator → camera."""
    profiles = pytest.importorskip("galileo.equipment.profiles")
    mgr = profiles.ProfileManager()
    mgr.save(minimal_profile)
    profile = mgr.get("TestSetup")

    train = profile.piers[0].optical_trains[0]
    assert train.name == "MainScope"
    assert train.focal_length_mm == 1000
    assert train.camera["name"] == "SimCamera"


# ---------------------------------------------------------------------------
# TC-PROF-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PROF-080")
@pytest.mark.priority("MVP")
def test_tc_prof_080_multiple_optical_trains_in_profile(tmp_path):
    """PROF-080: Support multiple concurrently defined optical trains within one equipment profile."""
    profiles = pytest.importorskip("galileo.equipment.profiles")
    mgr = profiles.ProfileManager(storage_dir=tmp_path)

    profile_data = {
        "name": "DualScope",
        "version": 1,
        "piers": [
            {
                "name": "Pier-1",
                "optical_trains": [
                    {"name": "Widefield", "focal_length_mm": 500, "aperture_mm": 100, "camera": {"name": "Cam1", "backend": "indi", "host": "localhost"}},
                    {"name": "Narrowfield", "focal_length_mm": 2000, "aperture_mm": 300, "camera": {"name": "Cam2", "backend": "indi", "host": "localhost"}},
                ],
            }
        ],
    }
    mgr.save(profile_data)
    profile = mgr.get("DualScope")

    assert len(profile.piers[0].optical_trains) == 2
    train_names = [t.name for t in profile.piers[0].optical_trains]
    assert "Widefield" in train_names
    assert "Narrowfield" in train_names


# ---------------------------------------------------------------------------
# TC-PROF-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PROF-090")
@pytest.mark.priority("MVP")
def test_tc_prof_090_auto_derive_focal_length_and_plate_scale(minimal_profile):
    """PROF-090: Auto-derive effective focal length and plate scale from optical train chain."""
    profiles = pytest.importorskip("galileo.equipment.profiles")
    mgr = profiles.ProfileManager()
    mgr.save(minimal_profile)
    profile = mgr.get("TestSetup")
    train = profile.piers[0].optical_trains[0]

    # plate scale = (pixel_size_um / focal_length_mm) * 206.265  [arcsec/px]
    expected_plate_scale = (5.86 / 1000.0) * 206.265
    assert abs(train.plate_scale_arcsec_px - expected_plate_scale) < 0.01
    assert train.effective_focal_length_mm == 1000
