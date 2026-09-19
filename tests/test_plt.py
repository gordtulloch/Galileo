# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""PLT — Plate Solving (TC-PLT-010 … TC-PLT-060)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def solver():
    plt_mod = pytest.importorskip("galileo.platesolve")
    return plt_mod.PlateSolver(backend="astap", executable="/usr/bin/astap")


# ---------------------------------------------------------------------------
# TC-PLT-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLT-010")
@pytest.mark.priority("MVP")
async def test_tc_plt_010_invoke_solver_return_radec_rotation(solver, sample_fits_file):
    """PLT-010: Invoke external plate-solving engine against a frame and return solved RA/Dec and rotation."""
    plt_mod = pytest.importorskip("galileo.platesolve")
    solver._run_solver = AsyncMock(return_value=plt_mod.SolveResult(
        success=True,
        ra_deg=83.8221,
        dec_deg=-5.3911,
        rotation_deg=0.5,
        scale_arcsec_px=1.22,
    ))

    result = await solver.solve(sample_fits_file)
    assert result.success is True
    assert abs(result.ra_deg - 83.8221) < 0.01
    assert abs(result.dec_deg - (-5.3911)) < 0.01
    assert isinstance(result.rotation_deg, float)


# ---------------------------------------------------------------------------
# TC-PLT-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLT-020")
@pytest.mark.priority("MVP")
def test_tc_plt_020_supports_local_offline_solver():
    """PLT-020: Support at least one local/offline solver; functional without an internet connection."""
    plt_mod = pytest.importorskip("galileo.platesolve")
    assert plt_mod.PlateSolver.is_offline_capable("astap")
    assert plt_mod.PlateSolver.is_offline_capable("astrometry_local")

    with patch("socket.getaddrinfo", side_effect=OSError("no network")):
        solver = plt_mod.PlateSolver(backend="astap", executable="/usr/bin/astap")
        assert solver is not None


# ---------------------------------------------------------------------------
# TC-PLT-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLT-030")
@pytest.mark.priority("MVP")
async def test_tc_plt_030_solve_and_sync(solver, mock_indi_mount, sample_fits_file):
    """PLT-030: Solve-and-sync workflow syncs the mount's reported position to the solved coordinates."""
    plt_mod = pytest.importorskip("galileo.platesolve")
    solver._run_solver = AsyncMock(return_value=plt_mod.SolveResult(
        success=True, ra_deg=83.8221, dec_deg=-5.3911, rotation_deg=0.0, scale_arcsec_px=1.22
    ))

    await solver.solve_and_sync(sample_fits_file, mount=mock_indi_mount)
    mock_indi_mount.sync_to_coordinates.assert_called_with(ra=83.8221, dec=-5.3911)


# ---------------------------------------------------------------------------
# TC-PLT-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLT-040")
@pytest.mark.priority("MVP")
async def test_tc_plt_040_solve_and_center(solver, mock_indi_mount, mock_indi_camera, sample_fits_file):
    """PLT-040: Solve-and-center workflow iteratively slews and re-solves until within configured tolerance."""
    import numpy as np
    plt_mod = pytest.importorskip("galileo.platesolve")

    # First solve: 0.5° off center; second solve: within tolerance
    solve_results = [
        plt_mod.SolveResult(success=True, ra_deg=83.3, dec_deg=-5.9, rotation_deg=0.0, scale_arcsec_px=1.22),
        plt_mod.SolveResult(success=True, ra_deg=83.82, dec_deg=-5.39, rotation_deg=0.0, scale_arcsec_px=1.22),
    ]
    solver._run_solver = AsyncMock(side_effect=solve_results)
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.float32))

    await solver.solve_and_center(
        target_ra=83.8221,
        target_dec=-5.3911,
        mount=mock_indi_mount,
        camera=mock_indi_camera,
        tolerance_arcsec=30.0,
    )
    assert mock_indi_mount.slew_to_coordinates.call_count >= 1


