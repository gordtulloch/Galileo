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
def test_tc_obs_030_safety_monitor_is_shared_by_every_pier():
    """OBS-030: A safety device is scoped at the Observatory and shared by all member Piers - a Pier has none of its own."""
    obs_mod = pytest.importorskip("galileo.observatory")
    obs = obs_mod.Observatory(name="TestObs")
    pier1 = obs_mod.Pier(name="Pier-1")
    pier2 = obs_mod.Pier(name="Pier-2")
    obs.add_pier(pier1)
    obs.add_pier(pier2)

    shared_sm = MagicMock(name="SharedSafetyMonitor")
    obs.set_safety_monitor(shared_sm)
    assert obs.safety_monitor is shared_sm
    assert not hasattr(pier1, "safety_monitor") and not hasattr(pier2, "set_safety_monitor")


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
    obs, _pier1, _pier2 = two_pier_observatory
    pytest.importorskip("galileo.observatory")

    dashboard = obs.get_dashboard()
    assert isinstance(dashboard, list)
    assert len(dashboard) == 2
    for entry in dashboard:
        assert "pier_name" in entry
        assert "equipment_state" in entry
        assert "sequence_state" in entry
        assert entry["scheduler_state"] == "idle"


# ---------------------------------------------------------------------------
# TC-OBS-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-OBS-070")
@pytest.mark.priority("P2")
def test_tc_obs_070_scheduler_assigns_jobs_to_any_pier(two_pier_observatory):
    """OBS-070: Scheduler supports assigning jobs to any Pier and coordinates shared-resource constraints."""
    pytest.importorskip("galileo.observatory")
    scheduler_mod = pytest.importorskip("galileo.scheduler")
    obs, _pier1, _pier2 = two_pier_observatory

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
        edited = {
            "name": "Dark Site", "latitude": 44.5, "longitude": -79.25, "elevation_m": 250.0, "timezone": "America/Toronto",
            "physical_address": "1 Rural Rd", "owner": "Gord", "notification_type": "Both",
            "email_address": "a@example.com", "cell_number": "+1-555-555-5555",
        }
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


# ---------------------------------------------------------------------------
# TC-OBS-100 ... TC-OBS-130  (cross-Pier shared-resource arbitration)
# ---------------------------------------------------------------------------

class _DomeCloseBlock:
    label = "Dome Close"
    indent = 0


@pytest.mark.requirement("TC-OBS-100")
@pytest.mark.priority("P2")
def test_tc_obs_100_dome_close_denied_while_other_pier_images():
    """OBS-100: A disruptive dome action is denied while another Pier is active; non-disruptive and Pier-scoped are not."""
    m = pytest.importorskip("galileo.observatory")
    obs = m.Observatory(name="Roof")
    arb = obs.arbiter
    arb.begin_activity("Pier-1", "dome", "imaging")
    denied = arb.check("Pier-2", "dome", "close")
    assert not denied.granted and denied.blocked_by == ("Pier-1",)
    assert not arb.check("Pier-2", "dome", "slew").granted
    assert arb.check("Pier-2", "dome", "open").granted
    assert arb.check("Pier-1", "dome", "close").granted  # own work never blocks itself
    obs.set_dome(object(), scope="pier")
    assert arb.check("Pier-2", "dome", "close").granted


@pytest.mark.requirement("TC-OBS-110")
@pytest.mark.priority("P2")
async def test_tc_obs_110_request_queues_until_released_or_times_out():
    """OBS-110: A queued request is granted on release, denied on timeout; a denied session block is skipped, not fatal."""
    import asyncio
    m = pytest.importorskip("galileo.observatory")
    arb = m.ResourceArbiter(bus=MagicMock(), poll_s=0.01)
    arb.begin_activity("Pier-1", "dome")
    assert not (await arb.request("Pier-2", "dome", "close", wait_s=0.05)).granted
    asyncio.get_running_loop().call_later(0.05, arb.end_activity, "Pier-1", "dome")
    assert (await arb.request("Pier-2", "dome", "close", wait_s=1.0)).granted

    from galileo.session_exec import SessionContext, SessionExecutor
    arb.begin_activity("Pier-1", "dome")
    block = type("DomeCloseBlock", (_DomeCloseBlock,), {})()
    ex = SessionExecutor(SessionContext(pier_name="Pier-2", dome=AsyncMock(), arbiter=arb))
    result = await ex.run([block])
    assert result.succeeded and result.errors  # skipped and logged, run completes
    ex.context.dome.close_shutter.assert_not_called()


