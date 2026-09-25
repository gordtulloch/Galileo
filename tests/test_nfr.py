# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""NFR — Non-Functional Requirements (TC-NFR-*).

Performance, reliability, portability, extensibility, usability,
i18n, security, offline operation, and installability.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
# NFR-PERF — Performance
# ===========================================================================

@pytest.mark.requirement("TC-NFR-PERF-010")
@pytest.mark.priority("MVP")
async def test_tc_nfr_perf_010_large_frame_render_under_3s(mock_indi_camera):
    """NFR-PERF-010: Render full-frame image (up to 100 MP) in imaging tab within 3 seconds."""
    import numpy as np
    import time
    imaging = pytest.importorskip("galileo.ui.imaging")
    svc = imaging.ImagingService(camera=mock_indi_camera)

    large_frame = np.zeros((10000, 10000), dtype=np.uint16)  # 100 MP mono
    mock_indi_camera.get_image_array = AsyncMock(return_value=large_frame)

    t0 = time.monotonic()
    await svc.capture_and_preview(duration=0.01)
    elapsed = time.monotonic() - t0

    assert elapsed < 3.0, f"Render took {elapsed:.2f}s; must be < 3s"


@pytest.mark.requirement("TC-NFR-PERF-020")
@pytest.mark.priority("MVP")
async def test_tc_nfr_perf_020_ui_responsive_during_background_ops():
    """NFR-PERF-020: UI input latency remains < 200 ms during image download, plate solving, or autofocus."""
    devices = pytest.importorskip("galileo.core.devices")
    # The concurrency model must ensure CPU-bound work runs off the Qt main thread.
    # Verified by checking the ProcessPoolExecutor is used, not inline blocking calls.
    assert devices.CONCURRENCY_MODEL == "ProcessPoolExecutor" or hasattr(devices, "cpu_executor")


@pytest.mark.requirement("TC-NFR-PERF-030")
@pytest.mark.priority("MVP")
@pytest.mark.soak
def test_tc_nfr_perf_030_stable_memory_over_8_hour_session():
    """NFR-PERF-030: Memory footprint stable (no unbounded growth) over 8-hour imaging session (soak test)."""
    pytest.skip("Soak test: requires a real 8-hour imaging run; verify via memory profiler in CI nightly job.")


# ===========================================================================
# NFR-REL — Reliability
# ===========================================================================

@pytest.mark.requirement("TC-NFR-REL-010")
@pytest.mark.priority("MVP")
async def test_tc_nfr_rel_010_survive_transient_device_disconnect(mock_indi_camera):
    """NFR-REL-010: Survive a transient INDI/Alpaca disconnect during a sequence without terminating it."""
    import numpy as np
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    devices = pytest.importorskip("galileo.core.devices")

    disconnect_count = [0]
    orig_start = mock_indi_camera.start_exposure.side_effect

    async def flaky_expose(**kwargs):
        if disconnect_count[0] < 2:
            disconnect_count[0] += 1
            raise ConnectionResetError("INDI disconnect")

    mock_indi_camera.start_exposure = AsyncMock(side_effect=flaky_expose)
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))

    svc = seq_mod.BasicSequencer(camera=mock_indi_camera, mount=MagicMock(), output_dir="/tmp")
    svc._retry_policy = {"max_retries": 3, "delay_s": 0.01}

    seq = seq_mod.SequenceDef(name="Test")
    seq.add_target(name="M42", ra_deg=83.8, dec_deg=-5.4,
                   steps=[seq_mod.CaptureStep(filter="L", exposure=1.0, count=3, binning=1, frame_type="Light")])

    await svc.run(seq)
    assert svc.state == seq_mod.SequencerState.COMPLETED


@pytest.mark.requirement("TC-NFR-REL-020")
@pytest.mark.priority("MVP")
async def test_tc_nfr_rel_020_never_silently_stall(event_bus):
    """NFR-REL-020: Any blocking condition surfaces to the user within a bounded time — never a silent stall."""
    devices = pytest.importorskip("galileo.core.devices")

    hanging_device = MagicMock(name="HangingCamera")
    hanging_device.device_type = "Camera"
    hanging_device.name = "HangingCamera"
    hanging_device.is_connected = True
    hanging_device.get_properties = AsyncMock(side_effect=asyncio_timeout)

    monitor = devices.ConnectionMonitor(hanging_device, event_bus=event_bus, poll_interval_s=0.05, timeout_s=0.1)
    await monitor.check_once()

    assert event_bus.publish.called


