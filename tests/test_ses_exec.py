# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SES — block-based session execution engine (``galileo.sequencer.session_exec``).

Covers the execution-side requirements of the Sessions screen's blocks — SES-030 (run
start-to-finish), SES-040 (pause/resume/stop), SES-050 (live progress), SES-080 (recoverable
errors), SES-150 (Notification block), SES-170 (run-time ordering rules), SES-230 (mosaic
model), SES-350 (current-block reporting) — and their hand-off to the scheduler
(``SCHED-060``). Devices are hand-written fakes, not mocks, so the tests exercise the
executor's real control flow.
"""

import asyncio

import pytest

from galileo.sequencer.session_exec import (
    RunState,
    SessionContext,
    SessionExecutor,
    build_tree,
    estimate_frames,
    preflight,
)

sessions = pytest.importorskip("galileo.ui.sessions")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeMount:
    def __init__(self, fail_slew=False):
        self.slews = []
        self.parked = False
        self.fail_slew = fail_slew
        self.tracking = None

    async def get_status(self):
        return {"equatorial_system": "J2000", "slewing": False}

    async def slew_to_coordinates(self, ra, dec):
        if self.fail_slew:
            raise RuntimeError("slew limit")
        self.slews.append((ra, dec))

    async def set_tracking(self, enabled):
        self.tracking = enabled

    async def abort_slew(self):
        pass

    async def park(self):
        self.parked = True


class FakeWheel:
    filter_names = ("L", "R", "G")
    position = 0

    def __init__(self):
        self.moves = []

    async def move_to(self, index):
        self.moves.append(index)
        self.position = index


class FakeImaging:
    """Stands in for ImagingService: records each frame; optionally fails or blocks."""

    def __init__(self, log, fail_on=(), delay=0.0):
        self.log = log
        self.fail_on = set(fail_on)
        self.delay = delay
        self.stop_requested = False
        self.object_name = ""
        self.gain = self.offset = 0
        self.series_done = 0

    async def capture_series(self, count, duration, filter_name="", frame_type="Light", **_):
        n = len(self.log) + 1
        if n in self.fail_on:
            self.log.append(("failed", filter_name))
            raise RuntimeError("download failed")
        if self.delay:
            await asyncio.sleep(self.delay)
        self.log.append((filter_name, duration, frame_type, self.object_name))

    def request_stop(self):
        self.stop_requested = True


class FakeNotify:
    def __init__(self):
        self.events = []

    async def emit(self, event, detail=""):
        self.events.append((event, detail))


def make_context(frames=None, **kw):
    frames = frames if frames is not None else []
    imaging_kw = kw.pop("imaging", {})
    ctx = SessionContext(
        camera=kw.pop("camera", object()), mount=kw.pop("mount", FakeMount()),
        filter_wheel=kw.pop("filter_wheel", FakeWheel()),
        make_imaging=lambda: FakeImaging(frames, **imaging_kw), **kw,
    )
    return ctx, frames


def run(executor, blocks):
    return asyncio.run(executor.run(blocks))


def blocks_for_two_filters():
    ForFilter = sessions.ForFilterBlock
    loop = ForFilter(filters=["L", "R"])
    child = sessions.ImageBlock(exposure=30.0, count=2)
    child.indent = 1
    return [sessions.TargetBlock(name="M31", ra_deg=10.68, dec_deg=41.27), loop, child]


# ---------------------------------------------------------------------------
# SES-030 — run start to finish
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-030")
@pytest.mark.priority("MVP")
def test_tc_ses_030_block_session_runs_start_to_finish_with_loops():
    """SES-030: a defined session executes start-to-finish without user interaction — the
    Target slews, and a FOR Filter loop repeats its indented Image block once per filter."""
    ctx, frames = make_context()
    result = run(SessionExecutor(ctx, name="t"), blocks_for_two_filters())

    assert result.state == RunState.COMPLETED
    assert result.frames_captured == 4
    assert ctx.mount.slews == [(10.68, 41.27)]
    assert ctx.mount.tracking is True
    assert ctx.filter_wheel.moves == [0, 1]
    # Two exposures per filter, in loop order, tagged with the target's name.
    assert [(f[0], f[3]) for f in frames] == [("L", "M31"), ("L", "M31"), ("R", "M31"), ("R", "M31")]


@pytest.mark.requirement("TC-SES-030")
@pytest.mark.priority("MVP")
def test_tc_ses_030_indent_builds_nested_tree_and_frame_estimate():
    """SES-030/SES-050: the flat, indent-annotated block list becomes a tree, and the frame
    total used for progress multiplies a loop body by its passes."""
    tree = build_tree(blocks_for_two_filters())
    assert [type(n.block).__name__ for n in tree] == ["TargetBlock", "ForFilterBlock"]
    assert [type(c.block).__name__ for c in tree[1].children] == ["ImageBlock"]
    assert estimate_frames(tree) == 4


@pytest.mark.requirement("TC-SES-030")
@pytest.mark.priority("MVP")
def test_tc_ses_030_notification_block_runs_through_context():
    """SES-150: a Notification block executed by the engine reaches the Observatory's
    notification service."""
    notify = FakeNotify()
    ctx, _ = make_context(notify_service=notify)
    result = run(SessionExecutor(ctx), [sessions.NotificationBlock(message="Halfway there")])
    assert result.state == RunState.COMPLETED
    from galileo.notify import NotificationEvent
    assert (NotificationEvent.SESSION_MESSAGE, "Halfway there") in notify.events
    # ... and the outcome itself is announced (NOTIF-010).
    assert any(e[0] == NotificationEvent.SEQUENCE_COMPLETE for e in notify.events)


# ---------------------------------------------------------------------------
# SES-040 / SES-050 / SES-350 — control and progress
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-040")
@pytest.mark.priority("MVP")
def test_tc_ses_040_stop_ends_run_and_skips_remaining_blocks():
    """SES-040: Stop ends a running session promptly; blocks after the current one never run."""
    async def scenario():
        ctx, frames = make_context(imaging={"delay": 0.3})
        executor = SessionExecutor(ctx)
        blocks = [sessions.ImageBlock(exposure=1.0, count=10), sessions.ParkMountBlock()]
        task = asyncio.create_task(executor.run(blocks))
        await asyncio.sleep(0.1)
        executor.stop()
        return await task, ctx, frames

    result, ctx, frames = asyncio.run(scenario())
    assert result.state == RunState.STOPPED
    assert len(frames) < 10
    assert ctx.mount.parked is False


@pytest.mark.requirement("TC-SES-040")
@pytest.mark.priority("MVP")
def test_tc_ses_040_pause_holds_until_resumed():
    """SES-040: Pause holds the session between frames; Resume lets it finish."""
    async def scenario():
        ctx, frames = make_context(imaging={"delay": 0.05})
        states = []
        executor = SessionExecutor(ctx, on_progress=lambda p: states.append(p.state))
        task = asyncio.create_task(executor.run([sessions.ImageBlock(exposure=1.0, count=6)]))
        await asyncio.sleep(0.12)
        executor.pause()
        await asyncio.sleep(0.4)            # long enough that, unpaused, all six would be done
        held = len(frames)
        executor.resume()
        return await task, held, len(frames), states

    result, held, final, states = asyncio.run(scenario())
    assert result.state == RunState.COMPLETED
    assert held < 6 and final == 6
    assert RunState.PAUSED in states


@pytest.mark.requirement("TC-SES-050")
@pytest.mark.priority("MVP")
def test_tc_ses_050_progress_reports_current_block_and_frame_counts():
    """SES-050/SES-350: progress snapshots name the executing block, its position, and
    frames done of total."""
    ctx, _ = make_context()
    seen = []
    executor = SessionExecutor(ctx, on_progress=seen.append)
    blocks = [sessions.ImageBlock(exposure=5.0, count=2), sessions.ImageBlock(exposure=5.0, count=1)]
    run(executor, blocks)

    assert seen[0].state == RunState.RUNNING
    running_blocks = [p.block for p in seen if p.block is not None]
    assert blocks[0] in running_blocks and blocks[1] in running_blocks
    assert all(p.block_total == 2 for p in seen)
    assert max(p.frames_done for p in seen) == 3
    assert {p.frames_total for p in seen} == {3}
    assert seen[-1].state == RunState.COMPLETED


# ---------------------------------------------------------------------------
# SES-080 — error handling
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-080")
@pytest.mark.priority("MVP")
def test_tc_ses_080_failed_frame_is_logged_and_session_continues():
    """SES-080: one bad frame is a recoverable error — logged, then the session carries on."""
    ctx, _frames = make_context(imaging={"fail_on": {2}})
    result = run(SessionExecutor(ctx), [sessions.ImageBlock(exposure=5.0, count=4)])
    assert result.state == RunState.COMPLETED
    assert result.frames_captured == 3
    assert any("download failed" in e for e in result.errors)


@pytest.mark.requirement("TC-SES-080")
@pytest.mark.priority("MVP")
def test_tc_ses_080_repeated_failures_give_up_the_block_not_the_session():
    """SES-080: three failed frames in a row abandon that Image block, but the next block runs."""
    ctx, _frames = make_context(imaging={"fail_on": {1, 2, 3}})
    blocks = [sessions.ImageBlock(exposure=5.0, count=10), sessions.ParkMountBlock()]
    result = run(SessionExecutor(ctx), blocks)
    assert result.state == RunState.COMPLETED
    assert ctx.mount.parked is True
    assert any("giving up" in e for e in result.errors)


@pytest.mark.requirement("TC-SES-080")
@pytest.mark.priority("MVP")
def test_tc_ses_080_failed_slew_to_target_ends_the_session():
    """SES-080: a block the session depends on (slew to target) is fatal — imaging the wrong
    sky would be worse than stopping — so later blocks do not run."""
    ctx, frames = make_context(mount=FakeMount(fail_slew=True))
    blocks = [sessions.TargetBlock(name="M31", ra_deg=10.0, dec_deg=40.0), sessions.ImageBlock(count=3)]
    result = run(SessionExecutor(ctx), blocks)
    assert result.state == RunState.ERROR
    assert frames == []
    assert "slew limit" in result.errors[-1]


@pytest.mark.requirement("TC-SES-080")
@pytest.mark.priority("MVP")
def test_tc_ses_080_fatal_error_inside_a_loop_still_ends_the_session():
    """SES-080: a fatal failure nested inside a (non-fatal) FOR Filter loop is not swallowed."""
    ctx, _frames = make_context(mount=FakeMount(fail_slew=True))
    loop = sessions.ForFilterBlock(filters=["L", "R"])
    target = sessions.TargetBlock(name="M31", ra_deg=10.0, dec_deg=40.0)
    target.indent = 1
    result = run(SessionExecutor(ctx), [loop, target, sessions.ParkMountBlock()])
    assert result.state == RunState.ERROR
    assert ctx.mount.parked is False


@pytest.mark.requirement("TC-SES-080")
@pytest.mark.priority("MVP")
def test_tc_ses_080_unsafe_conditions_run_only_shutdown_blocks():
    """Safety: while the safety monitor says unsafe, imaging is skipped but Park still runs."""
    ctx, frames = make_context(is_safe=lambda: False)
    result = run(SessionExecutor(ctx), [sessions.ImageBlock(count=3), sessions.ParkMountBlock()])
    assert frames == []
    assert ctx.mount.parked is True
    assert any("unsafe" in line.lower() for line in result.log)


# ---------------------------------------------------------------------------
# SES-170 / SES-230 — validation
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-170")
@pytest.mark.priority("MVP")
def test_tc_ses_170_run_time_ordering_and_placeholder_checks():
    """SES-170: at run time a Plate Solve with no Target before it, or a template's
    placeholder Target, makes the session invalid — nothing is executed."""
    ctx, frames = make_context()
    bad = [sessions.PlateSolveBlock(), sessions.ImageBlock(count=2)]
    result = run(SessionExecutor(ctx), bad)
    assert result.state == RunState.ERROR and frames == []

    placeholder = [sessions.TargetBlock(name="", is_placeholder_target=True)]
    assert any("placeholder" in p for p in preflight(placeholder, ctx))


@pytest.mark.requirement("TC-SES-170")
@pytest.mark.priority("MVP")
def test_tc_ses_170_preflight_reports_missing_equipment():
    """Run pre-flight names every device a block needs but the Pier hasn't connected."""
    ctx = SessionContext(mount=FakeMount())          # no camera, no guider
    blocks = [sessions.TargetBlock(name="M31", ra_deg=1.0, dec_deg=1.0),
              sessions.ImageBlock(count=1), sessions.GuideStartBlock()]
    problems = " ".join(preflight(blocks, ctx))
    assert "camera" in problems and "guider" in problems and "mount" not in problems