@pytest.mark.requirement("TC-OBS-120")
@pytest.mark.priority("P2")
async def test_tc_obs_120_outcomes_published_on_bus():
    """OBS-120: Granted, denied and released outcomes are published on the event bus."""
    m = pytest.importorskip("galileo.observatory")
    bus = MagicMock()
    arb = m.ResourceArbiter(bus=bus)
    arb.begin_activity("Pier-1", "dome")
    await arb.request("Pier-2", "dome", "close")
    await arb.request("Pier-2", "dome", "open")
    arb.end_activity("Pier-1", "dome")
    kinds = [type(c.args[0]) for c in bus.publish.call_args_list]
    assert kinds == [m.ResourceClaimDeniedEvent, m.ResourceClaimGrantedEvent, m.ResourceReleasedEvent]
    assert bus.publish.call_args_list[0].args[0].blocked_by == ["Pier-1"]


@pytest.mark.requirement("TC-OBS-130")
@pytest.mark.priority("P2")
async def test_tc_obs_130_emergency_overrides_imaging():
    """OBS-130: A safety-driven (emergency) request overrides another Pier's imaging."""
    m = pytest.importorskip("galileo.observatory")
    arb = m.ResourceArbiter(bus=MagicMock())
    arb.begin_activity("Pier-1", "dome")
    assert (await arb.request("Pier-2", "dome", "close", priority=m.PRIORITY_EMERGENCY)).granted

    from galileo.session_exec import SessionContext, SessionExecutor
    ctx = SessionContext(pier_name="Pier-2", dome=AsyncMock(), arbiter=arb, is_safe=lambda: False)
    block = type("DomeCloseBlock", (_DomeCloseBlock,), {})()
    await SessionExecutor(ctx).run([block])
    ctx.dome.close_shutter.assert_awaited_once()


@pytest.mark.requirement("TC-OBS-100")
@pytest.mark.priority("P2")
def test_tc_obs_100_session_context_shares_one_arbiter_per_observatory():
    """OBS-100: Every Pier's run of one Observatory gets the same ResourceArbiter; another
    Observatory gets its own."""
    from galileo.ui.session_runner import _observatory_arbiter

    class _Obs:
        def __init__(self, name):
            self.name = name

    class _Win:
        pass

    win = _Win()
    win._current_observatory = _Obs("Backyard")
    first = _observatory_arbiter(win)
    win._current_pier = "Pier-2"          # switching Pier within the Observatory
    assert _observatory_arbiter(win) is first
    win._current_observatory = _Obs("Remote")
    assert _observatory_arbiter(win) is not first
    win._current_observatory = _Obs("Backyard")
    assert _observatory_arbiter(win) is first


# ---------------------------------------------------------------------------
# TC-OBS-140 — scheduled sessions run on every Pier, not only the selected one
# ---------------------------------------------------------------------------

class _Piers:
    """Three Piers of one Observatory, each with its own devices, behind a fake AppWindow."""

    def __init__(self, monkeypatch):
        import datetime
        from types import SimpleNamespace
        from galileo.current_object import pier_key
        from galileo.safety import LiveSafetyMonitor
        from galileo.scheduler import ObservatoryScheduler, SchedulerJob
        from galileo.ui import session_runner

        self.piers = [SimpleNamespace(id=i, name=f"Pier-{i}") for i in (1, 2, 3)]
        self.unsafe = False                  # one verdict for the whole Observatory (OBS-030)
        self.mounts = {p.id: MagicMock(name=f"mount{p.id}") for p in self.piers}
        self.cameras = {p.id: MagicMock(name=f"camera{p.id}") for p in self.piers}
        self.connected = {p.id: True for p in self.piers}

        class _Window:
            @property
            def _camera_backends(self):
                return self._camera_backends_by_pier.setdefault(pier_key(self._current_pier), {})

        win = _Window()
        win._current_pier = self.piers[0]
        win._current_observatory = SimpleNamespace(name="Backyard")
        win._active_camera_slot = "primary"
        win._window = SimpleNamespace(isVisible=lambda: True)
        win._camera_backends_by_pier = {p.id: {"primary camera": self.cameras[p.id]} for p in self.piers}
        win._device_pages = {
            "mount": {"adapter": self.mounts[1],
                      "adapter_for": lambda k: self.mounts[k] if self.connected[k] else None},
        }
        self.window = win

        self.schedulers = {}
        past = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)).isoformat()
        for pier in self.piers:
            scheduler = ObservatoryScheduler()
            scheduler.set_safety_monitor(LiveSafetyMonitor(
                lambda: (True, not self.unsafe, ["the weather station reports rain"])))
            region = SimpleNamespace(blocks=[], name=f"session-{pier.id}", _scheduler=scheduler)
            job = SchedulerJob(f"job-{pier.id}", sequence=region, pier_name=pier.name)
            job.scheduled_start_utc = past
            region._job = job
            scheduler.add_job(job)
            self.schedulers[pier.name] = scheduler
        win._scheduler_for_pier = lambda name: self.schedulers[name]

        monkeypatch.setattr("galileo.observatory.list_piers", lambda _obs: list(self.piers))
        monkeypatch.setattr(session_runner, "_build_notify_service", lambda _w: None)
        monkeypatch.setattr(session_runner, "get_history", lambda: None)
        monkeypatch.setattr(session_runner, "preflight", lambda blocks, ctx: [])


