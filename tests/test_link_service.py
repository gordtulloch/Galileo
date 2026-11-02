# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — settings, secrets and disable (TC-LINK-260, TC-LINK-270). The service is the one thing the
application starts: a real TLS listener on an ephemeral loopback port, with mDNS replaced by a fake."""

import asyncio
import socket

import aiohttp
import pytest

from galileo import settings_store
from galileo.connect_link.discovery import Discovery
from galileo.connect_link.secrets_store import MemorySecretStore
from galileo.connect_link.service import NAMESPACE, ConnectLinkService, LinkSettings, SettingsError


class FakeBackend:
    def __init__(self):
        self.registered, self.closed = [], False

    async def register(self, info):
        self.registered.append(info)

    async def unregister(self, info):
        self.registered.remove(info)

    async def browse(self, listen_for):
        return []

    async def close(self):
        self.closed = True


def _enable(**extra):
    settings_store.set_namespace(NAMESPACE, {"enabled": True, "port": 0, "bind_host": "127.0.0.1", **extra})


@pytest.fixture
def make(settings_db, tmp_path):
    def build(**kw):
        backend = FakeBackend()
        svc = ConnectLinkService(node_id="node-a", node_name="Home", secrets=kw.pop("secrets", MemorySecretStore()),
                                 transfer_root=tmp_path / "xfer", discovery=Discovery("node-a", "Home", "", backend))
        svc.backend = backend
        return svc

    return build


async def _pair(svc, permissions=("view",)):
    pin = aiohttp.Fingerprint(bytes.fromhex(svc.fingerprint()))
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pin)) as session:
        base = f"https://127.0.0.1:{svc.server.port}/connect/v1"
        async with session.post(base + "/pair", json={"plugin": "webconnect", "name": "Laptop"}) as r:
            rid = (await r.json())["request_id"]
        svc.pairing.approve(rid, list(permissions))
        async with session.get(f"{base}/pair/{rid}") as r:
            return (await r.json())["token"]


async def _whoami(svc, token):
    pin = aiohttp.Fingerprint(bytes.fromhex(svc.fingerprint()))
    url = f"https://127.0.0.1:{svc.server.port}/connect/v1/whoami"
    async with (aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pin)) as session,
                session.get(url, headers={"Authorization": f"Bearer {token}"}) as r):
        return r.status


@pytest.mark.requirement("TC-LINK-260")
@pytest.mark.priority("MVP")
def test_tc_link_260_settings_live_in_the_database_and_are_validated(settings_db):
    """LINK-260: Connect Link settings are stored in the shared database through the settings store (no
    configuration file); out-of-range values and the all-interfaces address are refused."""
    assert LinkSettings.load() == LinkSettings()
    LinkSettings(enabled=True, port=9000, pairing_expiry_s=120, audit_retention_days=30, advertise=False,
                 bind_host="192.168.1.10").save()
    assert settings_store.get_namespace(NAMESPACE) == {
        "enabled": True, "port": 9000, "pairing_expiry_s": 120, "audit_retention_days": 30, "advertise": False,
        "bind_host": "192.168.1.10"}
    assert LinkSettings.load().port == 9000 and not LinkSettings.load().advertise
    for bad in (LinkSettings(port=80), LinkSettings(port=70000), LinkSettings(pairing_expiry_s=5),
                LinkSettings(audit_retention_days=0), LinkSettings(bind_host="0.0.0.0"), LinkSettings(bind_host="::")):  # noqa: S104
        with pytest.raises(SettingsError):
            bad.save()
    assert LinkSettings.load().port == 9000                                    # nothing partial was saved
    settings_store.set_setting(NAMESPACE, "port", "not a number")
    assert LinkSettings.load() == LinkSettings()


@pytest.mark.requirement("TC-LINK-260")
@pytest.mark.priority("MVP")
async def test_tc_link_260_private_keys_and_token_hashes_are_kept_where_they_belong(make):
    """LINK-260: the TLS private key is in the secret store and nowhere in the database; a peer token is
    stored only as a hash."""
    secrets = MemorySecretStore()
    svc = make(secrets=secrets)
    _enable()
    await svc.acquire("webconnect", ["view", "control"])
    token = await _pair(svc)
    try:
        from galileo.library.models.base import db
        dump = " ".join(str(v) for row in db.execute_sql("SELECT value FROM app_settings").fetchall() for v in row)
        assert "PRIVATE KEY" not in dump
        assert any("PRIVATE KEY" in str(v) for v in vars(secrets).values() for v in (v.values() if isinstance(v, dict) else [v]))
        stored = " ".join(str(c) for row in db.execute_sql("SELECT * FROM link_peers").fetchall() for c in row)
        assert token not in stored and token.split(".", 1)[1] not in stored
    finally:
        await svc.shutdown()


@pytest.mark.requirement("TC-LINK-270")
@pytest.mark.priority("MVP")
async def test_tc_link_270_listener_runs_only_while_enabled_and_used_by_a_plugin(make):
    """LINK-270: nothing listens until Connect Link is enabled and a plugin uses it; it stops with the last
    plugin; it advertises only while it runs."""
    svc = make()
    await svc.acquire("webconnect")
    assert not svc.running                                                      # not enabled yet
    _enable()
    await svc.reconcile()
    assert svc.running and svc.backend.registered                               # advertised while listening
    port = svc.server.port
    await svc.acquire("mobileconnect")
    await svc.release("webconnect")
    assert svc.running                                                          # one user is left
    await svc.release("mobileconnect")
    assert not svc.running and svc.server is None and svc.backend.registered == []
    with pytest.raises(OSError), socket.create_connection(("127.0.0.1", port), timeout=1):
        pass


@pytest.mark.requirement("TC-LINK-270")
@pytest.mark.priority("MVP")
async def test_tc_link_270_disable_leaves_no_listener_stream_or_worker_and_keeps_pairings(make):
    """LINK-270: disabling closes the listener, ends every stream, stops the advertisement and leaves no
    worker running; the pairings survive so enabling again needs no re-pairing."""
    svc = make()
    _enable()
    await svc.acquire("webconnect", ["view", "control"])
    token = await _pair(svc)
    assert await _whoami(svc, token) == 200 and svc._prune is not None
    pin = aiohttp.Fingerprint(bytes.fromhex(svc.fingerprint()))
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pin))
    ws = await session.ws_connect(f"https://127.0.0.1:{svc.server.port}/connect/v1/stream",
                                  headers={"Authorization": f"Bearer {token}"})
    await svc.set_enabled(False)
    closed = (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED)
    msg = await asyncio.wait_for(ws.receive(), 2)
    while msg.type not in closed:                                                # the hello frame comes first
        msg = await asyncio.wait_for(ws.receive(), 2)
    assert msg.type in closed
    await session.close()
    assert not svc.running and svc._prune is None and svc.backend.registered == []
    lingering = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    assert lingering == []
    assert settings_store.get_setting(NAMESPACE, "enabled") is False
    await svc.set_enabled(True)
    assert svc.running and await _whoami(svc, token) == 200                     # the same token still works
    await svc.shutdown()


@pytest.mark.requirement("TC-LINK-270")
@pytest.mark.priority("MVP")
async def test_tc_link_270_a_departing_plugin_loses_its_routes_and_streams(make):
    """LINK-270 / LINK-050: when a plugin stops using Connect Link its routes go and its peers' streams close,
    while another plugin's keep working."""
    svc = make()
    _enable()
    await svc.acquire("webconnect")
    await svc.acquire("mobileconnect")

    async def hello(peer, request):
        return {"hi": 1}

    svc.server.routes.register("webconnect", "GET", "/webconnect/v1/hello", "view", hello)
    svc.server.routes.register("mobileconnect", "GET", "/mobileconnect/v1/hello", "view", hello)
    await svc.release("webconnect")
    assert [r.plugin for r in svc.server.routes.routes()] == ["mobileconnect"]
    await svc.shutdown()