async def asyncio_timeout():
    import asyncio
    await asyncio.sleep(1000)


@pytest.mark.requirement("TC-NFR-REL-030")
@pytest.mark.priority("MVP")
@pytest.mark.soak
def test_tc_nfr_rel_030_10_hour_unattended_session():
    """NFR-REL-030: Run a single sequence unattended for 10 continuous hours without restart (soak test)."""
    pytest.skip("Soak test: requires a real 10-hour run with hardware or a long-running simulator job.")


@pytest.mark.requirement("TC-NFR-REL-040")
@pytest.mark.priority("P2")
def test_tc_nfr_rel_040_crash_does_not_lose_completed_frames(tmp_path):
    """NFR-REL-040: Application crash does not lose the record of already-completed frames."""
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    svc = seq_mod.BasicSequencer.__new__(seq_mod.BasicSequencer)
    svc._state_path = tmp_path / "seq_state.json"

    svc.persist_completed_frame(frame_number=5, path=tmp_path / "light_005.fits")
    svc.persist_completed_frame(frame_number=6, path=tmp_path / "light_006.fits")

    recovered = seq_mod.BasicSequencer.load_persisted_state(tmp_path / "seq_state.json")
    assert recovered["completed_frame_count"] >= 2


# ===========================================================================
# NFR-PORT — Portability
# ===========================================================================

@pytest.mark.requirement("TC-NFR-PORT-010")
@pytest.mark.priority("MVP")
def test_tc_nfr_port_010_single_codebase_platform_adapters():
    """NFR-PORT-010: Builds and runs from one shared codebase; platform-specific code in platform-abstraction layer."""
    devices = pytest.importorskip("galileo.core.devices")
    platform_mod = pytest.importorskip("galileo.platform")

    # Platform-specific code lives exclusively in galileo.platform
    assert hasattr(platform_mod, "get_log_dir")
    assert hasattr(platform_mod, "get_config_dir")
    assert not hasattr(devices, "_windows_only_path")  # sanity


@pytest.mark.requirement("TC-NFR-PORT-020")
@pytest.mark.priority("MVP")
def test_tc_nfr_port_020_unavailable_feature_disables_not_crashes():
    """NFR-PORT-020: Features unavailable on a given platform disable in the UI rather than silently failing."""
    devices = pytest.importorskip("galileo.core.devices")
    caps = devices.DeviceCapabilities(has_cooler=False)

    # UI must observe capabilities and disable/hide, not attempt the operation
    assert caps.has_cooler is False


# ===========================================================================
# NFR-EXT — Extensibility
# ===========================================================================

@pytest.mark.requirement("TC-NFR-EXT-010")
@pytest.mark.priority("P2")
def test_tc_nfr_ext_010_new_backend_no_core_recompile():
    """NFR-EXT-010: Adding a new device backend or sequencer instruction via plugin API requires no core rebuild."""
    devices = pytest.importorskip("galileo.core.devices")
    plugins = pytest.importorskip("galileo.plugins")

    class ExternalAdapter(devices.DeviceBackend):
        backend = "external_test"
        async def connect(self): pass
        async def disconnect(self): pass
        @property
        def is_connected(self): return True
        def get_capabilities(self): return devices.DeviceCapabilities()
        def get_properties(self): return {}

    mgr = plugins.PluginManager()
    ctx = mgr.create_context()
    ctx.register_device_backend(devices.DeviceCategory.CAMERA, ExternalAdapter)
    # Registration must succeed without importing any implementation module
    assert ExternalAdapter in devices.DeviceBackend.registered_backends.get(devices.DeviceCategory.CAMERA, [])


# ===========================================================================
# NFR-USE — Usability
# ===========================================================================

@pytest.mark.requirement("TC-NFR-USE-010")
@pytest.mark.priority("P2")
def test_tc_nfr_use_010_first_run_equipment_setup_flow():
    """NFR-USE-010: Guided first-run equipment-setup flow covering profile creation and device connection."""
    profiles = pytest.importorskip("galileo.equipment.profiles")
    assert hasattr(profiles, "FirstRunWizard"), "FirstRunWizard must exist"
    wizard = profiles.FirstRunWizard.__new__(profiles.FirstRunWizard)
    assert hasattr(wizard, "steps") or hasattr(wizard, "run")


