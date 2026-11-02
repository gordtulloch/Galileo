# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — the request pipeline (TC-LINK-230) and the lease as the pipeline applies it (TC-LEASE-060)."""

import pytest

from galileo.bus import EventBus
from galileo.connect_link import AuditLog
from galileo.connect_link.gateway import (
    CLASS_BULK,
    CLASS_EMERGENCY,
    CLASS_INTERACTIVE,
    CLASS_PREVIEW,
    Gateway,
    GatewayRequest,
    LoadGovernor,
    RateLimiter,
)
from galileo.control_surface import (
    DESKTOP,
    Arg,
    LeaseBroker,
    OperationSpec,
    RegistrationError,
    Registry,
    Refused,
    register_emergency,
)


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def rig(settings_db, clock):
    bus = EventBus()
    registry = Registry(bus)
    leases = LeaseBroker(clock, bus=bus)
    calls = []

    def record(name):
        def handler(ctx, args):
            calls.append((name, ctx.principal, dict(args)))
            return name
        return handler

    registry.register(OperationSpec("sky.view", "read"), record("sky.view"))
    registry.register(OperationSpec("camera.expose", "operate", (Arg("seconds", "float", minimum=0.001, maximum=3600),),
                                    needs_lease=True), record("camera.expose"))
    registry.register(OperationSpec("session.stop", "confirm", needs_lease=True), record("session.stop"))
    registry.register(OperationSpec("preview.render", "read"), record("preview.render"))

    def unsafe(ctx, args):
        raise Refused("Unsafe: wind 45 km/h")

    registry.register(OperationSpec("mount.unpark", "operate", needs_lease=True), unsafe)
    audit = AuditLog(clock)
    gw = Gateway(registry, leases, audit, clock=clock, guest_allowlist={"sky.view"})
    return gw, registry, leases, audit, calls


def req(name, *, args=None, perms=("control",), client="c1", pier="p1", **kw):
    return GatewayRequest(client_id=client, name=name, pier=pier, args=args or {}, plugin="webconnect",
                          permissions=frozenset(perms), **kw)


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_identify_authorise_and_validate_come_before_anything_runs(rig):
    """LINK-230: an anonymous request is refused; the permission needed depends on the class; invalid
    arguments and unknown operations are typed outcomes; nothing reaches a service in any of these cases."""
    gw, _, leases, _, calls = rig
    leases.acquire("p1", "webconnect:c1")
    assert (await gw.handle(req("sky.view", client=""))).status == "refused"
    assert (await gw.handle(req("camera.expose", args={"seconds": 5}, perms=("view",)))).status == "refused"
    assert (await gw.handle(req("camera.expose", args={"seconds": -1}))).status == "invalid"
    assert (await gw.handle(req("camera.nope"))).status == "unavailable"
    assert (await gw.handle(req("profile.edit", perms=("config.write",)))).status in ("refused", "unavailable")
    assert calls == []
    assert (await gw.handle(req("sky.view", perms=("view",)))).ok          # view is enough for a read
    assert (await gw.handle(req("camera.expose", args={"seconds": 5}))).ok
    assert [c[0] for c in calls] == ["sky.view", "camera.expose"]


