# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Weather Equipment page (``AppWindow._build_weather_page``), built offscreen (EQP-WX-020).

Drives the real Qt widgets with a fake Weather Station adapter, the same
pattern test_rotator_page.py uses for EQP-ROT-010.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


class FakeWeatherStation:
    """Records nothing; reports a configurable, static set of readings."""

    def __init__(self, **readings) -> None:
        self.is_connected = True
        self.cloud_cover = 0.0
        self.wind_speed = 0.0
        self.wind_gust = 0.0
        self.humidity = 50.0
        self.temperature = 10.0
        self.dew_point = 0.0
        self.pressure = 1013.0
        self.rain_rate = 0.0
        self.rain = 0.0
        for key, value in readings.items():
            setattr(self, key, value)

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def poll(self) -> None:
        pass

    def get_capabilities(self):
        from galileo.core.capabilities import DeviceCapabilities
        return DeviceCapabilities()

    def get_properties(self) -> dict:
        return {}

    async def set_property(self, name, value) -> None:
        pass


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "weather_safety_pages.db")  # throwaway DB, never the user's
    from galileo.ui.app_window import AppWindow

    boxes: list[str] = []
    for kind in ("information", "warning"):
        monkeypatch.setattr(QtWidgets.QMessageBox, kind, staticmethod(lambda *a, **k: boxes.append(a[1])))
    win = AppWindow()
    win.boxes = boxes
    win.app = app

    from galileo.observatory import create_observatory, create_pier
    obs = create_observatory("Test Observatory")
    win._current_pier = create_pier(obs, "Test Pier")

    yield win
    win._window.close()
    db.close()


def _find(page, cls, text):
    matches = [w for w in page.findChildren(cls) if getattr(w, "text", lambda: None)() == text]
    assert matches, f"no {cls.__name__} with text {text!r}"
    return matches[0]


def _button(page, text):
    return _find(page, QtWidgets.QPushButton, text)


def _connect_weather(window, adapter):
    """Build the Weather page, and connect it to *adapter* through the real Connect button."""
    page = window._build_weather_page()
    window._connect_device_adapter = lambda *a, **k: adapter
    device_combo = [c for c in page.findChildren(QtWidgets.QComboBox) if c.isEditable()][0]
    device_combo.setEditText("Fake Weather Station")
    _button(page, "Connect").click()
    return page


def _rule_row(page, label: str) -> int:
    table = page.findChildren(QtWidgets.QTableWidget)[1]  # [0] is the connection row, [1] is the rules table
    for row in range(table.rowCount()):
        if table.item(row, 0).text().startswith(label):
            return row
    raise AssertionError(f"no rule row for {label!r}")


