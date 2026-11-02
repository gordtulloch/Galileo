# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — plugin routes, delegation over the wire and the version handshake (TC-LINK-050,
TC-LINK-080, TC-LINK-090). Continues ``test_link_net.py``."""

import aiohttp
import pytest
from aiohttp import web

from galileo.connect_link import AuditLog, PeerStore, handshake
from galileo.connect_link.certs import CertificateStore
from galileo.connect_link.pairing import PairingService
from galileo.connect_link.routes import RouteError, RouteRegistry
from galileo.connect_link.secrets_store import MemorySecretStore
from galileo.connect_link.server import ACTING_CLIENT_HEADER, LinkServer


@pytest.fixture
def store(settings_db):
    s = PeerStore()
    s.declare_plugin("webconnect", ["control", "view"])
    s.declare_plugin("nodeconnect", ["data.push", "data.pull", "view"])
    return s


async def _hello(request, principal):
    return web.json_response({"who": principal.name})


# -- registry (no network) ---------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-050")
@pytest.mark.priority("MVP")
def test_tc_link_050_a_plugin_registers_only_under_its_own_versioned_prefix():
    """LINK-050: routes sit under /<plugin>/v<N>/, never core's or another plugin's prefix, with a
    permission a paired peer can hold; disabling the plugin removes them."""
    reg, changes = RouteRegistry(), []
    reg.on_change(changes.append)
    reg.register("webconnect", "GET", "/webconnect/v1/state", "view", _hello)
    reg.register("webconnect", "post", "/webconnect/v1/op/", "control", _hello)
    for plugin, path, perm in [
        ("connect", "/connect/v1/x", "view"),                  # core's prefix
        ("webconnect", "/nodeconnect/v1/x", "view"),            # another plugin's prefix
        ("webconnect", "/webconnect/state", "view"),            # unversioned
        ("webconnect", "/webconnect/v1/../x", "view"),
        ("webconnect", "/webconnect/v1/y", "outreach.view"),    # a guest permission
        ("webconnect", "/webconnect/v1/state", "view"),         # duplicate
    ]:
        with pytest.raises(RouteError):
            reg.register(plugin, "GET", path, perm, _hello)
    assert reg.find("POST", "/webconnect/v1/op").permission == "control" and len(reg) == 2
    assert reg.unregister_plugin("webconnect") == 2 and len(reg) == 0 and changes == [1, 2, 0]
    assert reg.find("GET", "/webconnect/v1/state") is None


@pytest.fixture
async def link(store, settings_db):
    certs = CertificateStore(MemorySecretStore(), "test-node")
    audit = AuditLog()
    server = LinkServer(store, PairingService(store), certs, audit)
    server.routes.register("webconnect", "GET", "/webconnect/v1/hello", "view", _hello)
    server.routes.register("webconnect", "POST", "/webconnect/v1/move", "control", _hello)
    await server.start("127.0.0.1", 0)
    pin = aiohttp.Fingerprint(bytes.fromhex(certs.fingerprint()))
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pin))
    yield server, session, f"https://127.0.0.1:{server.port}", audit
    await session.close()
    await server.stop()


def _auth(token, **extra):
    return {"Authorization": f"Bearer {token}", **extra}


@pytest.mark.requirement("TC-LINK-050")
@pytest.mark.priority("MVP")
async def test_tc_link_050_routes_are_hidden_until_authenticated_then_permission_checked(link, store):
    """LINK-050: an unauthenticated caller cannot tell a registered route from an unregistered one;
    an authenticated one needs the declared permission and the route's own plugin."""
    _, session, base, _ = link
    _, vt = store.create_peer("webconnect", "Viewer", ["view"])
    _, ot = store.create_peer("nodeconnect", "Node", ["view"])
    async with session.get(base + "/webconnect/v1/hello") as a, session.get(base + "/webconnect/v1/nope") as b:
        assert a.status == b.status == 401 and await a.text() == await b.text()
    async with session.get(base + "/webconnect/v1/hello", headers=_auth(vt)) as r:
        assert r.status == 200 and (await r.json()) == {"who": "Viewer"}
    async with session.post(base + "/webconnect/v1/move", headers=_auth(vt)) as r:
        assert r.status == 403                                  # lacks `control`
    async with session.get(base + "/webconnect/v1/hello", headers=_auth(ot)) as r:
        assert r.status == 403                                  # another plugin's peer
    async with session.get(base + "/webconnect/v1/nope", headers=_auth(vt)) as r:
        assert r.status == 404


