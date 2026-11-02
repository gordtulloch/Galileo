# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — the Master relay (TC-LINK-220) and the spoke-held lease (TC-LEASE-070). A real TLS spoke
listener; the Master reaches it through ``HttpSpokeLink`` pinned to the spoke's certificate."""

import asyncio

import aiohttp
import pytest

from galileo.connect_link import AuditLog, PeerStore
from galileo.connect_link.certs import CertificateStore
from galileo.connect_link.gateway import Gateway, GatewayRequest
from galileo.connect_link.pairing import PairingService
from galileo.connect_link.relay import HttpSpokeLink, MasterRelay, SpokeEndpoints, qualify, split_ref
from galileo.connect_link.secrets_store import MemorySecretStore
from galileo.connect_link.server import LinkServer
from galileo.control_surface import LeaseBroker, ObservableState, OperationSpec, Registry


def _clock():
    return 1_000_000.0


def _node(name, piers):
    registry = Registry()
    calls = []
    registry.register(OperationSpec("sky.view", "read"), lambda ctx, a: f"{name}:sky")
    registry.register(OperationSpec("camera.expose", "operate", needs_lease=True),
                      lambda ctx, a: calls.append((name, ctx.principal)) or "exposing")
    leases, audit = LeaseBroker(_clock), AuditLog(_clock)
    return Gateway(registry, leases, audit, clock=_clock), leases, audit, calls, list(piers)


@pytest.fixture
async def duo(settings_db):
    """A spoke ('Backyard') with a listener, and a Master with its own gateway."""
    s_gw, s_leases, s_audit, s_calls, s_piers = _node("spoke", ["main"])
    store = PeerStore(_clock)
    store.declare_plugin("relay", ["control", "view"])
    certs = CertificateStore(MemorySecretStore(), "spoke")
    state = ObservableState()
    state.publish("main", "mount.tracking", True)

    async def preview(pier, params):
        return b"JPEGDATA" if pier == "main" else None

    pairing = PairingService(store, _clock)
    server = LinkServer(store, pairing, certs, s_audit,
                        spoke=SpokeEndpoints(s_gw, lambda: s_piers, state, preview))
    await server.start("127.0.0.1", 0)
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(
        ssl=aiohttp.Fingerprint(bytes.fromhex(certs.fingerprint()))))
    base = f"https://127.0.0.1:{server.port}/connect/v1"

    async def grant(permissions):
        async with session.post(base + "/pair", json={"plugin": "relay", "name": "Master"}) as r:
            rid = (await r.json())["request_id"]
        pairing.approve(rid, permissions)
        async with session.get(f"{base}/pair/{rid}") as r:
            data = await r.json()
        return {"Authorization": f"Bearer {data['token']}"}, {"peer_id": data["token"].split(".")[0]}

    m_gw, _, m_audit, m_calls, _ = _node("master", ["home"])
    relay = MasterRelay(m_gw, lambda: ["home"], node_name="Home", clock=_clock)
    yield relay, session, base, grant, server, s_leases, s_audit, m_audit, s_calls, m_calls, store
    await relay.close()
    await session.close()
    await server.stop()


def request(name, pier, client="browser-1", perms=("control",), **kw):
    return GatewayRequest(client_id=client, name=name, pier=pier, plugin="webconnect",
                          permissions=frozenset(perms), **kw)


def test_pier_references_round_trip():
    assert split_ref(qualify("obs2", "main")) == ("obs2", "main") and split_ref("home") == ("", "home")


@pytest.mark.requirement("TC-LINK-220")
@pytest.mark.priority("MVP")
async def test_tc_link_220_one_list_of_piers_with_the_grant_each_spoke_made(duo):
    """LINK-220: the Master lists its own Piers and those of paired spokes as one list; a view-only grant
    is shown as such; a spoke that granted nothing is absent from the list but still reported."""
    relay, session, base, grant, *_ = duo
    headers, _ = await grant(["view"])
    await relay.add_spoke("obs2", "Backyard", HttpSpokeLink(session, base, headers))
    got = {e.ref: e for e in await relay.piers()}
    assert set(got) == {"home", "obs2~main"}
    assert got["home"].local and not got["home"].view_only
    assert got["obs2~main"].view_only and got["obs2~main"].reachable and got["obs2~main"].node_name == "Backyard"
    assert relay.spoke_status()[0]["grant"] == "view"

    class NoGrant(HttpSpokeLink):
        async def whoami(self):
            return {"permissions": []}

    await relay.add_spoke("obs3", "Cabin", NoGrant(session, base, headers))
    assert {e.ref for e in await relay.piers()} == {"home", "obs2~main"}
    assert {s["node_id"]: s["grant"] for s in relay.spoke_status()} == {"obs2": "view", "obs3": "none"}
    out = await relay.invoke(request("sky.view", "obs3~main"))
    assert out.status == "refused" and "has not granted" in out.reason


