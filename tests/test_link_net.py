# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — certificate, pairing and listener (TC-LINK-010, TC-LINK-020). Continues ``test_link.py``;
a real TLS listener on an ephemeral loopback port, with the client pinning the certificate."""

import ssl

import aiohttp
import pytest

from galileo.connect_link import AuditLog, PeerStore
from galileo.connect_link.certs import CertificateError, CertificateStore
from galileo.connect_link.pairing import PairingService, PendingListFull, RateLimited
from galileo.connect_link.secrets_store import MemorySecretStore
from galileo.connect_link.server import LinkServer, default_bind_host


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(settings_db, clock):
    s = PeerStore(clock)
    s.declare_plugin("webconnect", ["control", "view"])
    return s


@pytest.fixture
def secrets_store():
    return MemorySecretStore()


@pytest.fixture
def certs(settings_db, secrets_store):
    return CertificateStore(secrets_store, "test-node")


@pytest.mark.requirement("TC-LINK-010")
@pytest.mark.priority("MVP")
def test_tc_link_010_certificate_generated_once_key_only_in_secret_store(certs, secrets_store):
    """LINK-010 / LINK-260: a self-signed certificate is generated on first use and reused; its
    private key is in the secret store and nowhere in the database."""
    fp = certs.fingerprint()
    assert len(fp) == 64 and CertificateStore(secrets_store).fingerprint() == fp
    from galileo.library.models.app_setting import AppSettingRecord
    stored = " ".join(r.value for r in AppSettingRecord.select())
    assert "BEGIN CERTIFICATE" in stored and "PRIVATE KEY" not in stored
    assert "PRIVATE KEY" in secrets_store.get("tls_private_key")
    assert certs.ssl_context().minimum_version >= ssl.TLSVersion.TLSv1_2


@pytest.mark.requirement("TC-LINK-010")
@pytest.mark.priority("MVP")
def test_tc_link_010_user_certificate_replaces_it_only_if_the_key_matches(certs):
    """LINK-010: a user-supplied certificate and key replace the generated pair; a mismatch is refused."""
    mine, theirs = CertificateStore(MemorySecretStore(), "mine"), CertificateStore(MemorySecretStore(), "theirs")
    cert_a, cert_b = mine.ensure(), theirs.ensure()
    key_a, key_b = mine._secrets.get("tls_private_key"), theirs._secrets.get("tls_private_key")
    assert cert_b
    before = certs.fingerprint()
    with pytest.raises(CertificateError):
        certs.install_user_pair(cert_a, key_b)
    with pytest.raises(CertificateError):
        certs.install_user_pair("garbage", key_a)
    assert certs.fingerprint() == before
    certs.install_user_pair(cert_a, key_a)
    assert certs.fingerprint() != before


@pytest.fixture
def pairing(store, clock):
    return PairingService(store, clock, expiry_s=300, max_pending=3, rate_limit=(2, 60.0))


@pytest.mark.requirement("TC-LINK-020")
@pytest.mark.priority("MVP")
def test_tc_link_020_request_held_until_approved_then_token_collected_once(pairing, store):
    """LINK-020: a request carries a confirmation code and is held; approval issues a token the
    peer collects exactly once; the token works."""
    req = pairing.request("webconnect", "Phone", "app", "ios", "10.0.0.5")
    assert len(req.code) == 6 and req.code.isdigit()
    assert pairing.pending()[0].code == req.code
    assert pairing.poll(req.request_id) == ("pending", None)
    peer = pairing.approve(req.request_id, ["view"])
    state, token = pairing.poll(req.request_id)
    assert state == "approved" and store.authenticate(token).peer_id == peer.peer_id
    assert pairing.poll(req.request_id) == ("collected", None)
    assert pairing.pending() == []


@pytest.mark.requirement("TC-LINK-020")
@pytest.mark.priority("MVP")
def test_tc_link_020_reject_expiry_rate_limit_and_capacity(pairing, clock):
    """LINK-020: rejected and expired requests yield no token; requests are rate-limited per source
    address and refused when the pending list is full."""
    r = pairing.request("webconnect", "A", "", "", "1.1.1.1")
    pairing.reject(r.request_id)
    assert pairing.poll(r.request_id) == ("rejected", None)
    e = pairing.request("webconnect", "B", "", "", "1.1.1.1")
    with pytest.raises(RateLimited):
        pairing.request("webconnect", "C", "", "", "1.1.1.1")
    clock.t += 301
    assert pairing.poll(e.request_id) == ("expired", None) and pairing.pending() == []
    for i in range(3):
        pairing.request("webconnect", f"P{i}", "", "", f"2.2.2.{i}")
    with pytest.raises(PendingListFull):
        pairing.request("webconnect", "X", "", "", "3.3.3.3")


def test_default_bind_host_is_never_the_wildcard():
    """LINK-010: the default bind address is a specific interface, never 0.0.0.0."""
    assert default_bind_host() not in ("0.0.0.0", "")  # noqa: S104


@pytest.fixture
async def link(store, certs, clock):
    audit = AuditLog(clock)
    pairing = PairingService(store, clock)
    server = LinkServer(store, pairing, certs, audit)
    await server.start("127.0.0.1", 0)
    pin = aiohttp.Fingerprint(bytes.fromhex(certs.fingerprint()))
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pin))
    yield server, pairing, session, f"https://127.0.0.1:{server.port}/connect/v1", audit
    await session.close()
    await server.stop()


@pytest.mark.requirement("TC-LINK-010")
@pytest.mark.priority("MVP")
async def test_tc_link_010_listener_serves_tls_and_answers_nothing_without_a_token(link):
    """LINK-010: HTTPS only; apart from pairing, no request without a valid token is answered, and an
    existing and a non-existent path look identical to an unauthenticated caller."""
    server, _, session, base, _ = link
    assert server.running and server.host == "127.0.0.1" and server.port
    async with session.get(base + "/whoami") as a, session.get(base + "/no/such/route") as b:
        assert a.status == b.status == 401 and await a.text() == await b.text()
    async with session.get(base + "/whoami", headers={"Authorization": "Bearer junk.junk"}) as c:
        assert c.status == 401
    await server.stop()
    assert not server.running


@pytest.mark.requirement("TC-LINK-020")
@pytest.mark.priority("MVP")
async def test_tc_link_020_pair_over_the_wire_then_revoke_takes_effect_at_once(link, store):
    """LINK-020 / LINK-030: request -> approve on the node -> poll for the token -> authenticated
    call; revoking refuses the token on its next request; the audit log recorded it."""
    _, pairing, session, base, audit = link
    async with session.post(base + "/pair", json={"plugin": "webconnect", "name": "Laptop",
                                                  "kind": "browser", "platform": "win"}) as r:
        assert r.status == 202
        body = await r.json()
    assert body["fingerprint"] and len(body["code"]) == 6
    shown = pairing.pending()[0]
    assert shown.code == body["code"] and shown.name == "Laptop"
    async with session.get(f"{base}/pair/{body['request_id']}") as r:
        assert (await r.json()) == {"state": "pending"}
    peer = pairing.approve(body["request_id"], ["view"])
    async with session.get(f"{base}/pair/{body['request_id']}") as r:
        got = await r.json()
    assert got["state"] == "approved"
    auth = {"Authorization": f"Bearer {got['token']}"}
    async with session.get(base + "/whoami", headers=auth) as r:
        assert r.status == 200 and (await r.json())["permissions"] == ["view"]
    store.revoke(peer.peer_id)
    async with session.get(base + "/whoami", headers=auth) as r:
        assert r.status == 401
    outcomes = {(e.route, e.outcome) for e in audit.query()}
    assert ("pair.request", "pending") in outcomes and ("GET /connect/v1/whoami", "ok") in outcomes


@pytest.mark.requirement("TC-LINK-020")
@pytest.mark.priority("MVP")
async def test_tc_link_020_bad_requests_and_limits_over_the_wire(link):
    """LINK-020: a malformed request is 400, and a source that asks too often gets 429."""
    _, _, session, base, _ = link
    async with session.post(base + "/pair", data="not json") as r:
        assert r.status == 400
    async with session.post(base + "/pair", json={"plugin": "webconnect"}) as r:
        assert r.status == 400
    statuses = []
    for i in range(7):
        async with session.post(base + "/pair", json={"plugin": "webconnect", "name": f"n{i}"}) as r:
            statuses.append(r.status)
    assert statuses[0] == 202 and 429 in statuses


async def _paired(pairing, session, base, permissions, plugin="webconnect"):
    async with session.post(base + "/pair", json={"plugin": plugin, "name": "P"}) as r:
        rid = (await r.json())["request_id"]
    pairing.approve(rid, permissions)
    async with session.get(f"{base}/pair/{rid}") as r:
        return {"Authorization": f"Bearer {(await r.json())['token']}"}


@pytest.mark.requirement("TC-LINK-050")
@pytest.mark.priority("MVP")
async def test_tc_link_050_plugin_routes_are_authenticated_permissioned_and_audited(link):
    """LINK-050: a registered route answers only an authenticated peer of that plugin holding its
    permission; unauthenticated callers cannot tell it from a missing path; failures are isolated."""
    server, pairing, session, base, audit = link
    root = base.removesuffix("/connect/v1")

    async def hello(peer, request):
        return {"hi": peer.name}

    async def boom(peer, request):
        raise RuntimeError("secret detail")

    server.routes.register("webconnect", "GET", "/webconnect/v1/hello", "view", hello)
    server.routes.register("webconnect", "POST", "/webconnect/v1/act", "control", hello)
    server.routes.register("webconnect", "GET", "/webconnect/v1/boom", "view", boom)
    async with session.get(root + "/webconnect/v1/hello") as a, session.get(root + "/webconnect/v1/nope") as b:
        assert a.status == b.status == 401 and await a.text() == await b.text()
    auth = await _paired(pairing, session, base, ["view"])
    async with session.get(root + "/webconnect/v1/hello", headers=auth) as r:
        assert r.status == 200 and await r.json() == {"hi": "P"}
    async with session.post(root + "/webconnect/v1/act", headers=auth) as r:
        assert r.status == 403
    async with session.get(root + "/webconnect/v1/nope", headers=auth) as r:
        assert r.status == 404
    async with session.get(root + "/webconnect/v1/boom", headers=auth) as r:
        assert r.status == 500 and "secret" not in await r.text()
    assert server.routes.unregister_plugin("webconnect") == 3
    async with session.get(root + "/webconnect/v1/hello", headers=auth) as r:
        assert r.status == 404
    outcomes = {(e.route, e.outcome) for e in audit.query()}
    assert ("POST /webconnect/v1/act", "denied") in outcomes
    assert ("GET /webconnect/v1/hello", "ok") in outcomes


@pytest.mark.requirement("TC-LINK-050")
@pytest.mark.priority("MVP")
def test_tc_link_050_a_plugin_cannot_register_outside_its_own_prefix():
    """LINK-050: no registering under another plugin's or core's prefix, an unknown permission,
    a duplicate, or an unclean path."""
    from galileo.connect_link import RouteError, RouteRegistry

    async def h(peer, request):
        return {}

    reg = RouteRegistry()
    reg.register("WebConnect", "get", "/webconnect/v1/a", "view", h)
    for plugin, path, perm in [("webconnect", "/nodeconnect/v1/a", "view"), ("connect", "/connect/v1/a", "view"),
                               ("webconnect", "/webconnect/v1/b", "root"), ("webconnect", "/webconnect/v1/a", "view"),
                               ("webconnect", "/webconnect/v1/../x", "view"), ("webconnect", "/webconnect/a", "view")]:
        with pytest.raises(RouteError):
            reg.register(plugin, "GET", path, perm, h)
    assert len(reg) == 1


@pytest.mark.requirement("TC-LINK-080")
@pytest.mark.priority("MVP")
def test_tc_link_080_handshake_refuses_protocol_restricts_schema_and_lets_a_plugin_extend():
    """LINK-080: a different protocol is refused, a different schema restricts to control/view, both
    with a readable message; a plugin adds its payload and may refuse or restrict."""
    from galileo.connect_link import Handshake, Versions
    from galileo.connect_link.handshake import OK, REFUSED, RESTRICTED, ExtensionResult, schema_level
    assert schema_level("033_add_connect_link") == 33 and schema_level("none") == 0
    hs = Handshake(lambda: Versions("1.0", "1", 33, 1))
    same = {"protocol": 1, "schema": 33}
    r = hs.evaluate("webconnect", same)
    assert r.verdict == OK and "control" in r.allowed and "data.push" in r.allowed
    r = hs.evaluate("webconnect", {"protocol": 2, "schema": 33})
    assert r.verdict == REFUSED and not r.allowed and "newer" in r.message
    r = hs.evaluate("webconnect", {"protocol": 1, "schema": 30})
    assert r.verdict == RESTRICTED and r.allowed == {"control", "view"} and "older" in r.message
    assert hs.evaluate("webconnect", {"protocol": "x"}).verdict == REFUSED
    hs.extend("WebConnect", lambda p: ExtensionResult({"streams": 8}, RESTRICTED, "Limited."))
    r = hs.evaluate("webconnect", {**same, "plugin": {}})
    assert r.plugin == {"streams": 8} and r.verdict == RESTRICTED and r.allowed == {"control", "view"}
    hs.extend("webconnect", lambda p: ExtensionResult({}, REFUSED, "No."))
    assert hs.evaluate("webconnect", same).verdict == REFUSED
    hs.remove_extension("webconnect")
    assert hs.evaluate("webconnect", same).verdict == OK


@pytest.mark.requirement("TC-LINK-080")
@pytest.mark.priority("MVP")
async def test_tc_link_080_handshake_over_the_wire(link):
    """LINK-080: an authenticated peer posts its versions and gets the verdict and this node's."""
    from galileo.connect_link import Handshake, Versions
    server, pairing, session, base, _ = link
    server.handshake = Handshake(lambda: Versions("1.0", "1", 33, 1))
    auth = await _paired(pairing, session, base, ["view"])
    async with session.post(base + "/handshake", json={"protocol": 1, "schema": 32}, headers=auth) as r:
        body = await r.json()
    assert body["verdict"] == "restricted" and body["allowed"] == ["control", "view"] and body["node"]["schema"] == 33
    async with session.post(base + "/handshake", data="x", headers=auth) as r:
        assert r.status == 400
    async with session.post(base + "/handshake", json={"protocol": 1, "schema": 33}) as r:
        assert r.status == 401