@pytest.fixture
def qt_app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


@pytest.mark.requirement("TC-OBS-140")
@pytest.mark.priority("P2")
def test_tc_obs_140_session_context_uses_the_named_piers_own_devices(qt_app, monkeypatch):
    """OBS-140: a context built for a Pier that is not selected carries that Pier's mount and
    camera, never the selected Pier's."""
    from galileo.ui.session_runner import build_session_context
    rig = _Piers(monkeypatch)
    for pier in rig.piers:
        ctx = build_session_context(rig.window, pier)
        assert ctx.pier_name == pier.name
        assert ctx.mount is rig.mounts[pier.id] and ctx.camera is rig.cameras[pier.id]
    assert build_session_context(rig.window).mount is rig.mounts[1]       # the selected Pier, as before
    rig.connected[3] = False
    assert build_session_context(rig.window, rig.piers[2]).mount is None


@pytest.mark.requirement("TC-OBS-140")
@pytest.mark.priority("P2")
def test_tc_obs_140_one_tick_starts_a_due_job_on_each_of_three_piers(qt_app, monkeypatch):
    """OBS-020/OBS-140: with Pier-1 selected, a single scheduler tick starts the due job on all
    three Piers, each against its own devices - the others no longer wait to be selected."""
    from galileo.ui.session_runner import SessionRunController
    rig = _Piers(monkeypatch)
    controller = SessionRunController(rig.window)
    launched = []
    monkeypatch.setattr(controller, "_launch", lambda region, ctx, manual, key=None, **kw: launched.append((key, ctx)))

    controller._tick()

    assert [key for key, _ in launched] == [1, 2, 3]
    assert [ctx.mount for _, ctx in launched] == [rig.mounts[1], rig.mounts[2], rig.mounts[3]]
    assert [ctx.camera for _, ctx in launched] == [rig.cameras[1], rig.cameras[2], rig.cameras[3]]


@pytest.mark.requirement("TC-OBS-140")
@pytest.mark.priority("P2")
def test_tc_obs_140_unsafe_weather_holds_every_pier_of_the_observatory(qt_app, monkeypatch):
    """OBS-030/OBS-140: one weather station serves the whole Observatory, so when it reports
    unsafe conditions no Pier starts its job, each showing the reason; when it clears they all start."""
    from galileo.ui.session_runner import SessionRunController
    rig = _Piers(monkeypatch)
    rig.unsafe = True
    controller = SessionRunController(rig.window)
    launched = []
    monkeypatch.setattr(controller, "_launch", lambda region, ctx, manual, key=None, **kw: launched.append(key))

    controller._tick()
    assert launched == []
    assert all("rain" in controller.blocked_reason(k) for k in (1, 2, 3))

    rig.unsafe = False
    controller._tick()
    assert launched == [1, 2, 3]
    assert all(controller.blocked_reason(k) == "" for k in (1, 2, 3))


@pytest.mark.requirement("TC-OBS-140")
@pytest.mark.priority("P2")
def test_tc_obs_140_pier_with_nothing_connected_waits_without_holding_the_others(qt_app, monkeypatch):
    """OBS-140: a Pier with no camera and no mount connected is skipped (its job stays pending);
    the other Piers still start."""
    from galileo.ui.session_runner import SessionRunController
    rig = _Piers(monkeypatch)
    rig.connected[3] = False
    rig.window._camera_backends_by_pier[3].clear()
    controller = SessionRunController(rig.window)
    launched = []
    monkeypatch.setattr(controller, "_launch", lambda region, ctx, manual, key=None, **kw: launched.append(key))

    controller._tick()

    assert launched == [1, 2]
    assert rig.schedulers["Pier-3"].jobs[0].run_state == "pending"


