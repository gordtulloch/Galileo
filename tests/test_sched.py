# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SCHED — Observatory Scheduler (TC-SCHED-010 … TC-SCHED-100)."""

import pytest


@pytest.fixture
def scheduler():
    sched_mod = pytest.importorskip("galileo.scheduler")
    return sched_mod.ObservatoryScheduler()


@pytest.fixture
def sample_job():
    sched_mod = pytest.importorskip("galileo.scheduler")
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef(name="M42 Ha")
    return sched_mod.SchedulerJob(
        name="M42",
        sequence=seq,
        pier_name="Pier-1",
        target_ra=83.8221,
        target_dec=-5.3911,
    )


# ---------------------------------------------------------------------------
# TC-SCHED-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SCHED-010")
@pytest.mark.priority("MVP")
def test_tc_sched_010_prioritized_job_queue(scheduler, sample_job):
    """SCHED-010: Prioritized job queue where each job specifies target, sequence, and Pier/optical train."""
    sched_mod = pytest.importorskip("galileo.scheduler")
    job2 = sched_mod.SchedulerJob(name="M31", pier_name="Pier-1", target_ra=10.7, target_dec=41.3)

    sample_job.priority = 2
    job2.priority = 1

    scheduler.add_job(sample_job)
    scheduler.add_job(job2)

    queue = scheduler.get_ordered_jobs()
    assert queue[0].priority < queue[1].priority or queue[0].name == "M31"


# ---------------------------------------------------------------------------
# TC-SCHED-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SCHED-020")
@pytest.mark.priority("MVP")
def test_tc_sched_020_add_remove_reorder_modify_jobs(scheduler, sample_job):
    """SCHED-020: Add, remove, reorder, and modify jobs both before and during execution."""
    sched_mod = pytest.importorskip("galileo.scheduler")
    job2 = sched_mod.SchedulerJob(name="M31", pier_name="Pier-1", target_ra=10.7, target_dec=41.3)

    scheduler.add_job(sample_job)
    scheduler.add_job(job2)
    assert len(scheduler.jobs) == 2

    scheduler.move_job(sample_job, new_position=1)
    assert scheduler.jobs.index(sample_job) == 1

    scheduler.remove_job(job2)
    assert len(scheduler.jobs) == 1

    scheduler.update_job(sample_job, {"target_ra": 84.0})
    assert sample_job.target_ra == 84.0


# ---------------------------------------------------------------------------
# TC-SCHED-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SCHED-030")
@pytest.mark.priority("MVP")
def test_tc_sched_030_per_job_constraints(scheduler, sample_job):
    """SCHED-030: Per-job constraints: min altitude, min moon separation, twilight restriction, horizon avoidance."""
    sched_mod = pytest.importorskip("galileo.scheduler")
    sample_job.constraints = sched_mod.JobConstraints(
        min_altitude_deg=20.0,
        min_moon_separation_deg=30.0,
        twilight_restriction="astronomical",
        respect_horizon=True,
    )
    scheduler.add_job(sample_job)
    job = scheduler.jobs[0]
    assert job.constraints.min_altitude_deg == 20.0
    assert job.constraints.twilight_restriction == "astronomical"


# ---------------------------------------------------------------------------
# TC-SCHED-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SCHED-040")
@pytest.mark.priority("MVP")
def test_tc_sched_040_per_job_startup_conditions(scheduler, sample_job):
    """SCHED-040: Per-job startup conditions: immediate, at culmination, or at a specific time."""
    sched_mod = pytest.importorskip("galileo.scheduler")

    sample_job.startup_condition = sched_mod.StartAtCulmination()
    scheduler.add_job(sample_job)
    assert isinstance(scheduler.jobs[0].startup_condition, sched_mod.StartAtCulmination)

    job2 = sched_mod.SchedulerJob(name="M31", pier_name="Pier-1", target_ra=10.7, target_dec=41.3)
    job2.startup_condition = sched_mod.StartAtTime(time_utc="2026-09-17T01:00:00")
    scheduler.add_job(job2)
    assert isinstance(scheduler.jobs[1].startup_condition, sched_mod.StartAtTime)


# ---------------------------------------------------------------------------
# TC-SCHED-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SCHED-050")
@pytest.mark.priority("MVP")
def test_tc_sched_050_per_job_completion_conditions(scheduler, sample_job):
    """SCHED-050: Per-job completion: run once, repeat N times, or repeat indefinitely."""
    sched_mod = pytest.importorskip("galileo.scheduler")
    sample_job.completion_condition = sched_mod.RunOnce()
    assert isinstance(sample_job.completion_condition, sched_mod.RunOnce)

    sample_job.completion_condition = sched_mod.RepeatNTimes(n=3)
    assert sample_job.completion_condition.n == 3

    sample_job.completion_condition = sched_mod.RepeatIndefinitely()
    assert isinstance(sample_job.completion_condition, sched_mod.RepeatIndefinitely)


