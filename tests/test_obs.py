# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""OBS — Multi-Mount Observatory Management (TC-OBS-010 … TC-OBS-080)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def two_pier_observatory():
    obs_mod = pytest.importorskip("galileo.observatory")
    pier1 = obs_mod.Pier(name="Pier-1")
    pier2 = obs_mod.Pier(name="Pier-2")
    obs = obs_mod.Observatory(name="Backyard")
    obs.add_pier(pier1)
    obs.add_pier(pier2)
    return obs, pier1, pier2


# ---------------------------------------------------------------------------
# TC-OBS-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-OBS-010")
@pytest.mark.priority("P2")
def test_tc_obs_010_group_piers_into_observatory():
    """OBS-010: Allow multiple Piers to be grouped into a named Observatory."""
    obs_mod = pytest.importorskip("galileo.observatory")
    obs = obs_mod.Observatory(name="Backyard")
    p1 = obs_mod.Pier(name="Pier-1")
    p2 = obs_mod.Pier(name="Pier-2")
    obs.add_pier(p1)
    obs.add_pier(p2)

    assert obs.name == "Backyard"
    assert len(obs.piers) == 2
    assert obs.piers[0].name == "Pier-1"


# ---------------------------------------------------------------------------
# TC-OBS-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-OBS-020")
@pytest.mark.priority("P2")
async def test_tc_obs_020_concurrent_sequences_across_piers(two_pier_observatory):
    """OBS-020: Independent sequences run concurrently across different Piers, each targeting a different object."""
    obs, pier1, pier2 = two_pier_observatory

    pier1_done = []
    pier2_done = []

    async def run_seq_1():
        pier1_done.append("M42")

    async def run_seq_2():
        pier2_done.append("M31")

    pier1.sequence_runner = MagicMock(run=AsyncMock(side_effect=run_seq_1))
    pier2.sequence_runner = MagicMock(run=AsyncMock(side_effect=run_seq_2))

    await obs.run_all_sequences()

    assert pier1_done == ["M42"]
    assert pier2_done == ["M31"]


# ---------------------------------------------------------------------------
# TC-OBS-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-OBS-030")
@pytest.mark.priority("P2")
def test_tc_obs_030_safety_monitor_scope_observatory_or_pier():
    """OBS-030: Safety-monitor/weather source scoped at Observatory (shared) or Pier (independent)."""
    obs_mod = pytest.importorskip("galileo.observatory")
    obs = obs_mod.Observatory(name="TestObs")
    pier1 = obs_mod.Pier(name="Pier-1")
    pier2 = obs_mod.Pier(name="Pier-2")
    obs.add_pier(pier1)
    obs.add_pier(pier2)

    shared_sm = MagicMock(name="SharedSafetyMonitor")
    obs.set_safety_monitor(shared_sm, scope="observatory")
    assert obs.safety_monitor is shared_sm
    assert pier1.safety_monitor is None  # pier-level not set

    pier_sm = MagicMock(name="Pier1SafetyMonitor")
    pier1.set_safety_monitor(pier_sm)
    assert pier1.safety_monitor is pier_sm


# ---------------------------------------------------------------------------
# TC-OBS-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-OBS-040")
@pytest.mark.priority("P2")
async def test_tc_obs_040_observatory_safety_abort_all_piers(two_pier_observatory, event_bus):
    """OBS-040: Observatory-scoped unsafe condition pauses/aborts and parks equipment across ALL member Piers."""
    obs, pier1, pier2 = two_pier_observatory
    obs._event_bus = event_bus

    pier1.abort_and_park = AsyncMock()
    pier2.abort_and_park = AsyncMock()

    await obs.handle_safety_unsafe(source="observatory", explanation="Rain detected")

    pier1.abort_and_park.assert_called_once()
    pier2.abort_and_park.assert_called_once()


# ---------------------------------------------------------------------------
# TC-OBS-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-OBS-050")
@pytest.mark.priority("P2")
def test_tc_obs_050_dome_scope_observatory_or_pier():
    """OBS-050: A dome/roof scoped at Observatory level (shared) or Pier level (independent)."""
    obs_mod = pytest.importorskip("galileo.observatory")
    obs = obs_mod.Observatory(name="TestObs")
    pier1 = obs_mod.Pier(name="Pier-1")
    pier2 = obs_mod.Pier(name="Pier-2")
    obs.add_pier(pier1)
    obs.add_pier(pier2)

    shared_dome = MagicMock(name="SharedRoof")
    obs.set_dome(shared_dome, scope="observatory")
    assert obs.dome is shared_dome

    pier_dome = MagicMock(name="Pier1Dome")
    pier1.set_dome(pier_dome)
    assert pier1.dome is pier_dome


# ---------------------------------------------------------------------------
# TC-OBS-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-OBS-060")
@pytest.mark.priority("P2")
def test_tc_obs_060_multi_pier_status_dashboard(two_pier_observatory):
    """OBS-060: Present a multi-Pier status dashboard with equipment/sequence/scheduler state per Pier."""
    obs, pier1, pier2 = two_pier_observatory
    obs_mod = pytest.importorskip("galileo.observatory")

    dashboard = obs.get_dashboard()
    assert isinstance(dashboard, list)
    assert len(dashboard) == 2
    for entry in dashboard:
        assert "pier_name" in entry
        assert "equipment_state" in entry
        assert "sequence_state" in entry


# ---------------------------------------------------------------------------
# TC-OBS-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-OBS-070")
@pytest.mark.priority("P2")
def test_tc_obs_070_scheduler_assigns_jobs_to_any_pier(two_pier_observatory):
    """OBS-070: Scheduler supports assigning jobs to any Pier and coordinates shared-resource constraints."""
    obs_mod = pytest.importorskip("galileo.observatory")
    scheduler_mod = pytest.importorskip("galileo.scheduler")
    obs, pier1, pier2 = two_pier_observatory

    scheduler = scheduler_mod.ObservatoryScheduler(observatory=obs)
    job1 = scheduler_mod.SchedulerJob(name="M42", pier_name="Pier-1", target_ra=83.8, target_dec=-5.4)
    job2 = scheduler_mod.SchedulerJob(name="M31", pier_name="Pier-2", target_ra=10.7, target_dec=41.3)

    scheduler.add_job(job1)
    scheduler.add_job(job2)

    assigned = {j.pier_name for j in scheduler.jobs}
    assert "Pier-1" in assigned
    assert "Pier-2" in assigned


# ---------------------------------------------------------------------------
# TC-OBS-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-OBS-080")
@pytest.mark.priority("P2")
async def test_tc_obs_080_concurrent_device_sets_in_single_instance(two_pier_observatory):
    """OBS-080: Connect to and concurrently operate device sets of multiple Piers in a single app instance."""
    obs, pier1, pier2 = two_pier_observatory

    cam1 = MagicMock(name="Cam1", device_type="Camera")
    cam1.connect = AsyncMock()
    cam2 = MagicMock(name="Cam2", device_type="Camera")
    cam2.connect = AsyncMock()

    pier1.device_pool = MagicMock()
    pier1.device_pool.connect_all = AsyncMock()
    pier2.device_pool = MagicMock()
    pier2.device_pool.connect_all = AsyncMock()

    await obs.connect_all_piers()

    pier1.device_pool.connect_all.assert_called_once()
    pier2.device_pool.connect_all.assert_called_once()