@pytest.mark.requirement("TC-SES-230")
@pytest.mark.priority("P2")
def test_tc_ses_230_mosaic_image_block_uses_mosaic_capture():
    """SES-230: an Image block with a mosaic defined runs the mosaic round-robin capture."""
    calls = []

    class FakeMosaicImaging(FakeImaging):
        async def capture_mosaic(self, per_pane, duration, filter_name="", frame_type="Light", **_):
            calls.append((per_pane, duration))
            self.series_done += 6

    class Mosaic:
        panels = [object()] * 3

    block = sessions.ImageBlock(exposure=20.0, count=2)
    block.set_mosaic(Mosaic())
    ctx = SessionContext(camera=object(), mount=FakeMount(), make_imaging=lambda: FakeMosaicImaging([]))
    result = run(SessionExecutor(ctx), [block])
    assert result.state == RunState.COMPLETED
    assert calls == [(2, 20.0)]
    assert result.frames_captured == 6
    assert estimate_frames(build_tree([block])) == 6


# ---------------------------------------------------------------------------
# Scheduler hand-off (SCHED-060)
# ---------------------------------------------------------------------------

def _scheduled_job(frames_ctx=None, blocks=None):
    from galileo.scheduler import ObservatoryScheduler
    region = sessions.SessionRegion("Tonight", scheduler=ObservatoryScheduler())
    for b in blocks or [sessions.ImageBlock(exposure=5.0, count=2)]:
        region.insert_block(b)
    region.run_now()
    return region, region._scheduler, region._job