@pytest.mark.requirement("TC-LINK-220")
@pytest.mark.priority("MVP")
async def test_tc_link_220_operations_state_and_previews_are_relayed_with_the_clients_identity(duo):
    """LINK-220: operations, state and previews for a spoke's Pier are relayed; the spoke audits the
    originating client as actor and the Master's peer as carrier; the Master audits it too; local Piers
    do not touch the network."""
    relay, session, base, grant, _, _, s_audit, m_audit, s_calls, m_calls, _ = duo
    headers, data = await grant(["control", "view"])
    await relay.add_spoke("obs2", "Backyard", HttpSpokeLink(session, base, headers))
    out = await relay.invoke(request("sky.view", "obs2~main"))
    assert out.ok and out.value == "spoke:sky"
    assert (await relay.state("obs2~main"))["values"] == {"mount.tracking": True}
    assert await relay.preview("obs2~main", {"size": 256}) == b"JPEGDATA"
    assert await relay.preview("obs2~nope", {}) is None
    assert (await relay.invoke(request("sky.view", "home"))).value == "master:sky"
    spoke_rows = {(e.actor, e.carrier, e.route, e.outcome) for e in s_audit.query()}
    assert ("browser-1", data["peer_id"], "op sky.view", "ok") in spoke_rows
    assert any(e.route == "op sky.view" and e.actor == "browser-1" and e.fields.get("class") == "relay"
               for e in m_audit.query())
    assert (await relay.invoke(request("sky.view", "obs2~ghost"))).status == "unavailable"
    assert (await relay.invoke(request("sky.view", "obs2~main", client=""))).status == "refused"
    assert s_calls == [] and m_calls == []


@pytest.mark.requirement("TC-LEASE-070")
@pytest.mark.priority("MVP")
async def test_tc_lease_070_a_spoke_piers_lease_is_held_on_the_spoke(duo):
    """LEASE-070: the lease for a spoke's Pier is held on that spoke, so a client of the Master contends
    with the spoke's own desktop through one lease and the Master keeps no copy."""
    relay, session, base, grant, _, s_leases, _, _, s_calls, _, _ = duo
    headers, _ = await grant(["control", "view"])
    await relay.add_spoke("obs2", "Backyard", HttpSpokeLink(session, base, headers))
    s_leases.acquire("main", "desktop")
    out = await relay.invoke(request("camera.expose", "obs2~main"))
    assert out.status == "refused" and "desktop" in out.reason and s_calls == []
    s_leases.take("main", "relay:browser-1", confirmed=True)
    assert (await relay.invoke(request("camera.expose", "obs2~main"))).ok
    assert s_calls == [("spoke", "relay:browser-1")]
    assert (await relay.invoke(request("camera.expose", "obs2~main", client="browser-2"))).status == "refused"


@pytest.mark.requirement("TC-LINK-220")
@pytest.mark.priority("MVP")
async def test_tc_link_220_a_view_only_grant_cannot_operate(duo):
    """LINK-220: a spoke that granted only view lets the Master relay reads and nothing else — the spoke
    enforces it, whatever the Master's client claims."""
    relay, session, base, grant, _, s_leases, *_ = duo
    headers, _ = await grant(["view"])
    await relay.add_spoke("obs2", "Backyard", HttpSpokeLink(session, base, headers))
    s_leases.acquire("main", "relay:browser-1")
    assert (await relay.invoke(request("sky.view", "obs2~main", perms=("control",)))).ok
    out = await relay.invoke(request("camera.expose", "obs2~main", perms=("control",)))
    assert out.status == "refused" and "control" in out.reason


@pytest.mark.requirement("TC-LINK-220")
@pytest.mark.priority("MVP")
async def test_tc_link_220_unreachable_spoke_is_reported_and_reattaches_without_repairing(duo):
    """LINK-220: an unreachable spoke is reported with the time last heard and operations to it are
    refused with that reason; when it returns the relay re-attaches with the same token."""
    relay, session, base, grant, server, *_ = duo
    headers, _ = await grant(["control", "view"])
    await relay.add_spoke("obs2", "Backyard", HttpSpokeLink(session, base, headers))
    port = server.port
    await server.stop()
    out = await relay.invoke(request("sky.view", "obs2~main"))
    assert out.status == "unreachable" and "Backyard" in out.reason and "last heard" in out.reason
    entry = next(e for e in await relay.piers() if e.ref == "obs2~main")
    assert not entry.reachable and entry.last_heard
    state = await relay.state("obs2~main")
    assert state["reachable"] is False and "last heard" in state["reason"]
    await server.start("127.0.0.1", port)
    assert await relay.refresh("obs2")
    assert (await relay.invoke(request("sky.view", "obs2~main"))).ok


@pytest.mark.requirement("TC-LINK-220")
@pytest.mark.priority("MVP")
async def test_tc_link_220_revoking_on_the_spoke_ends_access_at_once(duo):
    """LINK-220: the grant is revocable on the spoke at any time; the Master then sees the spoke as
    unreachable/denied and cannot operate."""
    relay, session, base, grant, server, *_ = duo
    headers, data = await grant(["control", "view"])
    await relay.add_spoke("obs2", "Backyard", HttpSpokeLink(session, base, headers))
    server.revoke_peer(data["peer_id"])
    assert (await relay.invoke(request("sky.view", "obs2~main"))).status == "unreachable"
    assert not await relay.refresh("obs2")


@pytest.mark.requirement("TC-LINK-220")
@pytest.mark.priority("MVP")
async def test_tc_link_220_spoke_events_are_relayed_and_resume_after_an_outage(duo):
    """LINK-220: a spoke's events reach the Master's sink; after a drop the relay reconnects by itself."""
    relay, *_ = duo
    delivered, attempts = [], []

    class Flaky:
        async def whoami(self):
            return {"permissions": ["view"]}

        async def piers(self):
            return ["main"]

        async def stream(self, sink):
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("dropped")
            sink({"type": "lease", "holder": "desktop"})
            await asyncio.sleep(3600)

    await relay.add_spoke("obs2", "Backyard", Flaky())

    async def no_sleep(_):
        await asyncio.sleep(0)

    relay.attach_events("obs2", lambda node, m: delivered.append((node, m)), retry_s=0, sleep=no_sleep)
    for _ in range(50):
        await asyncio.sleep(0.01)
        if delivered:
            break
    assert delivered == [("obs2", {"type": "lease", "holder": "desktop"})] and len(attempts) == 2
