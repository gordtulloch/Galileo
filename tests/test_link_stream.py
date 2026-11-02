# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — event stream, transfer, discovery and listener lifecycle (TC-LINK-040, -060, -070, -270).
Continues ``test_link_routes.py``."""

import asyncio
import hashlib

import aiohttp
import pytest
from aiohttp import web

from galileo.connect_link import AuditLog, PeerStore
from galileo.connect_link.certs import CertificateStore
from galileo.connect_link.discovery import Discovery, advert_properties, node_from_service
from galileo.connect_link.events import RESYNC, EventHub
from galileo.connect_link.pairing import PairingService
from galileo.connect_link.secrets_store import MemorySecretStore
from galileo.connect_link.server import LinkServer
from galileo.connect_link.service import LinkService
from galileo.connect_link.transfer import TransferStore


@pytest.fixture
def store(settings_db):
    s = PeerStore()
    s.declare_plugin("nodeconnect", ["data.push", "data.pull", "view", "control"])
    s.declare_plugin("webconnect", ["view", "control"])
    return s


async def _noop(request, principal):
    return web.json_response({})


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def link(store, settings_db, tmp_path):
    certs = CertificateStore(MemorySecretStore(), "test-node")
    server = LinkServer(store, PairingService(store), certs, AuditLog(),
                        transfers=TransferStore(tmp_path / "xfer"))
    server.routes.register("nodeconnect", "GET", "/nodeconnect/v1/x", "view", _noop)
    server.routes.register("webconnect", "GET", "/webconnect/v1/x", "view", _noop)
    await server.start("127.0.0.1", 0)
    pin = aiohttp.Fingerprint(bytes.fromhex(certs.fingerprint()))
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pin))
    yield server, session, f"https://127.0.0.1:{server.port}/connect/v1"
    await session.close()
    await server.stop()


# -- event stream (LINK-060) ---------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-060")
@pytest.mark.priority("MVP")
async def test_tc_link_060_hub_sequences_filters_replays_and_asks_for_resync(store):
    """LINK-060: messages carry a per-stream sequence id; a peer receives only its plugin's messages
    that its permissions allow; a reconnecting peer gets what it missed from the replay window, or is
    told to resynchronise once it has fallen off the window or the stream restarted."""
    hub = EventHub(replay=3)
    viewer, _ = store.create_peer("nodeconnect", "V", ["view"])
    other, _ = store.create_peer("webconnect", "W", ["view"])
    sub, osub = hub.subscribe(viewer), hub.subscribe(other)
    assert [hub.publish("nodeconnect", "a"), hub.publish("nodeconnect", "b", permission="control"),
            hub.publish("nodeconnect", "c")] == [1, 2, 3]
    assert (await sub.next())["id"] == 1 and (await sub.next())["id"] == 3     # no `control` message
    assert osub._queue.empty()                                                  # another plugin's stream
    hub.publish("nodeconnect", "d")
    again = hub.subscribe(viewer, last_id=1)
    assert [(await again.next())["id"] for _ in range(2)] == [3, 4]           # 2 is not for a viewer
    behind = hub.subscribe(viewer, last_id=0)
    assert (await behind.next())["type"] == RESYNC                             # window is 2..4
    assert (await hub.subscribe(viewer, last_id=99).next())["type"] == RESYNC  # ahead of us: restarted


@pytest.mark.requirement("TC-LINK-060")
@pytest.mark.priority("MVP")
async def test_tc_link_060_slow_peer_is_dropped_not_buffered_forever(store):
    """LINK-060: a peer that does not read is closed once its bounded queue fills."""
    hub = EventHub(queue_size=2)
    peer, _ = store.create_peer("nodeconnect", "V", ["view"])
    sub = hub.subscribe(peer)
    for i in range(5):
        hub.publish("nodeconnect", "m", i)
    assert sub.closed and sub.close_reason == "too slow" and hub.count() == 1
    while await sub.next() is not None:
        pass


@pytest.mark.requirement("TC-LINK-060")
@pytest.mark.priority("MVP")
async def test_tc_link_060_websocket_stream_closes_on_revoke_and_on_plugin_disable(link, store):
    """LINK-060: over the wire a peer receives pushed messages, resumes with last_id, and its stream
    is closed at once when the peer is revoked or the plugin disabled."""
    server, session, base = link
    peer, tok = store.create_peer("nodeconnect", "V", ["view"])
    ws = await session.ws_connect(base + "/events", headers=_auth(tok))
    await asyncio.sleep(0.05)
    server.events.publish("nodeconnect", "hello", {"n": 1})
    msg = await asyncio.wait_for(ws.receive_json(), 2)
    assert msg == {"id": 1, "type": "hello", "data": {"n": 1}}
    server.events.publish("nodeconnect", "later")
    store.revoke(peer.peer_id)
    closed = await asyncio.wait_for(ws.receive(), 2)
    while closed.type == aiohttp.WSMsgType.TEXT:
        closed = await asyncio.wait_for(ws.receive(), 2)
    assert closed.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED)
    async with session.get(base + "/events", headers=_auth(tok)) as r:
        assert r.status == 401
    _, tok2 = store.create_peer("nodeconnect", "V2", ["view"])
    ws2 = await session.ws_connect(base + "/events?last_id=0", headers=_auth(tok2))
    assert (await asyncio.wait_for(ws2.receive_json(), 2))["id"] == 1          # replayed from last_id=0
    server.remove_plugin("nodeconnect")
    end = await asyncio.wait_for(ws2.receive(), 2)
    while end.type == aiohttp.WSMsgType.TEXT:
        end = await asyncio.wait_for(ws2.receive(), 2)
    assert end.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED)
    assert server.routes.find("GET", "/nodeconnect/v1/x") is None and server.events.count("nodeconnect") == 0


# -- transfer (LINK-070) -------------------------------------------------------------------
async def _begin(session, base, tok, data, chunk, name="f.fits"):
    async with session.post(base + "/transfer", headers=_auth(tok), json={
            "name": name, "size": len(data), "sha256": _sha(data), "chunk_size": chunk}) as r:
        return r.status, await r.json()


async def _put(session, base, tok, tid, data, chunk, n, digest=None):
    piece = data[n * chunk:(n + 1) * chunk]
    async with session.put(f"{base}/transfer/{tid}/chunk/{n}", data=piece, headers={
            **_auth(tok), "X-Chunk-SHA256": digest or _sha(piece)}) as r:
        return r.status, await r.json()


@pytest.mark.requirement("TC-LINK-070")
@pytest.mark.priority("MVP")
async def test_tc_link_070_upload_resumes_verifies_and_is_recognised_by_hash(link, store):
    """LINK-070: an interrupted upload resumes at the first chunk not yet stored, a corrupt chunk is
    refused, the whole object is verified before it is complete, and the same object offered again is
    recognised by its hash."""
    server, session, base = link
    _, tok = store.create_peer("nodeconnect", "Node", ["data.push", "data.pull"])
    done = []
    server.transfers.on_complete(lambda peer, name, sha, path: done.append((name, sha, path.read_bytes())))
    data, chunk = bytes(range(256)) * 40, 4096                         # 10240 bytes = 3 chunks
    status, st = await _begin(session, base, tok, data, chunk)
    assert status == 200 and st["state"] == "open" and st["next_chunk"] == 0
    tid = st["transfer_id"]
    assert (await _put(session, base, tok, tid, data, chunk, 0)) == (200, {"next_chunk": 1})
    status, body = await _put(session, base, tok, tid, data, chunk, 1, digest="0" * 64)
    assert status == 422 and body["next_chunk"] == 1                   # corrupt chunk refused
    assert (await _put(session, base, tok, tid, data, chunk, 2))[0] == 409   # out of order
    # connection lost; the peer begins again and is told where to resume
    status, st = await _begin(session, base, tok, data, chunk)
    assert st["next_chunk"] == 1 and st["transfer_id"] == tid
    assert (await _put(session, base, tok, tid, data, chunk, 0))[1] == {"next_chunk": 1}   # lost-reply retry
    assert (await _put(session, base, tok, tid, data, chunk, 1))[1] == {"next_chunk": 2}
    async with session.post(f"{base}/transfer/{tid}/complete", headers=_auth(tok)) as r:
        assert r.status == 409                                         # not all there yet
    assert (await _put(session, base, tok, tid, data, chunk, 2))[1] == {"next_chunk": 3}
    async with session.post(f"{base}/transfer/{tid}/complete", headers=_auth(tok)) as r:
        assert r.status == 200 and (await r.json())["sha256"] == _sha(data)
    assert done == [("f.fits", _sha(data), data)]
    assert (await _begin(session, base, tok, data, chunk))[1]["state"] == "have"


@pytest.mark.requirement("TC-LINK-070")
@pytest.mark.priority("MVP")
async def test_tc_link_070_whole_object_mismatch_is_refused_and_restarts(link, store):
    """LINK-070: chunks that each verify but do not add up to the announced hash are not accepted."""
    _, session, base = link
    _, tok = store.create_peer("nodeconnect", "Node", ["data.push"])
    real, fake = b"A" * 100, b"B" * 100
    async with session.post(base + "/transfer", headers=_auth(tok), json={
            "name": "x", "size": 100, "sha256": _sha(real), "chunk_size": 100}) as r:
        tid = (await r.json())["transfer_id"]
    assert (await _put(session, base, tok, tid, fake, 100, 0))[0] == 200
    async with session.post(f"{base}/transfer/{tid}/complete", headers=_auth(tok)) as r:
        assert r.status == 422
    async with session.post(base + "/transfer", headers=_auth(tok), json={
            "name": "x", "size": 100, "sha256": _sha(real), "chunk_size": 100}) as r:
        assert (await r.json())["next_chunk"] == 0


@pytest.mark.requirement("TC-LINK-070")
@pytest.mark.priority("MVP")
async def test_tc_link_070_download_chunks_are_checksummed_and_scoped(link, store, tmp_path):
    """LINK-070 / LINK-030: a peer holding data.pull downloads a published object in verifiable
    chunks; one without it, and another peer's upload id, are refused."""
    server, session, base = link
    _, pull = store.create_peer("nodeconnect", "Puller", ["data.pull"])
    _, push = store.create_peer("nodeconnect", "Pusher", ["data.push"])
    _, mallory = store.create_peer("nodeconnect", "Mallory", ["data.push"])
    src = tmp_path / "frame.fits"
    blob = b"0123456789" * 1000
    src.write_bytes(blob)
    sha = server.transfers.publish_file(src)
    async with session.get(f"{base}/objects/{sha}", headers=_auth(pull)) as r:
        assert (await r.json()) == {"sha256": sha, "size": len(blob)}
    got = b""
    for n in range(3):
        async with session.get(f"{base}/objects/{sha}/chunk/{n}?chunk_size=4096", headers=_auth(pull)) as r:
            body = await r.read()
            assert r.status == 200 and r.headers["X-Chunk-SHA256"] == _sha(body)
            got += body
    assert got == blob
    async with session.get(f"{base}/objects/{sha}/chunk/3?chunk_size=4096", headers=_auth(pull)) as r:
        assert r.status == 416
    async with session.get(f"{base}/objects/{sha}", headers=_auth(push)) as r:
        assert r.status == 403
    st = (await _begin(session, base, push, blob, 4096))[1]
    async with session.put(f"{base}/transfer/{st['transfer_id']}/chunk/0", data=blob[:4096], headers={
            **_auth(mallory), "X-Chunk-SHA256": _sha(blob[:4096])}) as r:
        assert r.status == 404                                         # not Mallory's transfer


