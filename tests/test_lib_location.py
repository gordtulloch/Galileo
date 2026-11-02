# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LIB — a frame's location, Local or On Master (TC-LIB-200, TC-LIB-210, TC-LIB-220). Continues
``test_lib.py``, which covers the rest of the LIB domain."""

import hashlib

import pytest

from galileo.library.core.location import (
    LOCAL,
    ON_MASTER,
    LocationError,
    delete_local_copy,
    ensure_local,
    location_of,
    mark_on_master,
    retrieve,
    set_retriever,
)
from galileo.library.models.fits_file import fitsFile


def _catalogue_frame(tmp_path, frame_id="f1", payload=b"SIMPLE  = T" + bytes(range(256)) * 20):
    path = tmp_path / "frames" / f"{frame_id}.fits"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    fitsFile.create(fitsFileId=frame_id, fitsFileName=str(path), fitsFileHash=sha, fitsFileStarCount=87,
                    fitsFileAvgHFRArcsec=2.4, fitsFileType="Light")
    return path, sha, payload


@pytest.mark.requirement("TC-LIB-200")
@pytest.mark.priority("MVP")
def test_tc_lib_200_a_frame_is_on_master_only_after_its_hash_is_verified(settings_db, tmp_path):
    """LIB-200: a frame is Local until the holding node reports the whole file's content hash and it equals
    the catalog's; a wrong or missing hash marks nothing."""
    _, sha, _ = _catalogue_frame(tmp_path)
    assert location_of("f1") == (LOCAL, None)
    for bad in ("0" * 64, "", sha[:-1] + ("0" if sha[-1] != "0" else "1")):
        with pytest.raises(LocationError):
            mark_on_master("f1", "master-1", bad)
    assert location_of("f1") == (LOCAL, None)
    with pytest.raises(LocationError):
        mark_on_master("f1", "", sha)
    with pytest.raises(LocationError):
        mark_on_master("nope", "master-1", sha)
    mark_on_master("f1", "master-1", sha.upper())
    assert location_of("f1") == (ON_MASTER, "master-1")


@pytest.mark.requirement("TC-LIB-220")
@pytest.mark.priority("MVP")
def test_tc_lib_220_only_a_verified_on_master_frame_loses_its_local_copy_and_keeps_its_row(settings_db, tmp_path):
    """LIB-220: the local copy of a verified On Master frame can be deleted; the catalog row, hash and quality
    metrics are untouched; a Local frame is never deleted."""
    path, sha, _ = _catalogue_frame(tmp_path)
    with pytest.raises(LocationError):
        delete_local_copy("f1")
    assert path.exists()
    mark_on_master("f1", "master-1", sha)
    assert delete_local_copy("f1") is True and not path.exists()
    assert delete_local_copy("f1") is False                                   # already gone: harmless
    row = fitsFile.get(fitsFile.fitsFileId == "f1")
    assert (row.fitsFileHash, row.fitsFileStarCount, row.fitsFileAvgHFRArcsec, row.fitsFileName) == (
        sha, 87, 2.4, str(path))
    assert row.fitsFileSoftDelete in (None, False)