@pytest.mark.requirement("TC-LINK-090")
@pytest.mark.priority("MVP")
async def test_tc_link_090_service_acts_for_a_client_with_the_clients_scopes(link, store):
    """LINK-090: a service credential presenting an acting-client header is held to that client's
    permissions, the audit names the client as actor and the service as carrier, and a revoked,
    unknown or other-plugin client, or a non-service caller, is refused."""
    _, session, base, audit = link
    svc, st = store.create_peer("webconnect", "web", ["control", "view"], is_service=True)
    viewer, _ = store.create_peer("webconnect", "Browser A", ["view"])
    operator, _ = store.create_peer("webconnect", "Browser B", ["control", "view"])
    stranger, _ = store.create_peer("nodeconnect", "Node", ["view"])

    def hdr(client):
        return _auth(st, **{ACTING_CLIENT_HEADER: client})

    async with session.post(base + "/webconnect/v1/move", headers=hdr(viewer.peer_id)) as r:
        assert r.status == 403                                  # the client may not, though the service may
    async with session.post(base + "/webconnect/v1/move", headers=hdr(operator.peer_id)) as r:
        assert r.status == 200 and (await r.json()) == {"who": "Browser B"}
    for bad in (stranger.peer_id, "nobody", svc.peer_id):
        async with session.get(base + "/webconnect/v1/hello", headers=hdr(bad)) as r:
            assert r.status == 403
    ok = [e for e in audit.query() if e.outcome == "ok" and e.route.endswith("/webconnect/v1/move")]
    assert ok and ok[0].actor == operator.peer_id and ok[0].carrier == svc.peer_id
    store.revoke(operator.peer_id)
    async with session.post(base + "/webconnect/v1/move", headers=hdr(operator.peer_id)) as r:
        assert r.status == 403
    _, plain = store.create_peer("webconnect", "Plain", ["view"])
    async with session.get(base + "/webconnect/v1/hello",
                           headers=_auth(plain, **{ACTING_CLIENT_HEADER: viewer.peer_id})) as r:
        assert r.status == 403


# -- handshake ---------------------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-080")
@pytest.mark.priority("MVP")
def test_tc_link_080_incompatible_protocol_refuses_and_schema_difference_restricts():
    """LINK-080: a protocol mismatch is refused and a schema mismatch restricts the exchange, each
    with a message a person can read; matching versions are compatible."""
    ours = {"galileo": "1", "plugin_api": "1", "schema": 33, "protocol": 1}
    assert handshake.check(ours, dict(ours)) == handshake.Compatibility(True, False, "Compatible.")
    newer = handshake.check(ours, {**ours, "protocol": 2})
    assert not newer.ok and "newer" in newer.message
    older = handshake.check({**ours, "protocol": 2}, ours)
    assert not older.ok and "older" in older.message
    diff = handshake.check(ours, {**ours, "schema": 31})
    assert diff.ok and diff.restricted and "31" in diff.message
    for junk in ({}, {"protocol": "x"}, {"protocol": 1}):
        assert not handshake.check(ours, junk).ok


@pytest.mark.requirement("TC-LINK-080")
@pytest.mark.priority("MVP")
async def test_tc_link_080_handshake_over_the_wire_with_plugin_extension(link, store):
    """LINK-080: the handshake reports the four versions, includes what a plugin adds (a failing
    extension does not break it) and judges the caller's reported versions."""
    server, session, base, _ = link
    _, tok = store.create_peer("webconnect", "Viewer", ["view"])
    server.handshake_extensions.register("webconnect", lambda: {"max_streams": 4})
    server.handshake_extensions.register("broken", lambda: 1 / 0)
    async with session.get(base + "/connect/v1/handshake") as r:
        assert r.status == 401                                  # no token, no handshake
    async with session.get(base + "/connect/v1/handshake?protocol=1&schema=-1", headers=_auth(tok)) as r:
        body = await r.json()
    assert {"galileo", "plugin_api", "schema", "protocol"} <= body.keys()
    assert body["plugins"]["webconnect"] == {"max_streams": 4} and body["plugins"]["broken"] == {}
    assert body["compatibility"]["ok"] and body["compatibility"]["restricted"]
    async with session.get(base + "/connect/v1/handshake?protocol=9&schema=1", headers=_auth(tok)) as r:
        assert (await r.json())["compatibility"]["ok"] is False
