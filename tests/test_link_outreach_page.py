# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — Options > Outreach (TC-LINK-190): opening, extending and ending an event from the page, its QR codes,
and saving the options. No keychain is touched (the test never enters a passphrase)."""

import pytest

from galileo import settings_store
from galileo.connect_link import host as host_module
from galileo.connect_link.discovery import Discovery
from galileo.connect_link.host import LinkHost
from galileo.connect_link.outreach import NAMESPACE as OUTREACH_NS
from galileo.connect_link.secrets_store import MemorySecretStore
from galileo.connect_link.service import NAMESPACE, ConnectLinkService


class FakeBackend:
    async def register(self, info):
        pass

    async def unregister(self, info):
        pass

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
    from galileo.library.models.base import db
    db.execute_sql("INSERT INTO observatories (name) VALUES ('Home')")
    db.execute_sql("INSERT INTO piers (observatory_id, name, connect_on_startup) VALUES (1, 'Pier A', 0)")
    service = ConnectLinkService(node_id="n", node_name="Home", secrets=MemorySecretStore(),
                                 transfer_root=tmp_path / "x", discovery=Discovery("n", "Home", "", FakeBackend()))
    service.outreach._passphrase_source = lambda: ""
    host = LinkHost(service)
    monkeypatch.setattr(host_module, "_host", host)
    yield host
    host.shutdown()


@pytest.fixture
def page(qt_app, link_host):
    from galileo.ui.app_window import AppWindow
    win = AppWindow()
    widget = win._build_outreach_settings_page()
    widget.show()
    qt_app.processEvents()
    yield widget._outreach
    widget.close()
    win._window.close()


def _qr_count(ui):
    return sum(1 for i in range(ui["display"].count()) if ui["display"].itemAt(i).widget() is not None)


@pytest.mark.requirement("TC-LINK-190")
@pytest.mark.priority("MVP")
def test_tc_link_190_the_page_is_in_options_with_help_and_no_event_is_open(page):
    """LINK-190: Outreach has its own Options page and built-in help, and starts with no event open and only
    Open event available."""
    from galileo.help import load as load_help
    from galileo.ui.app_window._common import OPTIONS_ITEMS
    assert ("connect_link_outreach", "Outreach", "connect_link") in OPTIONS_ITEMS
    doc = load_help("options.connect_link_outreach")
    assert doc is not None and "Open event" in {s.title for s in doc.sections.values()}
    assert "No event is open" in page["status"].text()
    assert page["open"].isEnabled() and not any(page[k].isEnabled() for k in ("extend", "end", "eject", "secret"))
    assert _qr_count(page) == 0


@pytest.mark.requirement("TC-LINK-190")
@pytest.mark.priority("MVP")
def test_tc_link_190_options_are_saved_validated_and_offer_the_piers(page, link_host, monkeypatch):
    """LINK-190 / LINK-110: the options are saved to the settings database, a public network is refused with a
    message, and the Piers to offer are listed."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    assert page["piers"].count() == 1 and page["piers"].item(0).text() == "Home / Pier A"
    page["ssid"].setText("Obs-Guest")
    page["subnets"].setText("8.8.8.0/24")
    page["save"].click()
    assert warned and "private" in warned[0]
    page["subnets"].setText("192.168.50.0/24, 10.9.0.0/16")
    page["piers"].item(0).setCheckState(Qt.CheckState.Checked)
    page["cap"].setValue(7)
    page["save"].click()
    saved = settings_store.get_namespace(OUTREACH_NS)
    assert saved["ssid"] == "Obs-Guest" and saved["subnets"] == ["192.168.50.0/24", "10.9.0.0/16"]
    assert saved["piers"] == ["1"] and saved["guest_cap"] == 7 and len(warned) == 1


@pytest.mark.requirement("TC-LINK-190")
@pytest.mark.priority("MVP")
def test_tc_link_190_opening_needs_connect_link_and_says_why(page, link_host, monkeypatch):
    """LINK-190 / LINK-210: with Connect Link not running the event does not open, and the page says so."""
    from PySide6.QtWidgets import QMessageBox
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    page["open"].click()
    assert warned and "not running" in warned[0] and "No event is open" in page["status"].text()


@pytest.mark.requirement("TC-LINK-190")
@pytest.mark.priority("MVP")
def test_tc_link_190_the_owner_opens_extends_ends_and_sees_the_codes(page, link_host, qt_app):
    """LINK-190: open an event, see time left, guests and Piers and the Wi-Fi QR code; extend it, re-issue the
    secret (the codes are redrawn), eject guests, and end it — which leaves the page ready again."""
    from PySide6.QtCore import Qt
    settings_store.set_namespace(NAMESPACE, {"enabled": True, "port": 0, "bind_host": "127.0.0.1"})
    page["ssid"].setText("Obs-Guest")
    page["subnets"].setText("192.168.50.0/24")
    page["piers"].item(0).setCheckState(Qt.CheckState.Checked)
    page["save"].click()
    link_host.acquire("webconnect", ("view",))
    page["duration"].setValue(20)
    page["open"].click()
    assert "Event open" in page["status"].text() and "Home / Pier A" in page["status"].text()
    assert link_host.service.outreach.remaining() > 19 * 60
    assert page["end"].isEnabled() and not page["open"].isEnabled() and _qr_count(page) == 1
    assert link_host.event_display()["wifi"] == "WIFI:T:nopass;S:Obs-Guest;;"
    before = link_host.service.outreach._event.secret
    page["secret"].click()
    assert link_host.service.outreach._event.secret != before
    token = link_host.service.outreach.enrol(link_host.service.outreach._event.secret, "192.168.50.7").token
    page["refresh"]()
    assert "1 visitor" in page["status"].text()
    page["extend"].click()
    assert link_host.service.outreach.remaining() > 49 * 60
    page["eject"].click()
    assert link_host.service.outreach.handle(token, "192.168.50.7", "list_piers") is None
    page["end"].click()
    assert not link_host.service.outreach.is_open and "No event is open" in page["status"].text()
    assert page["open"].isEnabled() and _qr_count(page) == 0