@pytest.mark.requirement("TC-LIB-210")
@pytest.mark.priority("MVP")
async def test_tc_lib_210_retrieve_verifies_the_hash_and_restores_the_frame(settings_db, tmp_path):
    """LIB-210: retrieving fetches the file by its hash, verifies it, restores it to its place and makes the
    frame Local; a corrupt or interrupted transfer is discarded and the frame stays On Master."""
    path, sha, payload = _catalogue_frame(tmp_path)
    mark_on_master("f1", "master-1", sha)
    path.unlink()
    asked = []

    async def corrupt(h, dest):
        asked.append(h)
        dest.write_bytes(payload[:-1] + b"X")

    with pytest.raises(LocationError, match="does not match"):
        await retrieve("f1", corrupt)
    assert location_of("f1")[0] == ON_MASTER and not path.exists() and not list(path.parent.glob("*.retrieving"))

    async def good(h, dest):
        asked.append(h)
        dest.write_bytes(payload)

    assert await retrieve("f1", good) == path
    assert asked == [sha, sha] and path.read_bytes() == payload and location_of("f1") == (LOCAL, None)
    with pytest.raises(LocationError, match="already"):
        await retrieve("f1", good)

    async def broken(h, dest):
        dest.write_bytes(b"half")
        raise ConnectionError("master went away")

    mark_on_master("f1", "master-1", sha)
    path.unlink()
    with pytest.raises(ConnectionError):
        await retrieve("f1", broken)
    assert location_of("f1")[0] == ON_MASTER and not list(path.parent.glob("*.retrieving"))


@pytest.mark.requirement("TC-LIB-210")
@pytest.mark.priority("MVP")
async def test_tc_lib_210_operations_needing_pixels_call_the_ensure_local_hook(settings_db, tmp_path):
    """LIB-210: the hook returns a Local frame's path at once, fetches an On Master one through the installed
    retriever, and says clearly when nothing can fetch it."""
    path, sha, payload = _catalogue_frame(tmp_path)
    assert await ensure_local("f1") == path
    mark_on_master("f1", "master-1", sha)
    path.unlink()
    set_retriever(None)
    with pytest.raises(LocationError, match="nothing is available"):
        await ensure_local("f1")

    async def fetch(h, dest):
        dest.write_bytes(payload)

    set_retriever(fetch)
    try:
        assert await ensure_local("f1") == path and path.exists()
    finally:
        set_retriever(None)

    async def unreachable(h, dest):
        raise ConnectionError("no route to master")

    mark_on_master("f1", "master-1", sha)
    path.unlink()
    set_retriever(unreachable)
    try:
        with pytest.raises(LocationError, match="could not be retrieved"):
            await ensure_local("f1")
    finally:
        set_retriever(None)


@pytest.mark.requirement("TC-LIB-210")
@pytest.mark.priority("MVP")
async def test_tc_lib_210_retrieval_over_connect_link_uses_data_pull(settings_db, tmp_path):
    """LIB-210: the file comes back over Connect Link under data.pull, by its content hash, through the
    resumable transfer — end to end against a real listener."""
    import aiohttp

    from galileo.connect_link import AuditLog, PeerStore
    from galileo.connect_link.certs import CertificateStore
    from galileo.connect_link.pairing import PairingService
    from galileo.connect_link.secrets_store import MemorySecretStore
    from galileo.connect_link.server import LinkServer
    from galileo.connect_link.transfer import TransferClient, TransferService

    def clock():
        return 1_000_000.0

    path, sha, payload = _catalogue_frame(tmp_path)
    service = TransferService(tmp_path / "master-store")
    upload = tmp_path / "upload.bin"
    upload.write_bytes(payload)
    store = PeerStore(clock)
    store.declare_plugin("nodeconnect", ["data.push", "data.pull"])
    certs = CertificateStore(MemorySecretStore(), "master")
    pairing = PairingService(store, clock)
    server = LinkServer(store, pairing, certs, AuditLog(clock), transfers=service)
    await server.start("127.0.0.1", 0)
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(
        ssl=aiohttp.Fingerprint(bytes.fromhex(certs.fingerprint()))))
    base = f"https://127.0.0.1:{server.port}/connect/v1"
    try:
        async with session.post(base + "/pair", json={"plugin": "nodeconnect", "name": "spoke"}) as r:
            rid = (await r.json())["request_id"]
        pairing.approve(rid, ["data.push", "data.pull"])
        async with session.get(f"{base}/pair/{rid}") as r:
            headers = {"Authorization": f"Bearer {(await r.json())['token']}"}
        client = TransferClient(session, base, headers, chunk=1024)
        assert await client.upload(upload) == sha                                # the spoke gives it to the Master
        mark_on_master("f1", "master-1", sha)
        path.unlink()
        assert await retrieve("f1", client.download) == path
        assert path.read_bytes() == payload and location_of("f1")[0] == LOCAL
    finally:
        await session.close()
        await server.stop()