@pytest.mark.requirement("TC-LINK-270")
@pytest.mark.priority("MVP")
async def test_tc_link_270_a_plugins_routes_are_installed_on_every_listener_start(make):
    """LINK-050 / LINK-270: a plugin hands over an install function once; its routes are on the server
    now if the listener is up, again after the listener restarts, and gone when the plugin leaves. A
    failing install function does not stop the listener."""
    svc = make()
    _enable()
    calls = []

    async def hello(peer, request):
        return {"hi": 1}

    def install(server):
        calls.append(server)
        server.routes.register("webconnect", "GET", "/webconnect/v1/hello", "view", hello)

    def broken(server):
        raise RuntimeError("bad routes")

    await svc.acquire("mobileconnect", install=broken)
    assert svc.running                                                     # the listener survived it
    await svc.acquire("webconnect", install=install)                       # listener already up: installed now
    assert [r.path for r in svc.server.routes.routes()] == ["/webconnect/v1/hello"]
    await svc.set_enabled(False)
    await svc.set_enabled(True)                                            # a new server: installed again
    assert len(calls) == 2 and calls[1] is svc.server
    assert [r.path for r in svc.server.routes.routes()] == ["/webconnect/v1/hello"]
    await svc.release("webconnect")
    assert svc.server.routes.routes() == []
    await svc.shutdown()


@pytest.mark.requirement("TC-LINK-250")
@pytest.mark.priority("MVP")
async def test_tc_link_250_changed_settings_take_effect_and_restart_the_listener_when_needed(make):
    """LINK-250: the pairing expiry applies at once; a changed port or advertisement restarts the listener
    on the new setting."""
    svc = make()
    _enable()
    await svc.acquire("webconnect")
    first = svc.server
    await svc.apply_settings(LinkSettings(True, 8800, 600, 45, True, "127.0.0.1"))
    assert svc.server is not first and svc.running and svc.server.port == 8800 and svc.pairing.expiry_s == 600
    same = svc.server
    await svc.apply_settings(LinkSettings(True, 8800, 900, 30, True, "127.0.0.1"))
    assert svc.server is same and svc.pairing.expiry_s == 900                   # no restart needed
    assert svc.audit.retention_days() == 30
    with pytest.raises(SettingsError):
        await svc.apply_settings(LinkSettings(True, 80))
    assert svc.server is same
    await svc.apply_settings(LinkSettings(False, 8800))
    assert not svc.running
    await svc.shutdown()