async def _stream(session, base, auth, **query):
    return await session.ws_connect(base + "/stream", headers=auth, params=query)


@pytest.mark.requirement("TC-LINK-060")
@pytest.mark.priority("MVP")
async def test_tc_link_060_stream_delivers_sequenced_messages_and_needs_a_token(link):
    """LINK-060: an authenticated peer receives plugin messages tagged with a per-stream sequence id;
    an unauthenticated one cannot open the stream."""
    server, pairing, session, base, _ = link
    with pytest.raises(aiohttp.WSServerHandshakeError):
        await session.ws_connect(base + "/stream")
    auth = await _paired(pairing, session, base, ["view"])
    ws = await _stream(session, base, auth)
    hello = await ws.receive_json(timeout=5)
    assert hello["type"] == "hello" and hello["seq"] == 0
    peer_id = (await (await session.get(base + "/whoami", headers=auth)).json())["peer_id"]
    assert server.streams.publish(peer_id, {"n": 1}) == 1
    assert server.streams.broadcast("webconnect", {"n": 2}) == 1
    assert server.streams.broadcast("nodeconnect", {"n": 3}) == 0
    assert await ws.receive_json(timeout=5) == {"seq": 1, "data": {"n": 1}}
    assert await ws.receive_json(timeout=5) == {"seq": 2, "data": {"n": 2}}
    await ws.close()


