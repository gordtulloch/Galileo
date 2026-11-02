# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — resumable chunked transfer (TC-LINK-070). A real TLS listener on an ephemeral loopback
port, the client pinning the certificate, with small chunks so a few KiB exercise resume."""

import hashlib

import aiohttp
import pytest

from galileo.connect_link import AuditLog, PeerStore
from galileo.connect_link.certs import CertificateStore
from galileo.connect_link.pairing import PairingService
from galileo.connect_link.secrets_store import MemorySecretStore
from galileo.connect_link.server import LinkServer
from galileo.connect_link.transfer import TransferClient, TransferError, TransferService


class Env:
    busy = False


def _clock():
    return 1_000_000.0


@pytest.fixture
async def xfer(settings_db, tmp_path):
    store = PeerStore(_clock)
    store.declare_plugin("nodeconnect", ["data.push", "data.pull", "view"])
    certs = CertificateStore(MemorySecretStore(), "test-node")
    env = Env()
    service = TransferService(tmp_path / "store", busy=lambda: env.busy)
    pairing = PairingService(store, _clock)
    server = LinkServer(store, pairing, certs, AuditLog(_clock), transfers=service)
    await server.start("127.0.0.1", 0)
    pin = aiohttp.Fingerprint(bytes.fromhex(certs.fingerprint()))
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pin))
    base = f"https://127.0.0.1:{server.port}/connect/v1"

    async def auth(permissions):
        async with session.post(base + "/pair", json={"plugin": "nodeconnect", "name": "N"}) as r:
            rid = (await r.json())["request_id"]
        pairing.approve(rid, permissions)
        async with session.get(f"{base}/pair/{rid}") as r:
            return {"Authorization": f"Bearer {(await r.json())['token']}"}

    yield service, session, base, auth, env, tmp_path
    await session.close()
    await server.stop()


def _blob(tmp_path, n=5000, name="a.bin"):
    p = tmp_path / name
    p.write_bytes(bytes(i * 7 % 251 for i in range(n)))
    return p


@pytest.mark.requirement("TC-LINK-070")
@pytest.mark.priority("MVP")
async def test_tc_link_070_upload_is_chunked_verified_and_recognised_by_hash(xfer):
    """LINK-070: an object arrives in checksummed chunks, is verified whole before it is reported
    complete, and the receiver recognises it by hash so a second upload sends nothing."""
    service, session, base, auth, _, tmp = xfer
    client = TransferClient(session, base, await auth(["data.push"]), chunk=1024)
    src = _blob(tmp)
    seen = []
    sha = await client.upload(src, progress=lambda done, total: seen.append(done))
    assert sha == hashlib.sha256(src.read_bytes()).hexdigest()
    assert seen == [1024, 2048, 3072, 4096, 5000]
    assert service.has(sha) and service.object_path(sha).read_bytes() == src.read_bytes()
    assert service.received(sha) == 0
    seen.clear()
    assert await client.upload(src, progress=lambda d, t: seen.append(d)) == sha and seen == []


@pytest.mark.requirement("TC-LINK-070")
@pytest.mark.priority("MVP")
async def test_tc_link_070_interrupted_upload_resumes_from_the_last_verified_chunk(xfer):
    """LINK-070: after an interruption the receiver reports what it holds and the sender continues
    from there; a stale offset is answered 409 with the resume point."""
    service, session, base, auth, _, tmp = xfer
    headers = await auth(["data.push"])
    src = _blob(tmp)
    data = src.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    first = data[:2048]
    async with session.put(f"{base}/transfer/{sha}", params={"size": len(data), "offset": 0}, data=first,
                           headers={**headers, "X-Chunk-SHA256": hashlib.sha256(first).hexdigest()}) as r:
        assert r.status == 200 and (await r.json()) == {"complete": False, "received": 2048}
    async with session.get(f"{base}/transfer/{sha}", headers=headers) as r:
        assert (await r.json())["received"] == 2048
    stale = data[:1024]
    async with session.put(f"{base}/transfer/{sha}", params={"size": len(data), "offset": 0}, data=stale,
                           headers={**headers, "X-Chunk-SHA256": hashlib.sha256(stale).hexdigest()}) as r:
        assert r.status == 409 and (await r.json())["received"] == 2048
    seen = []
    await TransferClient(session, base, headers, chunk=1024).upload(src, progress=lambda d, t: seen.append(d))
    assert seen == [3072, 4096, 5000] and service.has(sha)


@pytest.mark.requirement("TC-LINK-070")
@pytest.mark.priority("MVP")
async def test_tc_link_070_corrupt_chunks_and_objects_are_refused(xfer):
    """LINK-070: a chunk whose checksum is wrong is refused and not kept; an object whose whole-file
    hash does not match its name is discarded and never becomes available."""
    service, session, base, auth, _, tmp = xfer
    headers = await auth(["data.push"])
    data = b"x" * 100
    sha = hashlib.sha256(data).hexdigest()
    async with session.put(f"{base}/transfer/{sha}", params={"size": 100, "offset": 0}, data=data,
                           headers={**headers, "X-Chunk-SHA256": "0" * 64}) as r:
        assert r.status == 422
    assert service.received(sha) == 0
    liar = hashlib.sha256(b"something else").hexdigest()
    async with session.put(f"{base}/transfer/{liar}", params={"size": 100, "offset": 0}, data=data,
                           headers={**headers, "X-Chunk-SHA256": hashlib.sha256(data).hexdigest()}) as r:
        assert r.status == 422
    assert not service.has(liar) and service.received(liar) == 0
    async with session.get(f"{base}/transfer/not-a-hash", headers=headers) as r:
        assert r.status == 400
    assert not list((tmp / "store" / "objects").iterdir())


@pytest.mark.requirement("TC-LINK-070")
@pytest.mark.priority("MVP")
async def test_tc_link_070_download_resumes_and_is_verified(xfer):
    """LINK-070: a download continues a partial file, checks every chunk and the whole object, and
    only then produces the destination."""
    service, session, base, auth, _, tmp = xfer
    push = TransferClient(session, base, await auth(["data.push"]), chunk=1024)
    sha = await push.upload(_blob(tmp, 4000))
    pull = TransferClient(session, base, await auth(["data.pull"]), chunk=1024)
    dest = tmp / "out" / "got.bin"
    dest.parent.mkdir()
    part = dest.with_name("got.bin.part")
    part.write_bytes(service.object_path(sha).read_bytes()[:2048])
    seen = []
    await pull.download(sha, dest, progress=lambda d, t: seen.append(d))
    assert dest.read_bytes() == service.object_path(sha).read_bytes() and not part.exists()
    assert seen == [3072, 4000]
    with pytest.raises(TransferError) as err:
        await pull.download("0" * 64, tmp / "missing.bin")
    assert err.value.status == 404


@pytest.mark.requirement("TC-LINK-070")
@pytest.mark.priority("MVP")
async def test_tc_link_070_transfers_need_data_permissions(xfer):
    """LINK-070 / LINK-030: upload needs data.push, download needs data.pull; a view-only peer can do
    neither, and an unauthenticated caller is not answered."""
    _, session, base, auth, _, _ = xfer
    sha = "a" * 64
    async with session.get(f"{base}/transfer/{sha}", headers=await auth(["view"])) as r:
        assert r.status == 403
    async with session.put(f"{base}/transfer/{sha}", params={"size": 1, "offset": 0}, data=b"x",
                           headers=await auth(["data.pull"])) as r:
        assert r.status == 403
    async with session.get(f"{base}/transfer/{sha}/chunk", params={"offset": 0, "length": 1},
                           headers=await auth(["data.push"])) as r:
        assert r.status == 403
    async with session.get(f"{base}/transfer/{sha}") as r:
        assert r.status == 401


@pytest.mark.requirement("TC-LINK-070")
@pytest.mark.priority("MVP")
async def test_tc_link_070_transfers_yield_to_a_running_session_and_are_capped(xfer):
    """LINK-070: transfers run below the session's own work and interactive requests: while the node
    is busy, or the concurrency cap is used, a chunk is refused 503 with Retry-After, while the status
    probe (an interactive-class request) still answers."""
    service, session, base, auth, env, _ = xfer
    headers = await auth(["data.push", "data.pull"])
    data = b"y" * 10
    sha = hashlib.sha256(data).hexdigest()
    put = {"headers": {**headers, "X-Chunk-SHA256": sha}, "data": data, "params": {"size": 10, "offset": 0}}
    env.busy = True
    async with session.put(f"{base}/transfer/{sha}", **put) as r:
        assert r.status == 503 and r.headers["Retry-After"]
    async with session.get(f"{base}/transfer/{sha}", headers=headers) as r:
        assert r.status == 200
    env.busy = False
    service._active = service._max_concurrent
    async with session.put(f"{base}/transfer/{sha}", **put) as r:
        assert r.status == 503
    service._active = 0
    async with session.put(f"{base}/transfer/{sha}", **put) as r:
        assert r.status == 200 and (await r.json())["complete"] is True
