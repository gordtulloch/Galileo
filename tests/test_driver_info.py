"""Driver name/version info on the Equipment pages (EQP-070).

Adapter level: ``DeviceBackend.get_driver_info`` for INDI (against the
real-protocol fake server, both connected and *not* connected) and Alpaca
(against a stubbed HTTP ``_get``). UI level: every device page shows a
"Driver info" / "Driver version" row and fills it when a device is picked.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from galileo.adapters import indi, indi_client
from galileo.adapters.alpaca import AlpacaCameraAdapter
from galileo.core.devices import DeviceCategory
from galileo.exceptions import DeviceConnectionError, DevicePropertyError

from tests.indi_fake_server import FakeIndiServer

FOCUSER = "Focuser Simulator"


@pytest.fixture
def server():
    srv = FakeIndiServer()
    yield srv
    srv.close()
    assert indi_client._registry == {}, "adapters leaked a shared INDI connection"


def _indi(server, device=FOCUSER):
    return indi.IndiFocuserAdapter(host="127.0.0.1", port=server.port, device_name=device)


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
async def test_tc_eqp_070_indi_driver_info_is_readable_without_connecting(server):
    """EQP-070: an INDI device's driver name/version can be read before it is connected, and without switching it on."""
    adapter = _indi(server)
    info = await adapter.get_driver_info()
    assert info == {
        "name": FOCUSER, "description": "indi_focuser",
        "driver_info": FOCUSER, "driver_version": "1.0",
    }
    assert not adapter.is_connected
    assert [v for _, d, n, v in server.received if d == FOCUSER and n == "CONNECTION"] == []


@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
async def test_tc_eqp_070_indi_driver_info_when_connected_matches(server):
    """EQP-070: the same driver info is reported once the device is connected."""
    adapter = _indi(server)
    before = await adapter.get_driver_info()
    await adapter.connect()
    try:
        assert await adapter.get_driver_info() == before
    finally:
        await adapter.disconnect()


@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
async def test_tc_eqp_070_indi_driver_info_for_an_unknown_device_is_an_error(server):
    """EQP-070: asking about a device the server doesn't have is reported, not silently empty."""
    with pytest.raises(DeviceConnectionError, match="no device named"):
        await _indi(server, "No Such Device").get_driver_info()


@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
async def test_tc_eqp_070_indi_driver_info_without_a_device_name_is_empty(server):
    """EQP-070: no device picked yet -> nothing to look up."""
    assert await _indi(server, "").get_driver_info() == {}


def _alpaca(values, failing=()):
    adapter = AlpacaCameraAdapter(host="h", port=1)
    reads = []

    async def fake_get(attribute):
        reads.append(attribute)
        if attribute in failing:
            raise DevicePropertyError(f"no {attribute}")
        return values.get(attribute)

    adapter._get = fake_get
    adapter.reads = reads
    return adapter


@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
async def test_tc_eqp_070_alpaca_driver_info_reads_the_ascom_common_properties():
    """EQP-070: Alpaca reports the ASCOM Name/Description/DriverInfo/DriverVersion, without connecting."""
    adapter = _alpaca({"name": "ASI294", "description": "ZWO camera", "driverinfo": "ZWO ASCOM", "driverversion": "6.5"})
    info = await adapter.get_driver_info()
    assert info == {"name": "ASI294", "description": "ZWO camera", "driver_info": "ZWO ASCOM", "driver_version": "6.5"}
    assert not adapter.is_connected and "connected" not in adapter.reads


@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
async def test_tc_eqp_070_alpaca_optional_properties_may_be_missing():
    """EQP-070: a driver that lacks an optional property still yields the rest."""
    adapter = _alpaca({"driverinfo": "Drv", "driverversion": "2"}, failing=("name", "description"))
    info = await adapter.get_driver_info()
    assert info == {"name": None, "description": None, "driver_info": "Drv", "driver_version": "2"}


@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
async def test_tc_eqp_070_alpaca_unreachable_device_fails_once_not_four_times():
    """EQP-070: a connectivity failure surfaces from the first read rather than timing out on every property."""
    adapter = _alpaca({}, failing=("driverinfo", "driverversion", "name", "description"))
    with pytest.raises(DevicePropertyError):
        await adapter.get_driver_info()
    assert adapter.reads == ["driverinfo"]


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

INFO = {"name": "X", "description": "d", "driver_info": "Acme Driver", "driver_version": "2.3"}