@pytest.mark.requirement("TC-SCHED-050")
@pytest.mark.priority("P2")
async def test_tc_sched_050_completed_job_is_reaped_and_its_session_deleted(scheduler):
    """SCHED-050: a job that completes (RunOnce, all required frames captured) is removed
    from the queue, and the session it came from is deleted, not just desecheduled — it has
    nothing left to do."""
    ses_mod = pytest.importorskip("galileo.ui.sessions")

    ses_screen = ses_mod.SessionsScreen()
    region = ses_screen.add_session(ses_mod.SessionRegion(name="M42 Session", scheduler=scheduler),
                                     pier_name="Pier-1")
    ses_screen.set_active_pier("Pier-1")
    region.insert_block(ses_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))

    region.schedule()
    job = region._job
    job.total_required = 10
    assert scheduler.jobs == [job]
    assert region in ses_screen.visible_sessions

    await scheduler.record_frames_captured(job, count=10)
    assert job.is_complete is True

    reaped = scheduler.reap_completed_jobs()
    assert reaped == [job]
    assert scheduler.jobs == []
    assert region not in ses_screen.visible_sessions   # deleted, not just desecheduled


@pytest.mark.requirement("TC-SCHED-050")
@pytest.mark.priority("P2")
async def test_tc_sched_050_incomplete_or_repeating_jobs_are_not_reaped(scheduler, sample_job):
    """SCHED-050: a job still short of its required frames, or one that repeats, stays queued."""
    sched_mod = pytest.importorskip("galileo.scheduler")

    sample_job.total_required = 10
    scheduler.add_job(sample_job)
    await scheduler.record_frames_captured(sample_job, count=5)
    assert scheduler.reap_completed_jobs() == []

    sample_job.completion_condition = sched_mod.RepeatIndefinitely()
    await scheduler.record_frames_captured(sample_job, count=5)  # now "complete" by frame count
    assert sample_job.is_complete is False   # but RepeatIndefinitely never auto-completes
    assert scheduler.reap_completed_jobs() == []
    assert scheduler.jobs == [sample_job]


# ---------------------------------------------------------------------------
# TC-SCHED-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SCHED-060")
@pytest.mark.priority("MVP")
async def test_tc_sched_060_gate_on_safety_monitor(scheduler, sample_job, mock_safety_monitor):
    """SCHED-060: Gate job startup and continued execution on safety-monitor state."""
    scheduler.add_job(sample_job)
    scheduler.set_safety_monitor(mock_safety_monitor)

    mock_safety_monitor.is_safe = False
    can_start = await scheduler.can_start_job(sample_job)
    assert can_start is False

    mock_safety_monitor.is_safe = True
    can_start2 = await scheduler.can_start_job(sample_job)
    assert can_start2 is True


# ---------------------------------------------------------------------------
# TC-SCHED-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SCHED-070")
@pytest.mark.priority("P2")
async def test_tc_sched_070_priority_preemption(scheduler):
    """SCHED-070: Continuously replan using priority-based preemption; higher-priority job preempts lower."""
    sched_mod = pytest.importorskip("galileo.scheduler")

    low_job = sched_mod.SchedulerJob(name="M42", priority=10, pier_name="Pier-1", target_ra=83.8, target_dec=-5.4)
    high_job = sched_mod.SchedulerJob(name="Alert Target", priority=1, pier_name="Pier-1", target_ra=0.0, target_dec=0.0)

    scheduler.add_job(low_job)
    low_job._state = "running"

    scheduler.add_job(high_job)
    await scheduler.replan()

    assert scheduler.active_job is high_job or scheduler.next_job() is high_job


# ---------------------------------------------------------------------------
# TC-SCHED-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SCHED-080")
@pytest.mark.priority("P2")
def test_tc_sched_080_altitude_trajectory_chart(scheduler, sample_job):
    """SCHED-080: Display each queued job's altitude trajectory and projected run window as a chart."""
    sched_mod = pytest.importorskip("galileo.scheduler")
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    loc = sky_mod.ObservingLocation(name="Home", latitude=51.5, longitude=-1.0, elevation_m=100, timezone="UTC")
    scheduler.set_location(loc)
    scheduler.add_job(sample_job)

    chart = scheduler.get_job_trajectory_chart(sample_job, date="2026-09-16")
    assert "times" in chart
    assert "altitudes" in chart
    assert "run_window" in chart


# ---------------------------------------------------------------------------
# TC-SCHED-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SCHED-090")
@pytest.mark.priority("MVP")
async def test_tc_sched_090_track_capture_progress_across_nights(scheduler, sample_job):
    """SCHED-090: Track per-job capture progress across multiple nights; avoid recapturing already-obtained frames."""
    scheduler.add_job(sample_job)

    sample_job.total_required = 100
    await scheduler.record_frames_captured(sample_job, count=40)

    remaining = scheduler.get_remaining_frames(sample_job)
    assert remaining == 60


