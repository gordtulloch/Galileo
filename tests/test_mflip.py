# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""MFLIP — Meridian Flip (TC-MFLIP-010 … TC-MFLIP-040)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mflip_service(mock_indi_mount, mock_guider):
    mflip_mod = pytest.importorskip("galileo.meridianflip")
    return mflip_mod.MeridianFlipService(mount=mock_indi_mount, guider=mock_guider)


# ---------------------------------------------------------------------------
# TC-MFLIP-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-MFLIP-010")
@pytest.mark.priority("P2")
def test_tc_mflip_010_compute_time_to_flip(mflip_service, mock_indi_mount):
    """MFLIP-010: Compute time remaining until GEM mount reaches its configured meridian-flip limit."""
    mock_indi_mount.ra = 12.0
    mock_indi_mount.pier_side = "East"
    mock_indi_mount.hour_angle = 5.5  # near meridian limit of 6h

    mflip_mod = pytest.importorskip("galileo.meridianflip")
    mflip_service.set_flip_limit_ha(6.0)
    time_remaining_min = mflip_service.time_to_flip_minutes()

    assert isinstance(time_remaining_min, float)
    assert time_remaining_min >= 0


# ---------------------------------------------------------------------------
# TC-MFLIP-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-MFLIP-020")
@pytest.mark.priority("P2")
async def test_tc_mflip_020_auto_pause_flip_resume(mflip_service, mock_indi_mount):
    """MFLIP-020: Automatically pause sequence, execute meridian flip, and resume without user interaction."""
    seq_paused = []
    seq_resumed = []
    mock_sequence = MagicMock()
    mock_sequence.pause = AsyncMock(side_effect=lambda: seq_paused.append(True))
    mock_sequence.resume = AsyncMock(side_effect=lambda: seq_resumed.append(True))

    mock_indi_mount.slew_to_coordinates = AsyncMock()
    mock_indi_mount.pier_side = "West"

    await mflip_service.execute_flip(sequence=mock_sequence, target_ra=12.5, target_dec=45.0)

    assert len(seq_paused) == 1
    mock_indi_mount.slew_to_coordinates.assert_called()
    assert len(seq_resumed) == 1


# ---------------------------------------------------------------------------
# TC-MFLIP-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-MFLIP-030")
@pytest.mark.priority("P2")
async def test_tc_mflip_030_recenter_and_restart_guiding_after_flip(mflip_service, mock_indi_mount, mock_guider):
    """MFLIP-030: Re-center via solve-and-center and restart guiding after meridian flip before resuming."""
    recentered = []
    guider_started = []

    plt_mod = pytest.importorskip("galileo.platesolve")
    mock_solver = MagicMock()
    mock_solver.solve_and_center = AsyncMock(side_effect=lambda **kw: recentered.append(True))
    mock_guider.start_guiding = AsyncMock(side_effect=lambda: guider_started.append(True))

    mflip_service._solver = mock_solver
    await mflip_service.post_flip_recovery(target_ra=12.5, target_dec=45.0)

    assert len(recentered) == 1
    assert len(guider_started) == 1


# ---------------------------------------------------------------------------
# TC-MFLIP-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-MFLIP-040")
@pytest.mark.priority("P2")
def test_tc_mflip_040_configure_flip_limit_per_profile():
    """MFLIP-040: Allow meridian-flip limit and pre/post-flip behavior to be configured per equipment profile."""
    mflip_mod = pytest.importorskip("galileo.meridianflip")
    config = mflip_mod.MeridianFlipConfig(
        flip_ha_limit=6.0,
        pre_flip_settle_s=30,
        post_flip_recenter=True,
        post_flip_restart_guiding=True,
    )
    assert config.flip_ha_limit == 6.0
    assert config.post_flip_recenter is True
