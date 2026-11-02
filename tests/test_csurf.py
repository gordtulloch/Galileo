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
