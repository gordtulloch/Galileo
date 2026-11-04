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


class _FakeRunner:
    """Stands in for the engine's SessionRunner: one run on Pier p1."""

    def __init__(self):
        from galileo.engine.runner import RunSnapshot
        from galileo.session_exec import RunState, SessionProgress
        self.snap = RunSnapshot("p1", "M31 night", "running", SessionProgress(
            state=RunState.RUNNING, block_index=2, block_total=5, frames_done=10, frames_total=30, message="Imaging"))
        self.calls = []

    def snapshot(self):
        return [self.snap]

    def pause(self, pier):
        self.calls.append(("pause", pier))
        return pier == "p1"

    def resume(self, pier):
        self.calls.append(("resume", pier))
        return pier == "p1"

    def stop(self, pier):
        self.calls.append(("stop", pier))
        return pier == "p1"


@pytest.mark.requirement("TC-CSURF-180")
@pytest.mark.priority("MVP")
async def test_tc_csurf_180_running_sessions_can_be_read_paused_resumed_and_stopped():
    """CSURF-180: the catalogue offers the running session with its progress block by block, and pause, resume and
    stop through the same runner the desktop uses; with nothing running the controls are unavailable."""
    from galileo.control_surface.sessions import RunnerSessions, register_session_operations
    registry, runner = Registry(EventBus()), _FakeRunner()
    register_session_operations(registry, RunnerSessions(runner))
    status = await registry.invoke("session.status", {}, "p1", "c1")
    assert status.ok and status.value["name"] == "M31 night" and status.value["state"] == "running"
    assert (status.value["block_index"], status.value["block_total"], status.value["frames_done"]) == (2, 5, 10)
    for name in ("pause", "resume", "stop"):
        assert (await registry.invoke(f"session.{name}", {}, "p1", "c1")).ok
    assert [c[0] for c in runner.calls] == ["pause", "resume", "stop"]
    idle = await registry.invoke("session.status", {}, "p2", "c1")
    assert idle.ok and idle.value == {"state": "idle"}
    assert (await registry.invoke("session.stop", {}, "p2", "c1")).status == "unavailable"


class _Starter:
    """A SessionStarter: templates and a start that refuses what the engine would refuse."""

    def __init__(self):
        self.started = []

    def progress(self, pier):
        return None

    def pause(self, pier):
        return False

    resume = stop = pause

    def templates(self):
        return ["Deep sky", "Flats"]

    async def start(self, pier, template, target=None, camera_slot="primary"):
        from galileo.control_surface.sessions import SessionRefused
        if template not in self.templates():
            raise SessionRefused(f"There is no session template named {template!r}.")
        self.started.append((pier, template, target, camera_slot))


@pytest.mark.requirement("TC-CSURF-180")
@pytest.mark.priority("MVP")
async def test_tc_csurf_180_saved_templates_are_listed_and_started_with_a_target():
    """CSURF-180: the catalogue lists the saved templates and starts one with a target for its placeholder; a refusal
    by the session layer comes back as a refusal in its own words, and a half-given target is invalid."""
    from galileo.control_surface.sessions import register_session_operations
    registry, starter = Registry(EventBus()), _Starter()
    register_session_operations(registry, starter)
    assert (await registry.invoke("session.templates", {}, "p1", "c1")).value == {"templates": ["Deep sky", "Flats"]}
    ok = await registry.invoke("session.run", {"template": "Deep sky", "target_name": "M31", "ra_deg": 10.68,
                                               "dec_deg": 41.27}, "p1", "c1")
    assert ok.ok and starter.started == [("p1", "Deep sky", {"name": "M31", "ra_deg": 10.68, "dec_deg": 41.27}, "primary")]
    refused = await registry.invoke("session.run", {"template": "Nope"}, "p1", "c1")
    assert refused.status == "refused" and "no session template named 'Nope'" in refused.reason
    half = await registry.invoke("session.run", {"template": "Deep sky", "target_name": "M31"}, "p1", "c1")
    assert half.status == "refused" and len(starter.started) == 1


class _Mount:
    is_connected = True

    async def get_status(self):
        return {"right_ascension": 1.0, "declination": 20.0, "side_of_pier": "east"}


class _Devices:
    def __init__(self, pier, with_mount=True):
        self.pier, self.mount = pier, _Mount() if with_mount else None

    def pier_record(self, pier):
        return self.pier if pier == "p1" else None

    def controller(self, pier, category):
        return self.mount if category == "mount" else None

    def controllers(self, pier, category):
        return {}


