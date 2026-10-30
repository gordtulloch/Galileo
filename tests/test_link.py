# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — Connect Link (TC-LINK-*). Covers the peer store, permissions, delegation and audit log."""

import pytest

from galileo.connect_link import AuditLog, DelegationError, GrantError, PeerError, PeerStore

NODE_PERMS = ["config.read", "config.write", "data.push", "data.pull", "view"]
APP_PERMS = ["control", "view"]


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
    s.declare_plugin("nodeconnect", NODE_PERMS)
    s.declare_plugin("webconnect", APP_PERMS)
    return s


@pytest.mark.requirement("TC-LINK-030")
@pytest.mark.priority("MVP")
def test_tc_link_030_token_authenticates_and_is_stored_only_hashed(store):
    """LINK-030: a peer's permissions are held per peer; its token is stored only as a salted hash."""
    peer, token = store.create_peer("nodeconnect", "Roof Pi", ["data.pull", "view"], kind="node")
    got = store.authenticate(token)
    assert got and got.peer_id == peer.peer_id and got.permissions == {"data.pull", "view"}

    from galileo.library.models.link import LinkPeerRecord
    row = LinkPeerRecord.get(LinkPeerRecord.peer_id == peer.peer_id)
    secret = token.split(".", 1)[1]
    assert secret not in (row.token_hash, row.token_salt, row.metadata) and row.token_hash
    assert store.authenticate(token + "x") is None
    assert store.authenticate(peer.peer_id + ".wrong") is None
    assert store.authenticate("") is None and store.authenticate("nodot") is None


@pytest.mark.requirement("TC-LINK-030")
@pytest.mark.priority("MVP")
def test_tc_link_030_grants_are_limited_to_what_the_plugin_declares(store):
    """LINK-030: a paired peer never gets outreach.view, and nothing the pairing plugin does not declare."""
    with pytest.raises(GrantError):
        store.create_peer("webconnect", "Phone", ["control", "config.write"])
    with pytest.raises(GrantError):
        store.create_peer("nodeconnect", "Node", ["outreach.view"])
    with pytest.raises(PeerError):
        store.create_peer("undeclared", "X", ["view"])
    peer, _ = store.create_peer("webconnect", "Phone", ["view"])
    with pytest.raises(GrantError):
        store.set_permissions(peer.peer_id, ["config.read"])
    assert store.set_permissions(peer.peer_id, ["control", "view"]).permissions == {"control", "view"}


@pytest.mark.requirement("TC-LINK-030")
@pytest.mark.priority("MVP")
def test_tc_link_030_revoked_and_expired_peers_stop_authenticating(store, clock):
    """LINK-030: revocation is immediate; an expired peer is refused."""
    a, ta = store.create_peer("webconnect", "A", ["view"])
    _b, tb = store.create_peer("webconnect", "B", ["view"], expires_at=clock.t + 60)
    assert store.authenticate(ta) and store.authenticate(tb)
    store.revoke(a.peer_id)
    assert store.authenticate(ta) is None
    clock.t += 61
    assert store.authenticate(tb) is None


@pytest.mark.requirement("TC-LINK-030")
@pytest.mark.priority("MVP")
def test_tc_link_030_plugin_metadata_is_deleted_with_the_peer(store):
    """LINK-030 / LINK-260: a plugin's own per-peer fields live on the peer and go when it does."""
    peer, token = store.create_peer("nodeconnect", "N", ["view"], metadata={"site": "roof"})
    assert store.set_metadata(peer.peer_id, {"site": "dome"}).metadata == {"site": "dome"}
    assert store.delete(peer.peer_id) and store.get(peer.peer_id) is None
    assert store.authenticate(token) is None
    store.create_peer("nodeconnect", "M", ["view"])
    assert store.delete_plugin_peers("nodeconnect") == 1 and store.list() == []


@pytest.mark.requirement("TC-LINK-090")
@pytest.mark.priority("MVP")
def test_tc_link_090_service_credential_acts_with_the_clients_scopes(store, clock):
    """LINK-090: the service credential resolves the named client, whose scopes (not the service's) apply."""
    service, _ = store.create_peer("webconnect", "web", ["control", "view"], is_service=True)
    client, _ = store.create_peer("webconnect", "Browser", ["view"])
    resolved = store.resolve_client(service, client.peer_id)
    assert resolved.peer_id == client.peer_id and resolved.permissions == {"view"}


