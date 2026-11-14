# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""CSURF-350 — ``flip.defer``: hold a pending meridian flip back for a few minutes, never past the mount's limits."""

import pytest

from galileo.control_surface import Registry
from galileo.control_surface.flips import register_flip_operations
from galileo.engine.flips import EngineFlips
from galileo.mount_limits import (
    DEFER_MAX_MINUTES,
    FlipDeferrals,
    MountLimits,
    defer_refusal,
    deferrals,
    evaluate,
)
from tests.test_csurf_catalogue import _Devices, _FlipMount, _Runner


class _Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.mark.requirement("TC-CSURF-350")
@pytest.mark.priority("P2")
async def test_tc_csurf_350_a_pending_flip_can_be_deferred_and_status_says_until_when(settings_db):
    """CSURF-350: flip.defer is an operate-class operation that needs the lease; it holds back a flip that is due or
    imminent, answers with when the deferral ends, and flip.status then reports ``deferred`` and ``deferred_until``."""
    from galileo.observatory import create_observatory, create_pier, save_device_config

    pier = create_pier(create_observatory("Home", latitude=45.0, longitude=-75.0), "Pier 1")
    devices, runner = _Devices(pier), _Runner()
    devices.mount = mount = _FlipMount(ra_hours=11.9)          # LST 12: hour angle +0.1 h, a few minutes from the limit
    registry = Registry()
    register_flip_operations(registry, EngineFlips(devices, runner))
    spec = {o["name"]: o for o in registry.catalogue("p1")["operations"]}["flip.defer"]
    assert spec["class"] == "operate" and spec["needs_lease"]
    try:
        save_device_config(pier, "mount", "d", "s", 1, mount_limits=MountLimits(flip_enabled=True, flip_ha_deg=5.0))
        before = (await registry.invoke("flip.status", {}, "p1", "c1")).value
        assert before["deferred"] is False and before["deferred_until"] is None

        done = await registry.invoke("flip.defer", {}, "p1", "c1")
        assert done.ok and done.value["deferred"] and done.value["minutes"] == pytest.approx(10.0, abs=0.2)
        state = (await registry.invoke("flip.status", {}, "p1", "c1")).value
        assert state["deferred"] is True and state["deferred_until"] == pytest.approx(done.value["deferred_until"])
        again = await registry.invoke("flip.defer", {"minutes": 99}, "p1", "c1")
        assert not again.ok or again.value["minutes"] <= DEFER_MAX_MINUTES        # at most half an hour at a time
    finally:
        deferrals.clear(mount)


@pytest.mark.requirement("TC-CSURF-350")
@pytest.mark.priority("P2")
async def test_tc_csurf_350_defer_is_refused_in_words_when_there_is_no_flip_to_hold_back(settings_db):
    """CSURF-350: deferring is refused when flips are off, when the flip is still far away, from the east side, while a
    session runs, with no mount, and once the mount is too far past the limit or too close to its hour-angle limit."""
    from galileo.observatory import create_observatory, create_pier, save_device_config

    pier = create_pier(create_observatory("Home", latitude=45.0, longitude=-75.0), "Pier 1")
    devices, runner = _Devices(pier), _Runner()
    devices.mount = mount = _FlipMount(ra_hours=12.5)          # hour angle -0.5 h: about 50 minutes to the limit
    registry = Registry()
    register_flip_operations(registry, EngineFlips(devices, runner))
    try:
        assert "off" in (await registry.invoke("flip.defer", {}, "p1", "c1")).reason           # flips not requested
        save_device_config(pier, "mount", "d", "s", 1, mount_limits=MountLimits(flip_enabled=True, flip_ha_deg=5.0))
        assert "minutes away" in (await registry.invoke("flip.defer", {}, "p1", "c1")).reason

        mount.ra, mount.side = 11.9, "East"
        assert "west side" in (await registry.invoke("flip.defer", {}, "p1", "c1")).reason
        mount.side = "West"
        runner.running = True
        assert "Meridian Flip block" in (await registry.invoke("flip.defer", {}, "p1", "c1")).reason
        runner.running = False

        mount.ra = 10.5                                         # 1.5 h past the meridian: 70 minutes past the limit
        assert "past the flip limit" in (await registry.invoke("flip.defer", {}, "p1", "c1")).reason
        save_device_config(pier, "mount", "d", "s", 1, mount_limits=MountLimits(
            flip_enabled=True, flip_ha_deg=5.0, ha_limits_enabled=True, max_ha_hours=1.6))
        mount.ra = 10.45
        assert (await registry.invoke("flip.defer", {}, "p1", "c1")).reason                    # refused either way
        devices.mount = None
        assert "no mount" in (await registry.invoke("flip.defer", {}, "p1", "c1")).reason
    finally:
        deferrals.clear(mount)


@pytest.mark.requirement("TC-CSURF-350")
@pytest.mark.priority("P2")
def test_tc_csurf_350_a_deferred_flip_still_happens_before_the_limits_and_never_silences_one():
    """CSURF-350: while deferred the monitor holds the flip back, but a limit still stops the mount; the deferral ends
    when its time is up and early near the hour-angle limit, and then the flip goes ahead."""
    clock, mount = _Clock(), object()
    held = FlipDeferrals(clock)
    limits = MountLimits(flip_enabled=True, flip_ha_deg=5.0, ha_limits_enabled=True, max_ha_hours=2.0)
    due = {"alt_deg": 40.0, "side_of_pier": "West", "tracking": True, "slewing": False}

    held.defer(mount, 10)
    assert held.active(mount, limits, 0.5) is not None
    assert evaluate(limits, ha_hours=0.5, flip_deferred=True, **due).flip is False         # held back
    assert evaluate(limits, ha_hours=0.5, flip_deferred=False, **due).flip is True         # the unchanged default
    stop = evaluate(limits, ha_hours=2.5, flip_deferred=True, **due)
    assert stop.stop and not stop.flip                                                     # a limit is still a stop

    assert held.active(mount, limits, 1.8) is None, "within the margin of the hour-angle limit the deferral is over"
    held.defer(mount, 10)
    clock.now += 11 * 60
    assert held.active(mount, limits, 0.5) is None, "the deferral ran out"
    assert evaluate(limits, ha_hours=0.5, flip_deferred=False, **due).flip is True         # so the flip happens

    assert defer_refusal(limits, 0.5, "West") is None
    assert "past the flip limit" in defer_refusal(limits, 1.4, "West")
    assert held.defer(mount, 500) - clock.now == pytest.approx(DEFER_MAX_MINUTES * 60)