class _Runner:
    def __init__(self):
        self.started, self.running = [], False

    def is_running(self, pier):
        return self.running

    def start(self, pier, name, executor, blocks, **kw):
        self.started.append((pier, name, executor, blocks, kw))


def _save_template(name, blocks):
    from galileo.library.models.session_template import SessionTemplateRecord
    from galileo.ui.session_blocks import block_to_dict
    SessionTemplateRecord.create(name=name, blocks_json=__import__("json").dumps([block_to_dict(b) for b in blocks]))


@pytest.mark.requirement("TC-CSURF-180")
@pytest.mark.priority("MVP")
async def test_tc_csurf_180_the_engine_starts_a_template_with_the_target_in_the_placeholder(settings_db):
    """CSURF-180: starting a template builds the Pier's context from the device service without Qt, puts the chosen
    target in place of the placeholder, checks it before anything moves, and hands it to the runner; a missing target,
    a missing device, a busy Pier and an unknown template are each refused in words."""

    from galileo.control_surface.sessions import SessionRefused
    from galileo.engine.sessions import EngineSessions
    from galileo.observatory import create_observatory, create_pier
    from galileo.ui.session_blocks import ParkMountBlock, TargetBlock

    pier = create_pier(create_observatory("Home", latitude=45.0, longitude=-75.0), "Pier 1")
    _save_template("Park after", [TargetBlock(name="", is_placeholder_target=True), ParkMountBlock()])
    runner, devices = _Runner(), _Devices(pier)
    sessions = EngineSessions(devices, runner)
    assert sessions.templates() == ["Park after"]

    await sessions.start("p1", "Park after", {"name": "M31", "ra_deg": 10.68, "dec_deg": 41.27})
    (_, name, executor, blocks, kw), = runner.started
    assert name == "Park after" and kw == {"manual": True}
    assert blocks[0].name == "M31" and blocks[0].ra_deg == 10.68 and not blocks[0].is_placeholder_target
    assert executor.context.mount is devices.mount and executor.context.pier_name == "Pier 1"

    with pytest.raises(SessionRefused, match="needs a target"):
        await sessions.start("p1", "Park after")
    with pytest.raises(SessionRefused, match="no session template"):
        await sessions.start("p1", "Missing")
    runner.running = True
    with pytest.raises(SessionRefused, match="already running"):
        await sessions.start("p1", "Park after", {"name": "M31", "ra_deg": 1, "dec_deg": 2})
    runner.running = False
    with pytest.raises(SessionRefused, match="No mount connected"):
        await EngineSessions(_Devices(pier, with_mount=False), runner).start(
            "p1", "Park after", {"name": "M31", "ra_deg": 1, "dec_deg": 2})
    assert len(runner.started) == 1


@pytest.mark.requirement("TC-CSURF-180")
@pytest.mark.priority("MVP")
def test_tc_csurf_180_the_engines_session_start_needs_no_qt():
    """CSURF-180 / HEAD-010: the modules that start a session on the engine load without Qt."""
    import subprocess
    import sys
    code = ("import sys; import galileo.engine.sessions, galileo.session_context; "
            "sys.exit(1 if any(m.startswith('PySide6') for m in sys.modules) else 0)")
    assert subprocess.run([sys.executable, "-c", code], check=False, timeout=120).returncode == 0  # noqa: S603 -- this interpreter on a fixed snippet


@pytest.mark.requirement("TC-CSURF-100")
@pytest.mark.priority("MVP")
async def test_tc_csurf_100_piers_are_listed_with_their_devices_and_running_session():
    """CSURF-100: a client can list the Piers a node runs, each with its Observatory, connected devices, devices that
    would not connect, and running session (idle when none), and needs no lease to do it."""
    from galileo.control_surface.piers import EnginePiers, register_pier_operations
    from galileo.control_surface.sessions import RunnerSessions

    class Devices:
        problems = {"2": ["camera"]}

        def pier_ids(self):
            return ["1", "2"]

        def pier_name(self, pier):
            return {"1": "North", "2": "South"}[pier]

        def pier_record(self, pier):
            from types import SimpleNamespace
            return SimpleNamespace(observatory=SimpleNamespace(name="Home"))

        def connected(self, pier):
            return ["mount/primary"] if pier == "1" else []

    runner = _FakeRunner()                                  # a run on Pier "p1" only; rename it for this test
    runner.snap.pier = "1"
    registry = Registry(EventBus())
    register_pier_operations(registry, EnginePiers(Devices(), RunnerSessions(runner)))
    out = await registry.invoke("pier.list", {}, "1", "c1")
    first, second = out.value["piers"]
    assert (first["id"], first["name"], first["observatory"], first["connected"]) == ("1", "North", "Home", ["mount/primary"])
    assert first["session"]["name"] == "M31 night" and first["problems"] == []
    assert second["session"] == {"state": "idle"} and second["problems"] == ["camera"] and second["connected"] == []