# ---------------------------------------------------------------------------
# TC-PLT-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLT-050")
@pytest.mark.priority("MVP")
async def test_tc_plt_050_report_failure_distinctly(solver, sample_fits_file):
    """PLT-050: Report plate-solve failure distinctly from success; allow invoking workflow to react."""
    plt_mod = pytest.importorskip("galileo.platesolve")
    solver._run_solver = AsyncMock(return_value=plt_mod.SolveResult(
        success=False, ra_deg=None, dec_deg=None, rotation_deg=None, scale_arcsec_px=None,
        failure_reason="No matching stars found",
    ))

    result = await solver.solve(sample_fits_file)
    assert result.success is False
    assert result.failure_reason


# ---------------------------------------------------------------------------
# TC-PLT-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLT-060")
@pytest.mark.priority("P2")
def test_tc_plt_060_search_params_per_profile():
    """PLT-060: Configure solver search parameters (FOV hint, search radius, downsample) per equipment profile."""
    plt_mod = pytest.importorskip("galileo.platesolve")
    params = plt_mod.SolverParams(
        fov_hint_deg=1.2,
        search_radius_deg=15.0,
        downsample=2,
    )
    solver = plt_mod.PlateSolver(backend="astap", executable="/usr/bin/astap", params=params)
    assert solver.params.fov_hint_deg == 1.2
    assert solver.params.downsample == 2


# ---------------------------------------------------------------------------
# ASTAP integration details (PLT-010, PLT-050, PLT-060) — against a stand-in for the ASTAP process
# ---------------------------------------------------------------------------

# What a real ASTAP run wrote to <name>.ini for a successful solve of a north-up, east-left frame.
_ASTAP_OK_INI = """PLTSOLVD=T
CRPIX1= 8.0050000000000000E+002
CRPIX2= 6.0050000000000000E+002
CRVAL1= 1.1400188410380058E+002
CRVAL2=-3.8001301564651165E+001
CDELT1=-3.3335109550123448E-003
CDELT2= 3.3332229942587997E-003
CROTA1= 3.0367572026753159E-003
CROTA2=-5.4528860545771827E-003
CD1_1=-3.3335109503301796E-003
CD1_2=-1.7668078668481821E-007
CD2_1= 3.1722554975628003E-007
CD2_2= 3.3332229791634927E-003
"""


def _fake_astap(monkeypatch, returncode: int = 0, ini: str = "", stderr: bytes = b""):
    """Replace the ASTAP process. Returns the list its command lines are appended to.
    Like the real thing it writes its result to ``<-o value>.ini`` (when *ini* is given)."""
    import asyncio
    from pathlib import Path
    commands: list[list[str]] = []

    class _Proc:
        def __init__(self) -> None:
            self.returncode = returncode

        async def communicate(self):
            return b"", stderr

    async def fake_exec(*cmd, **kwargs):
        commands.append(list(cmd))
        if ini:
            Path(cmd[cmd.index("-o") + 1]).with_suffix(".ini").write_text(ini)
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return commands


@pytest.fixture
def astap(tmp_path):
    """A PlateSolver whose executable exists (it is never run) and a frame path for it to solve."""
    import sys
    plt_mod = pytest.importorskip("galileo.platesolve")
    solver = plt_mod.PlateSolver(backend="astap", executable=sys.executable,
                                 params=plt_mod.SolverParams(downsample=1))
    return solver, tmp_path / "frame.fits"


@pytest.mark.requirement("TC-PLT-010")
@pytest.mark.priority("MVP")
async def test_tc_plt_010_reads_the_solution_astap_writes(astap, monkeypatch):
    """PLT-010: Solved RA/Dec, rotation and pixel scale are read from the .ini file ASTAP writes."""
    solver, frame = astap
    _fake_astap(monkeypatch, ini=_ASTAP_OK_INI)
    result = await solver.solve(frame)
    assert result.success is True
    assert result.ra_deg == pytest.approx(114.00188, abs=1e-4)
    assert result.dec_deg == pytest.approx(-38.00130, abs=1e-4)
    assert result.scale_arcsec_px == pytest.approx(12.0006, abs=1e-3)
    assert result.rotation_deg == pytest.approx(0.0, abs=0.01)     # north up, east left is 0°, not 180°


