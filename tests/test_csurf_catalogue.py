# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""CSURF — the device, focus and safety catalogue (TC-CSURF-110, 150, 220, 300) driven through the real registry
and, where the lease and confirmation matter, the real gateway."""

import asyncio

import pytest

from galileo.autofocus import ManualFocus
from galileo.bus import EventBus
from galileo.connect_link import AuditLog
from galileo.connect_link.gateway import Gateway, GatewayRequest
from galileo.control_surface import HoldManager, LeaseBroker, OperationFinished, Registry
from galileo.control_surface.catalogue import register_device_operations
from galileo.exceptions import DeviceConnectionError, MountLimitError, MountParkedError


class Mount:
    is_connected = True

    def __init__(self):
        self.calls, self.fail = [], None

    def get_status(self):
        return {"ra": 10.0, "dec": 20.0, "is_tracking": True, "is_slewing": False}

    async def slew_to_coordinates(self, ra, dec):
        if self.fail:
            raise self.fail
        self.calls.append(("slew", ra, dec))

    async def sync_to_coordinates(self, ra, dec):
        self.calls.append(("sync", ra, dec))

    async def set_tracking(self, enabled):
        self.calls.append(("track", enabled))

    async def abort_slew(self):
        self.calls.append(("abort",))

    async def park(self):
        self.calls.append(("park",))

    async def unpark(self):
        self.calls.append(("unpark",))


class Camera:
    is_connected = True

    def __init__(self):
        self.calls = []

    async def start_exposure(self, duration, gain, offset, binning, frame_type):
        self.calls.append((duration, gain, offset, binning, frame_type))
        await asyncio.sleep(0)

    async def abort_exposure(self):
        self.calls.append("abort")

    async def set_target_temperature(self, c):
        self.calls.append(("cool", c))

    def get_temperature(self):
        return -10.0

    def get_cooler_power(self):
        return 55.0


class Dome:
    is_connected = True

    def __init__(self):
        self.calls = []

    async def close_shutter(self):
        self.calls.append("close")

    async def abort_slew(self):
        self.calls.append("abort")

    def get_status(self):
        return {"azimuth": 90.0, "shutter_state": "open", "is_at_park": False}


class Safety:
    is_connected = True
    is_safe = False
    explanation = "Rain detected"
    last_abort_trigger = "rain"


class Focuser:
    def __init__(self):
        self.position, self.max_step, self.temperature, self.moves = 5000, 8000, 3.5, []

    async def move_to(self, position):
        self.moves.append(position)
        self.position = position


class Access:
    def __init__(self):
        self.mount, self.camera, self.dome, self.safety = Mount(), Camera(), Dome(), Safety()
        self.focuser = Focuser()
        self.stopped = []

    def controller(self, pier, category):
        if pier != "p1":
            return None
        return {"mount": self.mount, "camera": self.camera, "dome": self.dome, "safety": self.safety}.get(category)

    def manual_focus(self, pier):
        return ManualFocus(self.focuser, pier_key=pier) if pier == "p1" else None

    async def stop_session(self, pier):
        self.stopped.append(pier)


@pytest.fixture
def rig(settings_db):
    bus = EventBus()
    registry, access, holds = Registry(bus), Access(), HoldManager()
    register_device_operations(registry, access, holds)
    clock = [1_000_000.0]
    leases = LeaseBroker(lambda: clock[0], bus=bus)
    gateway = Gateway(registry, leases, AuditLog(lambda: clock[0]), clock=lambda: clock[0])
    return registry, access, holds, leases, gateway, bus


def req(name, pier="p1", args=None, perms=("control",), **kw):
    return GatewayRequest(client_id="c1", name=name, pier=pier, args=args or {}, plugin="webconnect",
                          permissions=frozenset(perms), **kw)


@pytest.mark.requirement("TC-CSURF-110")
@pytest.mark.priority("MVP")
def test_tc_csurf_110_the_catalogue_lists_device_operations_and_says_what_each_pier_lacks(rig):
    """CSURF-110 / CSURF-030: the catalogue offers the device operations with their schemas, class and lease
    need, and says per Pier why one is unavailable; nothing in it edits a stored definition."""
    registry, *_ = rig
    cat = {o["name"]: o for o in registry.catalogue("p1")["operations"]}
    for name in ("mount.slew", "mount.sync", "mount.track", "mount.park", "camera.expose", "camera.set_temperature",
                 "dome.open", "dome.close", "filter.select", "rotator.move", "flatpanel.light", "focus.move_to"):
        assert name in cat, name
    assert cat["mount.slew"]["needs_lease"] and cat["mount.slew"]["long_running"]
    assert cat["mount.park"]["class"] == "confirm" and cat["mount.status"]["class"] == "read"
    assert not cat["mount.status"]["needs_lease"] and cat["mount.slew"]["args"][0]["max"] == 360
    assert cat["mount.slew"]["available"] and not cat["rotator.move"]["available"]
    assert cat["rotator.move"]["reason"] == "this Pier has no rotator"
    other = {o["name"]: o for o in registry.catalogue("p2")["operations"]}
    assert other["mount.slew"]["reason"] == "this Pier has no mount" and other["focus.move_to"]["reason"]
    assert {o["class"] for o in cat.values()} <= {"read", "operate", "confirm", "emergency"}
    assert not any(n.startswith(("focuser.", "profile.", "equipment.", "options.")) for n in cat)


@pytest.mark.requirement("TC-CSURF-110")
@pytest.mark.priority("MVP")
async def test_tc_csurf_110_operations_call_the_same_controller_and_return_the_device_layers_own_refusals(rig):
    """CSURF-110 / CSURF-050: a slew reaches the mount controller in degrees; a parked mount, an obstructed
    or over-limit slew come back as refused with the device layer's own words; a lost connection is
    unreachable."""
    registry, access, *_ = rig
    out = await registry.invoke("mount.slew", {"ra_deg": 83.8, "dec_deg": -5.4}, "p1", "c1")
    assert out.ok and out.correlation_id
    await registry.wait_idle()
    assert access.mount.calls == [("slew", 83.8, -5.4)]
    access.mount.fail = MountParkedError("The mount is parked, so slew_to_coordinates was not sent — unpark it first.")
    await registry.invoke("mount.slew", {"ra_deg": 1, "dec_deg": 1}, "p1", "c1")
    await registry.wait_idle()
    access.mount.fail = MountLimitError("Below the altitude limit of 20°")
    finished = []
    registry._bus.subscribe(OperationFinished, lambda e: finished.append((e.outcome, e.reason)))
    await registry.invoke("mount.slew", {"ra_deg": 1, "dec_deg": 1}, "p1", "c1")
    await registry.wait_idle()
    assert finished == [("refused", "Below the altitude limit of 20°")]
    out = await registry.invoke("mount.sync", {"ra_deg": 400, "dec_deg": 0}, "p1", "c1")
    assert out.status == "invalid" and out.path == "ra_deg"
    access.mount.fail = None
    assert (await registry.invoke("mount.status", {}, "p1", "c1")).value["is_tracking"] is True
    assert (await registry.invoke("mount.track", {"enabled": False}, "p1", "c1")).ok
    assert access.mount.calls[-1] == ("track", False)

    async def drop(*a):
        raise DeviceConnectionError("INDI server went away")

    access.mount.sync_to_coordinates = drop
    out = await registry.invoke("mount.sync", {"ra_deg": 1, "dec_deg": 1}, "p1", "c1")
    assert (out.status, out.reason) == ("unreachable", "INDI server went away")


@pytest.mark.requirement("TC-CSURF-110")
@pytest.mark.priority("MVP")
async def test_tc_csurf_110_exposures_are_long_running_and_the_lease_and_confirmation_apply(rig):
    """CSURF-110 / LEASE-060 / LINK-230: an exposure announces started and finished with a correlation id;
    through the gateway an operation needs the lease; parking needs a second confirmation."""
    registry, access, _, leases, gateway, bus = rig
    events = []
    bus.subscribe(OperationFinished, lambda e: events.append(e.operation))
    refused = await gateway.handle(req("camera.expose", args={"seconds": 2}))
    assert refused.status == "refused" and "lease" in refused.reason and access.camera.calls == []
    leases.acquire("p1", "webconnect:c1")
    out = await gateway.handle(req("camera.expose", args={"seconds": 2, "gain": 120}))
    assert out.ok and out.correlation_id
    await registry.wait_idle()
    assert access.camera.calls == [(2.0, 120, 0, 1, "Light")] and events == ["camera.expose"]
    first = await gateway.handle(req("mount.park"))
    assert first.status == "refused" and first.confirm_token and ("park",) not in access.mount.calls
    assert (await gateway.handle(req("mount.park", confirm_token=first.confirm_token))).ok
    assert access.mount.calls[-1] == ("park",)
    assert (await gateway.handle(req("camera.status", perms=("view",)))).value == {"temperature": -10.0, "cooler_power": 55.0}


@pytest.mark.requirement("TC-CSURF-150")
@pytest.mark.priority("MVP")
async def test_tc_csurf_150_focus_uses_the_modules_manual_focus_and_its_limits_and_held_moves(rig):
    """CSURF-150 / FOC-120 / FOC-130: manual focus is offered as focus.* from the module's ManualFocus with
    its limits; a held move starts, is kept alive by beats and stops on request, through the registry."""
    registry, _, holds, *_ = rig
    assert (await registry.invoke("focus.move_to", {"position": 9500}, "p1", "c1")).value == 8000
    assert (await registry.invoke("focus.move_by", {"steps": -500}, "p1", "c1")).value == 7500
    assert (await registry.invoke("focus.status", {}, "p1", "c1")).value == {"position": 7500, "temperature": 3.5}
    started = await registry.invoke("focus.hold_start", {"direction": -1}, "p1", "c1")
    assert started.ok
    hold_id = started.value
    await asyncio.sleep(0)
    assert (await registry.invoke("focus.hold_beat", {"hold_id": hold_id}, "p1", "c1")).value is True
    assert (await registry.invoke("focus.hold_beat", {"hold_id": hold_id}, "p1", "someone-else")).value is False
    assert (await registry.invoke("focus.hold_stop", {"hold_id": hold_id}, "p1", "c1")).value is True
    assert holds.active("p1") == []
    assert (await registry.invoke("focus.move_to", {"position": 1}, "p2", "c1")).status == "unavailable"


@pytest.mark.requirement("TC-CSURF-220")
@pytest.mark.priority("MVP")
async def test_tc_csurf_220_safety_is_read_only(rig):
    """CSURF-220: a client can read the safety state and why a session stopped, and the catalogue offers no
    operation that clears an unsafe state, disables the monitor or overrides a limit."""
    registry, *_ = rig
    out = await registry.invoke("safety.status", {}, "p1", "c1")
    assert out.value == {"safe": False, "explanation": "Rain detected", "last_abort": "rain"}
    assert [n for n in registry.names() if n.startswith("safety.")] == ["safety.status"]
    assert not any(w in n for n in registry.names() for w in ("override", "disable", "clear", "bypass"))


@pytest.mark.requirement("TC-CSURF-300")
@pytest.mark.priority("MVP")
async def test_tc_csurf_300_emergency_operations_work_without_the_lease_and_survive_a_failing_device(rig):
    """CSURF-300: stop everything aborts mount, camera, dome, focuser and the session even when one device
    fails; park and close dome need no lease or second step; all are audited."""
    _, access, _, leases, gateway, _ = rig

    async def broken():
        raise RuntimeError("serial port gone")

    access.camera.abort_exposure = broken
    leases.acquire("p1", "desktop")
    out = await gateway.handle(req("system.stop_everything"))
    assert out.ok
    assert ("abort",) in access.mount.calls and access.dome.calls == ["abort"] and access.stopped == ["p1"]
    assert access.focuser.moves[-1] == access.focuser.position
    assert (await gateway.handle(req("mount.emergency_park"))).ok and access.mount.calls[-1] == ("park",)
    assert (await gateway.handle(req("dome.emergency_close"))).ok and access.dome.calls[-1] == "close"
    no_dome = await gateway.handle(req("dome.emergency_close", pier="p2"))
    assert no_dome.status in ("refused", "unavailable")
    rows = {(e.route, e.outcome) for e in gateway._audit.query()}
    assert ("op system.stop_everything", "ok") in rows and ("op mount.emergency_park", "ok") in rows