@pytest.mark.requirement("TC-LINK-070")
@pytest.mark.priority("MVP")
async def test_tc_link_070_transfers_defer_to_interactive_work(tmp_path):
    """LINK-070: while the node is busy with a session or interactive request a chunk waits."""
    busy = {"v": True}
    ts = TransferStore(tmp_path, busy_probe=lambda: busy["v"])
    data = b"x" * 10
    st = ts.begin("p", "n", 10, _sha(data), 10)
    task = asyncio.ensure_future(ts.put_chunk("p", st.transfer_id, 0, data, _sha(data)))
    await asyncio.sleep(0.3)
    assert not task.done()
    busy["v"] = False
    assert await asyncio.wait_for(task, 2) == 1


# -- discovery (LINK-040) ------------------------------------------------------------------
@pytest.mark.requirement("TC-LINK-040")
@pytest.mark.priority("MVP")
def test_tc_link_040_advertisement_carries_no_secret_and_browse_results_are_validated():
    """LINK-040: the TXT record holds only node id, protocol and role; a browsed service without an
    address or a numeric protocol is not offered as a node."""
    assert advert_properties("n1", 1, "master") == {"node_id": "n1", "protocol": "1", "role": "master"}
    props = {b"node_id": b"n2", b"protocol": b"1", b"role": b""}
    node = node_from_service("Roof Pi._galileo-link._tcp.local.", ["10.0.0.7"], 8765, props)
    assert (node.name, node.node_id, node.host, node.port, node.protocol) == ("Roof Pi", "n2", "10.0.0.7", 8765, 1)
    assert node_from_service("x._galileo-link._tcp.local.", [], 8765, props) is None
    assert node_from_service("x._galileo-link._tcp.local.", ["10.0.0.7"], 8765, {b"protocol": b"abc"}) is None