@pytest.fixture
def window(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "driver_info.db")
    from galileo.ui.app_window import AppWindow
    win = AppWindow()
    win.app = app
    win.lookups = []

    def fake_lookup(category, driver, server, port, device_name):
        win.lookups.append((category, driver, server, port, device_name))
        return dict(INFO) if device_name else {}

    win._lookup_driver_info = fake_lookup
    yield win
    win._window.close()
    db.close()


def _texts(page):
    return [label.text() for label in page.findChildren(QtWidgets.QLabel)]


@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("cat_id,label", [
    ("switch", "Switches"), ("flat_panel", "Flat Panel"),
    ("weather", "Weather"), ("dome", "Dome"), ("safety_monitor", "Safety Monitor"),
])
def test_tc_eqp_070_scan_pages_show_driver_info_for_the_picked_device(window, cat_id, label):
    """EQP-070: on the scan-only pages, picking a device from the results fills Driver info / version."""
    from PySide6.QtCore import Qt
    from galileo.ui.app_window import _CATEGORY_ENUM

    page = window._build_device_config_page(cat_id, label)
    assert {"Driver info", "Driver version"} <= set(_texts(page))
    assert "Acme Driver" not in _texts(page)

    results = page.findChildren(QtWidgets.QListWidget)[0]
    item = QtWidgets.QListWidgetItem("My Device (#0)")
    item.setData(Qt.UserRole, True)
    results.addItem(item)
    results.itemClicked.emit(item)

    assert {"Acme Driver", "2.3"} <= set(_texts(page))
    assert window.lookups[-1][0] == _CATEGORY_ENUM[cat_id] and window.lookups[-1][-1] == "My Device (#0)"


@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
def test_tc_eqp_070_camera_and_focuser_panels_show_driver_info_when_a_device_is_picked(window):
    """EQP-070: each camera / focuser panel has its own driver row, filled when its device is picked."""
    for build in (window._build_camera_page, window._build_focuser_page):
        page = build()
        assert {"Driver info", "Driver version"} <= set(_texts(page))
        combo = [c for c in page.findChildren(QtWidgets.QComboBox) if c.isEditable()][0]
        combo.setEditText("Some Device (#0)")
        combo.activated.emit(0)
        assert {"Acme Driver", "2.3"} <= set(_texts(page)), build.__name__


@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
def test_tc_eqp_070_rotator_page_shows_driver_info_when_a_device_is_picked(window):
    """EQP-070: the rotator page shows the driver row and fills it on device pick."""
    page = window._build_rotator_page()
    assert {"Driver info", "Driver version"} <= set(_texts(page))
    combo = [c for c in page.findChildren(QtWidgets.QComboBox) if c.isEditable()][0]
    combo.setEditText("Some Rotator (#0)")
    combo.activated.emit(0)
    assert {"Acme Driver", "2.3"} <= set(_texts(page))


@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
def test_tc_eqp_070_no_device_shows_dashes(window):
    """EQP-070: with no device chosen the row shows a dash rather than stale or blank text."""
    page = window._build_device_config_page("switch", "Switches")
    row = window._build_driver_info_row()[1]
    row({})  # applying nothing must not raise
    assert _texts(page).count("—") >= 2


@pytest.mark.requirement("TC-EQP-070")
@pytest.mark.priority("MVP")
def test_tc_eqp_070_real_lookup_reads_from_a_server_and_degrades_when_unreachable(server, tmp_path):
    """EQP-070: the pages' lookup returns the driver info from a live INDI server, and {} (not an error) when unreachable."""
    from galileo.ui.app_window import AppWindow

    # The lookup needs no window state beyond adapter construction, so run it against a stand-in
    # instead of building a whole AppWindow.
    from types import SimpleNamespace
    stand_in = SimpleNamespace(_make_adapter=AppWindow._make_adapter)
    lookup = lambda *args: AppWindow._lookup_driver_info(stand_in, DeviceCategory.FOCUSER, "INDI", *args)  # noqa: E731

    found = lookup("127.0.0.1", server.port, FOCUSER)
    assert found["driver_info"] == FOCUSER and found["driver_version"] == "1.0"

    assert lookup("127.0.0.1", server.port, "") == {}  # nothing picked
    # Nothing listens on port 1: must be reported to the log and come back empty.
    assert lookup("127.0.0.1", 1, FOCUSER) == {}