# ---------------------------------------------------------------------------
# TC-SCHED-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SCHED-100")
@pytest.mark.priority("MVP")
def test_tc_sched_100_persist_queue_across_restarts(scheduler, sample_job, tmp_path):
    """SCHED-100: Persist job queue and per-job progress across application restarts."""
    sched_mod = pytest.importorskip("galileo.scheduler")
    from galileo.library.database import db, init_db
    init_db(tmp_path / "scheduler.db")
    try:
        scheduler.set_persistence("Pier-1")
        scheduler.add_job(sample_job)
        scheduler.save()

        scheduler2 = sched_mod.ObservatoryScheduler()
        scheduler2.set_persistence("Pier-1")
        scheduler2.load()

        assert len(scheduler2.jobs) == 1
        assert scheduler2.jobs[0].name == "M42"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Planning > Scheduler screen (galileo.ui.scheduler)
# ---------------------------------------------------------------------------

@pytest.fixture
def window(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "scheduler_page.db")
    from galileo.ui.app_window import AppWindow
    win = AppWindow()
    yield win
    win._window.close()
    db.close()


def _sessions_and_scheduler_pages(window):
    from galileo.observatory import create_observatory, create_pier
    from galileo.ui.scheduler import SchedulerPageWidget
    from galileo.ui.sessions import SessionsPageWidget

    obs = create_observatory("Home", 40.0, 0.0)
    window._select_observatory(obs)
    pier = create_pier(obs, "Pier-1")
    window._current_pier = pier
    window._on_pier_changed()
    window._primary_nav.select("planning")
    sessions = window._window.findChildren(SessionsPageWidget)[0]
    scheduler_page = window._window.findChildren(SchedulerPageWidget)[0]
    return sessions, scheduler_page


@pytest.mark.requirement("TC-SCHED-010")
@pytest.mark.priority("MVP")
def test_scheduler_page_shows_jobs_scheduled_from_sessions(window):
    """SCHED-010: a job only enters the queue via a session's Schedule control, and
    Planning > Scheduler shows it — sharing the same per-Pier ObservatoryScheduler
    Planning > Sessions submits to, not a separate queue."""
    sessions, scheduler_page = _sessions_and_scheduler_pages(window)

    region = sessions.screen.create_session_for_target("M31", 10.68, 41.27)
    region._scheduler = sessions._scheduler_for(region._pier_name)
    assert sessions._scheduler_for("Pier-1") is scheduler_page._scheduler()

    region.schedule()
    scheduler_page.reload()
    assert scheduler_page._table.rowCount() == 1
    assert scheduler_page._table.item(0, 1).text() == "M31 Session"


@pytest.mark.requirement("TC-SCHED-020")
@pytest.mark.priority("MVP")
def test_scheduler_page_move_and_edit_job(window):
    """SCHED-020: jobs can be reordered and modified (priority, frames required) from the screen."""
    from galileo.ui.scheduler import _EditJobDialog
    sessions, scheduler_page = _sessions_and_scheduler_pages(window)

    for name, ra, dec in (("M31", 10.68, 41.27), ("M42", 83.8, -5.4)):
        region = sessions.screen.create_session_for_target(name, ra, dec)
        region._scheduler = sessions._scheduler_for(region._pier_name)
        region.schedule()
    scheduler_page.reload()

    scheduler_page._table.selectRow(0)
    scheduler_page._move_selected(1)
    assert [j.name for j in scheduler_page._scheduler().jobs] == ["M42 Session", "M31 Session"]

    job = scheduler_page._scheduler().jobs[0]
    dialog = _EditJobDialog(job, scheduler_page)
    dialog.priority_spin.setValue(1)
    dialog.total_spin.setValue(20)
    dialog.apply()
    assert job.priority == 1 and job.total_required == 20


@pytest.mark.requirement("TC-SCHED-020")
@pytest.mark.priority("MVP")
def test_scheduler_page_remove_deschedules_session_rather_than_deleting_it(window, monkeypatch):
    """SCHED-020: removing a job from the queue returns its session to editable draft
    state (deschedule) — only a job that actually completes deletes its session."""
    from PySide6.QtWidgets import QMessageBox
    sessions, scheduler_page = _sessions_and_scheduler_pages(window)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    region = sessions.screen.create_session_for_target("M31", 10.68, 41.27)
    region._scheduler = sessions._scheduler_for(region._pier_name)
    region.schedule()
    scheduler_page.reload()

    scheduler_page._table.selectRow(0)
    scheduler_page._remove_selected()

    assert scheduler_page._table.rowCount() == 0
    sessions.reload()
    assert region in sessions.screen.visible_sessions   # still there
    assert region.is_editable is True and region.is_scheduled is False   # just unlocked