@pytest.mark.requirement("TC-LEASE-060")
@pytest.mark.priority("MVP")
async def test_tc_lease_060_lease_operations_are_refused_to_non_holders_naming_the_holder(rig):
    """LEASE-060: an operation needing the lease is refused when the caller is not the holder, with the
    holder named; reads and emergency operations need no lease."""
    gw, registry, leases, _, calls = rig
    register_emergency(registry, stop_everything=lambda p: "stopped", park=lambda p: "p", close_dome=lambda p: "d")
    out = await gw.handle(req("camera.expose", args={"seconds": 1}))
    assert out.status == "refused" and "lease" in out.reason
    leases.acquire("p1", DESKTOP)
    out = await gw.handle(req("camera.expose", args={"seconds": 1}))
    assert out.status == "refused" and DESKTOP in out.reason and calls == []
    assert (await gw.handle(req("sky.view", perms=("view",)))).ok
    assert (await gw.handle(req("system.stop_everything"))).ok               # no lease needed
    leases.take("p1", "webconnect:c1", confirmed=True)
    assert (await gw.handle(req("camera.expose", args={"seconds": 1}))).ok


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_confirm_class_needs_a_two_step_single_use_token(rig):
    """LINK-230: a confirm-class operation first returns a token, runs only when it is presented back by
    the same client for the same request, and the token works once."""
    gw, _, leases, _, calls = rig
    leases.acquire("p1", "webconnect:c1")
    first = await gw.handle(req("session.stop"))
    assert first.status == "refused" and first.confirm_token and calls == []
    leases.acquire("p2", "webconnect:c2")
    other = await gw.handle(req("session.stop", client="c2", pier="p2", confirm_token=first.confirm_token))
    assert other.status == "refused"                                  # someone else's token does not work
    assert (await gw.handle(req("session.stop", confirm_token="forged"))).status == "refused"
    assert (await gw.handle(req("session.stop", confirm_token=first.confirm_token))).ok
    token = (await gw.handle(req("session.stop"))).confirm_token
    assert (await gw.handle(req("session.stop", confirm_token=token))).ok
    assert (await gw.handle(req("session.stop", confirm_token=token))).status == "refused"
    assert len(calls) == 2


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_confirm_token_expires(rig, clock):
    """LINK-230: a confirmation not used within its time is void."""
    gw, _, leases, _, calls = rig
    leases.acquire("p1", "webconnect:c1")
    token = (await gw.handle(req("session.stop"))).confirm_token
    clock.t += 61
    assert (await gw.handle(req("session.stop", confirm_token=token))).status == "refused" and calls == []


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_a_retried_idempotency_key_returns_the_original_result(rig, clock):
    """LINK-230: a retry with the same key does not run the operation again (even a confirmed one) and
    returns the original result; reusing a key for a different request is invalid; keys expire."""
    gw, _, leases, _, calls = rig
    leases.acquire("p1", "webconnect:c1")
    r1 = await gw.handle(req("camera.expose", args={"seconds": 5}, idempotency_key="k1"))
    r2 = await gw.handle(req("camera.expose", args={"seconds": 5}, idempotency_key="k1"))
    assert r1.ok and r2 == r1 and len(calls) == 1
    clash = await gw.handle(req("camera.expose", args={"seconds": 9}, idempotency_key="k1"))
    assert clash.status == "invalid" and len(calls) == 1
    token = (await gw.handle(req("session.stop", idempotency_key="k2"))).confirm_token
    done = await gw.handle(req("session.stop", confirm_token=token, idempotency_key="k2"))
    retry = await gw.handle(req("session.stop", confirm_token=token, idempotency_key="k2"))
    assert done.ok and retry == done and [c[0] for c in calls].count("session.stop") == 1
    clock.t += 601
    leases.acquire("p1", "webconnect:c1")                 # the lease itself lapsed after ten idle minutes
    await gw.handle(req("camera.expose", args={"seconds": 5}, idempotency_key="k1"))
    assert len(calls) == 3


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_safety_refusals_are_returned_verbatim(rig):
    """LINK-230 / CSURF-050: a refusal by a safety service is never swallowed or overridden."""
    gw, _, leases, _, _ = rig
    leases.acquire("p1", "webconnect:c1")
    out = await gw.handle(req("mount.unpark"))
    assert (out.status, out.reason) == ("refused", "Unsafe: wind 45 km/h")


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_every_request_is_audited_including_refusals(rig):
    """LINK-230: audit always, with the actor, carrier, plugin, route, outcome and reason; a guest's
    identifier is never stored."""
    gw, _, _, audit, _ = rig
    await gw.handle(req("camera.expose", args={"seconds": 1}))                          # refused: no lease
    await gw.handle(req("sky.view", perms=("view",), carrier="svc-1"))
    await gw.handle(GatewayRequest("guest-secret-77", "sky.view", "p1", plugin="mobileconnect", kind="guest",
                                   permissions=frozenset({"outreach.view"})))
    rows = {(e.actor, e.carrier, e.route, e.outcome) for e in audit.query()}
    assert ("c1", "", "op camera.expose", "refused") in rows
    assert ("c1", "svc-1", "op sky.view", "ok") in rows
    assert ("guest", "", "op sky.view", "ok") in rows
    assert not any("guest-secret-77" in e.actor + str(e.fields) for e in audit.query())


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_guests_see_and_use_only_the_allowlist(rig):
    """LINK-230: a guest is refused everything outside the allowlist and cannot call a write even if listed
    elsewhere; its catalogue shows only the allowlist."""
    gw, _, _, _, calls = rig

    def guest(name):
        return GatewayRequest("g", name, "p1", plugin="mobileconnect", kind="guest",
                              permissions=frozenset({"outreach.view"}))

    assert (await gw.handle(guest("sky.view"))).ok
    for name in ("camera.expose", "preview.render", "session.stop"):
        assert (await gw.handle(guest(name))).status == "refused"
    assert (await gw.handle(GatewayRequest("g", "sky.view", "p1", kind="guest",
                                           permissions=frozenset({"view"})))).status == "refused"
    assert [o["name"] for o in gw.catalogue(guest("x"))["operations"]] == ["sky.view"]
    assert len(calls) == 1


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_rate_limit_per_client(settings_db, clock):
    """LINK-230: requests are rate-limited per client; one client's burst does not affect another."""
    registry = Registry()
    registry.register(OperationSpec("sky.view", "read"), lambda ctx, a: 1)
    gw = Gateway(registry, LeaseBroker(clock), AuditLog(clock), clock=clock, limiter=RateLimiter(clock, 3, 1.0))
    results = [(await gw.handle(req("sky.view", perms=("view",)))).status for _ in range(5)]
    assert results == ["ok", "ok", "ok", "busy", "busy"]
    assert (await gw.handle(req("sky.view", perms=("view",), client="other"))).ok
    clock.t += 2
    assert (await gw.handle(req("sky.view", perms=("view",)))).ok


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
def test_tc_link_230_governor_serves_higher_classes_first():
    """LINK-230: under load a lower class is turned away first (emergency, session, interactive,
    previews, transfers); a running session makes previews and transfers yield; emergencies always run."""
    busy = [False]
    g = LoadGovernor(capacity=8, session_busy=lambda: busy[0])
    for _ in range(2):
        assert g.admit(CLASS_BULK) == ""
    assert g.admit(CLASS_BULK) != ""                       # transfers stop first (8 - 6 = 2 slots)
    for _ in range(2):
        assert g.admit(CLASS_PREVIEW) == ""
    assert g.admit(CLASS_PREVIEW) != ""
    for _ in range(2):
        assert g.admit(CLASS_INTERACTIVE) == ""
    assert g.admit(CLASS_INTERACTIVE) != ""
    assert g.admit(CLASS_EMERGENCY) == ""                  # still admitted at capacity
    fresh = LoadGovernor(session_busy=lambda: True)
    assert fresh.admit(CLASS_PREVIEW) == "yielding to the running session"
    assert fresh.admit(CLASS_INTERACTIVE) == ""


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
def test_tc_link_230_start_up_rejects_a_config_entry(settings_db, clock):
    """LINK-230 / CSURF-020: the gateway re-checks the catalogue at start-up and refuses to start with a
    class *config* entry in it."""
    registry = Registry()
    registry._ops["profile.edit"] = (OperationSpec("profile.edit", "config"), lambda ctx, a: None)
    with pytest.raises(RegistrationError):
        Gateway(registry, LeaseBroker(clock), AuditLog(clock), clock=clock)
