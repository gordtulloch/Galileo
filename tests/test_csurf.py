# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""CSURF / LEASE — the Control Surface registry, state, events, lease, held motion and emergency
operations (TC-CSURF-*, TC-LEASE-*). `test_csurf.py` covers both domains: the lease belongs to the same
module (SDD §4.29). The area-by-area operation inventory (CSURF-100 to 250) is tested where each
service registers its operations."""

import asyncio

import pytest

from galileo.bus import EventBus
from galileo.control_surface import (
    DESKTOP,
    Arg,
    Busy,
    HoldError,
    HoldManager,
    LeaseBroker,
    LeaseChanged,
    ObservableState,
    OperationFinished,
    OperationProgress,
    OperationSpec,
    OperationStarted,
    Refused,
    RegistrationError,
    Registry,
    Unreachable,
    register_emergency,
    validate_timing,
)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def registry(bus):
    return Registry(bus)


def _slew(registry):
    registry.register(
        OperationSpec("mount.slew", "operate", (Arg("ra", "float", minimum=0, maximum=24, unit="h"),
                                                Arg("dec", "float", minimum=-90, maximum=90, unit="deg"),
                                                Arg("rate", "enum", required=False, default="max",
                                                    choices=("max", "centre"))), needs_lease=True),
        lambda ctx, a: {"slewing_to": [a["ra"], a["dec"]], "rate": a["rate"], "by": ctx.principal})


# ---- CSURF-010 .. 040 -----------------------------------------------------------------
@pytest.mark.requirement("TC-CSURF-010")
@pytest.mark.priority("MVP")
async def test_tc_csurf_010_services_register_by_declaration_and_are_invoked(registry):
    """CSURF-010: a service declares an operation (schema, class, lease, availability) and a new one
    needs no change in any consumer."""
    _slew(registry)
    out = await registry.invoke("mount.slew", {"ra": 5.5, "dec": -20}, "pier1", "client-a")
    assert out.ok and out.value == {"slewing_to": [5.5, -20.0], "rate": "max", "by": "client-a"}
    registry.register(OperationSpec("camera.expose", "operate"), lambda ctx, a: "shot")
    assert (await registry.invoke("camera.expose", None, "pier1", "c")).value == "shot"
    with pytest.raises(RegistrationError):
        registry.register(OperationSpec("camera.expose", "operate"), lambda ctx, a: None)


@pytest.mark.requirement("TC-CSURF-020")
@pytest.mark.priority("MVP")
def test_tc_csurf_020_config_class_is_refused_at_registration_and_at_verify(registry):
    """CSURF-020: exactly one of read/operate/confirm/emergency; an entry that would edit a stored
    definition (class config) is refused, and verify() repeats the check."""
    for cls in ("config", "admin", ""):
        with pytest.raises(RegistrationError):
            registry.register(OperationSpec("profile.edit", cls), lambda ctx, a: None)
    registry.register(OperationSpec("profile.view", "read"), lambda ctx, a: None)
    registry._ops["profile.sneaky"] = (OperationSpec("profile.sneaky", "config"), lambda ctx, a: None)
    with pytest.raises(RegistrationError):
        registry.verify()
    with pytest.raises(RegistrationError):
        registry.register(OperationSpec("system.stop", "emergency", needs_lease=True), lambda ctx, a: None)


@pytest.mark.requirement("TC-CSURF-030")
@pytest.mark.priority("MVP")
def test_tc_csurf_030_catalogue_describes_every_entry_and_availability_per_pier(registry):
    """CSURF-030: the catalogue gives each entry's schema, class, lease requirement and version, and says
    per Pier whether it is available and why not."""
    registry.register(OperationSpec("rotator.move", "operate", (Arg("angle", "float", minimum=0, maximum=360),),
                                    available=lambda pier: None if pier == "p1" else "no rotator on this Pier"),
                      lambda ctx, a: None)
    _slew(registry)
    cat = registry.catalogue("p2")
    assert cat["version"] >= 1
    rot = next(o for o in cat["operations"] if o["name"] == "rotator.move")
    assert rot["available"] is False and rot["reason"] == "no rotator on this Pier"
    assert rot["args"][0] == {"name": "angle", "type": "float", "required": True, "min": 0, "max": 360}
    slew = next(o for o in cat["operations"] if o["name"] == "mount.slew")
    assert slew["needs_lease"] is True and slew["class"] == "operate"
    assert next(o for o in registry.catalogue("p1")["operations"] if o["name"] == "rotator.move")["available"]


@pytest.mark.requirement("TC-CSURF-040")
@pytest.mark.priority("MVP")
async def test_tc_csurf_040_invoke_validates_first_and_never_raises(registry):
    """CSURF-040: arguments are validated before the service is called (invalid carries the field
    path); unknown operations are unavailable; a crashing handler becomes a typed outcome."""
    calls = []
    registry.register(OperationSpec("mount.slew", "operate", (Arg("ra", "float", minimum=0, maximum=24),
                                                              Arg("track", "bool", required=False, default=True))),
                      lambda ctx, a: calls.append(a))
    for args, path in (({}, "ra"), ({"ra": 99}, "ra"), ({"ra": "x"}, "ra"), ({"ra": True}, "ra"),
                       ({"ra": 1, "bogus": 1}, "bogus"), ({"ra": 1, "track": "yes"}, "track"),
                       ({"ra": float("nan")}, "ra")):
        out = await registry.invoke("mount.slew", args, "p", "c")
        assert out.status == "invalid" and out.path == path and out.reason
    assert calls == []
    assert (await registry.invoke("mount.nope", {}, "p", "c")).status == "unavailable"
    assert (await registry.invoke("profile.set", {}, "p", "c")).status == "unavailable"

    def boom(ctx, a):
        raise RuntimeError("secret internals")

    registry.register(OperationSpec("camera.boom", "operate"), boom)
    out = await registry.invoke("camera.boom", None, "p", "c")
    assert out.status == "unavailable" and "secret" not in out.reason


@pytest.mark.requirement("TC-CSURF-050")
@pytest.mark.priority("MVP")
async def test_tc_csurf_050_safety_refusals_pass_through_verbatim(registry):
    """CSURF-050: the handler is the service's own method; a refusal (safety, limit) is returned as
    refused with its reason unchanged, busy and unreachable are typed too."""
    def refuse(ctx, a):
        raise Refused("Unsafe: rain detected; the roof is closed")

    def busy(ctx, a):
        raise Busy("a session is running")

    async def away(ctx, a):
        raise Unreachable("spoke last heard 12:00")

    registry.register(OperationSpec("mount.unpark", "operate"), refuse)
    registry.register(OperationSpec("camera.expose", "operate"), busy)
    registry.register(OperationSpec("dome.open", "operate"), away)
    out = await registry.invoke("mount.unpark", None, "p", "c")
    assert (out.status, out.reason) == ("refused", "Unsafe: rain detected; the roof is closed")
    assert (await registry.invoke("camera.expose", None, "p", "c")).status == "busy"
    assert (await registry.invoke("dome.open", None, "p", "c")).status == "unreachable"


@pytest.mark.requirement("TC-CSURF-060")
@pytest.mark.priority("MVP")
def test_tc_csurf_060_subscribers_get_a_snapshot_then_sequenced_deltas():
    """CSURF-060: state is readable on demand; a subscription delivers a snapshot then changes with a
    per-Pier sequence; an unchanged value is not republished; a failing subscriber is isolated."""
    state = ObservableState()
    state.publish("p1", "mount.tracking", True)
    state.publish("p1", "focuser.position", 5000)
    got = []
    seq, snap, unsub = state.subscribe("p1", lambda pier, s, k, v: got.append((s, k, v)))
    state.subscribe("p1", lambda *a: 1 / 0)
    assert seq == 2 and snap == {"mount.tracking": True, "focuser.position": 5000}
    state.publish("p1", "focuser.position", 5100)
    state.publish("p1", "focuser.position", 5100)            # unchanged
    state.publish("p2", "mount.tracking", False)              # another Pier has its own sequence
    assert got == [(3, "focuser.position", 5100)]
    assert state.snapshot("p2")[0] == 1 and state.read("p1", "focuser.position") == 5100
    unsub()
    state.publish("p1", "focuser.position", 5200)
    assert len(got) == 1


@pytest.mark.requirement("TC-CSURF-070")
@pytest.mark.priority("MVP")
async def test_tc_csurf_070_long_operations_publish_started_progress_finished_once(registry, bus):
    """CSURF-070: a long-running operation returns a correlation id at once and publishes started,
    progress and exactly one finished; a dying handler still produces one finished."""
    events = []
    for kind in (OperationStarted, OperationProgress, OperationFinished):
        bus.subscribe(kind, lambda e: events.append((type(e).__name__, e.correlation_id, getattr(e, "outcome", ""))))

    async def autofocus(ctx, a):
        ctx.progress(0.5, "halfway")
        await asyncio.sleep(0)
        return "done"

    registry.register(OperationSpec("focus.autofocus", "operate", long_running=True), autofocus)
    out = await registry.invoke("focus.autofocus", None, "p", "c")
    assert out.ok and out.correlation_id
    await registry.wait_idle()
    cid = out.correlation_id
    assert events == [("OperationStarted", cid, ""), ("OperationProgress", cid, ""), ("OperationFinished", cid, "ok")]
    events.clear()

    async def dies(ctx, a):
        await asyncio.sleep(10)

    registry.register(OperationSpec("session.run", "operate", long_running=True), dies)
    await registry.invoke("session.run", None, "p", "c")
    await asyncio.sleep(0)
    registry.cancel_background()
    await registry.wait_idle()
    assert [e[0] for e in events] == ["OperationStarted", "OperationFinished"] and events[1][2] == "unavailable"


@pytest.mark.requirement("TC-CSURF-080")
@pytest.mark.priority("MVP")
async def test_tc_csurf_080_registry_is_free_when_unused_and_isolates_subscribers(registry, bus):
    """CSURF-080: registering and reading state starts no thread or task; a failing event subscriber
    never reaches the service."""
    import threading
    before = threading.active_count()
    _slew(registry)
    ObservableState().publish("p", "k", 1)
    assert threading.active_count() == before and not registry._tasks
    bus.subscribe(OperationStarted, lambda e: 1 / 0)
    registry.register(OperationSpec("focus.run", "operate", long_running=True), lambda ctx, a: "fine")
    assert (await registry.invoke("focus.run", None, "p", "c")).ok
    await registry.wait_idle()


@pytest.mark.requirement("TC-CSURF-250")
@pytest.mark.priority("P3")
def test_tc_csurf_250_plugins_register_only_under_their_namespace(registry):
    """CSURF-250: a plugin registers operations under its own namespace, never core's, and they leave
    the catalogue when the plugin is disabled."""
    registry.register(OperationSpec("vstarget.add_target", "operate"), lambda ctx, a: None, namespace="vstarget")
    with pytest.raises(RegistrationError):
        registry.register(OperationSpec("mount.hijack", "operate"), lambda ctx, a: None, namespace="vstarget")
    assert "vstarget.add_target" in registry.names()
    assert registry.unregister_namespace("vstarget") == 1 and registry.names() == []


# ---- CSURF-300 / 400 .. 420 ------------------------------------------------------------
@pytest.mark.requirement("TC-CSURF-300")
@pytest.mark.priority("MVP")
async def test_tc_csurf_300_three_emergency_operations_need_no_lease(registry):
    """CSURF-300: stop everything, park and close dome are emergency-class, need no lease, and stop
    everything also cancels held motion."""
    done = []
    stops = []
    holds = HoldManager()
    holds.start("p1", "client-a", lambda: stops.append("jog"))
    register_emergency(registry, stop_everything=lambda p: done.append(("stop", p)),
                       park=lambda p: done.append(("park", p)), close_dome=lambda p: done.append(("dome", p)),
                       holds=holds)
    cat = {o["name"]: o for o in registry.catalogue("p1")["operations"]}
    assert set(cat) == {"system.stop_everything", "mount.emergency_park", "dome.emergency_close"}
    assert all(o["class"] == "emergency" and not o["needs_lease"] for o in cat.values())
    for name in cat:
        assert (await registry.invoke(name, None, "p1", "client-b")).ok
    assert sorted(done) == [("dome", "p1"), ("park", "p1"), ("stop", "p1")] and stops == ["jog"]


@pytest.mark.requirement("TC-CSURF-410")
@pytest.mark.priority("MVP")
def test_tc_csurf_410_timing_is_validated():
    """CSURF-410: the deadman must exceed twice the keep-alive interval and stop motion within a second."""
    validate_timing(0.25, 0.6)
    for beat, dead in ((0.25, 0.5), (0.3, 0.5), (0, 0.6), (0.25, 1.2), (0.4, 0.9)):
        with pytest.raises(HoldError):
            validate_timing(beat, dead)
    with pytest.raises(HoldError):
        HoldManager(beat_s=0.5, deadman_s=0.9)


@pytest.mark.requirement("TC-CSURF-400")
@pytest.mark.priority("MVP")
def test_tc_csurf_400_motion_stops_when_the_keepalive_stops(clock):
    """CSURF-400: a hold keeps going while beats arrive, stops when they stop, or on stop(); only its
    holder can beat or stop it; one hold per Pier."""
    stopped = []
    holds = HoldManager(clock)
    hid = holds.start("p1", "a", lambda: stopped.append("p1"))
    with pytest.raises(HoldError):
        holds.start("p1", "b", lambda: None)
    for _ in range(5):
        clock.t += 0.25
        assert holds.beat(hid, "a") and holds.check() == 0
    assert not holds.beat(hid, "mallory") and not holds.stop(hid, "mallory")
    clock.t += 0.6
    assert holds.check() == 1 and stopped == ["p1"] and holds.active() == []
    hid2 = holds.start("p1", "a", lambda: stopped.append("again"))
    assert holds.stop(hid2, "a") and stopped == ["p1", "again"] and not holds.beat(hid2, "a")


@pytest.mark.requirement("TC-CSURF-420")
@pytest.mark.priority("MVP")
def test_tc_csurf_420_holds_cancel_on_revocation_plugin_disable_and_safety_stop(clock):
    """CSURF-420: revoking the holder's pairing, disabling the originating plugin and a safety stop
    each stop motion at once; a stop that fails does not prevent the others."""
    stopped = []
    holds = HoldManager(clock)

    def make(pier, holder, origin="webconnect"):
        return holds.start(pier, holder, lambda: stopped.append(pier), origin)

    make("p1", "a")
    assert holds.cancel_holder("a", "revoked") == 1
    make("p1", "a")
    assert holds.cancel_origin("webconnect") == 1 and holds.cancel_origin("") == 0
    make("p1", "a")

    def bad():
        raise OSError("serial gone")

    holds.start("p2", "b", bad)
    assert holds.cancel_all("safety stop") == 2 and stopped == ["p1", "p1", "p1"]


@pytest.mark.requirement("TC-CSURF-410")
@pytest.mark.priority("MVP")
async def test_tc_csurf_410_watchdog_loop_stops_motion_within_a_second():
    """CSURF-410: the real watchdog loop stops motion within one second of the last keep-alive."""
    import time
    stopped = []
    holds = HoldManager(beat_s=0.05, deadman_s=0.12)
    holds.start("p1", "a", lambda: stopped.append(time.monotonic()))
    task = asyncio.create_task(holds.run())
    t0 = time.monotonic()
    await asyncio.sleep(0.4)
    task.cancel()
    assert stopped and stopped[0] - t0 < 1.0


# ---- LEASE ------------------------------------------------------------------------------
@pytest.mark.requirement("TC-LEASE-010")
@pytest.mark.priority("MVP")
def test_tc_lease_010_020_one_holder_per_pier_granted_when_free_and_memory_only(clock, bus):
    """LEASE-010 / LEASE-020: a Pier has at most one holder, a free Pier is granted at once, and a new
    broker (a restart) starts clear."""
    leases = LeaseBroker(clock, bus=bus)
    assert leases.holder("p1") == ""
    assert leases.acquire("p1", "peer:a").granted and leases.holder("p1") == "peer:a"
    assert leases.acquire("p1", "peer:a").granted
    assert leases.acquire("p2", "peer:b").granted and leases.holder("p2") == "peer:b"
    assert LeaseBroker(clock, bus=bus).holder("p1") == ""


@pytest.mark.requirement("TC-LEASE-030")
@pytest.mark.priority("MVP")
def test_tc_lease_030_a_held_lease_is_refused_with_the_holder_and_taken_over_with_confirmation(clock, bus):
    """LEASE-030: acquiring a held lease is refused naming the holder with an offer to take over, which
    needs the requester's confirmation; the previous holder is notified."""
    leases = LeaseBroker(clock, bus=bus)
    told = []
    leases.add_listener(lambda pier, prev, new, why: told.append((prev, new, why)))
    leases.acquire("p1", DESKTOP)
    r = leases.acquire("p1", "peer:a")
    assert not r.granted and r.holder == DESKTOP and r.can_take_over and DESKTOP in r.reason
    assert not leases.take("p1", "peer:a", confirmed=False).granted and leases.holder("p1") == DESKTOP
    assert leases.take("p1", "peer:a", confirmed=True).granted and leases.holder("p1") == "peer:a"
    assert told[-1] == (DESKTOP, "peer:a", "taken over")


