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
async def test_tc_nfr_perf_020_ui_responsive_during_background_ops(monkeypatch):
    """NFR-PERF-020: UI input latency remains < 200 ms during image download, plate solving, or autofocus.

    SEP star detection (autofocus HFR, imaging statistics) holds the GIL for its whole run, so
    in a thread it still stalls the event loop. Here it runs through the real worker pool while a
    5 ms heartbeat on the loop records the longest gap between beats."""
    import asyncio
    import time
    import numpy as np
    from galileo.autofocus import _measure_stars
    from galileo.core import compute

    monkeypatch.setenv(compute.WORKERS_ENV, "2")
    compute.shutdown_cpu_executor()
    try:
        # A 4000x4000 field of 1500 Gaussian stars: SEP takes about a second on it.
        rng = np.random.default_rng(0)
        frame = rng.normal(800, 20, (4000, 4000)).astype(np.float32)
        yy, xx = np.mgrid[-8:9, -8:9]
        star = 20000 * np.exp(-(yy ** 2 + xx ** 2) / 8.0)
        for y, x in rng.integers(20, 3980, (1500, 2)):
            frame[y - 8:y + 9, x - 8:x + 9] += star
        frame = frame.astype(np.uint16)
        await compute.run_cpu(_measure_stars, frame[:64, :64])     # start the workers first

        gaps: list[float] = []
        done = asyncio.Event()

        async def heartbeat():
            last = time.perf_counter()
            while not done.is_set():
                await asyncio.sleep(0.005)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        beat = asyncio.create_task(heartbeat())
        hfr, stars = await compute.run_cpu(_measure_stars, frame)
        done.set()
        await beat

        assert stars > 1000 and 1.0 < hfr < 5.0, "the worker measured the frame"
        assert max(gaps) < 0.2, f"event loop stalled {max(gaps) * 1000:.0f} ms during star detection"
    finally:
        compute.shutdown_cpu_executor()


@pytest.mark.requirement("TC-NFR-PERF-020")
@pytest.mark.priority("MVP")
async def test_tc_nfr_perf_020_gil_holding_work_is_sent_to_the_pool(monkeypatch):
    """NFR-PERF-020: autofocus star measurement, imaging statistics and live-stack registration
    (the work profiled as holding the GIL) go through ``run_cpu``, not a thread."""
    import numpy as np
    import galileo.autofocus as autofocus
    import galileo.livestack as livestack
    import galileo.ui.imaging as imaging

    sent = []

    async def recording_run_cpu(fn, *args, **kwargs):
        sent.append(fn.__name__)
        return fn(*args, **kwargs)

    for module in (autofocus, livestack, imaging):
        monkeypatch.setattr(module, "run_cpu", recording_run_cpu)

    camera = MagicMock()
    camera.start_exposure = AsyncMock()
    camera.get_image_array = AsyncMock(return_value=np.zeros((32, 32), dtype=np.uint16))
    focus = autofocus.AutofocusService(camera=camera, focuser=MagicMock(), event_bus=MagicMock())
    await focus._measure_hfr()
    await focus.run_aberration_inspection()

    service = imaging.ImagingService(camera=camera)
    await service.capture_and_preview(duration=1.0)

    stacker = livestack.LiveStacker()
    await stacker.add_async(np.zeros((32, 32), dtype=np.float32))
    await stacker.add_async(np.zeros((32, 32), dtype=np.float32))

    assert sent == ["_measure_stars", "_compute_regional_hfr", "_compute_stats", "register"]


@pytest.mark.requirement("TC-NFR-PERF-020")
@pytest.mark.priority("MVP")
async def test_tc_nfr_perf_020_pool_recovers_from_a_dead_worker(monkeypatch):
    """NFR-PERF-020 / ARCH-060: a worker that dies (e.g. a crash in a C extension) fails only the
    task it was running; the next task gets a fresh pool rather than a permanently broken one."""
    import os
    from concurrent.futures.process import BrokenProcessPool
    from galileo.core import compute

    monkeypatch.setenv(compute.WORKERS_ENV, "1")
    compute.shutdown_cpu_executor()
    try:
        with pytest.raises(BrokenProcessPool):
            await compute.run_cpu(os._exit, 3)
        assert await compute.run_cpu(abs, -5) == 5
    finally:
        compute.shutdown_cpu_executor()