@pytest.mark.requirement("TC-PLT-010")
@pytest.mark.priority("MVP")
async def test_tc_plt_010_scale_and_rotation_survive_a_rotated_frame(astap, monkeypatch):
    """PLT-010: Pixel scale is the size of a pixel however the frame is turned, and rotation is the angle it is turned by."""
    import math
    solver, frame = astap
    scale, angle = 2.0 / 3600.0, math.radians(30.0)               # 2″/px, north 30° from up
    ini = "\n".join([
        "PLTSOLVD=T", "CRVAL1=10.0", "CRVAL2=20.0",
        f"CD1_1={-scale * math.cos(angle)}", f"CD1_2={scale * math.sin(angle)}",
        f"CD2_1={scale * math.sin(angle)}", f"CD2_2={scale * math.cos(angle)}",
    ])
    _fake_astap(monkeypatch, ini=ini)
    result = await solver.solve(frame)
    assert result.scale_arcsec_px == pytest.approx(2.0, abs=1e-6)
    assert result.rotation_deg == pytest.approx(30.0, abs=1e-6)


@pytest.mark.requirement("TC-PLT-050")
@pytest.mark.priority("MVP")
async def test_tc_plt_050_failure_reason_comes_from_astap_ini(astap, monkeypatch):
    """PLT-050: A failed solve says why. ASTAP exits non-zero with nothing on stderr; the reason is in its .ini."""
    solver, frame = astap
    _fake_astap(monkeypatch, returncode=2, ini="PLTSOLVD=F\nERROR=Not enough stars.\n")
    result = await solver.solve(frame)
    assert result.success is False
    assert result.failure_reason == "Not enough stars."
    assert result.ra_deg is None


@pytest.mark.requirement("TC-PLT-050")
@pytest.mark.priority("MVP")
async def test_tc_plt_050_failure_reason_falls_back_to_the_exit_code(astap, monkeypatch):
    """PLT-050: With no .ini at all, the failure is still explained from ASTAP's exit code."""
    solver, frame = astap
    _fake_astap(monkeypatch, returncode=32)
    result = await solver.solve(frame)
    assert result.success is False
    assert "database" in result.failure_reason.lower()


@pytest.mark.requirement("TC-PLT-050")
@pytest.mark.priority("MVP")
async def test_tc_plt_050_a_stale_result_is_not_mistaken_for_this_solve(astap, monkeypatch):
    """PLT-050: An .ini left by an earlier solve of the same frame must not report a solution for a solve that failed."""
    solver, frame = astap
    frame.with_suffix(".ini").write_text(_ASTAP_OK_INI)
    _fake_astap(monkeypatch, returncode=1)                        # this run leaves no .ini of its own
    result = await solver.solve(frame)
    assert result.success is False


@pytest.mark.requirement("TC-PLT-060")
@pytest.mark.priority("P2")
async def test_tc_plt_060_search_parameters_reach_astap(tmp_path, monkeypatch):
    """PLT-060: The field-of-view hint, downsample and — given where the mount points — the search position and radius reach ASTAP."""
    import sys
    plt_mod = pytest.importorskip("galileo.platesolve")
    solver = plt_mod.PlateSolver(backend="astap", executable=sys.executable,
                                 params=plt_mod.SolverParams(fov_hint_deg=1.2, search_radius_deg=15.0, downsample=2))
    commands = _fake_astap(monkeypatch, ini=_ASTAP_OK_INI)
    await solver.solve(tmp_path / "frame.fits", hint=(114.0, -38.0))
    cmd = commands[-1]
    assert cmd[cmd.index("-fov") + 1] == "1.2"
    assert cmd[cmd.index("-z") + 1] == "2"                        # ASTAP's flag; it silently ignores "-down"
    assert "-down" not in cmd
    assert float(cmd[cmd.index("-ra") + 1]) == pytest.approx(114.0 / 15.0)          # hours
    assert float(cmd[cmd.index("-spd") + 1]) == pytest.approx(52.0)                 # Dec + 90°
    assert cmd[cmd.index("-r") + 1] == "15"

    await solver.solve(tmp_path / "frame.fits")                   # no idea where the mount points: blind search
    assert "-ra" not in commands[-1] and "-r" not in commands[-1]