@pytest.mark.requirement("TC-OBS-140")
@pytest.mark.priority("P2")
def test_tc_obs_140_a_failing_pier_does_not_stop_the_others(qt_app, monkeypatch):
    """OBS-140: an exception servicing one Pier (e.g. a safety device that cannot be read) is
    logged and the remaining Piers are still serviced."""
    from galileo.ui.session_runner import SessionRunController
    rig = _Piers(monkeypatch)
    rig.schedulers["Pier-1"].set_safety_monitor(type("Boom", (), {"is_safe": property(lambda s: 1 / 0)})())
    controller = SessionRunController(rig.window)
    launched = []
    monkeypatch.setattr(controller, "_launch", lambda region, ctx, manual, key=None, **kw: launched.append(key))

    controller._tick()

    assert launched == [2, 3]


@pytest.mark.requirement("TC-OBS-030")
@pytest.mark.priority("P2")
def test_tc_obs_030_migration_moves_safety_settings_up_to_the_observatory():
    """OBS-030: migration 029 carries each Observatory's per-Pier safety devices and rules up to the
    Observatory (the lowest-numbered Pier's winning), removes the per-Pier safety rows, and leaves
    every other device category on its Pier."""
    import importlib
    import sqlite3

    migration = importlib.import_module("galileo.library.migrations.029_scope_safety_devices_to_observatory")
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE observatories (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE piers (id INTEGER PRIMARY KEY, observatory_id INTEGER, name TEXT);"
        "CREATE TABLE device_configs (id INTEGER PRIMARY KEY, pier_id INTEGER, category TEXT, slot TEXT,"
        " driver TEXT, server TEXT, port INTEGER, device_name TEXT);"
        "CREATE TABLE weather_safety_rules (id INTEGER PRIMARY KEY, pier_id INTEGER, slot TEXT, parameter TEXT,"
        " label TEXT, unit TEXT, safety_related INTEGER, operator TEXT, threshold REAL);"
        "INSERT INTO observatories VALUES (1, 'Home'), (2, 'Remote');"
        "INSERT INTO piers VALUES (10, 1, 'North'), (11, 1, 'South'), (20, 2, 'Only');"
        "INSERT INTO device_configs VALUES"
        " (1, 11, 'weather', 'primary', 'Alpaca', 'south-wx', 11111, 'South Station'),"
        " (2, 10, 'weather', 'primary', 'INDI', 'north-wx', 7624, 'North Station'),"
        " (3, 10, 'safety_monitor', 'safety_monitor_2', 'Alpaca', 'roof', 11111, 'Roof'),"
        " (4, 20, 'weather', 'primary', 'INDI', 'remote-wx', 7624, 'Remote Station'),"
        " (5, 10, 'camera', 'primary', 'INDI', 'cam', 7624, 'ZWO');"
        "INSERT INTO weather_safety_rules VALUES"
        " (1, 11, 'primary', 'rain', 'Rain', 'bool', 0, '>', 0.0),"
        " (2, 10, 'primary', 'rain', 'Rain', 'bool', 1, '>', 0.0),"
        " (3, 20, 'primary', 'wind_speed', 'Wind', 'km/h', 1, '>=', 20.0);"
    )

    class _SqlMigrator:
        def sql(self, statement):
            conn.execute(statement)

    migration.migrate(_SqlMigrator(), None)

    rows = conn.execute(
        "SELECT observatory_id, category, slot, device_name FROM safety_device_configs ORDER BY 1, 2, 3").fetchall()
    assert rows == [(1, "safety_monitor", "safety_monitor_2", "Roof"), (1, "weather", "primary", "North Station"),
                    (2, "weather", "primary", "Remote Station")]
    rules = conn.execute(
        "SELECT observatory_id, parameter, safety_related FROM observatory_safety_rules ORDER BY 1, 2").fetchall()
    assert rules == [(1, "rain", 1), (2, "wind_speed", 1)]                 # North's rule beat South's
    assert conn.execute("SELECT category FROM device_configs").fetchall() == [("camera",)]
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE name = 'weather_safety_rules'").fetchall() == []

    migration.rollback(_SqlMigrator(), None)
    assert conn.execute("SELECT COUNT(*) FROM weather_safety_rules").fetchone()[0] == 3     # 2 piers + 1 pier
    assert conn.execute("SELECT COUNT(*) FROM device_configs WHERE category = 'weather'").fetchone()[0] == 3