@pytest.mark.requirement("TC-LEASE-040")
@pytest.mark.priority("MVP")
def test_tc_lease_040_release_disconnect_and_idle_free_the_lease(clock, bus):
    """LEASE-040: the lease is released on request, on the holder's disconnect or revocation and after
    the idle time without an operation (default 10 minutes); activity restarts the timer."""
    leases = LeaseBroker(clock, bus=bus)
    assert leases.idle_s == 600
    leases.acquire("p1", "peer:a")
    assert not leases.release("p1", "peer:b") and leases.release("p1", "peer:a")
    leases.acquire("p1", "peer:a")
    leases.acquire("p2", "peer:a")
    assert sorted(leases.on_disconnect("peer:a")) == ["p1", "p2"] and leases.holder("p1") == ""
    leases.acquire("p1", "peer:a")
    clock.t += 500
    leases.touch("p1", "peer:a")
    clock.t += 500
    assert leases.holder("p1") == "peer:a"
    clock.t += 101
    assert leases.expire_idle() == ["p1"] and leases.holder("p1") == ""


@pytest.mark.requirement("TC-LEASE-050")
@pytest.mark.priority("MVP")
def test_tc_lease_050_every_change_is_published_on_the_bus(clock, bus):
    """LEASE-050: a change of holder is published, so the desktop and every client stay correct."""
    seen = []
    bus.subscribe(LeaseChanged, lambda e: seen.append((e.pier, e.holder, e.previous, e.reason)))
    leases = LeaseBroker(clock, bus=bus)
    leases.acquire("p1", "peer:a")
    leases.take("p1", DESKTOP, True)
    leases.release("p1", DESKTOP)
    assert seen == [("p1", "peer:a", "", "acquired"), ("p1", DESKTOP, "peer:a", "taken over"),
                    ("p1", "", DESKTOP, "released")]