@pytest.mark.requirement("TC-SCHED-060")
@pytest.mark.priority("MVP")
def test_tc_sched_060_scheduler_runs_a_due_job_through_the_executor():
    """SCHED-060/SES-030: the scheduler fires a due session via the same executor, records its
    frames and log on the job, and a RunOnce job is complete afterwards."""
    _region, scheduler, job = _scheduled_job()
    assert job in scheduler.due_jobs()
    assert job.total_required == 2

    ctx, _frames = make_context()

    async def runner(j):
        return await SessionExecutor(ctx, name=j.name).run(j.sequence.blocks)

    state = asyncio.run(scheduler.run_job(job, runner))
    assert state == "completed"
    assert job.frames_captured == 2 and job.is_complete
    assert job.run_log and scheduler.active_job is None
    assert scheduler.due_jobs() == []
    assert scheduler.reap_completed_jobs() == [job]


@pytest.mark.requirement("TC-SCHED-060")
@pytest.mark.priority("MVP")
def test_tc_sched_060_failed_and_stopped_runs_are_not_refired():
    """A job whose run errored or was stopped keeps its state/log and is not picked up again."""
    for outcome, expected in ((RunState.ERROR, "error"), (RunState.STOPPED, "stopped")):
        _region, scheduler, job = _scheduled_job()

        async def runner(j, outcome=outcome):
            from galileo.sequencer.session_exec import SessionRunResult
            return SessionRunResult(state=outcome, log=["x"])

        assert asyncio.run(scheduler.run_job(job, runner)) == expected
        assert job.is_complete is False
        assert scheduler.due_jobs() == []


