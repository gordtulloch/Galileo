# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""OBS — Multi-Mount Observatory Management (TC-OBS-010 … TC-OBS-090)."""

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


# ---------------------------------------------------------------------------
# TC-OBS-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-OBS-090")
@pytest.mark.priority("P2")
def test_tc_obs_090_observatory_carries_operator_contact_details():
    """OBS-090: Allow an Observatory record to carry the operator's own contact details — email address, phone/SMS number, and which channel(s) NOTIF should use — since being notified is scoped to the person running the Observatory, not to an individual Pier within it (traces to NOTIF-020, NOTIF-040)."""
    obs_mod = pytest.importorskip("galileo.observatory")
    obs = obs_mod.Observatory(name="Backyard")

    assert obs.contact_details is None  # unset by default

    obs.set_contact_details(
        email="operator@example.com", phone_number="+15551234567", channels=["email", "sms"],
    )

    assert obs.contact_details.email == "operator@example.com"
    assert obs.contact_details.phone_number == "+15551234567"
    assert obs.contact_details.channels == ["email", "sms"]

    # One contact record per Observatory, not per Pier.
    pier1 = obs_mod.Pier(name="Pier-1")
    pier2 = obs_mod.Pier(name="Pier-2")
    obs.add_pier(pier1)
    obs.add_pier(pier2)
    assert not hasattr(pier1, "contact_details")
    assert not hasattr(pier2, "contact_details")


# ---------------------------------------------------------------------------
# Observatory/Pier deletion (persisted settings records, not RTM-numbered —
# a direct counterpart to the already-shipped create_observatory/create_pier)
# ---------------------------------------------------------------------------

def test_delete_pier_removes_the_record_and_its_device_config(tmp_path):
    """Deleting a Pier removes its settings record, and its device config cascades with it (ON DELETE CASCADE) without touching a sibling Pier's."""
    from galileo.library.database import db, init_db
    from galileo.observatory import (
        create_observatory, create_pier, delete_pier, get_device_config, list_piers, save_device_config,
    )
    init_db(tmp_path / "delete_pier.db")
    try:
        obs = create_observatory("Backyard")
        keep, gone = create_pier(obs, "Keep"), create_pier(obs, "Gone")
        save_device_config(keep, "Camera", driver="indi", server="localhost", port=7624)
        save_device_config(gone, "Camera", driver="indi", server="localhost", port=7624)

        delete_pier(gone)

        assert [p.name for p in list_piers(obs)] == ["Keep"]
        assert get_device_config(keep, "Camera") is not None
        assert get_device_config(gone, "Camera") is None
    finally:
        db.close()


def test_delete_observatory_cascades_to_its_piers_and_horizon_points(tmp_path):
    """Deleting an Observatory removes its record, every Pier under it (and that Pier's device config), and its horizon points — but leaves an unrelated Observatory untouched."""
    from galileo.library.database import db, init_db
    from galileo.observatory import (
        create_observatory, create_pier, delete_observatory, get_device_config,
        list_horizon_points, list_observatories, list_piers, save_device_config, save_horizon_points,
    )
    init_db(tmp_path / "delete_observatory.db")
    try:
        gone = create_observatory("Gone")
        pier = create_pier(gone, "Pier-1")
        save_device_config(pier, "Camera", driver="indi", server="localhost", port=7624)
        save_horizon_points(gone, [(0.0, 5.0)])
        keep = create_observatory("Keep")
        keep_pier = create_pier(keep, "Keep Pier")

        delete_observatory(gone)

        assert [o.name for o in list_observatories()] == ["Keep"]
        assert list_piers(keep) == [keep_pier]
        assert list_piers(gone) == []            # its Pier row cascaded away with it
        assert get_device_config(pier, "Camera") is None
        assert list_horizon_points(gone) == []    # its horizon points cascaded away too
    finally:
        db.close()


def _built_window(tmp_path, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import init_db
    init_db(tmp_path / "delete_ui.db")
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Yes))
    from galileo.ui.app_window import AppWindow
    win = AppWindow()
    win.app = app
    return win


def test_the_delete_buttons_are_only_enabled_with_a_selection(tmp_path, monkeypatch):
    """The top bar's Observatory/Pier delete buttons start disabled (nothing saved yet) and enable once a real Observatory/Pier is selected."""
    from galileo.library.database import db
    win = _built_window(tmp_path, monkeypatch)
    try:
        assert win._observatory_delete_btn.isEnabled() is False
        assert win._pier_delete_btn.isEnabled() is False

        from galileo.observatory import create_observatory, create_pier
        pier = create_pier(create_observatory("Backyard"), "Pier A")
        win._current_pier = pier
        win._current_observatory = pier.observatory
        win._on_pier_changed()

        assert win._observatory_delete_btn.isEnabled() is True
        assert win._pier_delete_btn.isEnabled() is True
    finally:
        win._window.close()
        db.close()