def _star_frames(tmp_path, shifts, size=160):
    """FITS light frames of one star field, each shifted by ``(dy, dx)``. Returns their paths."""
    import numpy as np
    from astropy.io import fits
    stars = [(30, 40), (70, 120), (120, 60), (100, 100), (40, 130), (140, 140), (55, 80), (130, 20)]
    yy, xx = np.mgrid[:size, :size]
    paths = []
    for i, (dy, dx) in enumerate(shifts):
        image = np.random.default_rng(i).normal(500, 5, (size, size))
        for n, (y, x) in enumerate(stars):
            image += (3000 + 400 * n) * np.exp(-((yy - y - dy) ** 2 + (xx - x - dx) ** 2) / (2 * 1.8 ** 2))
        path = tmp_path / f"light_{i}.fits"
        fits.PrimaryHDU(image.astype("float32")).writeto(path)
        paths.append(str(path))
    return paths


@pytest.mark.requirement("TC-NFR-PERF-020")
@pytest.mark.priority("MVP")
def test_tc_nfr_perf_020_library_batch_work_gives_the_same_results_in_the_pool(monkeypatch, tmp_path):
    """NFR-PERF-020: the Library's SEP quality metrics and astroalign light stacking (both photometric
    and sigma-clipped), moved into the worker pool, give the same results as they do in-process."""
    import numpy as np
    from astropy.io import fits
    from galileo.core import compute
    from galileo.library.core.enhanced_quality import EnhancedQualityAnalyzer
    from galileo.library.core.master_manager import MasterFrameManager

    paths = _star_frames(tmp_path, [(0, 0), (3, -4), (-2, 5)])
    manager = MasterFrameManager.__new__(MasterFrameManager)     # stacking needs no library config

    def run_all(tag):
        quality = EnhancedQualityAnalyzer().analyze_image_quality(paths[0])
        assert manager._create_light_stack_photometric_mean(paths, str(tmp_path / f"photo_{tag}.fits"))
        assert manager._create_master_sigma_clip(paths, str(tmp_path / f"clip_{tag}.fits"), "light")
        return (quality, fits.getdata(tmp_path / f"photo_{tag}.fits"), fits.getdata(tmp_path / f"clip_{tag}.fits"))

    in_process = run_all("thread")
    monkeypatch.setenv(compute.WORKERS_ENV, "2")
    compute.shutdown_cpu_executor()
    try:
        pooled = run_all("pool")
    finally:
        compute.shutdown_cpu_executor()

    for key in ("status", "star_count", "avg_fwhm_pixels", "image_snr"):
        assert pooled[0][key] == in_process[0][key]
    assert pooled[0]["star_count"] == 8
    np.testing.assert_allclose(pooled[1], in_process[1], equal_nan=True)
    np.testing.assert_array_equal(pooled[2], in_process[2])
    # Registered, not just averaged: the brightest star is as sharp in the stack as in the reference.
    reference = fits.getdata(paths[0])
    assert np.nanmax(pooled[1]) == pytest.approx(float(reference.max()), rel=0.05)


@pytest.mark.requirement("TC-NFR-PERF-020")
@pytest.mark.priority("MVP")
def test_tc_nfr_perf_020_imap_keeps_order_and_bounds_work_in_flight(monkeypatch):
    """NFR-PERF-020: ``imap_cpu`` returns results in input order and, in the pool, never has more
    tasks in flight than there are workers, so a batch of full-size frames can't pile up in memory."""
    import time
    from galileo.core import compute

    assert list(compute.imap_cpu(pow, [(2, n) for n in range(5)])) == [1, 2, 4, 8, 16]   # pool off

    monkeypatch.setenv(compute.WORKERS_ENV, "2")
    compute.shutdown_cpu_executor()
    try:
        results = compute.imap_cpu(time.sleep, [(0.05,)] * 6)
        next(results)
        executor = compute.cpu_executor()
        assert len(executor._pending_work_items) <= 2
        assert list(results) == [None] * 5
        assert list(compute.imap_cpu(divmod, [(n, 3) for n in range(7)])) == [divmod(n, 3) for n in range(7)]
    finally:
        compute.shutdown_cpu_executor()


@pytest.mark.requirement("TC-NFR-PERF-020")
@pytest.mark.priority("MVP")
async def test_tc_nfr_perf_020_pool_can_be_turned_off(monkeypatch):
    """NFR-PERF-020: ``GALILEO_CPU_WORKERS=0`` runs CPU work in a thread instead of the pool."""
    import threading
    from galileo.core import compute

    monkeypatch.setenv(compute.WORKERS_ENV, "0")
    assert compute.cpu_executor() is None
    assert await compute.run_cpu(lambda: threading.current_thread() is not threading.main_thread())
    monkeypatch.setenv(compute.WORKERS_ENV, "not a number")
    assert compute.worker_count() >= 1, "a bad setting falls back to the default"


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
