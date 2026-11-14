# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""CSURF-360 — ``session.skip``: skip the block a running session is on and carry on with the next, driven through the
real executor (with the fakes ``test_ses_exec`` uses), the real runner and the real registry."""

import asyncio
import time

import pytest

from galileo.control_surface import Registry
from galileo.control_surface.sessions import RunnerSessions, register_session_operations
from galileo.engine.runner import SessionRunner
from galileo.session_exec import RunState, SessionExecutor, SkipRefused

sessions = pytest.importorskip("galileo.ui.sessions")
from tests.test_ses_exec import make_context


async def _until(condition, seconds=3.0):
    end = time.monotonic() + seconds
    while not condition() and time.monotonic() < end:  # noqa: ASYNC110 -- polling a condition set by another task or thread
        await asyncio.sleep(0.01)
    assert condition()


@pytest.mark.requirement("TC-CSURF-360")
@pytest.mark.priority("P2")
async def test_tc_csurf_360_skip_ends_the_block_in_flight_and_the_run_carries_on():
    """CSURF-360: skipping a running session ends the block it is on (the next frame is not taken, as the loop
    checks between frames) and runs the next block; the run completes and says which block was skipped."""
    frames: list = []
    ctx, _ = make_context(frames, imaging={"delay": 0.4})
    executor = SessionExecutor(ctx, name="skip")
    blocks = [sessions.ImageBlock(exposure=1.0, count=5), sessions.ImageBlock(exposure=2.0, count=1)]
    task = asyncio.create_task(executor.run(blocks))
    await _until(lambda: frames == [] and executor._current_index == 1 and executor.state == RunState.RUNNING)
    await asyncio.sleep(0.05)
    label = executor.skip()
    assert label
    result = await task

    assert result.state == RunState.COMPLETED
    durations = [f[1] for f in frames]
    assert durations.count(1.0) == 1 and durations[-1] == 2.0, "one frame was in flight; the other four were skipped"
    assert any("Skipped" in line for line in result.log)


@pytest.mark.requirement("TC-CSURF-360")
@pytest.mark.priority("P2")
async def test_tc_csurf_360_skip_while_paused_skips_the_next_block_and_idle_or_shutdown_blocks_refuse():
    """CSURF-360: a skip asked while the session is paused takes the next block once it resumes; there is nothing to
    skip when no session runs; and a shutdown block (park, dome close, ...) is never skipped."""
    ctx, _ = make_context([])
    idle = SessionExecutor(ctx, name="idle")
    with pytest.raises(SkipRefused, match="no session is running"):
        idle.skip()

    frames: list = []
    ctx, _ = make_context(frames, imaging={"delay": 0.05})
    executor = SessionExecutor(ctx, name="paused")
    task = asyncio.create_task(executor.run([sessions.ImageBlock(exposure=1.0, count=1),
                                             sessions.ImageBlock(exposure=2.0, count=1),
                                             sessions.ImageBlock(exposure=3.0, count=1)]))
    await _until(lambda: executor.state == RunState.RUNNING and executor._current_index >= 1)
    executor.pause()
    await _until(lambda: executor.state == RunState.PAUSED and len(frames) == 1)   # block 1 done; held before block 2
    await asyncio.sleep(0.15)
    executor.skip()
    executor.resume()
    result = await task
    assert result.state == RunState.COMPLETED
    assert [f[1] for f in frames] == [1.0, 3.0], "the block after the pause was skipped, the one after it ran"
    assert any("Skipped block 2" in line for line in result.log)

    parked = SessionExecutor(make_context([])[0], name="park")
    parked.state, parked._current_block = RunState.RUNNING, sessions.ParkMountBlock()
    with pytest.raises(SkipRefused, match="safe state"):
        parked.skip()


@pytest.mark.requirement("TC-CSURF-360")
@pytest.mark.priority("P2")
async def test_tc_csurf_360_the_operation_needs_the_lease_names_the_block_and_is_refused_when_idle():
    """CSURF-360: ``session.skip`` is an operate-class operation that needs the lease, is available only while a session
    runs on the Pier, returns the block it skipped, and refuses in words when nothing runs or the block must not go."""
    runner = SessionRunner()
    registry = Registry()
    register_session_operations(registry, RunnerSessions(runner))
    spec = {o["name"]: o for o in registry.catalogue("p1")["operations"]}["session.skip"]
    assert spec["class"] == "operate" and spec["needs_lease"]
    assert spec["available"] is False and "no session" in spec["reason"]
    assert "no session" in (await registry.invoke("session.skip", {}, "p1", "c1")).reason

    frames: list = []
    ctx, _ = make_context(frames, imaging={"delay": 0.3})
    executor = SessionExecutor(ctx, name="op")
    runner.start("p1", "op", executor, [sessions.ImageBlock(exposure=1.0, count=4), sessions.ImageBlock(exposure=2.0, count=1)])
    try:
        await _until(lambda: runner.is_running("p1") and executor._current_index == 1)
        await asyncio.sleep(0.05)
        done = await registry.invoke("session.skip", {}, "p1", "c1")
        assert done.ok and done.value["skipped"]
        await _until(lambda: not runner.is_running("p1"), seconds=5)
    finally:
        runner.shutdown(5)
    assert [f[1] for f in frames].count(2.0) == 1 and [f[1] for f in frames].count(1.0) < 4