@pytest.mark.requirement("TC-LEASE-080")
@pytest.mark.priority("MVP")
def test_tc_lease_080_taking_or_losing_the_lease_stops_the_previous_holders_motion(clock, bus):
    """LEASE-080: held motion of the previous holder stops when the lease is taken from it or lost."""
    leases, holds, stopped = LeaseBroker(clock, bus=bus), HoldManager(clock), []
    leases.add_listener(holds.on_lease_changed)
    leases.acquire("p1", "peer:a")
    holds.start("p1", "peer:a", lambda: stopped.append("taken"))
    leases.take("p1", "peer:b", True)
    assert stopped == ["taken"]
    holds.start("p1", "peer:b", lambda: stopped.append("released"))
    leases.release("p1", "peer:b")
    assert stopped == ["taken", "released"]


@pytest.mark.requirement("TC-CSURF-250")
@pytest.mark.priority("P3")
def test_tc_csurf_250_engine_publishes_its_surface_to_plugins():
    """CSURF-250: a front-end plugin reaches the engine's own registry, lease and pipeline (never copies of
    them); nothing is available while no engine is running."""
    from galileo.control_surface import LeaseBroker, ObservableState, Registry
    from galileo.control_surface.service import (
        ControlSurfaceService,
        get_control_surface,
        publish_control_surface,
        withdraw_control_surface,
    )
    from galileo.connect_link.audit import AuditLog
    from galileo.connect_link.gateway import Gateway

    withdraw_control_surface()
    assert get_control_surface() is None
    reg, leases = Registry(), LeaseBroker()
    svc = ControlSurfaceService(reg, leases, Gateway(reg, leases, AuditLog()), ObservableState(), list)
    publish_control_surface(svc)
    try:
        assert get_control_surface() is svc and get_control_surface().leases is leases
    finally:
        withdraw_control_surface()
    assert get_control_surface() is None