@pytest.mark.requirement("TC-LINK-090")
@pytest.mark.priority("MVP")
def test_tc_link_090_delegation_refusals(store, clock):
    """LINK-090: revoked, expired, unknown, other-plugin and service-as-client are refused; a client
    cannot delegate; a service credential never holds config.*."""
    service, _ = store.create_peer("webconnect", "web", ["view"], is_service=True)
    revoked, _ = store.create_peer("webconnect", "R", ["view"])
    expired, _ = store.create_peer("webconnect", "E", ["view"], expires_at=clock.t + 10)
    other, _ = store.create_peer("nodeconnect", "O", ["view"])
    node_service, _ = store.create_peer("nodeconnect", "svc", ["view"], is_service=True)
    store.revoke(revoked.peer_id)
    clock.t += 11
    for client_id in (revoked.peer_id, expired.peer_id, "nope", other.peer_id, node_service.peer_id):
        with pytest.raises(DelegationError):
            store.resolve_client(service, client_id)
    plain, _ = store.create_peer("webconnect", "P", ["view"])
    with pytest.raises(DelegationError):
        store.resolve_client(plain, plain.peer_id)
    with pytest.raises(GrantError):
        store.create_peer("nodeconnect", "svc2", ["config.read"], is_service=True)


@pytest.mark.requirement("TC-LINK-240")
@pytest.mark.priority("MVP")
def test_tc_link_240_audit_records_actor_carrier_and_plugin_fields(settings_db, clock):
    """LINK-240: each event keeps time, actor, carrier, plugin, route, outcome, reason and plugin fields."""
    log = AuditLog(clock)
    assert log.write("client1", "webconnect", "/web/v1/mount/slew", "ok", carrier="service1",
                     fields={"target": "M31"})
    assert log.write("other", "webconnect", "/web/v1/x", "denied", "scope")
    mine = log.query(peer="client1")
    assert len(mine) == 1 and mine[0].carrier == "service1" and mine[0].fields == {"target": "M31"}
    assert len(log.query(peer="service1")) == 1          # findable by carrier too
    assert len(log.query()) == 2 and log.query(since=clock.t + 1) == []


@pytest.mark.requirement("TC-LINK-240")
@pytest.mark.priority("MVP")
def test_tc_link_240_audit_never_stores_secrets(settings_db, clock):
    """LINK-240: a plugin-defined field that looks like a token/secret/passphrase/guest id is dropped."""
    log = AuditLog(clock)
    log.write("a", "p", "r", "ok", fields={
        "token": "t", "Pass_Phrase": "x", "secret_key": "s", "password": "p", "guest_id": "g",
        "passphrase": "pp", "target": "M31",
    })
    assert log.query()[0].fields == {"target": "M31"}


@pytest.mark.requirement("TC-LINK-240")
@pytest.mark.priority("MVP")
def test_tc_link_240_retention_defaults_to_90_days_and_is_configurable(settings_db, clock):
    """LINK-240: retention defaults to 90 days, is an option, and prune enforces it."""
    from galileo import settings_store
    log = AuditLog(clock)
    assert log.retention_days() == 90
    day = 86400.0
    for age in (100, 40, 1):
        clock.t = 1_000_000.0 - age * day
        log.write("a", "p", f"r{age}", "ok")
    clock.t = 1_000_000.0
    assert log.prune() == 1 and {e.route for e in log.query()} == {"r40", "r1"}
    settings_store.set_setting("connect_link", "audit_retention_days", 30)
    assert log.retention_days() == 30 and log.prune() == 1 and [e.route for e in log.query()] == ["r1"]


@pytest.mark.requirement("TC-LINK-240")
@pytest.mark.priority("MVP")
def test_tc_link_240_without_a_database_logging_never_raises():
    """LINK-240: the audit log must not take the request path down when the database is unavailable."""
    assert AuditLog().write("a", "p", "r", "ok") is False
    assert AuditLog().query() == []
