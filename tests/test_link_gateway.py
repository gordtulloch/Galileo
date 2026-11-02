# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — the request pipeline (TC-LINK-230). Continues ``test_link_stream.py``."""

import asyncio

import pytest

from galileo.connect_link import AuditLog, PeerStore
from galileo.connect_link.gateway import (
    BUSY, CONFIG, CONFIRM, EMERGENCY, INVALID, OK, OPERATE, READ, REFUSED, UNAVAILABLE, UNREACHABLE,
    Catalogue, CatalogueError, Gateway, Operation, Request, SafetyRefusal, Unreachable,
)


def _need_ra(args):
    return None if "ra" in args else "ra required"


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


class Lease:
    def __init__(self):
        self.owner = None

    def holds(self, client_id, pier):
        return self.owner == client_id


@pytest.fixture
def env(settings_db):
    store = PeerStore()
    store.declare_plugin("mobileconnect", ["view", "control"])
    viewer, _ = store.create_peer("mobileconnect", "Viewer", ["view"])
    op, _ = store.create_peer("mobileconnect", "Operator", ["view", "control"])
    calls = []

    async def handler(client, args):
        calls.append((client.name, args))
        return {"done": True}

    async def refuse(client, args):
        raise SafetyRefusal("weather unsafe")

    async def away(client, args):
        raise Unreachable("node offline")

    async def crash(client, args):
        raise RuntimeError("boom")

    cat = Catalogue()
    for name, cls, h in [("state", READ, handler), ("slew", OPERATE, handler), ("park", CONFIRM, handler),
                         ("abort", EMERGENCY, handler), ("open_roof", OPERATE, refuse),
                         ("remote", OPERATE, away), ("bad", OPERATE, crash)]:
        cat.register(Operation(name, cls, h, validate=_need_ra if name == "slew" else (lambda a: None)))
    audit, lease, clock = AuditLog(), Lease(), Clock()
    gw = Gateway(cat, audit, lease, clock=clock, max_inflight=1, rate=(100, 10.0))
    return gw, viewer, op, lease, audit, calls, clock


async def go(gw, client, op, **kw):
    return await gw.handle(Request(client, op, **kw))


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
def test_tc_link_230_a_config_class_operation_cannot_enter_the_catalogue():
    """LINK-230 / CSURF-020: the pipeline refuses a *config*-class entry at registration."""
    async def h(c, a):
        return None
    with pytest.raises(CatalogueError):
        Catalogue().register(Operation("set_profile", CONFIG, h))
    with pytest.raises(CatalogueError):
        Catalogue().register(Operation("x", "made-up", h))


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_stages_authorise_validate_and_lease_in_order(env):
    """LINK-230: unknown ops are invalid, a viewer cannot operate, invalid arguments are refused
    before the lease is consulted, the lease is required to operate, and reads need no lease."""
    gw, viewer, op, lease, _, calls, _ = env
    assert (await go(gw, op, "nonsense")).outcome == INVALID
    assert (await go(gw, viewer, "slew", args={"ra": 1})).outcome == REFUSED
    assert (await go(gw, viewer, "state")).outcome == OK
    assert (await go(gw, op, "slew", args={})).reason == "ra required"          # validate before lease
    r = await go(gw, op, "slew", args={"ra": 1})
    assert r.outcome == REFUSED and "lease" in r.reason
    lease.owner = op.peer_id
    assert (await go(gw, op, "slew", args={"ra": 1})).outcome == OK
    assert [c[0] for c in calls] == ["Viewer", "Operator"]


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_confirm_class_needs_a_single_use_token_bound_to_the_request(env):
    """LINK-230: a confirm-class operation is held until a two-step token for exactly that request
    is presented; the token works once and not for different arguments or another client."""
    gw, _, op, lease, _, calls, clock = env
    lease.owner = op.peer_id
    first = await go(gw, op, "park", args={"mode": "home"})
    token = first.data["confirm_token"]
    assert first.outcome == REFUSED and not calls
    assert (await go(gw, op, "park", args={"mode": "other"}, confirm_token=token)).outcome == REFUSED
    token = (await go(gw, op, "park", args={"mode": "home"})).data["confirm_token"]
    assert (await go(gw, op, "park", args={"mode": "home"}, confirm_token=token)).outcome == OK
    assert (await go(gw, op, "park", args={"mode": "home"}, confirm_token=token)).outcome == REFUSED   # used
    token = (await go(gw, op, "park", args={"mode": "home"})).data["confirm_token"]
    clock.t += 31
    assert (await go(gw, op, "park", args={"mode": "home"}, confirm_token=token)).outcome == REFUSED   # expired


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_a_retried_idempotency_key_returns_the_original_result(env):
    """LINK-230: the same key from the same client runs the operation once."""
    gw, _, op, lease, _, calls, _ = env
    lease.owner = op.peer_id
    a = await go(gw, op, "slew", args={"ra": 1}, idempotency_key="k1")
    b = await go(gw, op, "slew", args={"ra": 1}, idempotency_key="k1")
    assert a is b and len(calls) == 1
    await go(gw, op, "slew", args={"ra": 2}, idempotency_key="k2")
    assert len(calls) == 2


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_safety_refusal_unreachable_and_errors_are_typed_not_swallowed(env):
    """LINK-230: a safety refusal comes back verbatim as a refusal, a relay failure as unreachable,
    an unexpected error as unavailable; none is reported as success."""
    gw, _, op, lease, _, _, clock = env
    lease.owner = op.peer_id
    r = await go(gw, op, "open_roof")
    assert (r.outcome, r.reason) == (REFUSED, "weather unsafe")
    clock.t += 11
    assert (await go(gw, op, "remote")).outcome == UNREACHABLE
    clock.t += 11
    assert (await go(gw, op, "bad")).outcome == UNAVAILABLE


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_rate_limit_and_load_never_hold_back_an_emergency_operation(env):
    """LINK-230: a client is rate-limited and a busy node refuses new work, but an emergency
    operation needs no lease, is not rate-limited and is not held back by load."""
    gw, _, op, _, _, _, clock = env
    gw._rate = (3, 10.0)
    for _ in range(3):
        assert (await go(gw, op, "state")).outcome == OK
    assert (await go(gw, op, "state")).outcome == BUSY
    for _ in range(5):
        assert (await go(gw, op, "abort")).outcome == OK
    clock.t += 11
    gate, entered = asyncio.Event(), asyncio.Event()

    async def slow(client, args):
        entered.set()
        await gate.wait()

    gw._cat.register(Operation("slow", READ, slow))
    t = asyncio.ensure_future(go(gw, op, "slow"))
    await entered.wait()
    assert (await go(gw, op, "state")).outcome == BUSY and (await go(gw, op, "abort")).outcome == OK
    gate.set()
    assert (await t).outcome == OK


@pytest.mark.requirement("TC-LINK-230")
@pytest.mark.priority("MVP")
async def test_tc_link_230_every_request_is_audited_including_refusals(env):
    """LINK-230: audit runs for ok, refused and invalid alike, naming the client and operation."""
    gw, viewer, op, _, audit, _, _ = env
    await go(gw, viewer, "state")
    await go(gw, viewer, "slew", args={"ra": 1})
    await go(gw, op, "nonsense")
    got = {(e.route, e.outcome) for e in audit.query()}
    assert {("op:state", OK), ("op:slew", REFUSED), ("op:nonsense", INVALID)} <= got