@pytest.mark.requirement("TC-CSURF-260")
@pytest.mark.priority("MVP")
def test_tc_csurf_260_event_feed_orders_state_lease_and_operation_events():
    """CSURF-260: state, lease and operation events reach a reader as one ordered feed with ids, so a front end
    asking "after N" misses nothing, and a reader that fell behind is told to re-read state."""
    from galileo.control_surface import LeaseBroker, ObservableState, OperationTracker
    from galileo.control_surface.feed import EventFeed

    bus, state = EventBus(), ObservableState()
    leases = LeaseBroker(bus=bus)
    feed = EventFeed(state=state, leases=leases, bus=bus, pier_ids=lambda: ["p1"], capacity=10)
    try:
        assert feed.read(0) == {"entries": [], "last": 0, "gap": False, "closed": False}
        state.publish("p1", "mount.tracking", True)
        leases.acquire("p1", "webconnect:a")
        tracker = OperationTracker("mount.slew", "p1", "webconnect:a", bus=bus)
        tracker.start()
        tracker.finish("ok")
        got = feed.read(0)
        kinds = [(e["type"], e.get("key") or e.get("name") or e.get("holder")) for e in got["entries"]]
        assert kinds == [("state", "mount.tracking"), ("lease", "webconnect:a"),
                         ("event", "OperationStarted"), ("event", "OperationFinished")]
        assert [e["id"] for e in got["entries"]] == [1, 2, 3, 4] and got["last"] == 4 and not got["gap"]
        assert feed.read(4)["entries"] == []                       # nothing new: an empty read, same cursor
        assert feed.read(2)["entries"][0]["id"] == 3               # resumes exactly after the cursor

        for i in range(30):                                        # more than the feed keeps
            state.publish("p1", "k", i)
        behind = feed.read(4)
        assert behind["gap"] is True                               # entries 5..24 were dropped
        assert feed.read(feed.last_id - 3)["gap"] is False         # a reader that kept up is not told
    finally:
        feed.close()
    before = feed.last_id
    leases.release("p1", "webconnect:a")
    state.publish("p1", "after", 1)
    assert feed.read(0)["closed"] is True and feed.last_id == before         # closed feeds record nothing more


@pytest.mark.requirement("TC-CSURF-260")
@pytest.mark.priority("MVP")
def test_tc_csurf_260_event_feed_read_waits_for_news_and_wakes_on_close():
    """CSURF-260: a long-poll read returns as soon as something arrives, and a closing feed releases waiters."""
    import threading
    import time as _time

    from galileo.control_surface import LeaseBroker, ObservableState
    from galileo.control_surface.feed import EventFeed

    bus, state = EventBus(), ObservableState()
    feed = EventFeed(state=state, leases=LeaseBroker(bus=bus), bus=bus, pier_ids=lambda: ["p1"])
    result: dict = {}
    t = threading.Thread(target=lambda: result.update(feed.read(0, timeout=5)))
    t0 = _time.monotonic()
    t.start()
    _time.sleep(0.1)
    state.publish("p1", "focuser.position", 1200)
    t.join(3)
    assert result["entries"][0]["key"] == "focuser.position" and _time.monotonic() - t0 < 2

    waiter: dict = {}
    t2 = threading.Thread(target=lambda: waiter.update(feed.read(feed.last_id, timeout=5)))
    t2.start()
    _time.sleep(0.1)
    feed.close()
    t2.join(3)
    assert waiter["closed"] is True and waiter["entries"] == []