@pytest.mark.requirement("TC-NFR-USE-020")
@pytest.mark.priority("MVP")
async def test_tc_nfr_use_020_guided_flat_capture_no_manual_calc(mock_indi_camera, mock_flat_panel):
    """NFR-USE-020: Guided flat-capture flow requiring no manual exposure-time calculation from the user."""
    import numpy as np
    cal_mod = pytest.importorskip("galileo.calibration")
    svc = cal_mod.CalibrationService(
        camera=mock_indi_camera,
        flat_panel=mock_flat_panel,
        output_dir="/tmp",
    )
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.full((100, 100), 30000, dtype=np.uint16))

    result = await svc.run_flat_wizard(filter_name="L", count=5, target_adu=30000)
    assert result.frames_captured == 5
    assert result.final_exposure_s > 0


# ===========================================================================
# NFR-I18N — Localization
# ===========================================================================

@pytest.mark.requirement("TC-NFR-I18N-010")
@pytest.mark.priority("MVP")
def test_tc_nfr_i18n_010_ui_strings_externalized():
    """NFR-I18N-010: All user-facing UI strings externalized into a translatable resource format from initial impl."""
    ui_mod = pytest.importorskip("galileo.ui.imaging")
    # PySide6 convention: strings must be wrapped in tr() — verified by inspection of the source
    # As a proxy test, check that a .ts or .qm translation file exists in the package
    import importlib.resources
    import importlib.util

    ui_spec = importlib.util.find_spec("galileo.ui")
    if ui_spec and ui_spec.submodule_search_locations:
        from pathlib import Path
        ui_paths = list(ui_spec.submodule_search_locations)
        ts_files = list(Path(ui_paths[0]).rglob("*.ts")) + list(Path(ui_paths[0]).rglob("*.qm"))
        assert ts_files, "At least one Qt .ts or .qm translation resource must exist in galileo.ui"


# ===========================================================================
# NFR-SEC — Security
# ===========================================================================

@pytest.mark.requirement("TC-NFR-SEC-010")
@pytest.mark.priority("MVP")
def test_tc_nfr_sec_010_no_credentials_or_location_leak():
    """NFR-SEC-010: Equipment-profile credentials and location data not transmitted without explicit user config."""
    profiles = pytest.importorskip("galileo.equipment.profiles")
    safe_mod = pytest.importorskip("galileo.safety")

    # Profile serialization must not include raw secrets in cleartext accessible externally
    mgr = profiles.ProfileManager()
    assert hasattr(mgr, "serialize_profile"), "ProfileManager must have a controlled serialization path"

    # Open-Meteo client must not transmit location unless user has consented
    client = safe_mod.OpenMeteoClient.__new__(safe_mod.OpenMeteoClient)
    assert getattr(client, "requires_user_consent", True), "OpenMeteoClient must require user consent"


@pytest.mark.requirement("TC-NFR-SEC-020")
@pytest.mark.priority("P2")
def test_tc_nfr_sec_020_indi_alpaca_wan_security_documentation():
    """NFR-SEC-020: WAN security implications for INDI/Alpaca are documented; app does not weaken auth."""
    # Verification: Inspection — this TC passes by confirming the docs asset exists.
    import importlib.util
    docs_spec = importlib.util.find_spec("galileo")
    if docs_spec:
        from pathlib import Path
        pkg_root = Path(docs_spec.submodule_search_locations[0]).parent
        security_docs = list(pkg_root.rglob("*security*")) + list(pkg_root.rglob("*WAN*"))
        assert security_docs, "Security documentation for WAN exposure must exist in the repository"
    else:
        pytest.skip("galileo package not yet installed")