class _FakeZc:
    def __init__(self):
        self.registered, self.closed = [], False

    def register_service(self, info):
        self.registered.append(info)

    def unregister_service(self, info):
        self.registered.remove(info)

    def close(self):
        self.closed = True

    def add_service_listener(self, *a, **k):          # ServiceBrowser registers here
        pass

    def remove_service_listener(self, *a, **k):
        pass

    def async_add_service_listener(self, *a, **k):
        pass


@pytest.mark.requirement("TC-LINK-040")
@pytest.mark.priority("MVP")
def test_tc_link_040_advertise_while_running_and_withdraw_on_stop():
    """LINK-040: starting advertises the service; stopping withdraws it and releases mDNS."""
    zc = _FakeZc()
    class Browser:
        cancelled = False

        def __init__(self, *a, **k):
            pass

        def cancel(self):
            Browser.cancelled = True

    d = Discovery(lambda: zc, Browser)
    assert d.start("Home Pier!", "n1", "127.0.0.1", 8765, 1, "master")
    assert len(zc.registered) == 1 and zc.registered[0].name.startswith("Home Pier")
    props = zc.registered[0].properties
    assert props[b"node_id"] == b"n1" and b"secret" not in props
    d.stop()
    assert zc.registered == [] and zc.closed and Browser.cancelled and not d.advertising


