# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""CSURF-340 — autofocus on the Control Surface: ``focus.autofocus`` and ``focus.autofocus_cancel``."""

import asyncio
from types import SimpleNamespace

import pytest

from galileo.autofocus import AutofocusResult
from galileo.bus import EventBus, FocusCompleteEvent, FocusFrameEvent, FocusStartedEvent
from galileo.control_surface import ObservableState, Registry
from galileo.control_surface.autofocus import STATE_KEY, register_autofocus_operations
from galileo.engine.autofocus import EngineAutofocus

KEY = 7


class FakeAutofocus:
    """Stands in for ``ConfiguredAutofocus``: publishes the events the real service does, as it goes."""

    def __init__(self, bus, gate=None, fail=False):
        self.bus, self.gate, self.fail = bus, gate, fail
        self.cancelled = False
        self.positions = [4800, 5000, 5200]

    def cancel(self):
        self.cancelled = True

    async def run(self):
        self.bus.publish(FocusStartedEvent(source="autofocus", positions=self.positions, initial_position=5000,
                                           step_size=200, num_points=3, pier_key=KEY))
        hfrs = []
        for pos, hfr in zip(self.positions, (3.0, 2.0, 3.0), strict=True):
            if self.gate is not None:
                await self.gate.wait()
            hfrs.append(hfr)
            self.bus.publish(FocusFrameEvent(source="autofocus", position=pos, hfr=hfr, fwhm=hfr * 2, star_count=20,
                                             confirm=False, pier_key=KEY))
            if self.cancelled:
                result = AutofocusResult(False, failure_reason="Cancelled",
                                         sample_points=list(zip(self.positions, hfrs, strict=False)))
                self.bus.publish(FocusCompleteEvent(source="autofocus", result=result, pier_key=KEY))
                return result
        if self.fail:
            result = AutofocusResult(False, failure_reason="No valid HFR measurements — check camera/stars")
        else:
            self.bus.publish(FocusFrameEvent(source="autofocus", position=5000, hfr=1.5, fwhm=3.0, star_count=22,
                                             confirm=True, pier_key=KEY))
            result = AutofocusResult(True, best_position=5000, sample_points=list(zip(self.positions, hfrs, strict=True)))
        self.bus.publish(FocusCompleteEvent(source="autofocus", result=result, pier_key=KEY))
        return result


def _devices(**parts):
    parts = {"camera": SimpleNamespace(is_connected=True), "focuser": SimpleNamespace(is_connected=True), **parts}
    return SimpleNamespace(controller=lambda pier, cat, slot="primary": parts.get(cat))


def _build(devices=None, *, running=False, busy=False, gate=None, fail=False):
    bus, state, made = EventBus(), ObservableState(), []
    registry = Registry(bus)

    async def factory(pier):
        made.append(FakeAutofocus(bus, gate, fail))
        return made[0]

    runner = SimpleNamespace(is_running=lambda pier: running)
    af = EngineAutofocus(devices or _devices(), runner, state, factory=factory, busy=lambda pier: busy, bus=bus,
                         key_of=lambda pier: KEY)
    register_autofocus_operations(registry, af)
    return registry, state, made, af


@pytest.mark.requirement("TC-CSURF-340")
@pytest.mark.priority("MVP")
async def test_tc_csurf_340_autofocus_runs_and_reports_the_best_position():
    """CSURF-340: focus.autofocus sweeps, reports each measured point as state focus.autofocus, and ends with the best
    position; the catalogue lists both operations with the right class, lease and long-running flags."""
    registry, state, _, _ = _build()
    cat = {o["name"]: o for o in registry.catalogue("p1")["operations"]}
    assert cat["focus.autofocus"]["long_running"] and cat["focus.autofocus"]["needs_lease"]
    assert cat["focus.autofocus_cancel"]["needs_lease"] and not cat["focus.autofocus_cancel"]["long_running"]
    assert cat["focus.autofocus"]["class"] == cat["focus.autofocus_cancel"]["class"] == "operate"

    assert (await registry.invoke("focus.autofocus", {}, "p1", "web")).ok
    await registry.wait_idle()
    picture = state.read("p1", STATE_KEY)
    assert picture["running"] is False and picture["phase"] == "finished" and picture["success"] is True
    assert picture["best_position"] == 5000 and picture["cancelled"] is False and picture["failure_reason"] == ""
    assert picture["points"] == [[4800, 3.0], [5000, 2.0], [5200, 3.0]] and picture["steps"] == 3
    assert picture["message"] == "Best focus at 5000"


