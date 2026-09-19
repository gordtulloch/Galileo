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