def test_clicking_delete_pier_removes_it_and_falls_back_to_no_pier_selected(tmp_path, monkeypatch):
    """Clicking the Pier delete button (after confirming) deletes the current Pier's record and leaves no Pier selected since it was the only one."""
    from galileo.library.database import db
    win = _built_window(tmp_path, monkeypatch)
    try:
        from galileo.observatory import create_observatory, create_pier, list_piers
        observatory = create_observatory("Backyard")
        pier = create_pier(observatory, "Pier A")
        win._current_observatory = observatory
        win._current_pier = pier
        win._on_pier_changed()

        win._on_delete_pier_clicked()

        assert win._current_pier is None
        assert list_piers(observatory) == []
        assert win._pier_delete_btn.isEnabled() is False
    finally:
        win._window.close()
        db.close()


def test_clicking_delete_observatory_removes_it_and_falls_back_to_no_observatory_selected(tmp_path, monkeypatch):
    """Clicking the Observatory delete button (after confirming) deletes the current Observatory's record, along with its Pier, and leaves no Observatory selected since it was the only one."""
    from galileo.library.database import db
    win = _built_window(tmp_path, monkeypatch)
    try:
        from galileo.observatory import create_observatory, create_pier, list_observatories
        observatory = create_observatory("Backyard")
        create_pier(observatory, "Pier A")
        win._current_observatory = observatory
        win._on_pier_changed()

        win._on_delete_observatory_clicked()

        assert win._current_observatory is None
        assert list_observatories() == []
        assert win._observatory_delete_btn.isEnabled() is False
        assert win._pier_delete_btn.isEnabled() is False
    finally:
        win._window.close()
        db.close()


def test_update_observatory_persists_every_field_and_rename_pier_persists_name(tmp_path):
    """Editing an Observatory saves all of its fields; renaming a Pier saves its name; both survive a reload."""
    from galileo.library.database import db, init_db
    from galileo.observatory import (
        OBSERVATORY_FIELDS, create_observatory, create_pier, list_observatories, list_piers,
        rename_pier, update_observatory,
    )
    init_db(tmp_path / "edit.db")
    try:
        obs = create_observatory("Backyard")
        pier = create_pier(obs, "Pier A")
        edited = dict(
            name="Dark Site", latitude=44.5, longitude=-79.25, elevation_m=250.0, timezone="America/Toronto",
            physical_address="1 Rural Rd", owner="Gord", notification_type="Both",
            email_address="a@example.com", cell_number="+1-555-555-5555",
        )
        assert set(edited) == set(OBSERVATORY_FIELDS)
        update_observatory(obs, **edited)
        rename_pier(pier, "Pier B")

        reloaded = list_observatories()[0]
        for key, value in edited.items():
            assert getattr(reloaded, key) == value
        assert [p.name for p in list_piers(reloaded)] == ["Pier B"]
        with pytest.raises(ValueError):
            update_observatory(obs, bogus=1)
    finally:
        db.close()


def test_edit_buttons_follow_the_selection_and_edits_update_the_selectors(tmp_path, monkeypatch):
    """The pencil buttons enable with a selection, and editing an Observatory/renaming a Pier updates the DB and the combo boxes."""
    from galileo.library.database import db
    win = _built_window(tmp_path, monkeypatch)
    try:
        assert win._observatory_edit_btn.isEnabled() is False
        assert win._pier_edit_btn.isEnabled() is False

        from galileo.observatory import create_observatory, create_pier, list_observatories, list_piers
        observatory = create_observatory("Backyard", latitude=10.0)
        create_pier(observatory, "Pier A")
        win._load_observatories()
        assert win._observatory_edit_btn.isEnabled() is True
        assert win._pier_edit_btn.isEnabled() is True

        monkeypatch.setattr(win, "_prompt_new_observatory", lambda record=None: {
            "name": "Dark Site", "latitude": 44.5, "longitude": -79.0, "elevation_m": 5.0, "timezone": None,
            "physical_address": None, "owner": "Gord", "notification_type": None,
            "email_address": None, "cell_number": None,
        })
        win._on_edit_observatory_clicked()
        assert win._observatory_combo.findText("Dark Site") >= 0
        assert win._observatory_combo.findText("Backyard") < 0
        saved = list_observatories()[0]
        assert (saved.name, saved.latitude, saved.owner) == ("Dark Site", 44.5, "Gord")

        monkeypatch.setattr(win, "_prompt_new_name", lambda *a, **k: "Pier B")
        win._on_edit_pier_clicked()
        assert win._pier_combo.findText("Pier B") >= 0
        assert [p.name for p in list_piers(saved)] == ["Pier B"]
    finally:
        win._window.close()
        db.close()