@pytest.mark.requirement("TC-SCHED-060")
@pytest.mark.priority("MVP")
def test_tc_sched_060_repeat_n_times_job_becomes_due_again_until_done():
    from galileo.scheduler import RepeatNTimes
    _region, scheduler, job = _scheduled_job()
    job.completion_condition = RepeatNTimes(2)
    ctx, _ = make_context()

    async def runner(j):
        return await SessionExecutor(ctx).run(j.sequence.blocks)

    assert asyncio.run(scheduler.run_job(job, runner)) == "pending"
    assert not job.is_complete and job in scheduler.due_jobs()
    assert asyncio.run(scheduler.run_job(job, runner)) == "completed"
    assert job.is_complete


# ---------------------------------------------------------------------------
# Run control wired into the Sessions screen
# ---------------------------------------------------------------------------

@pytest.fixture
def window(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "ses_exec.db")
    from galileo.ui.app_window import AppWindow
    win = AppWindow()
    yield win
    win._window.close()
    db.close()


def _page(window):
    from galileo.observatory import create_observatory, create_pier
    obs = create_observatory("Home", 40.0, 0.0)
    window._select_observatory(obs)
    window._current_pier = create_pier(obs, "Pier-1")
    window._on_pier_changed()
    window._primary_nav.select("planning")
    return window._window.findChildren(sessions.SessionsPageWidget)[0]