@pytest.mark.requirement("TC-EQP-WX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_wx_020_page_keeps_the_shared_connection_line(window):
    """EQP-WX-020: the Weather page keeps the Driver/Server/Port/Scan + Device/Connect line every Equipment page has."""
    page = window._build_weather_page()
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    assert table.horizontalHeaderItem(0).text() == "Driver"
    for text in ("Scan", "Connect", "Save"):
        _button(page, text)


@pytest.mark.requirement("TC-EQP-WX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_wx_020_default_rules_preenable_rain_and_wind(window):
    """EQP-WX-020: an unconfigured Pier's Weather screen starts with Rain/Wind Speed marked safety-related."""
    page = window._build_weather_page()
    rain_row = _rule_row(page, "Rain (now)")
    wind_row = _rule_row(page, "Wind Speed")
    rules_table = page.findChildren(QtWidgets.QTableWidget)[1]
    assert rules_table.cellWidget(rain_row, 2).findChild(QtWidgets.QCheckBox).isChecked()
    assert rules_table.cellWidget(wind_row, 2).findChild(QtWidgets.QCheckBox).isChecked()


@pytest.mark.requirement("TC-EQP-WX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_wx_020_connecting_shows_readings_and_unsafe_banner(window):
    """EQP-WX-020: connecting a station over its safety thresholds shows the live readings and an UNSAFE banner."""
    station = FakeWeatherStation(rain=1.0, wind_speed=25.0)
    page = _connect_weather(window, station)

    rules_table = page.findChildren(QtWidgets.QTableWidget)[1]
    wind_row = _rule_row(page, "Wind Speed")
    assert rules_table.item(wind_row, 1).text() == "25.0 km/h"

    banner = [w for w in page.findChildren(QtWidgets.QLabel) if "UNSAFE" in w.text()]
    assert banner, "expected an UNSAFE banner with rain + high wind"
    assert "Rain" in banner[0].text() and "Wind" in banner[0].text()


class FakeSafetyMonitor:
    def __init__(self, is_safe: bool) -> None:
        self.is_connected = True
        self.is_safe = is_safe

    async def disconnect(self) -> None:
        pass

    async def poll(self) -> None:
        pass


def _tabs(page):
    return page.findChild(QtWidgets.QTabWidget)


def _add_device(page, window, label):
    """Pick *label* from the "+" button's menu."""
    menu = _button(page, "+").menu()
    [a for a in menu.actions() if a.text() == label][0].trigger()


@pytest.mark.requirement("TC-EQP-WX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_wx_020_screen_is_named_safety_with_a_plus_button(window):
    """EQP-WX-020: the Equipment screen is titled Safety, starts with one weather tab, and offers a + to add devices."""
    from galileo.ui.app_window import EQUIPMENT_CATEGORIES
    assert ("weather", "Safety", "safety") in EQUIPMENT_CATEGORIES
    page = window._build_weather_page()
    assert "Safety" in [w.text() for w in page.findChildren(QtWidgets.QLabel)]
    assert _tabs(page).count() == 1
    _button(page, "+")


@pytest.mark.requirement("TC-EQP-WX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_wx_020_plus_adds_a_safety_monitor_tab_with_its_own_parameter(window):
    """EQP-WX-020: + adds a Safety Monitor in a new tab whose only parameter is its own SAFE verdict."""
    page = window._build_weather_page()
    _add_device(page, window, "Safety Monitor")
    tabs = _tabs(page)
    assert tabs.count() == 2 and tabs.tabText(1) == "Safety Monitor"
    rules_table = tabs.widget(1).findChildren(QtWidgets.QTableWidget)[1]
    assert rules_table.rowCount() == 1
    assert rules_table.item(0, 0).text() == "Device reports safe"


@pytest.mark.requirement("TC-EQP-WX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_wx_020_unsafe_monitor_blocks_dome_opening_across_tabs(window):
    """EQP-WX-020: a connected Safety Monitor reporting not-safe makes the Safety screen's overall verdict unsafe, even with calm weather."""
    page = window._build_weather_page()
    window._connect_device_adapter = lambda *a, **k: FakeWeatherStation(rain=0.0, wind_speed=5.0)
    primary_device = [c for c in page.findChildren(QtWidgets.QComboBox) if c.isEditable()][0]
    primary_device.setEditText("Calm Weather")
    _button(page, "Connect").click()

    _add_device(page, window, "Safety Monitor")
    window._connect_device_adapter = lambda *a, **k: FakeSafetyMonitor(is_safe=False)
    monitor_tab = _tabs(page).widget(1)
    [c for c in monitor_tab.findChildren(QtWidgets.QComboBox) if c.isEditable()][0].setEditText("Roof Sensor")
    _button(monitor_tab, "Connect").click()

    connected, safe, reasons = window._device_pages["weather"]["evaluate"]()
    assert connected and not safe
    assert any("Device reports safe" in r for r in reasons)


@pytest.mark.requirement("TC-EQP-WX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_wx_020_extra_devices_and_their_rules_persist_per_slot(window):
    """EQP-WX-020: an added device's config and rules are saved under its own slot, restored on reload, and deleted when its tab is closed."""
    from galileo.observatory import get_device_config, get_weather_safety_rules

    page = window._build_weather_page()
    _add_device(page, window, "Safety Monitor")
    monitor_tab = _tabs(page).widget(1)
    [c for c in monitor_tab.findChildren(QtWidgets.QComboBox) if c.isEditable()][0].setEditText("Roof Sensor")
    _button(monitor_tab, "Save").click()

    assert get_device_config(window._current_pier, "safety_monitor", slot="safety_monitor_2").device_name == "Roof Sensor"
    assert get_weather_safety_rules(window._current_pier, slot="safety_monitor_2")[0].parameter == "is_safe"
    assert get_weather_safety_rules(window._current_pier, slot="primary") == []  # rules don't leak between devices

    window._device_pages["weather"]["reload"]()
    assert _tabs(page).count() == 2

    QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes)
    _tabs(page).tabCloseRequested.emit(1)
    assert _tabs(page).count() == 1
    assert get_device_config(window._current_pier, "safety_monitor", slot="safety_monitor_2") is None
    assert get_weather_safety_rules(window._current_pier, slot="safety_monitor_2") == []