@pytest.mark.requirement("TC-CSURF-230")
@pytest.mark.priority("P2")
async def test_tc_csurf_230_history_is_readable_and_never_changed(registry, tmp_path):
    """CSURF-230: a client can list recorded sessions and read a session's frames and averages from the real
    History store; an unknown session is refused, and nothing offered changes, exports or deletes history."""
    from galileo.control_surface.history import MAX_FRAMES, StoreHistory, register_history_operations
    from galileo.history import SessionHistory

    store = SessionHistory(tmp_path / "history.json")
    store.start_session("M31 night 1")
    store.record_frame("2026-11-01T21:00:00", 2.0, 100, 0.5, 0.4)
    store.record_frame("2026-11-01T21:05:00", 3.0, 200, 0.7, 0.6)
    store.end_session()
    register_history_operations(registry, StoreHistory(store))

    out = await registry.invoke("history.sessions", {}, "p1", "web")
    assert out.ok and out.value == {"sessions": [{"name": "M31 night 1", "frame_count": 2}]}

    out = await registry.invoke("history.report", {"session": "M31 night 1"}, "p1", "web")
    assert out.ok and out.value["avg_hfr"] == 2.5 and out.value["avg_star_count"] == 150 and out.value["total"] == 2
    out = await registry.invoke("history.frames", {"session": "M31 night 1"}, "p1", "web")
    assert out.ok and [f["star_count"] for f in out.value["frames"]] == [100, 200]

    for name in ("history.frames", "history.report"):
        out = await registry.invoke(name, {"session": "nope"}, "p1", "web")
        assert out.status == "refused" and "nope" in out.reason
        assert (await registry.invoke(name, {}, "p1", "web")).status == "invalid"

    offered = {s["name"]: s["class"] for s in registry.catalogue("p1")["operations"] if s["name"].startswith("history.")}
    assert offered == {"history.sessions": "read", "history.frames": "read", "history.report": "read"}
    assert MAX_FRAMES >= 1000


@pytest.mark.requirement("TC-CSURF-200")
@pytest.mark.priority("P2")
async def test_tc_csurf_200_scheduler_queue_is_readable_per_pier(registry, settings_db):
    """CSURF-200: a client can read a Pier's saved job queue in priority order and which job is next, as the
    scheduler saved it; another Pier's jobs are not shown, and no operation changes the queue."""
    from galileo.control_surface.schedule import StoredSchedule, register_schedule_operations
    from galileo.scheduler import ObservatoryScheduler, SchedulerJob

    sched = ObservatoryScheduler()
    sched.set_persistence("North pier")
    done = SchedulerJob("M13", pier_name="North pier", target_ra=250.4, target_dec=36.5, priority=1)
    done.total_required, done._frames_captured = 20, 20
    later = SchedulerJob("M51", pier_name="North pier", priority=7)
    later.total_required = 40
    first = SchedulerJob("M31", pier_name="North pier", target_ra=10.7, target_dec=41.3, priority=3)
    first.total_required = 30
    for job in (later, done, first):
        sched.add_job(job)
    sched.save()
    other = ObservatoryScheduler()
    other.set_persistence("South pier")
    other.add_job(SchedulerJob("Orion", pier_name="South pier"))
    other.save()

    register_schedule_operations(registry, StoredSchedule({"p-north": "North pier", "p-south": "South pier"}.get))
    out = await registry.invoke("scheduler.jobs", {}, "p-north", "web")
    assert out.ok
    assert [j["name"] for j in out.value["jobs"]] == ["M13", "M31", "M51"]           # priority order
    assert out.value["next"] == "M31"                                                # M13 is complete
    assert out.value["jobs"][0]["complete"] is True and out.value["jobs"][1]["target_dec"] == 41.3
    south = await registry.invoke("scheduler.jobs", {}, "p-south", "web")
    assert [j["name"] for j in south.value["jobs"]] == ["Orion"]
    names = [s["name"] for s in registry.catalogue("p-north")["operations"] if s["name"].startswith("scheduler.")]
    assert names == ["scheduler.jobs"]


class _FakePhd2:
    """Stands in for ``Phd2Adapter``: records what the service asks of PHD2, answers like PHD2 would."""

    def __init__(self, reject=()):
        self.is_connected = False
        self.on_event = self.on_disconnect = None
        self.requests: list = []
        self.reject = set(reject)

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    def call(self, method, params=None, timeout=0):
        return {"get_app_state": "Stopped", "get_exposure": 2000, "get_pixel_scale": 1.5, "get_connected": True,
                "get_calibrated": False}.get(method)

    def request(self, method, params=None):
        from concurrent.futures import Future
        self.requests.append((method, params))
        f: Future = Future()
        if method in self.reject:
            f.set_exception(RuntimeError("no star selected"))
        else:
            f.set_result(0)
        return f


def _guiding_world(registry, monkeypatch, saved=True, reject=()):
    from types import SimpleNamespace

    from galileo.control_surface.guiding import register_guiding_operations
    from galileo.engine.guiding import EngineGuiding
    from galileo.guiding import GuidingService

    fake = _FakePhd2(reject)
    monkeypatch.setattr(
        "galileo.observatory.get_device_config",
        lambda record, cat, slot="primary": (SimpleNamespace(driver="PHD2", server="phd2.local", port=4401)
                                             if saved and cat == "guider" else None))
    devices = SimpleNamespace(pier_record=lambda pier: SimpleNamespace(id=pier) if pier == "p1" else None)
    state = ObservableState()
    guiding = EngineGuiding(devices, state, factory=lambda host, port: GuidingService(host, port, client=fake),
                            poll_s=3600)
    register_guiding_operations(registry, guiding)
    return guiding, fake, state


