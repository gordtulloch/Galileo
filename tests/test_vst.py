"""VST — Variable Star Target Planning (TC-VST-010 … TC-VST-090)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def vst_planner():
    vst_mod = pytest.importorskip("galileo.vstarget.planning")
    return vst_mod.VariableStarPlanner()


# ---------------------------------------------------------------------------
# TC-VST-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-010")
@pytest.mark.priority("MVP")
async def test_tc_vst_010_sync_from_aavso_target_tool(vst_planner):
    """VST-010: Sync variable-star targets from AAVSO Target Tool API; filterable by observing section."""
    vst_mod = pytest.importorskip("galileo.vstarget.planning")
    vst_planner._aavso_client = vst_mod.AavsoTargetToolClient.__new__(vst_mod.AavsoTargetToolClient)
    vst_planner._aavso_client.fetch_targets = AsyncMock(return_value=[
        {"name": "Z UMa", "section": "LPV", "ra": 152.6, "dec": 57.9},
        {"name": "SS Cyg", "section": "Cataclysmic", "ra": 325.7, "dec": 43.6},
    ])

    await vst_planner.sync_from_aavso(section="LPV")
    targets = vst_planner.get_targets(section="LPV")
    assert any(t.name == "Z UMa" for t in targets)
    assert not any(t.name == "SS Cyg" for t in targets)


# ---------------------------------------------------------------------------
# TC-VST-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-020")
@pytest.mark.priority("MVP")
def test_tc_vst_020_sortable_searchable_target_list(vst_planner):
    """VST-020: Sortable, searchable variable-star target list with priority indication and solar-conjunction warnings."""
    vst_planner._targets = [
        MagicMock(name="R Leo", priority=2, solar_conjunction=False),
        MagicMock(name="Chi Cyg", priority=1, solar_conjunction=True),
        MagicMock(name="Mira", priority=1, solar_conjunction=False),
    ]

    sorted_targets = vst_planner.sorted_targets(key="priority")
    assert sorted_targets[0].priority <= sorted_targets[-1].priority

    conjunctions = [t for t in vst_planner._targets if t.solar_conjunction]
    assert any(t.name == "Chi Cyg" for t in conjunctions)


# ---------------------------------------------------------------------------
# TC-VST-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-030")
@pytest.mark.priority("MVP")
def test_tc_vst_030_filter_to_observable_tonight(vst_planner):
    """VST-030: Filter variable-star target list to targets observable from configured location tonight."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    loc = sky_mod.ObservingLocation(name="Home", latitude=51.5, longitude=-1.0, elevation_m=100, timezone="UTC")
    vst_planner.set_location(loc)

    vst_planner._targets = [
        MagicMock(name="R Leo", ra_deg=154.0, dec_deg=11.4),
        MagicMock(name="Mira", ra_deg=34.8, dec_deg=-2.9),
    ]

    observable = vst_planner.get_observable_tonight(date="2026-09-16")
    assert isinstance(observable, list)
    for t in observable:
        assert hasattr(t, "name")


# ---------------------------------------------------------------------------
# TC-VST-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-040")
@pytest.mark.priority("P2")
def test_tc_vst_040_import_target_list_from_file(vst_planner, tmp_path):
    """VST-040: Support manual import of a variable-star target list from a delimited text file."""
    csv_file = tmp_path / "targets.csv"
    csv_file.write_text("name,ra,dec\nR Leo,154.0,11.4\nMira,34.8,-2.9\n")

    vst_planner.import_from_file(csv_file)
    targets = vst_planner.get_targets()
    assert any(t.name == "R Leo" for t in targets)
    assert any(t.name == "Mira" for t in targets)