class _Camera:
    is_connected = True

    def __init__(self):
        self.exposures, self.aborted = [], 0

    async def start_exposure(self, duration, frame_type="Light", **options):
        self.exposures.append((duration, frame_type, options))

    async def get_image_array(self):
        import numpy as np
        return np.full((32, 32), 1000, dtype=np.uint16)

    async def abort_exposure(self):
        self.aborted += 1


class _ImagingDevices:
    def __init__(self, camera):
        self.camera = camera

    def controller(self, pier, category):
        return self.camera if category == "camera" and pier == "p1" else None


@pytest.mark.requirement("TC-CSURF-120")
@pytest.mark.priority("MVP")
async def test_tc_csurf_120_a_remote_client_takes_a_series_and_reads_the_current_frame(monkeypatch):
    """CSURF-120: imaging.capture takes a series on the Pier's camera, reporting progress per frame and finishing once;
    imaging.status gives the current frame's statistics and histogram as plain data; availability says why a capture
    cannot start (no camera, a session running, a capture already under way); imaging.stop ends a series."""
    import json
    from types import SimpleNamespace

    from galileo.control_surface import OperationFinished, OperationProgress
    from galileo.control_surface.imaging import register_imaging_operations
    from galileo.engine.imaging import EngineImaging
    from galileo.ui.imaging import ImagingService

    camera, runner = _Camera(), _Runner()
    devices = _ImagingDevices(camera)

    async def fake_context(devs, pier, slot="primary"):
        def make():
            service = ImagingService(camera=camera)
            service.auto_save_to_library = False
            return service
        return SimpleNamespace(make_imaging=make)

    monkeypatch.setattr("galileo.engine.imaging.build_context", fake_context)
    bus = EventBus()
    seen = []
    bus.subscribe(OperationProgress, seen.append)
    bus.subscribe(OperationFinished, seen.append)
    registry, imaging = Registry(bus), EngineImaging(devices, runner)
    register_imaging_operations(registry, imaging)

    started = await registry.invoke("imaging.capture", {"seconds": 2.0, "count": 2, "gain": 120}, "p1", "c1")
    assert started.ok and started.reason == "started" and started.correlation_id
    await registry.wait_idle()
    assert [e.message for e in seen if isinstance(e, OperationProgress)] == ["frame 1 of 2", "frame 2 of 2"]
    finished = [e for e in seen if isinstance(e, OperationFinished)]
    assert len(finished) == 1 and finished[0].outcome == "ok"
    assert [(d, t) for d, t, _ in camera.exposures] == [(2.0, "Light"), (2.0, "Light")]
    assert camera.exposures[0][2] == {"gain": 120}

    status = (await registry.invoke("imaging.status", {}, "p1", "c1")).value
    assert status["capturing"] is False and status["series_done"] == 2 and status["series_total"] == 2
    assert status["frame"]["shape"] == [32, 32] and status["frame"]["stats"]
    json.dumps(status)                                              # plain data all the way down

    assert (await registry.invoke("imaging.capture", {"seconds": 1.0}, "p2", "c1")).reason == "this Pier has no camera"
    runner.running = True
    assert (await registry.invoke("imaging.capture", {"seconds": 1.0}, "p1", "c1")).reason == "a session is running on this Pier"
    runner.running = False
    imaging._busy.add("p1")
    assert "already running" in (await registry.invoke("imaging.capture", {"seconds": 1.0}, "p1", "c1")).reason
    assert (await registry.invoke("imaging.stop", {}, "p1", "c1")).ok and camera.aborted == 1
    imaging._busy.clear()
    assert (await registry.invoke("imaging.stop", {}, "p1", "c1")).status == "refused"