@pytest.mark.requirement("TC-LIB-200")
@pytest.mark.priority("MVP")
def test_tc_lib_200_integrity_check_does_not_flag_an_on_master_frame_as_missing(settings_db, tmp_path):
    """LIB-200: an On Master frame without a local file is not a problem for the integrity check; a Local
    frame that is missing still is."""
    from galileo.library.core.duplicates import verify_integrity
    _, sha1, _ = _catalogue_frame(tmp_path, "f1")
    path2, _, _ = _catalogue_frame(tmp_path, "f2", payload=b"other" * 50)
    mark_on_master("f1", "master-1", sha1)
    delete_local_copy("f1")
    path2.unlink()
    assert [(p.file.fitsFileId, p.reason) for p in verify_integrity()] == [("f2", "missing")]


@pytest.mark.requirement("TC-LIB-200")
@pytest.mark.priority("MVP")
def test_tc_lib_200_migration_adds_the_columns_with_local_as_the_default(settings_db):
    """LIB-200: existing frames become Local when the migration runs."""
    from galileo.library.models.base import db
    cols = {c.name for c in db.get_columns("fitsFile")}
    assert {"fitsFileLocation", "fitsFileHolderNode"} <= cols
    db.execute_sql("INSERT INTO fitsFile (fitsFileId) VALUES ('legacy')")
    assert db.execute_sql("SELECT fitsFileLocation, fitsFileHolderNode FROM fitsFile WHERE fitsFileId = 'legacy'"
                          ).fetchone() == ("local", None)


@pytest.mark.requirement("TC-LIB-220")
@pytest.mark.priority("MVP")
def test_tc_lib_220_images_screen_shows_the_location_and_offers_retrieve_for_an_on_master_frame(
        settings_db, tmp_path, monkeypatch):
    """LIB-220: the Images screen shows an On Master frame differently from a Local one, carries its id for the
    Retrieve action, and a double-click or Retrieve asks for the frame back before using it."""
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtCore import Qt

    from galileo.ui.library.images_widget import ImagesWidget

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    _, sha1, _ = _catalogue_frame(tmp_path, "f1")
    _catalogue_frame(tmp_path, "f2", payload=b"second" * 40)
    mark_on_master("f1", "master-1", sha1)
    delete_local_copy("f1")
    widget = ImagesWidget()
    groups = widget._query_groups("Object", False, "All", "")
    widget.file_tree.clear()
    widget._populate_tree("Object", groups)
    kids = {widget.file_tree.topLevelItem(i).child(j).data(0, Qt.ItemDataRole.UserRole): widget.file_tree.topLevelItem(i).child(j)
            for i in range(widget.file_tree.topLevelItemCount())
            for j in range(widget.file_tree.topLevelItem(i).childCount())}
    assert set(kids) == {"f1", "f2"}
    assert kids["f1"].data(8, Qt.ItemDataRole.UserRole) == "on_master" and "On the Master" in kids["f1"].toolTip(8)
    assert kids["f2"].data(8, Qt.ItemDataRole.UserRole) == "local" and kids["f2"].toolTip(8).startswith("Local file")
    asked = []
    monkeypatch.setattr(widget, "_retrieve_frame", lambda frame_id, view_after="": asked.append((frame_id, view_after)))
    viewed = []
    monkeypatch.setattr(widget, "_view_file", viewed.append)
    widget.on_item_double_clicked(kids["f1"], 0)
    widget.on_item_double_clicked(kids["f2"], 0)
    assert asked == [("f1", kids["f1"].text(10))] and viewed == [kids["f2"].text(10)]