@pytest.mark.requirement("TC-PLT-020")
@pytest.mark.priority("MVP")
def test_tc_plt_020_finds_astap_where_its_installer_puts_it(monkeypatch):
    """PLT-020: ASTAP is found in its usual install location when it isn't on PATH (the Windows installer never adds it)."""
    import shutil
    plt_mod = pytest.importorskip("galileo.platesolve")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(plt_mod, "_KNOWN_LOCATIONS", {"astap": ["/no/such/astap", __file__]})
    assert plt_mod.PlateSolver._find_executable("astap") == __file__
    monkeypatch.setattr(plt_mod, "_KNOWN_LOCATIONS", {"astap": ["/no/such/astap"]})
    assert plt_mod.PlateSolver._find_executable("astap") == ""


# ---------------------------------------------------------------------------
# PLT-070 — solves are announced on the event bus; coordinates
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_a_solve_is_announced_on_the_bus(tmp_path):
    """PLT-070: Every solve publishes a started and a complete event, so a screen can follow solves it didn't start."""
    from galileo.bus import EventBus, SolveCompleteEvent, SolveStartedEvent
    plt_mod = pytest.importorskip("galileo.platesolve")
    bus = EventBus()
    seen: list = []
    bus.subscribe(SolveStartedEvent, lambda e: seen.append(("started", e.fits_path)))
    bus.subscribe(SolveCompleteEvent, lambda e: seen.append(("complete", e.fits_path, e.result)))
    solver = plt_mod.PlateSolver(backend="astap", executable="unused", event_bus=bus)
    ok = plt_mod.SolveResult(success=True, ra_deg=10.0, dec_deg=20.0)
    solver._run_solver = AsyncMock(return_value=ok)

    frame = tmp_path / "a.fits"
    await solver.solve(frame)
    assert seen == [("started", str(frame)), ("complete", str(frame), ok)]

    solver._run_solver = AsyncMock(return_value=plt_mod.SolveResult(success=False, failure_reason="Not enough stars."))
    await solver.solve(frame)
    assert seen[-1][2].success is False and seen[-1][2].failure_reason == "Not enough stars."


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_a_cancelled_solve_still_completes_on_the_bus(tmp_path):
    """PLT-070: A solve that is cancelled is announced as ended, so the screen isn't left showing it as still solving."""
    import asyncio
    from galileo.bus import EventBus, SolveCompleteEvent
    plt_mod = pytest.importorskip("galileo.platesolve")
    bus = EventBus()
    done: list = []
    bus.subscribe(SolveCompleteEvent, lambda e: done.append(e.result))
    solver = plt_mod.PlateSolver(backend="astap", executable="unused", event_bus=bus)

    async def never(*args, **kwargs):
        await asyncio.Event().wait()
    solver._run_solver = never

    task = asyncio.ensure_future(solver.solve(tmp_path / "a.fits"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(done) == 1 and done[0].success is False and done[0].failure_reason == "Cancelled"


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
def test_tc_plt_070_offsets_are_on_sky_and_east_north_positive():
    """PLT-070: dRA is an on-sky distance (RA difference × cos Dec); east and north are positive."""
    plt_mod = pytest.importorskip("galileo.platesolve")
    d_ra, d_dec = plt_mod.angular_offset_arcsec(10.01, 60.0, 10.0, 60.0)
    assert d_ra == pytest.approx(0.01 * 0.5 * 3600, rel=1e-3)      # cos 60° = 0.5
    assert d_dec == pytest.approx(0.0, abs=1e-9)
    assert plt_mod.angular_offset_arcsec(10.0, 60.01, 10.0, 60.0)[1] == pytest.approx(36.0)
    d_ra, _ = plt_mod.angular_offset_arcsec(0.005, 0.0, 359.995, 0.0)   # across RA 0°: 0.01° east, not −359.99°
    assert d_ra == pytest.approx(36.0, rel=1e-3)


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
def test_tc_plt_070_mount_frame_conversion_round_trips():
    """PLT-070: A J2000 position is turned into the mount's own frame (JNow, or J2000 if it says so) and back again."""
    plt_mod = pytest.importorskip("galileo.platesolve")
    assert plt_mod.j2000_to_mount_frame(37.95, 89.26, "J2000") == (37.95, 89.26)
    ra, dec = plt_mod.j2000_to_mount_frame(37.95, 89.26, "JNOW")
    assert abs(dec - 89.26) > 0.1                                   # Polaris has precessed a fair way since J2000
    back = plt_mod.mount_frame_to_j2000(ra, dec, "JNOW")
    assert back[0] == pytest.approx(37.95, abs=1e-6) and back[1] == pytest.approx(89.26, abs=1e-6)


# ---------------------------------------------------------------------------
# PLT-070 — the capture-solve-correct workflow, against fake devices
# ---------------------------------------------------------------------------

class _Rig:
    """A camera, a mount and a scripted solver, with every call to the mount recorded in order."""

    def __init__(self, tmp_path, mount_ra_deg=100.0, mount_dec_deg=20.0, system="JNOW"):
        import numpy as np
        self.plt = pytest.importorskip("galileo.platesolve")
        self.calls: list = []
        self.log: list[str] = []
        self.system = system
        self.camera = MagicMock(name="cam")
        self.camera.start_exposure = AsyncMock()
        self.camera.get_image_array = AsyncMock(return_value=np.full((40, 60), 100, dtype=np.uint16))
        self.camera.abort_exposure = AsyncMock()
        self.mount = MagicMock(name="mount")
        self.mount.get_status = AsyncMock(return_value={
            "right_ascension": mount_ra_deg / 15.0, "declination": mount_dec_deg,
            "equatorial_system": system, "slewing": False})
        self.mount.sync_to_coordinates = AsyncMock(side_effect=lambda ra, dec: self.calls.append(("sync", ra, dec)))
        self.mount.slew_to_coordinates = AsyncMock(side_effect=lambda ra, dec: self.calls.append(("slew", ra, dec)))
        self.mount.abort_slew = AsyncMock()
        self.solver = self.plt.PlateSolver(backend="astap", executable="unused")   # each test scripts _run_solver
        self.workflow = self.plt.SolveWorkflow(
            self.solver, camera=self.camera, mount=self.mount, work_dir=tmp_path / "solve", log=self.log.append)

    def ok(self, ra_deg, dec_deg):
        """A successful solve at a J2000 position."""
        return self.plt.SolveResult(success=True, ra_deg=ra_deg, dec_deg=dec_deg, rotation_deg=0.0, scale_arcsec_px=3.0)

    def in_mount_frame(self, ra_deg, dec_deg):
        return self.plt.j2000_to_mount_frame(ra_deg, dec_deg, self.system)


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_capture_and_solve_can_leave_the_mount_alone(tmp_path):
    """PLT-070: With the action "Nothing", a frame is captured and solved and the mount is neither synced nor slewed."""
    plt = pytest.importorskip("galileo.platesolve")
    rig = _Rig(tmp_path)
    ra, dec = plt.mount_frame_to_j2000(100.0, 20.0, "JNOW")
    rig.solver._run_solver = AsyncMock(return_value=rig.ok(ra + 0.01, dec))
    results = await rig.workflow.capture_and_solve(plt.SolveSettings(exposure_s=2.0, action=plt.SolveAction.NOTHING))
    assert [r.success for r in results] == [True]
    rig.camera.start_exposure.assert_awaited_once()
    assert rig.camera.start_exposure.await_args.kwargs["duration"] == 2.0
    assert rig.calls == []
    assert any("Capturing image" in line for line in rig.log) and any("Solver completed" in line for line in rig.log)
    # the target is where the mount was pointing when the run began, and the solver was told to look there
    assert rig.workflow.target == pytest.approx((ra, dec))
    assert rig.solver._run_solver.await_args.args[1] == pytest.approx((ra, dec))


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_sync_tells_the_mount_where_it_really_points(tmp_path):
    """PLT-070: With the action "Sync", the mount is synced once to the solution, in the mount's own frame."""
    rig = _Rig(tmp_path)
    solution = (30.0, 40.0)
    rig.solver._run_solver = AsyncMock(return_value=rig.ok(*solution))
    await rig.workflow.capture_and_solve(rig.plt.SolveSettings(action=rig.plt.SolveAction.SYNC))
    assert [c[0] for c in rig.calls] == ["sync"]
    assert rig.calls[0][1:] == pytest.approx(rig.in_mount_frame(*solution))


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_slew_to_target_syncs_then_slews_until_on_target(tmp_path):
    """PLT-070: "Slew to Target" syncs to the solution, slews back to the target and solves again, stopping once within the accuracy."""
    plt = pytest.importorskip("galileo.platesolve")
    target = plt.mount_frame_to_j2000(100.0, 20.0, "JNOW")
    off = (target[0] + 0.05, target[1])                            # ~170″ east of the target
    rig = _Rig(tmp_path)
    on_target = (target[0] + 0.001, target[1])                     # ~3″
    rig.solver._run_solver = AsyncMock(side_effect=[rig.ok(*off), rig.ok(*on_target)])
    settings = plt.SolveSettings(action=plt.SolveAction.SLEW_TO_TARGET, accuracy_arcsec=30.0, settle_s=0.0)
    results = await rig.workflow.capture_and_solve(settings)
    assert len(results) == 2
    assert [c[0] for c in rig.calls] == ["sync", "slew"]           # in that order, and only once each
    assert rig.calls[0][1:] == pytest.approx(rig.in_mount_frame(*off))
    assert rig.calls[1][1:] == pytest.approx(rig.in_mount_frame(*target))
    assert rig.camera.start_exposure.await_count == 2
    assert any("On target" in line for line in rig.log)


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_slew_to_target_gives_up_after_the_iteration_limit(tmp_path):
    """PLT-070: A target that is never reached ends after max_iterations frames instead of slewing forever."""
    plt = pytest.importorskip("galileo.platesolve")
    rig = _Rig(tmp_path)
    target = plt.mount_frame_to_j2000(100.0, 20.0, "JNOW")
    rig.solver._run_solver = AsyncMock(return_value=rig.ok(target[0] + 0.5, target[1]))   # always 0.5° out
    settings = plt.SolveSettings(action=plt.SolveAction.SLEW_TO_TARGET, settle_s=0.0, max_iterations=3)
    results = await rig.workflow.capture_and_solve(settings)
    assert len(results) == 3
    assert [c[0] for c in rig.calls] == ["sync", "slew", "sync", "slew"]   # none after the last frame
    assert any("giving up" in line for line in rig.log)


@pytest.mark.requirement("TC-PLT-050")
@pytest.mark.priority("MVP")
async def test_tc_plt_050_a_failed_solve_does_not_move_the_mount(tmp_path):
    """PLT-050: If the frame can't be solved, the mount is not synced or slewed and the log says why."""
    plt = pytest.importorskip("galileo.platesolve")
    rig = _Rig(tmp_path)
    rig.solver._run_solver = AsyncMock(return_value=plt.SolveResult(success=False, failure_reason="Not enough stars."))
    results = await rig.workflow.capture_and_solve(plt.SolveSettings(action=plt.SolveAction.SLEW_TO_TARGET))
    assert [r.success for r in results] == [False]
    assert rig.calls == []
    assert any("Solver failed" in line and "Not enough stars." in line for line in rig.log)


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_mount_actions_need_a_mount(tmp_path):
    """PLT-070: With no mount connected the frame is still solved, and the log says the action was skipped."""
    plt = pytest.importorskip("galileo.platesolve")
    rig = _Rig(tmp_path)
    rig.solver._run_solver = AsyncMock(return_value=rig.ok(30.0, 40.0))
    rig.workflow.mount = None
    results = await rig.workflow.capture_and_solve(plt.SolveSettings(action=plt.SolveAction.SYNC))
    assert [r.success for r in results] == [True]
    assert any("No mount" in line for line in rig.log)
    assert rig.solver._run_solver.await_args.args[1] is None       # nothing to hint the search with


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_slew_to_target_needs_a_readable_mount_position(tmp_path):
    """PLT-070: If the mount's position can't be read there is no target to slew back to; the frame is solved, the mount is
    left alone, and the log says why (rather than failing partway with an unrelated error)."""
    plt = pytest.importorskip("galileo.platesolve")
    rig = _Rig(tmp_path)
    rig.mount.get_status = AsyncMock(return_value={"right_ascension": None, "declination": None})
    rig.solver._run_solver = AsyncMock(return_value=rig.ok(30.0, 40.0))
    results = await rig.workflow.capture_and_solve(plt.SolveSettings(action=plt.SolveAction.SLEW_TO_TARGET))
    assert [r.success for r in results] == [True]
    assert rig.calls == []
    assert any("no target" in line for line in rig.log)
    assert not any(line.startswith("Failed") for line in rig.log)
    assert rig.solver._run_solver.await_args.args[1] is None              # nothing to hint the search with either


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_no_camera_is_reported_not_raised(tmp_path):
    """PLT-070: Capture & Solve with no camera logs it and ends cleanly."""
    plt = pytest.importorskip("galileo.platesolve")
    rig = _Rig(tmp_path)
    rig.workflow.camera = None
    assert await rig.workflow.capture_and_solve(plt.SolveSettings()) == []
    assert any("No camera" in line for line in rig.log)


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_a_parked_mount_ends_the_run_with_its_own_message(tmp_path):
    """PLT-070: A mount that refuses to slew (parked) stops the run; the reason reaches the log rather than a traceback."""
    from galileo.exceptions import MountParkedError
    plt = pytest.importorskip("galileo.platesolve")
    rig = _Rig(tmp_path)
    target = plt.mount_frame_to_j2000(100.0, 20.0, "JNOW")
    rig.solver._run_solver = AsyncMock(return_value=rig.ok(target[0] + 0.5, target[1]))
    rig.mount.slew_to_coordinates = AsyncMock(side_effect=MountParkedError("The mount is parked, so slew_to_coordinates was not sent — unpark it first."))
    await rig.workflow.capture_and_solve(plt.SolveSettings(action=plt.SolveAction.SLEW_TO_TARGET, settle_s=0.0))
    assert any("parked" in line for line in rig.log)


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_stop_cancels_the_run_and_aborts_the_hardware(tmp_path):
    """PLT-070: stop() — callable from another thread — ends a run mid-exposure, aborting the exposure and any slew."""
    import asyncio
    import threading
    plt = pytest.importorskip("galileo.platesolve")
    rig = _Rig(tmp_path)
    started = asyncio.Event()

    async def long_exposure(**kwargs):
        started.set()
        await asyncio.Event().wait()
    rig.camera.start_exposure = long_exposure

    run = asyncio.ensure_future(rig.workflow.capture_and_solve(plt.SolveSettings(exposure_s=600.0)))
    await asyncio.wait_for(started.wait(), 2)
    threading.Thread(target=rig.workflow.stop).start()
    results = await asyncio.wait_for(run, 5)
    assert results == [] and rig.workflow.stopped is True
    rig.camera.abort_exposure.assert_awaited_once()
    rig.mount.abort_slew.assert_awaited_once()
    assert "Stopped." in rig.log


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_load_and_slew_solves_a_copy_and_slews_to_the_solution(tmp_path, sample_fits_file):
    """PLT-070: Load & Slew solves a copy of the file (ASTAP rewrites what it is given) and slews the mount to the solution."""
    rig = _Rig(tmp_path)
    solved_paths: list = []

    async def run_solver(path, hint=None):
        solved_paths.append(path)
        return rig.ok(30.0, 40.0)
    rig.solver._run_solver = run_solver
    results = await rig.workflow.solve_file(sample_fits_file, slew=True)
    assert [r.success for r in results] == [True]
    assert solved_paths[0] != sample_fits_file and solved_paths[0].exists()
    assert [c[0] for c in rig.calls] == ["slew"]
    assert rig.calls[0][1:] == pytest.approx(rig.in_mount_frame(30.0, 40.0))


@pytest.mark.requirement("TC-PLT-070")
@pytest.mark.priority("MVP")
async def test_tc_plt_070_only_the_newest_frames_are_kept(tmp_path):
    """PLT-070: The frames kept for the screen to show are pruned so a night of solving doesn't fill the disk."""
    plt = pytest.importorskip("galileo.platesolve")
    rig = _Rig(tmp_path)
    rig.solver._run_solver = AsyncMock(return_value=rig.ok(30.0, 40.0))
    rig.workflow._KEEP_FILES = 3
    for _ in range(6):
        await rig.workflow.capture_and_solve(plt.SolveSettings())
        import time
        time.sleep(0.02)                                           # distinct modification times
    assert len(list((tmp_path / "solve").glob("solve_*.fits"))) == 3


@pytest.mark.integration
@pytest.mark.requirement("TC-PLT-010")
@pytest.mark.priority("MVP")
async def test_tc_plt_010_real_astap_solves_a_synthetic_star_field(tmp_path):
    """PLT-010: The real ASTAP, run through PlateSolver, solves a rendered star field to the right place, and reports a failed
    solve of noise with a reason. Needs ASTAP with a star database and the cached Bright Star Catalogue."""
    import numpy as np
    plt_mod = pytest.importorskip("galileo.platesolve")
    fits = pytest.importorskip("astropy.io.fits")
    solver = plt_mod.PlateSolver(backend="astap", params=plt_mod.SolverParams(fov_hint_deg=4.0, downsample=1))
    if not solver.executable:
        pytest.skip("ASTAP is not installed")
    # The Star Atlas cache the app keeps (the test session points the loader at an offline list, so read the file itself).
    import json
    from galileo.platform import get_cache_dir
    from galileo.planning import star_atlas
    cache = get_cache_dir() / star_atlas._CATALOG_FILENAME
    if not cache.exists():
        pytest.skip("the Bright Star Catalogue is not cached (open the Star Atlas once with a network connection)")
    raw = json.loads(cache.read_text("utf-8"))
    cat_ra, cat_dec, cat_mag = np.array(raw["ra"]), np.array(raw["dec"]), np.array(raw["mag"])

    # Render the catalogue's stars around a known place (a 5.3° × 4° field, 12″/px).
    width, height, scale, ra0, dec0 = 1600, 1200, 12.0, 114.0, -38.0
    d_ra, dec, d0 = np.radians(cat_ra - ra0), np.radians(cat_dec), np.radians(dec0)
    q = np.sin(d0) * np.sin(dec) + np.cos(d0) * np.cos(dec) * np.cos(d_ra)
    xi = np.cos(dec) * np.sin(d_ra) / q
    eta = (np.cos(d0) * np.sin(dec) - np.sin(d0) * np.cos(dec) * np.cos(d_ra)) / q
    px = width / 2 - np.degrees(xi) * 3600 / scale
    py = height / 2 + np.degrees(eta) * 3600 / scale
    inside = (q > 0) & (px > 8) & (px < width - 8) & (py > 8) & (py < height - 8)
    image = np.random.default_rng(7).normal(500, 15, (height, width))
    yy, xx = np.mgrid[0:height, 0:width]
    for x, y, mag in zip(px[inside], py[inside], cat_mag[inside]):
        window = (slice(max(int(y) - 7, 0), int(y) + 8), slice(max(int(x) - 7, 0), int(x) + 8))
        image[window] += 40000 * 10 ** (-0.4 * (mag - 1.0)) * np.exp(-((xx[window] - x) ** 2 + (yy[window] - y) ** 2) / (2 * 1.8 ** 2))
    if inside.sum() < 20:
        pytest.skip("too few catalogue stars in the test field to solve reliably")
    field = tmp_path / "field.fits"
    fits.PrimaryHDU(np.clip(image, 0, 65535).astype(np.float32)).writeto(field)

    result = await solver.solve(field, hint=(ra0, dec0))
    assert result.success, result.failure_reason
    assert result.ra_deg == pytest.approx(ra0, abs=0.02) and result.dec_deg == pytest.approx(dec0, abs=0.02)
    assert result.scale_arcsec_px == pytest.approx(scale, rel=0.01)

    noise = tmp_path / "noise.fits"
    fits.PrimaryHDU(np.random.default_rng(1).normal(1000, 30, (600, 800)).astype(np.float32)).writeto(noise)
    result = await solver.solve(noise, hint=(ra0, dec0))
    assert result.success is False and result.failure_reason