def _wait(controller, timeout_s=10.0):
    """Wait for the controller's run(s) to finish, delivering only *their* queued signals.

    Deliberately not ``QApplication.processEvents()``: other test files leave closed-but-alive
    AppWindows whose timers crash the process if the global event loop is pumped."""
    import time
    from PySide6.QtCore import QCoreApplication
    deadline = time.monotonic() + timeout_s
    while controller.is_running() and time.monotonic() < deadline:
        for run in list(controller._runs.values()):
            QCoreApplication.sendPostedEvents(run.thread, 0)
        QCoreApplication.sendPostedEvents(controller, 0)
        time.sleep(0.01)
    assert not controller.is_running(), "session did not finish"


@pytest.mark.requirement("TC-SES-030")
@pytest.mark.priority("MVP")
def test_tc_ses_030_run_button_refuses_without_equipment(window):
    """SES-030: Run checks equipment first — an Image block with no camera connected is
    refused with a reason, and nothing is scheduled or started."""
    page = _page(window)
    region = page.screen.add_session_from_context_menu()
    region._scheduler = page._scheduler_for(region._pier_name)
    region.insert_block(sessions.ImageBlock(count=1))

    problems, _conflicts = page._controller.start_region(region)
    assert any("camera" in p for p in problems)
    assert not region.is_scheduled and not page._controller.is_running()


@pytest.mark.requirement("TC-SES-030")
@pytest.mark.priority("MVP")
def test_tc_ses_030_run_button_executes_session_and_completed_session_is_deleted(window, monkeypatch):
    """SES-030/SES-210: Run executes the session's blocks now on a worker thread; on success
    the job completes and the session is deleted (a completed session has nothing left)."""
    from galileo.ui import session_runner
    page = _page(window)
    ctx, frames = make_context()
    monkeypatch.setattr(session_runner, "build_session_context", lambda _w: ctx)

    region = page.screen.add_session_from_context_menu()
    region._scheduler = page._scheduler_for(region._pier_name)
    region.insert_block(sessions.ImageBlock(exposure=5.0, count=2))

    problems, _ = page._controller.start_region(region)
    assert problems == []
    assert page._controller.is_running(region)
    _wait(page._controller)

    assert len(frames) == 2
    assert region not in page.screen.visible_sessions


@pytest.mark.requirement("TC-SES-040")
@pytest.mark.priority("MVP")
def test_tc_ses_040_stopped_manual_run_returns_session_to_editable_draft(window, monkeypatch):
    """SES-040/SES-210: stopping a manual Run leaves the session intact and editable again."""
    from galileo.ui import session_runner
    page = _page(window)
    ctx, _frames = make_context(imaging={"delay": 0.5})
    monkeypatch.setattr(session_runner, "build_session_context", lambda _w: ctx)

    region = page.screen.add_session_from_context_menu()
    region._scheduler = page._scheduler_for(region._pier_name)
    region.insert_block(sessions.ImageBlock(exposure=5.0, count=20))

    page._controller.start_region(region)
    page._controller.stop(region)
    _wait(page._controller)

    assert region in page.screen.visible_sessions
    assert region.is_scheduled is False and region.is_editable
