# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — Options > Connect Link (TC-LINK-250): the listener's state, pairing approvals and paired devices,
driven through the page's own controls. The host is built on in-memory secrets and a fake mDNS backend, so
no keychain, network or multicast is touched."""

import aiohttp
import pytest

from galileo.connect_link import host as host_module
from galileo.connect_link.discovery import Discovery
from galileo.connect_link.host import LinkHost
from galileo.connect_link.secrets_store import MemorySecretStore
from galileo.connect_link.service import NAMESPACE, ConnectLinkService


class FakeBackend:
    def __init__(self):
        self.registered = []

    async def register(self, info):
        self.registered.append(info)

    async def unregister(self, info):
        self.registered.remove(info)

    async def browse(self, listen_for):
        return []

    async def close(self):
        pass


@pytest.fixture
def qt_app():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def link_host(settings_db, tmp_path, monkeypatch):
    backend = FakeBackend()
    service = ConnectLinkService(node_id="node-a", node_name="Home", secrets=MemorySecretStore(),
                                 transfer_root=tmp_path / "xfer", discovery=Discovery("node-a", "Home", "", backend))
    host = LinkHost(service)
    host.backend = backend
    monkeypatch.setattr(host_module, "_host", host)
    yield host
    host.shutdown()


@pytest.fixture
def page(qt_app, link_host):
    from galileo.ui.app_window import AppWindow
    win = AppWindow()
    widget = win._build_connect_link_settings_page()
    widget.show()
    qt_app.processEvents()
    yield widget._connect_link, win
    widget.close()
    win._window.close()


@pytest.mark.requirement("TC-LINK-250")
@pytest.mark.priority("MVP")
def test_tc_link_250_the_page_is_in_options_with_help_and_starts_off(page, link_host):
    """LINK-250: Connect Link has its own page in Options, with built-in help, and a user who never enables it
    has no thread, no listener and no certificate."""
    from galileo.help import load as load_help
    from galileo.ui.app_window._common import OPTIONS_ITEMS
    ui, _ = page
    assert ("connect_link", "Connect Link", "connect_link") in OPTIONS_ITEMS
    assert not ui["enable"].isChecked() and "Off" in ui["status"].text()
    assert ui["fingerprint"].text() == "(made when first needed)"
    assert not link_host.loop_running and link_host.service.server is None
    doc = load_help("options.connect_link")
    assert doc is not None and doc.sections


@pytest.mark.requirement("TC-LINK-250")
@pytest.mark.priority("MVP")
def test_tc_link_250_enabling_without_a_plugin_listens_to_nothing_and_says_why(page, link_host):
    """LINK-250 / LINK-270: enabling stores the setting but opens nothing until a plugin uses Connect Link."""
    ui, _ = page
    ui["enable"].setChecked(True)
    ui["refresh"]()
    assert "no installed plugin" in ui["status"].text() and link_host.service.server is None
    ui["enable"].setChecked(False)
    from galileo import settings_store
    assert settings_store.get_setting(NAMESPACE, "enabled") is False


@pytest.mark.requirement("TC-LINK-250")
@pytest.mark.priority("MVP")
def test_tc_link_250_settings_are_validated_and_applied_from_the_page(page, link_host, monkeypatch):
    """LINK-250: the port, pairing lifetime and audit retention are set on the page and saved to the
    database; a value the service refuses is reported, not saved."""
    from PySide6.QtWidgets import QMessageBox
    ui, _ = page
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    ui["port"].setValue(9100)
    ui["expiry"].setValue(120)
    ui["retention"].setValue(30)
    ui["advertise"].setChecked(False)
    ui["apply"].click()
    s = link_host.settings()
    assert (s.port, s.pairing_expiry_s, s.audit_retention_days, s.advertise) == (9100, 120, 30, False)
    assert link_host.service.pairing.expiry_s == 120 and not warned


@pytest.mark.requirement("TC-LINK-250")
@pytest.mark.priority("MVP")
def test_tc_link_250_pending_requests_show_their_code_and_are_approved_or_rejected(page, link_host, monkeypatch):
    """LINK-250 / LINK-020: a pending request appears with its confirmation code; approving gives the
    permissions ticked in the dialog (config.* unticked by default) and the device can collect its token;
    rejecting refuses it."""
    from PySide6.QtWidgets import QCheckBox, QDialog
    ui, _ = page
    link_host.service.peers.declare_plugin("webconnect", ["view", "control", "config.read"])
    a = link_host.service.pairing.request("webconnect", "Tablet", "browser", "", "192.168.1.9")
    b = link_host.service.pairing.request("webconnect", "Stranger", "browser", "", "192.168.1.10")
    ui["refresh"]()
    table = ui["pending"]
    assert table.rowCount() == 2
    assert [table.item(r, 2).text() for r in range(2)] == [a.code, b.code]
    assert table.item(0, 0).text() == "Tablet" and table.item(0, 3).text() == "192.168.1.9"
    ticked = []

    def accept(dialog):
        boxes = dialog.findChildren(QCheckBox)
        ticked.extend((c.text(), c.isChecked()) for c in boxes)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", accept)
    table.selectRow(0)
    ui["approve"].click()
    assert sorted(ticked) == [("config.read", False), ("control", True), ("view", True)]
    state, token = link_host.service.pairing.poll(a.request_id)
    assert state == "approved" and token
    peer = link_host.service.peers.authenticate(token)
    assert peer is not None and peer.permissions == frozenset({"view", "control"})
    ui["refresh"]()
    assert table.rowCount() == 1 and table.item(0, 0).text() == "Stranger"
    ui["reject"].click()
    assert link_host.service.pairing.poll(b.request_id) == ("rejected", None)
    ui["refresh"]()
    assert table.rowCount() == 0 and not ui["approve"].isEnabled()
    assert ui["peers"].rowCount() == 1 and ui["peers"].item(0, 0).text() == "Tablet"
    assert ui["peers"].item(0, 5).text() == "active" and ui["peers"].item(0, 3).text() == "control, view"


@pytest.mark.requirement("TC-LINK-250")
@pytest.mark.priority("MVP")
def test_tc_link_250_revoke_takes_effect_at_once_and_delete_removes_the_device(page, link_host, monkeypatch):
    """LINK-250 / LINK-030: revoking stops the device's token at once and marks it revoked; deleting asks
    first and then removes it."""
    from PySide6.QtWidgets import QMessageBox
    ui, _ = page
    link_host.service.peers.declare_plugin("webconnect", ["view"])
    peer, token = link_host.service.peers.create_peer("webconnect", "Phone", ["view"], kind="app")
    ui["refresh"]()
    assert ui["peers"].rowCount() == 1
    ui["peers"].selectRow(0)
    ui["revoke"].click()
    assert link_host.service.peers.authenticate(token) is None
    assert ui["peers"].item(0, 5).text() == "revoked"
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    ui["delete"].click()
    assert link_host.service.peers.get(peer.peer_id) is not None
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    ui["delete"].click()
    assert link_host.service.peers.get(peer.peer_id) is None and ui["peers"].rowCount() == 0


@pytest.mark.requirement("TC-LINK-250")
@pytest.mark.priority("MVP")
def test_tc_link_250_with_a_plugin_the_listener_runs_pairs_over_the_wire_and_shuts_down(page, link_host):
    """LINK-250 / LINK-270: with Connect Link enabled and a plugin using it the listener runs on its own loop,
    the page shows where, a device pairs against it and appears in the list, and shutdown leaves no thread."""
    import asyncio

    ui, _ = page
    link_host.set_enabled(True)
    link_host.service.settings  # noqa: B018 - the settings are read from the database below
    from galileo import settings_store
    settings_store.set_namespace(NAMESPACE, {"enabled": True, "port": 0, "bind_host": "127.0.0.1"})
    link_host.acquire("webconnect", ("view", "control"))
    ui["refresh"]()
    assert link_host.status()["running"] and "Listening on 127.0.0.1" in ui["status"].text()
    assert link_host.loop_running and link_host.backend.registered

    async def pair():
        pin = aiohttp.Fingerprint(bytes.fromhex(link_host.fingerprint()))
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pin)) as session:
            base = f"https://127.0.0.1:{link_host.service.server.port}/connect/v1"
            async with session.post(base + "/pair", json={"plugin": "webconnect", "name": "Laptop"}) as r:
                return (await r.json())["code"]

    code = asyncio.run(pair())
    ui["refresh"]()
    assert ui["pending"].rowCount() == 1 and ui["pending"].item(0, 2).text() == code
    assert ui["fingerprint"].text() == link_host.fingerprint() != ""
    link_host.shutdown()
    assert not link_host.loop_running and not link_host.service.running