@pytest.mark.requirement("TC-CSURF-340")
@pytest.mark.priority("MVP")
async def test_tc_csurf_340_progress_is_live_and_a_second_start_is_refused():
    """CSURF-340: the picture is published point by point while the run is under way, a second start on the same Pier
    is refused, and the run's live status says so."""
    gate = asyncio.Event()
    registry, state, _, af = _build(gate=gate)
    assert (await registry.invoke("focus.autofocus", {}, "p1", "web")).ok
    for _ in range(100):
        await asyncio.sleep(0.01)
        picture = state.read("p1", STATE_KEY) or {}
        if picture.get("steps") == 3:
            break
    assert picture["running"] is True and picture["phase"] == "sweeping" and picture["points"] == []
    second = await registry.invoke("focus.autofocus", {}, "p1", "web")          # the first is held at its first exposure
    assert second.status == "unavailable" and "already running" in second.reason
    assert af.status("p1")["running"] is True and "already running" in af.status("p1")["why_not"]
    gate.set()
    await registry.wait_idle()
    done = state.read("p1", STATE_KEY)
    assert done["running"] is False and len(done["points"]) == 3 and af.status("p1")["running"] is False


@pytest.mark.requirement("TC-CSURF-340")
@pytest.mark.priority("MVP")
async def test_tc_csurf_340_cancel_stops_the_run():
    """CSURF-340: focus.autofocus_cancel asks the running service to stop; the run ends as Cancelled with the points
    measured so far, and cancel with nothing running is refused."""
    gate = asyncio.Event()
    registry, state, made, af = _build(gate=gate)
    assert (await registry.invoke("focus.autofocus_cancel", {}, "p1", "web")).status == "refused"
    assert (await registry.invoke("focus.autofocus", {}, "p1", "web")).ok
    for _ in range(100):
        await asyncio.sleep(0.01)
        if af.running("p1") and made:
            break
    assert (await registry.invoke("focus.autofocus_cancel", {}, "p1", "web")).ok and made[0].cancelled
    gate.set()
    await registry.wait_idle()
    picture = state.read("p1", STATE_KEY)
    assert picture["running"] is False and picture["cancelled"] is True and picture["success"] is False
    assert picture["failure_reason"] == "Cancelled" and picture["best_position"] is None
    assert picture["message"] == "Cancelled" and len(picture["points"]) >= 1


@pytest.mark.requirement("TC-CSURF-340")
@pytest.mark.priority("MVP")
async def test_tc_csurf_340_a_failed_sweep_reports_its_reason():
    """CSURF-340: a sweep that finds no usable stars ends unsuccessfully with the reason in the state and the result."""
    registry, state, _, _ = _build(fail=True)
    outcome = await registry.invoke("focus.autofocus", {}, "p1", "web")
    assert outcome.ok
    await registry.wait_idle()
    picture = state.read("p1", STATE_KEY)
    assert picture["success"] is False and picture["best_position"] is None
    assert picture["failure_reason"].startswith("No valid HFR measurements")


@pytest.mark.requirement("TC-CSURF-340")
@pytest.mark.priority("MVP")
async def test_tc_csurf_340_refusals():
    """CSURF-340: no camera, no focuser, a disconnected device, a running session, or a plate solve or polar run
    using the camera is refused with a reason before anything moves."""
    for devices, kwargs, words in (
        (_devices(camera=None), {}, "no camera"),
        (_devices(focuser=None), {}, "no focuser"),
        (_devices(camera=SimpleNamespace(is_connected=False)), {}, "camera is not connected"),
        (_devices(focuser=SimpleNamespace(is_connected=False)), {}, "focuser is not connected"),
        (None, {"running": True}, "session is running"),
        (None, {"busy": True}, "plate solve or polar"),
    ):
        registry, state, made, _ = _build(devices, **kwargs)
        outcome = await registry.invoke("focus.autofocus", {}, "p1", "web")
        assert outcome.status == "unavailable" and words in outcome.reason, (words, outcome)
        assert not made and state.read("p1", STATE_KEY) is None