@pytest.mark.requirement("TC-CSURF-220")
@pytest.mark.priority("MVP")
async def test_tc_csurf_220_after_a_safety_stop_only_acknowledging_is_offered(rig):
    """CSURF-220: a safety stop is listed; until it is acknowledged the Pier's other operations are unavailable (reads,
    the emergency operations and the acknowledgement stay); acknowledging is refused while conditions are still unsafe
    and restarts nothing; afterwards the operations are offered again."""
    from galileo.control_surface.safety import GuardSafety, register_safety_operations
    from galileo.engine.guard import Guard

    registry, access, *_ = rig

    class Devices:
        def pier_ids(self):
            return ["p1"]

        def controller(self, pier, category):
            return access.mount if category == "mount" else None

    class Runner:
        def stop(self, pier):
            return True

    guard = Guard(Devices(), Runner(), bus=EventBus())
    register_safety_operations(registry, GuardSafety(guard))
    assert (await registry.invoke("safety.acknowledge", {}, "p1", "c1")).status == "refused"       # nothing to acknowledge

    guard.unsafe["p1"] = "Rain detected"
    await guard._act("p1", "Rain detected")
    events = (await registry.invoke("safety.events", {}, "p1", "c1")).value
    assert events["pending"] == 1 and events["events"][0]["why"] == "Rain detected" and ("park",) in access.mount.calls

    blocked = await registry.invoke("mount.unpark", {}, "p1", "c1")
    assert blocked.status == "unavailable" and blocked.reason == "a safety stop must be acknowledged first"
    listed = {o["name"]: o for o in registry.catalogue("p1")["operations"]}
    assert not listed["mount.slew"]["available"] and listed["mount.status"]["available"]
    assert listed["safety.acknowledge"]["available"] and listed["system.stop_everything"]["available"]
    assert (await registry.invoke("mount.status", {}, "p1", "c1")).ok

    still = await registry.invoke("safety.acknowledge", {}, "p1", "c1")
    assert still.status == "refused" and "still unsafe" in still.reason

    guard.unsafe.clear()
    done = await registry.invoke("safety.acknowledge", {}, "p1", "c1")
    assert done.ok and done.value == {"acknowledged": 1}
    assert guard.events[0]["acknowledged_by"] == "c1"
    assert (await registry.invoke("mount.unpark", {}, "p1", "c1")).ok
    assert access.mount.calls[-1] == ("unpark",)                       # acknowledging restarted nothing by itself


class _FlipMount:
    """A German mount at LST 12 h tracking on the west side; slewing to where it points puts it on the east side."""
    is_connected = True

    def __init__(self, ra_hours=12.5, side="West", flips=True):
        self.ra, self.side, self.tracking, self.flips, self.calls = ra_hours, side, True, flips, []

    async def get_status(self):                          # no "slewing" key: a mount that does not report it
        return {"right_ascension": self.ra, "declination": 20.0, "sidereal_time": 12.0,
                "side_of_pier": self.side, "tracking": self.tracking}

    async def slew_to_coordinates(self, ra, dec):
        self.calls.append(("slew", ra, dec))
        if self.flips:
            self.side = "East"

    async def set_tracking(self, enabled):
        self.tracking = enabled