@pytest.mark.requirement("TC-CSURF-160")
@pytest.mark.priority("MVP")
async def test_tc_csurf_160_guiding_connects_commands_and_reports(registry, monkeypatch):
    """CSURF-160: a client connects to the Pier's saved PHD2, starts, recalibrates, dithers, finds a star and stops
    guiding, and reads the state, error trace and star cut-out; commands are not offered until connected, and the
    Pier's service is what a session would use."""
    import base64

    guiding, fake, state = _guiding_world(registry, monkeypatch)
    try:
        cat = {o["name"]: o for o in registry.catalogue("p1")["operations"] if o["name"].startswith("guiding.")}
        assert set(cat) == {"guiding.status", "guiding.star", "guiding.connect", "guiding.disconnect", "guiding.start",
                            "guiding.recalibrate", "guiding.stop", "guiding.dither", "guiding.find_star"}
        assert cat["guiding.connect"]["available"] is True
        assert cat["guiding.start"]["available"] is False and "not connected" in cat["guiding.start"]["reason"]
        assert cat["guiding.status"]["class"] == "read" and cat["guiding.start"]["needs_lease"] is True
        before = await registry.invoke("guiding.start", {}, "p1", "web")
        assert before.status == "unavailable" and fake.requests == []

        out = await registry.invoke("guiding.connect", {}, "p1", "web")
        assert out.ok and out.value == {"connected": True, "host": "phd2.local", "port": 4401}
        assert (await registry.invoke("guiding.connect", {}, "p1", "web")).status == "unavailable"   # already
        assert guiding.service("p1") is not None                                                    # sessions use it
        assert state.read("p1", "guiding.state") == {"connected": True, "app_state": "Stopped", "guiding": False,
                                                     "settling": False}

        for op, method in (("guiding.start", "guide"), ("guiding.dither", "dither"),
                           ("guiding.find_star", "find_star"), ("guiding.stop", "stop_capture")):
            fake.requests.clear()
            out = await registry.invoke(op, {}, "p1", "web")
            assert out.ok and fake.requests[0][0] == method, (op, out)
        fake.requests.clear()
        assert (await registry.invoke("guiding.recalibrate", {}, "p1", "web")).ok
        assert fake.requests[0][0] == "guide" and fake.requests[0][1][1] is True          # recalibrate flag
        fake.requests.clear()
        await registry.invoke("guiding.start", {"recalibrate": True}, "p1", "web")
        assert fake.requests[0][1][1] is True
        assert (await registry.invoke("guiding.start", {"recalibrate": "yes"}, "p1", "web")).status == "invalid"

        service = guiding.service("p1")
        service.model.apply_event({"Event": "StartGuiding"})
        for i, (ra, dec) in enumerate(((0.4, -0.2), (-0.3, 0.1)), start=1):
            service.model.apply_event({"Event": "GuideStep", "Frame": i, "Time": float(i), "RADistanceRaw": ra,
                                       "DECDistanceRaw": dec, "SNR": 20.0})
        status = (await registry.invoke("guiding.status", {}, "p1", "web")).value
        assert status["connected"] and status["guiding"] is True and status["app_state"] == "Guiding"
        assert len(status["trace"]) == 2 and status["trace"][0][:2] == [1.0, 1] and status["rms"]["total"] > 0
        guiding._publish("p1")
        assert state.read("p1", "guiding.state")["guiding"] is True and state.read("p1", "guiding.rms")["total"] > 0

        assert (await registry.invoke("guiding.star", {}, "p1", "web")).value == {"available": False}
        pixels = bytes(range(8))
        service.model.set_star_image({"width": 2, "height": 2, "pixels": base64.b64encode(pixels).decode(),
                                      "star_pos": [1.0, 1.0], "frame": 7})
        star = (await registry.invoke("guiding.star", {}, "p1", "web")).value
        assert star["width"] == 2 and base64.b64decode(star["pixels"]) == pixels and star["frame"] == 7

        assert (await registry.invoke("guiding.disconnect", {}, "p1", "web")).ok
        assert guiding.service("p1") is None
        assert state.read("p1", "guiding.state") == {"connected": False}
    finally:
        guiding.close()


@pytest.mark.requirement("TC-CSURF-160")
@pytest.mark.priority("MVP")
async def test_tc_csurf_160_guiding_refusals_name_their_reason(registry, monkeypatch):
    """CSURF-160: no PHD2 saved, no such Pier and a PHD2 that rejects a command are each refused with a reason a
    person can read; nothing is sent to PHD2 in the first two cases."""
    guiding, fake, _ = _guiding_world(registry, monkeypatch, saved=False)
    try:
        out = await registry.invoke("guiding.connect", {}, "p1", "web")
        assert out.status == "unavailable" and "no PHD2 guider saved" in out.reason
        assert (await registry.invoke("guiding.connect", {}, "nope", "web")).reason == "there is no such Pier"
        status = (await registry.invoke("guiding.status", {}, "p1", "web")).value
        assert status["configured"] is False and status["connected"] is False and "PHD2" in status["why_not_connect"]
        assert fake.requests == []
    finally:
        guiding.close()

    registry2 = Registry()
    guiding, fake, _ = _guiding_world(registry2, monkeypatch, reject=("guide",))
    try:
        assert (await registry2.invoke("guiding.connect", {}, "p1", "web")).ok
        out = await registry2.invoke("guiding.start", {}, "p1", "web")
        assert out.status == "refused" and "no star selected" in out.reason          # PHD2's own words
        assert (await registry2.invoke("guiding.stop", {}, "p1", "web")).ok
        assert (await registry2.invoke("guiding.disconnect", {}, "p1", "web")).ok
    finally:
        guiding.close()


class _FakeSolveWorkflow:
    """Records what the engine asks of a ``SolveWorkflow`` and answers with solutions."""

    def __init__(self, log, succeed=True, gate=None):
        self.log, self.succeed, self.gate = log, succeed, gate
        self.target = self.settings = self.filter_wheel = None
        self.stopped = False

    def set_target(self, ra, dec, name=""):
        self.target = (ra, dec, name)

    def stop(self):
        self.stopped = True
        if self.gate is not None:
            self.gate.set()

    async def capture_and_solve(self, settings):
        from galileo.platesolve_solvers import SolveResult
        self.settings = settings
        self.log("Exposing")
        if self.gate is not None:
            await asyncio.get_running_loop().run_in_executor(None, self.gate.wait, 5)
        if self.stopped:
            return []
        if not self.succeed:
            self.log("Failed: no stars")
            return [SolveResult(False, failure_reason="no stars")]
        return [SolveResult(True, ra_deg=10.5, dec_deg=41.2, rotation_deg=3.0, scale_arcsec_px=1.4)]