@pytest.mark.requirement("TC-LINK-060")
@pytest.mark.priority("MVP")
async def test_tc_link_060_reconnect_replays_what_was_missed_or_says_resync(link):
    """LINK-060: reconnecting with the last id replays the missed messages while they are in the
    ring; once the ring has moved on, or the epoch differs, the peer is told to resynchronise."""
    server, pairing, session, base, _ = link
    server.streams._ring_size = 3
    auth = await _paired(pairing, session, base, ["view"])
    ws = await _stream(session, base, auth)
    epoch = (await ws.receive_json(timeout=5))["epoch"]
    peer_id = (await (await session.get(base + "/whoami", headers=auth)).json())["peer_id"]
    server.streams.publish(peer_id, "a")
    assert (await ws.receive_json(timeout=5))["seq"] == 1
    await ws.close()
    for x in "bc":                                   # missed while disconnected
        server.streams.publish(peer_id, x)
    ws = await _stream(session, base, auth, last=1, epoch=epoch)
    assert (await ws.receive_json(timeout=5))["type"] == "hello"
    assert [await ws.receive_json(timeout=5) for _ in range(2)] == [{"seq": 2, "data": "b"}, {"seq": 3, "data": "c"}]
    await ws.close()
    for x in "def":                                  # the ring (3) now starts at 4
        server.streams.publish(peer_id, x)
    for q in ({"last": 1, "epoch": epoch}, {"last": 1, "epoch": "other"}, {"last": 99, "epoch": epoch},
              {"last": "x", "epoch": epoch}):
        ws = await _stream(session, base, auth, **q)
        msg = await ws.receive_json(timeout=5)
        assert msg["type"] == "resync" and msg["seq"] == 6
        await ws.close()
    ws = await _stream(session, base, auth, last=6, epoch=epoch)      # fully caught up: nothing to replay
    assert (await ws.receive_json(timeout=5))["type"] == "hello"
    await ws.close()