@pytest.mark.requirement("TC-CSURF-170")
@pytest.mark.priority("MVP")
async def test_tc_csurf_170_flip_state_time_to_flip_and_a_confirmed_flip(settings_db):
    """CSURF-170: flip.status gives the phase (inactive, waiting, armed, due, flipping), the hour angle, pier side, the
    clock minutes to the flip limit and the last outcome, from the Pier's saved Mount-page settings; flip.now is a
    confirm-class, long-running operation that flips the mount, resumes tracking and reports done only when the mount
    really changed side; it is refused when there is no flip to make, while a session runs, or from the east side."""
    from galileo.control_surface import OperationFinished
    from galileo.control_surface.flips import register_flip_operations
    from galileo.engine.flips import EngineFlips
    from galileo.mount_limits import MountLimits
    from galileo.observatory import create_observatory, create_pier, save_device_config

    pier = create_pier(create_observatory("Home", latitude=45.0, longitude=-75.0), "Pier 1")
    devices, runner = _Devices(pier), _Runner()
    devices.mount = mount = _FlipMount()
    bus = EventBus()
    finished = []
    bus.subscribe(OperationFinished, finished.append)
    registry, flips = Registry(bus), EngineFlips(devices, runner)
    register_flip_operations(registry, flips)
    spec = {o["name"]: o for o in registry.catalogue("p1")["operations"]}["flip.now"]
    assert spec["class"] == "confirm" and spec["needs_lease"]

    assert (await registry.invoke("flip.status", {}, "p1", "c1")).value["phase"] == "inactive"     # not requested

    save_device_config(pier, "mount", "d", "s", 1, mount_limits=MountLimits(flip_enabled=True, flip_ha_deg=5.0))
    state = (await registry.invoke("flip.status", {}, "p1", "c1")).value
    assert state["phase"] == "armed" and state["pier_side"] == "West" and state["pointing"].startswith("West")
    assert state["hour_angle_hours"] == pytest.approx(-0.5) and state["minutes_to_flip"] == pytest.approx(49.9, abs=0.1)
    assert state["last"] is None

    mount.tracking = False
    assert (await registry.invoke("flip.status", {}, "p1", "c1")).value["phase"] == "waiting"
    assert (await registry.invoke("flip.now", {}, "p1", "c1")).ok                                     # starts ...
    await registry.wait_idle()
    assert finished[-1].outcome != "ok" and "tracking" in finished[-1].reason          # ... and is refused in the event
    mount.tracking = True

    mount.ra = 11.0                                                       # one hour past the meridian: past the limit
    due = (await registry.invoke("flip.status", {}, "p1", "c1")).value
    assert due["phase"] == "due" and due["minutes_to_flip"] == 0.0

    runner.running = True
    assert "Meridian Flip block" in (await registry.invoke("flip.now", {}, "p1", "c1")).reason
    runner.running = False
    started = await registry.invoke("flip.now", {}, "p1", "c1")
    assert started.ok and started.reason == "started"
    await registry.wait_idle()
    assert finished[-1].outcome == "ok" and mount.calls == [("slew", 165.0, 20.0)] and mount.tracking
    after = (await registry.invoke("flip.status", {}, "p1", "c1")).value
    assert after["last"]["outcome"] == "done" and after["last"]["pier_side"] == "East"
    assert after["minutes_to_flip"] is None and after["phase"] == "armed"

    refused = await registry.invoke("flip.now", {}, "p1", "c1")                       # now on the east side
    await registry.wait_idle()
    assert refused.ok and finished[-1].outcome != "ok" and "no flip to make" in finished[-1].reason

    stuck = _FlipMount(flips=False)                                       # a mount that ignores the slew has not flipped
    devices.mount = stuck
    await registry.invoke("flip.now", {}, "p1", "c1")
    await registry.wait_idle()
    assert "did not flip" in finished[-1].reason
    assert (await registry.invoke("flip.status", {}, "p1", "c1")).value["last"]["outcome"] == "failed"
    devices.mount = None
    assert (await registry.invoke("flip.now", {}, "p2", "c1")).reason == "this Pier has no mount"
    assert (await registry.invoke("flip.status", {}, "p1", "c1")).value["phase"] == "unavailable"


@pytest.mark.requirement("TC-CSURF-170")
@pytest.mark.priority("MVP")
def test_tc_csurf_170_the_flip_rules_are_pure():
    """CSURF-170 / MFLIP-010: minutes to the limit and the phase come from the saved limits, hour angle and pier side
    alone: unknown or east-side mounts have no flip ahead, and a sidereal hour is shorter than a clock hour."""
    from galileo.mount_limits import MountLimits, flip_phase, minutes_to_flip

    limits = MountLimits(flip_enabled=True, flip_ha_deg=15.0)             # one hour past the meridian
    assert minutes_to_flip(limits, -1.0, "West") == pytest.approx(120 * 0.99727, abs=0.01)
    assert minutes_to_flip(limits, 2.0, "West") == 0.0
    assert minutes_to_flip(limits, -1.0, "East") is None and minutes_to_flip(limits, None, "West") is None
    kw = {"tracking": True, "slewing": False, "flipping": False}
    assert flip_phase(limits, 0.5, "West", **kw) == "armed" and flip_phase(limits, 1.5, "West", **kw) == "due"
    assert flip_phase(limits, 1.5, "East", **kw) == "armed"
    assert flip_phase(limits, 1.5, "West", **{**kw, "tracking": False}) == "waiting"
    assert flip_phase(limits, 1.5, "West", **{**kw, "flipping": True}) == "flipping"
    assert flip_phase(MountLimits(), 1.5, "West", **kw) == "inactive"