def _solve_world(registry, *, camera=True, mount=True, running=False, succeed=True, gate=None):
    from types import SimpleNamespace

    from galileo.control_surface.solve import register_solve_operations
    from galileo.engine.solve import EngineSolve

    parts = {"camera": SimpleNamespace(is_connected=True) if camera else None,
             "mount": SimpleNamespace(is_connected=True) if mount else None, "filter_wheel": "wheel"}
    devices = SimpleNamespace(controller=lambda pier, cat, slot="primary": parts.get(cat))
    runner = SimpleNamespace(is_running=lambda pier: running)
    made: list = []

    async def factory(pier, log):
        wf = _FakeSolveWorkflow(log, succeed, gate)
        made.append(wf)
        return wf

    solve = EngineSolve(devices, runner, factory=factory)
    register_solve_operations(registry, solve)
    return solve, made


async def _finish(registry, bus, name, args):
    """Start a long-running operation, wait for it, and return (started, finished-event payload)."""
    finished = []
    from galileo.control_surface import OperationFinished
    bus.subscribe(OperationFinished, lambda e: finished.append(dict(e.payload)))
    started = await registry.invoke(name, args, "p1", "web")
    await registry.wait_idle()
    return started, (finished[-1] if finished else None)


@pytest.mark.requirement("TC-CSURF-140")
@pytest.mark.priority("MVP")
async def test_tc_csurf_140_solve_captures_syncs_and_centres(registry, bus):
    """CSURF-140: a client solves a new frame, optionally syncing the mount to it, or centres on a J2000 target;
    the settings reach the workflow, the operation finishes once, and the solutions stay readable in solve.status."""
    from galileo.platesolve import SolveAction

    solve, made = _solve_world(registry)
    cat = {o["name"]: o for o in registry.catalogue("p1")["operations"] if o["name"].startswith("solve.")}
    assert set(cat) == {"solve.capture", "solve.sync", "solve.centre", "solve.stop", "solve.status"}
    assert cat["solve.capture"]["long_running"] and cat["solve.capture"]["needs_lease"]
    assert cat["solve.status"]["class"] == "read"

    started, done = await _finish(registry, bus, "solve.capture", {"exposure_s": 3, "binning": 2, "filter": "L"})
    assert started.ok and started.correlation_id == done["correlation_id"] and done["outcome"] == "ok"
    wf = made[0]
    assert wf.settings.action is SolveAction.NOTHING and wf.settings.exposure_s == 3 and wf.settings.binning == 2
    assert wf.settings.filter_name == "L" and wf.target is None and wf.filter_wheel is None   # factory's job
    last = solve.status("p1")["last"]
    assert last["solved"] is True and last["solutions"][0]["ra_deg"] == 10.5 and last["log"] == ["Exposing"]

    await _finish(registry, bus, "solve.sync", {})
    assert made[1].settings.action is SolveAction.SYNC

    await _finish(registry, bus, "solve.centre", {"ra_deg": 83.8, "dec_deg": -5.4, "name": "M42",
                                                  "accuracy_arcsec": 15, "max_iterations": 3})
    wf = made[2]
    assert wf.target == (83.8, -5.4, "M42")
    assert wf.settings.action is SolveAction.SLEW_TO_TARGET and wf.settings.accuracy_arcsec == 15
    assert wf.settings.max_iterations == 3
    status = (await registry.invoke("solve.status", {}, "p1", "web")).value
    assert status["running"] is False and status["last"]["solved"] is True


@pytest.mark.requirement("TC-CSURF-140")
@pytest.mark.priority("MVP")
async def test_tc_csurf_140_solve_refusals_failure_and_stop(registry, bus):
    """CSURF-140: no camera, a running session, a disconnected mount (for sync and centre), bad arguments and a
    second solve are each refused with a reason before anything moves; a failed solve says why; a running solve
    can be stopped."""
    import threading

    _solve_world(registry, camera=False)
    out = await registry.invoke("solve.capture", {}, "p1", "web")
    assert out.status == "unavailable" and "no camera" in out.reason

    r2 = Registry(bus)
    _solve_world(r2, running=True)
    assert "session is running" in (await r2.invoke("solve.capture", {}, "p1", "web")).reason

    r3 = Registry(bus)
    _, made3 = _solve_world(r3, mount=False)
    started, done = await _finish(r3, bus, "solve.capture", {})
    assert started.ok and done["outcome"] == "ok"                                  # solving alone needs no mount
    for name, args in (("solve.sync", {}), ("solve.centre", {"ra_deg": 1, "dec_deg": 2})):
        out = await r3.invoke(name, args, "p1", "web")
        assert out.status == "unavailable" and "mount is not connected" in out.reason
    assert len(made3) == 1                                                         # nothing else was started
    r3b = Registry(bus)
    _solve_world(r3b)
    for args in ({"ra_deg": 400, "dec_deg": 0}, {"ra_deg": 1}):
        assert (await r3b.invoke("solve.centre", args, "p1", "web")).status == "invalid"
    assert (await r3b.invoke("solve.capture", {"exposure_s": 0}, "p1", "web")).status == "invalid"

    r4 = Registry(bus)
    solve4, _ = _solve_world(r4, succeed=False)
    await _finish(r4, bus, "solve.capture", {})
    last = solve4.status("p1")["last"]
    assert last["solved"] is False and last["solutions"][0]["failure_reason"] == "no stars"
    assert "Failed: no stars" in last["log"]
    assert (await r4.invoke("solve.stop", {}, "p1", "web")).status == "refused"       # nothing running

    r5 = Registry(bus)
    gate = threading.Event()
    solve5, made5 = _solve_world(r5, gate=gate)
    assert (await r5.invoke("solve.capture", {}, "p1", "web")).ok
    for _ in range(200):
        await asyncio.sleep(0.01)
        if made5 and made5[0].settings is not None:
            break
    assert solve5.status("p1")["running"] is True
    second = await r5.invoke("solve.capture", {}, "p1", "web")
    assert second.status == "unavailable" and "already running" in second.reason
    assert (await r5.invoke("solve.stop", {}, "p1", "web")).ok
    await r5.wait_idle()
    last = solve5.status("p1")["last"]
    assert last["stopped"] is True and solve5.status("p1")["running"] is False


