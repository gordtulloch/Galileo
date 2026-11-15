# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""CSURF-330 — held mount jog, and the held focus operations, are real on a running engine (TC-CSURF-330)."""

import asyncio
from unittest.mock import MagicMock

import pytest

from galileo.control_surface import HoldManager, Registry
from galileo.control_surface.catalogue import register_device_operations
from galileo.control_surface.mounthold import DEFAULT_JOG_RATE_DEG_S, axis_command, axis_commands, register_mount_hold_operations
from galileo.exceptions import MountParkedError


class JogMount:
    is_connected = True

    def __init__(self):
        self.axes, self.parked = [], False

    async def move_axis(self, axis, rate):
        if rate and self.parked:
            raise MountParkedError("the mount is parked")
        self.axes.append((axis, rate))


class StaticMount:
    """An adapter with no jog primitive."""
    is_connected = True


class Access:
    def __init__(self, mount):
        self.mount = mount

    def controller(self, pier, category):
        return self.mount if (pier == "p1" and category == "mount") else None

    def manual_focus(self, pier):
        return None

    def stop_session(self, pier):
        return None


def rig(mount):
    registry, holds = Registry(), HoldManager()
    access = Access(mount)
    register_device_operations(registry, access, holds)
    register_mount_hold_operations(registry, access, holds)
    return registry, holds


@pytest.mark.requirement("TC-CSURF-330")
@pytest.mark.priority("MVP")
def test_tc_csurf_330_directions_drive_the_axes_the_desktop_pad_drives():
    """CSURF-330: north and south move the Dec axis, east and west the RA axis, north and east positively."""
    rate = DEFAULT_JOG_RATE_DEG_S
    assert axis_command("north") == (1, rate) and axis_command("south") == (1, -rate)
    assert axis_command("east") == (0, rate) and axis_command("west") == (0, -rate)
    with pytest.raises(ValueError):
        axis_command("up")
    pytest.importorskip("PySide6")
    from galileo.ui.imaging import nudge_command
    for name, letter in (("north", "N"), ("south", "S"), ("east", "E"), ("west", "W")):
        axis, signed = nudge_command(letter, rate)
        assert axis_command(name, rate) == (axis, signed)


@pytest.mark.requirement("TC-CSURF-330")
@pytest.mark.priority("MVP")
def test_tc_csurf_330_a_diagonal_drives_both_axes():
    """CSURF-330: northeast, northwest, southeast and southwest drive the Dec and RA axes together."""
    rate = DEFAULT_JOG_RATE_DEG_S
    assert axis_commands("north", rate) == [(1, rate)]
    assert axis_commands("northeast", rate) == [(1, rate), (0, rate)]
    assert axis_commands("northwest", rate) == [(1, rate), (0, -rate)]
    assert axis_commands("southeast", rate) == [(1, -rate), (0, rate)]
    assert axis_commands("southwest", rate) == [(1, -rate), (0, -rate)]
    with pytest.raises(ValueError):
        axis_commands("up")


@pytest.mark.requirement("TC-CSURF-330")
@pytest.mark.priority("MVP")
async def test_tc_csurf_330_a_held_jog_moves_while_beaten_and_stops_on_release_or_silence():
    """CSURF-330: hold_start moves the axis, a beat keeps it going, no beat stops it by the deadman, and hold_stop
    stops it at once."""
    mount = JogMount()
    registry, holds = rig(mount)
    started = await registry.invoke("mount.hold_start", {"direction": "east"}, "p1", "c1")
    assert started.ok and mount.axes == [(0, DEFAULT_JOG_RATE_DEG_S)]
    hold_id = started.value
    assert (await registry.invoke("mount.hold_beat", {"hold_id": hold_id}, "p1", "c1")).value is True
    assert (await registry.invoke("mount.hold_beat", {"hold_id": hold_id}, "p1", "someone-else")).value is False
    # silence: the watchdog's check ends it
    holds._holds[hold_id].last_beat -= holds.deadman_s + 0.1
    assert holds.check() == 1
    await asyncio.sleep(0.05)
    assert mount.axes[-1] == (0, 0.0) and holds.active("p1") == []
    # release: hold_stop
    again = await registry.invoke("mount.hold_start", {"direction": "north"}, "p1", "c1")
    assert again.ok and mount.axes[-1] == (1, DEFAULT_JOG_RATE_DEG_S)
    assert (await registry.invoke("mount.hold_stop", {"hold_id": again.value}, "p1", "c1")).value is True
    await asyncio.sleep(0.05)
    assert mount.axes[-1] == (1, 0.0) and holds.active("p1") == []


@pytest.mark.requirement("TC-CSURF-330")
@pytest.mark.priority("MVP")
async def test_tc_csurf_330_refusals_are_typed_and_leave_no_hold():
    """CSURF-330: a parked mount, a mount with no jog and a second hold on the Pier are refused with a reason, and
    a refused press leaves nothing to keep alive."""
    mount = JogMount()
    registry, holds = rig(mount)
    mount.parked = True
    refused = await registry.invoke("mount.hold_start", {"direction": "west"}, "p1", "c1")
    assert refused.status == "refused" and "parked" in refused.reason and holds.active("p1") == []
    mount.parked = False
    first = await registry.invoke("mount.hold_start", {"direction": "west"}, "p1", "c1")
    assert first.ok
    second = await registry.invoke("mount.hold_start", {"direction": "east"}, "p1", "c2")
    assert second.status == "refused" and "already" in second.reason
    holds.cancel_all("test")
    await asyncio.sleep(0.05)
    registry2, holds2 = rig(StaticMount())
    nojog = await registry2.invoke("mount.hold_start", {"direction": "north"}, "p1", "c1")
    assert nojog.status == "refused" and "no manual motion" in nojog.reason and holds2.active("p1") == []
    assert (await registry.invoke("mount.hold_start", {"direction": "north"}, "p2", "c1")).status == "unavailable"


@pytest.mark.requirement("TC-CSURF-330")
@pytest.mark.priority("MVP")
async def test_tc_csurf_330_the_lease_changing_hands_stops_the_jog():
    """CSURF-330 / LEASE-080: the hold manager's lease listener ends a jog when its holder loses the lease."""
    mount = JogMount()
    registry, holds = rig(mount)
    assert (await registry.invoke("mount.hold_start", {"direction": "south"}, "p1", "c1")).ok
    holds.on_lease_changed("p1", "c1", "c2", "taken")
    await asyncio.sleep(0.05)
    assert mount.axes[-1] == (1, 0.0) and holds.active("p1") == []


@pytest.mark.requirement("TC-CSURF-330")
@pytest.mark.priority("MVP")
def test_tc_csurf_330_a_running_engine_offers_the_held_operations(settings_db):
    """CSURF-330: the engine's real registry contains mount.hold_* and focus.hold_*, runs the deadman watchdog, and
    stops it again with the engine."""
    from galileo.engine.devices import DeviceService
    from galileo.engine.main import Engine
    engine = Engine(MagicMock(), embedded=True, devices=DeviceService())
    try:
        engine._start_devices()
        names = set(engine.registry.names())
        assert {"mount.hold_start", "mount.hold_beat", "mount.hold_stop",
                "focus.hold_start", "focus.hold_beat", "focus.hold_stop"} <= names
        assert engine.holds is not None and engine.holds.active() == []
        import time
        for _ in range(50):                                   # the watchdog task is started on the channel loop
            if engine._holds_task is not None:
                break
            time.sleep(0.05)
        assert engine._holds_task is not None and not engine._holds_task.done()
    finally:
        engine._stop_devices()
    assert engine._holds_task is None