# ---------------------------------------------------------------------------
# TC-VST-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-050")
@pytest.mark.priority("MVP")
def test_tc_vst_050_observation_plan_editor(vst_planner):
    """VST-050: Observation-plan editor with per-target filter, exposure count, interval, and binning."""
    vst_mod = pytest.importorskip("galileo.vstarget.planning")
    plan = vst_mod.ObservationPlan(target_name="R Leo")
    plan.add_filter_config(filter_name="V", exposure_s=60.0, count=3, interval_s=120.0, binning=1)
    plan.add_filter_config(filter_name="B", exposure_s=90.0, count=3, interval_s=120.0, binning=1)

    assert len(plan.filter_configs) == 2
    assert plan.filter_configs[0].filter_name == "V"
    assert plan.filter_configs[1].exposure_s == 90.0


# ---------------------------------------------------------------------------
# TC-VST-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-060")
@pytest.mark.priority("MVP")
def test_tc_vst_060_generate_acp_observing_script(vst_planner, tmp_path):
    """VST-060: Generate an ACP-compatible observing script with targets ordered by right ascension."""
    vst_mod = pytest.importorskip("galileo.vstarget.planning")
    plans = [
        vst_mod.ObservationPlan(target_name="Mira", ra_deg=34.8),
        vst_mod.ObservationPlan(target_name="R Leo", ra_deg=154.0),
    ]

    script_path = tmp_path / "obs_plan.acp"
    vst_planner.export_acp_script(plans, output_path=script_path)
    assert script_path.exists()

    content = script_path.read_text()
    # ACP scripts start with #TARGET
    assert "#TARGET" in content or "Mira" in content
    mira_pos = content.find("Mira")
    rleo_pos = content.find("R Leo")
    assert mira_pos < rleo_pos, "Targets must be ordered by RA (Mira RA < R Leo RA)"


# ---------------------------------------------------------------------------
# TC-VST-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-070")
@pytest.mark.priority("MVP")
def test_tc_vst_070_persist_plans_across_restarts(vst_planner, tmp_path):
    """VST-070: Persist observation plans across application restarts."""
    vst_mod = pytest.importorskip("galileo.vstarget.planning")
    plan = vst_mod.ObservationPlan(target_name="R Leo", ra_deg=154.0)
    vst_planner.set_persistence(tmp_path / "plans.db")
    vst_planner.save_plan(plan)

    vst_mod2 = pytest.importorskip("galileo.vstarget.planning")
    planner2 = vst_mod2.VariableStarPlanner()
    planner2.set_persistence(tmp_path / "plans.db")
    loaded = planner2.load_plans()
    assert any(p.target_name == "R Leo" for p in loaded)


# ---------------------------------------------------------------------------
# TC-VST-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-080")
@pytest.mark.priority("MVP")
async def test_tc_vst_080_simbad_coordinate_fallback(vst_planner):
    """VST-080: Look up target coordinates via Simbad when not already in synced AAVSO catalog data."""
    vst_mod = pytest.importorskip("galileo.vstarget.planning")
    vst_planner._simbad = vst_mod.SimbadClient.__new__(vst_mod.SimbadClient)
    vst_planner._simbad.lookup = AsyncMock(return_value={"ra_deg": 154.0, "dec_deg": 11.4, "magnitude_v": 8.5})

    coords = await vst_planner.resolve_target("R Leo")
    assert abs(coords["ra_deg"] - 154.0) < 0.1
    vst_planner._simbad.lookup.assert_called_with("R Leo")


# ---------------------------------------------------------------------------
# TC-VST-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-VST-090")
@pytest.mark.priority("MVP")
async def test_tc_vst_090_submit_target_to_scheduler_from_vst_ui(vst_planner):
    """VST-090: Submit a variable-star target with observation plan directly to SCHED job queue from VST UI."""
    sched_mod = pytest.importorskip("galileo.scheduler")
    vst_mod = pytest.importorskip("galileo.vstarget.planning")

    mock_scheduler = MagicMock()
    mock_scheduler.add_job = MagicMock()
    vst_planner._scheduler = mock_scheduler

    plan = vst_mod.ObservationPlan(target_name="R Leo", ra_deg=154.0, dec_deg=11.4)
    await vst_planner.submit_to_scheduler(plan)
    mock_scheduler.add_job.assert_called_once()
    submitted_job = mock_scheduler.add_job.call_args[0][0]
    assert "R Leo" in str(submitted_job)