@pytest.mark.requirement("TC-LINK-060")
@pytest.mark.priority("MVP")
async def test_tc_link_060_revoke_disable_and_slow_peer_close_the_stream(link):
    """LINK-060: the stream closes at once when the peer is revoked or the plugin disabled, and a peer
    that cannot keep up is disconnected instead of buffering without bound."""
    server, pairing, session, base, _ = link
    auth = await _paired(pairing, session, base, ["view"])
    peer_id = (await (await session.get(base + "/whoami", headers=auth)).json())["peer_id"]
    ws = await _stream(session, base, auth)
    await ws.receive_json(timeout=5)
    server.revoke_peer(peer_id)
    assert (await ws.receive(timeout=5)).type == aiohttp.WSMsgType.CLOSE
    assert not server.streams.connected(peer_id)
    async with session.get(base + "/whoami", headers=auth) as r:
        assert r.status == 401

    auth = await _paired(pairing, session, base, ["view"])
    ws = await _stream(session, base, auth)
    await ws.receive_json(timeout=5)
    server.disable_plugin("WebConnect")
    assert (await ws.receive(timeout=5)).type == aiohttp.WSMsgType.CLOSE

    auth = await _paired(pairing, session, base, ["view"])
    peer_id = (await (await session.get(base + "/whoami", headers=auth)).json())["peer_id"]
    ws = await _stream(session, base, auth)
    await ws.receive_json(timeout=5)
    stream = server.streams._streams[peer_id]
    stream.conn.queue = type(stream.conn.queue)(maxsize=1)     # a writer that never drains
    stream.conn.queue.put_nowait("x")
    server.streams.publish(peer_id, "y")
    assert stream.conn is None
    await ws.close()