@pytest.mark.requirement("TC-LINK-040")
@pytest.mark.priority("MVP")
def test_tc_link_040_unavailable_mdns_is_contained():
    """LINK-040: if mDNS cannot start, discovery reports False rather than failing the listener."""
    def boom():
        raise OSError("no multicast")
    d = Discovery(boom)
    assert d.start("n", "id", "127.0.0.1", 1, 1) is False and not d.advertising


# -- lifecycle (LINK-010, LINK-270) --------------------------------------------------------
async def _settle(svc):
    await asyncio.sleep(0)                      # let the marshalled reconcile start
    await asyncio.wait_for(asyncio.gather(*svc._tasks), 5)


@pytest.mark.requirement("TC-LINK-270")
@pytest.mark.priority("MVP")
async def test_tc_link_270_listener_runs_only_while_a_route_exists_and_disable_stops_all(store, settings_db, tmp_path):
    """LINK-010 / LINK-270: the first route starts the listener, removing the last stops it, and
    disabling leaves no listener, advertisement or open stream even with routes registered."""
    certs = CertificateStore(MemorySecretStore(), "test-node")
    server = LinkServer(store, PairingService(store), certs, AuditLog(), transfers=TransferStore(tmp_path))
    advertised = []

    class FakeDiscovery:
        def start(self, *a, **k):
            advertised.append(True)
            return True

        def stop(self):
            advertised.clear()

    svc = LinkService(server, FakeDiscovery(), host="127.0.0.1", port=0)       # type: ignore[arg-type]
    svc.attach_loop(asyncio.get_running_loop())
    assert not server.running
    server.routes.register("nodeconnect", "GET", "/nodeconnect/v1/x", "view", _noop)
    await _settle(svc)
    assert server.running and advertised
    peer, _ = store.create_peer("nodeconnect", "V", ["view"])
    sub = server.events.subscribe(peer)
    await svc.disable()
    assert not server.running and not advertised and sub.closed
    await svc.enable()
    assert server.running and advertised
    server.remove_plugin("nodeconnect")
    await _settle(svc)
    assert not server.running and not advertised
    await svc.shutdown()
