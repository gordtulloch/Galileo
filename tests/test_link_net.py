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