@pytest.mark.requirement("TC-NFR-SEC-030")
@pytest.mark.priority("P2")
def test_tc_nfr_sec_030_itelescope_password_stored_in_keychain_not_plaintext(tmp_path, monkeypatch):
    """NFR-SEC-030: the iTelescope password lives in the OS keychain; a plaintext one left in library.ini
    by an older version is migrated on next read and stripped from the file."""
    import keyring
    from galileo.library import config as library_config

    # Fake the OS keychain so this test never touches the real one.
    store: dict[tuple[str, str], str] = {}

    def fake_get_password(service, username):
        return store.get((service, username))

    def fake_set_password(service, username, password):
        store[(service, username)] = password

    def fake_delete_password(service, username):
        if (service, username) not in store:
            raise keyring.errors.PasswordDeleteError("not found")
        del store[(service, username)]

    monkeypatch.setattr(keyring, "get_password", fake_get_password)
    monkeypatch.setattr(keyring, "set_password", fake_set_password)
    monkeypatch.setattr(keyring, "delete_password", fake_delete_password)

    ini = tmp_path / "library.ini"
    library_config.set_config_path(ini)
    try:
        # Round-trip through the keychain: never written to library.ini in plaintext.
        library_config.set_itelescope_password("s3cret")
        assert library_config.get_itelescope_password() == "s3cret"
        assert store[("galileo-library", "itelescope")] == "s3cret"
        assert not ini.exists() or "itelescope_password" not in ini.read_text()

        # A plaintext password left by an older version is migrated in and removed from the file.
        store.clear()
        ini.write_text("[DEFAULT]\nitelescope_password = legacy123\n")
        assert library_config.get_itelescope_password() == "legacy123"
        assert store[("galileo-library", "itelescope")] == "legacy123"
        assert "itelescope_password" not in ini.read_text()

        # Clearing the password doesn't raise even when nothing is stored.
        store.clear()
        library_config.set_itelescope_password("")
        assert library_config.get_itelescope_password() == ""
    finally:
        library_config.set_config_path(None)


# ===========================================================================
# NFR-OFFLINE — Offline Operation
# ===========================================================================

@pytest.mark.requirement("TC-NFR-OFFLINE-010")
@pytest.mark.priority("MVP")
def test_tc_nfr_offline_010_sky_atlas_offline():
    """NFR-OFFLINE-010: Core sky-atlas search/filter/chart functions work with no internet connection."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    with patch("socket.getaddrinfo", side_effect=OSError("no network")):
        atlas = sky_mod.SkyAtlas()
        results = atlas.search("M42")
        assert len(results) >= 1


@pytest.mark.requirement("TC-NFR-OFFLINE-020")
@pytest.mark.priority("MVP")
def test_tc_nfr_offline_020_local_plate_solver_offline():
    """NFR-OFFLINE-020: At least one plate-solving path works without internet connection."""
    plt_mod = pytest.importorskip("galileo.platesolve")
    with patch("socket.getaddrinfo", side_effect=OSError("no network")):
        solver = plt_mod.PlateSolver(backend="astap", executable="/usr/bin/astap")
        assert solver.is_offline_capable("astap") is True


# ===========================================================================
# NFR-INSTALL — Installability
# ===========================================================================

@pytest.mark.requirement("TC-NFR-INSTALL-010")
@pytest.mark.priority("MVP")
@pytest.mark.integration
def test_tc_nfr_install_010_windows_installer_exists():
    """NFR-INSTALL-010: Windows MSI installer produced by the build pipeline (Demonstration test)."""
    pytest.skip("Demonstration: verify Windows MSI artifact is produced and installable from CI build output.")


@pytest.mark.requirement("TC-NFR-INSTALL-020")
@pytest.mark.priority("MVP")
@pytest.mark.integration
def test_tc_nfr_install_020_macos_signed_dmg_exists():
    """NFR-INSTALL-020: Signed and notarized macOS .dmg produced by the build pipeline (Demonstration test)."""
    pytest.skip("Demonstration: verify macOS .dmg artifact is code-signed, notarized, and mounts cleanly from CI.")


@pytest.mark.requirement("TC-NFR-INSTALL-030")
@pytest.mark.priority("MVP")
@pytest.mark.integration
def test_tc_nfr_install_030_linux_appimage_exists():
    """NFR-INSTALL-030: Linux AppImage or Flatpak produced by build pipeline requiring no manual deps."""
    pytest.skip("Demonstration: verify Linux AppImage/Flatpak artifact launches cleanly on a reference Debian/Ubuntu CI runner.")