@pytest.mark.requirement("TC-CSURF-140")
@pytest.mark.priority("MVP")
async def test_tc_csurf_140_engine_builds_the_workflow_from_the_session_assembly(monkeypatch):
    """CSURF-140: the engine's workflow is the one a session's Plate Solve block makes, given the operation's log
    and the Pier's filter wheel; a solver that is not set up is refused in the solver's own words."""
    from types import SimpleNamespace

    from galileo.control_surface import Refused
    from galileo.engine import solve as engine_solve

    lines, built = [], {}

    class Workflow:
        filter_wheel = None

    def make(log=None):
        built["log"] = log
        return Workflow()

    context = SimpleNamespace(make_solve_workflow=make)

    async def fake_context(devices, pier):
        return context

    monkeypatch.setattr(engine_solve, "build_context", fake_context)
    devices = SimpleNamespace(controller=lambda pier, cat, slot="primary": "wheel" if cat == "filter_wheel" else None)
    workflow = await engine_solve.build_workflow(devices, "p1", lines.append)
    assert workflow.filter_wheel == "wheel" and built["log"] == lines.append

    def unset(log=None):
        raise RuntimeError("the plate solver is not set up - ASTAP was not found")

    context.make_solve_workflow = unset
    with pytest.raises(Refused, match="ASTAP was not found"):
        await engine_solve.build_workflow(devices, "p1", lines.append)


def _sky_world(registry, monkeypatch, *, rig=True, site=True, rotator=False):
    from types import SimpleNamespace

    from galileo.control_surface.sky import register_sky_operations
    from galileo.engine.sky import EngineSky
    from galileo.planning.sky_atlas import DeepSkyObject, ObjectType, SkyAtlas

    m42 = DeepSkyObject("Orion Nebula", ["M42", "NGC 1976"], 83.82, -5.39, ObjectType.NEBULA, 4.0, 85.0, "bright")
    m31 = DeepSkyObject("Andromeda Galaxy", ["M31", "NGC 224"], 10.68, 41.27, ObjectType.GALAXY, 3.4, 190.0)
    atlas = SkyAtlas([m42, m31])
    observatory = SimpleNamespace(name="Home", latitude=44.0 if site else None, longitude=-79.0 if site else None)
    record = SimpleNamespace(id="p1", observatory=observatory)
    devices = SimpleNamespace(pier_record=lambda pier: record if pier == "p1" else None)
    camera = SimpleNamespace(sensor_width_px=4656, sensor_height_px=3520, pixel_size_um=5.86) if rig else None
    tubes = [SimpleNamespace(focal_length_mm=1000)] if rig else []
    monkeypatch.setattr("galileo.observatory.list_optical_tubes", lambda r: tubes)
    monkeypatch.setattr("galileo.observatory.get_device_config",
                        lambda r, cat, slot="primary": camera if cat == "camera" else (object() if rotator else None))
    register_sky_operations(registry, EngineSky(devices, atlas))


@pytest.mark.requirement("TC-CSURF-130")
@pytest.mark.priority("MVP")
async def test_tc_csurf_130_sky_search_and_object_details(registry, monkeypatch):
    """CSURF-130: a client finds catalogue objects by name or designation, and reads one object's details with its
    rise, transit and set at the Pier's site; an unknown object is refused."""
    _sky_world(registry, monkeypatch)
    cat = {o["name"]: o for o in registry.catalogue("p1")["operations"] if o["name"].startswith("sky.")}
    assert set(cat) == {"sky.search", "sky.object", "sky.framing"} and cat["sky.search"]["class"] == "read"

    found = (await registry.invoke("sky.search", {"query": "m31"}, "p1", "web")).value
    assert found["total"] == 1 and found["objects"][0]["name"] == "Andromeda Galaxy"
    both = (await registry.invoke("sky.search", {"query": "", "limit": 1}, "p1", "web")).value
    assert both["total"] == 2 and len(both["objects"]) == 1                      # cut to the limit, total kept
    assert (await registry.invoke("sky.search", {"query": "x", "limit": 0}, "p1", "web")).status == "invalid"

    detail = (await registry.invoke("sky.object", {"name": "NGC 1976"}, "p1", "web")).value
    assert detail["name"] == "Orion Nebula" and detail["site"] == "Home" and detail["description"] == "bright"
    assert set(detail["rise_transit_set"]) == {"rise", "transit", "set"}
    unknown = await registry.invoke("sky.object", {"name": "Nope 9"}, "p1", "web")
    assert unknown.status == "refused" and "Nope 9" in unknown.reason

    r2 = Registry()
    _sky_world(r2, monkeypatch, site=False)
    assert (await r2.invoke("sky.object", {"name": "M42"}, "p1", "web")).value["rise_transit_set"] is None


@pytest.mark.requirement("TC-CSURF-130")
@pytest.mark.priority("MVP")
async def test_tc_csurf_130_framing_uses_the_piers_rig(registry, monkeypatch):
    """CSURF-130: the field of view comes from the Pier's own tube and camera, a mosaic is laid out around the
    position, a rotation without a rotator reports the area a covering mosaic spans, and a Pier whose camera size is
    not saved is refused rather than framed with invented figures."""
    _sky_world(registry, monkeypatch)
    out = (await registry.invoke("sky.framing", {"ra_deg": 83.8, "dec_deg": -5.4}, "p1", "web")).value
    assert out["sensor_px"] == [4656, 3520] and out["rotator"] is False
    assert out["fov_deg"][0] == pytest.approx(4656 * 5.86 / 1000 * 206.265 / 3600, rel=1e-6)
    assert out["scale_arcsec_px"] == pytest.approx(1.2087, abs=1e-3)
    assert len(out["mosaic"]["panels"]) == 1 and "rotation_note" not in out

    mosaic = (await registry.invoke(
        "sky.framing", {"ra_deg": 83.8, "dec_deg": -5.4, "cols": 2, "rows": 2, "overlap_pct": 20,
                        "rotation_deg": 90}, "p1", "web")).value
    assert [p["index"] for p in mosaic["mosaic"]["panels"]] == [0, 1, 2, 3]
    assert "no rotator" in mosaic["rotation_note"] and mosaic["cover_deg"][0] == pytest.approx(out["fov_deg"][1])
    assert (await registry.invoke("sky.framing", {"ra_deg": 1, "dec_deg": 95}, "p1", "web")).status == "invalid"

    r2 = Registry()
    _sky_world(r2, monkeypatch, rig=False)
    refused = await r2.invoke("sky.framing", {"ra_deg": 1, "dec_deg": 2}, "p1", "web")
    assert refused.status == "refused" and "focal length" in refused.reason
