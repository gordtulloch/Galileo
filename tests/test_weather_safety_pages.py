# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Weather and Safety Monitor Equipment pages (``AppWindow._build_weather_page``/
``_build_safety_monitor_page``), built offscreen (EQP-WX-020, EQP-SAFE-020).

Drives the real Qt widgets with a fake Weather Station adapter, the same
pattern test_rotator_page.py uses for EQP-ROT-010 — plus the one thing that
makes this pair different from every other Equipment page: the Safety
Monitor page never opens its own connection to the Weather Station, it reads
the Weather page's live state through ``self._device_pages["weather"]``.
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


@pytest.mark.requirement("TC-EQP-SAFE-020")
@pytest.mark.priority("P2")
def test_tc_eqp_safe_020_surfaces_weather_measures_without_a_second_connection(window):
    """EQP-SAFE-020: the Safety Monitor page surfaces the safety-related readings read-only, via the Weather page's own connection."""
    station = FakeWeatherStation(rain=1.0, wind_speed=25.0, temperature=3.0)
    _connect_weather(window, station)

    # The Safety Monitor page must not need (or get) its own device adapter
    # to show this — _connect_device_adapter is left pointed at the weather
    # fake above, which a safety-monitor Connect click would misuse; this
    # page is built without ever clicking Connect on it.
    safety_page = window._build_safety_monitor_page()

    measures = safety_page.findChildren(QtWidgets.QTableWidget)[1]  # [0] is the connection row
    labels = [measures.item(row, 0).text() for row in range(measures.rowCount())]
    assert "Rain (now)" in labels and "Wind Speed" in labels

    wind_row = labels.index("Wind Speed")
    assert measures.item(wind_row, 1).text() == "25.0 km/h"
    assert measures.item(wind_row, 3).text() == "UNSAFE"

    rain_row = labels.index("Rain (now)")
    assert measures.item(rain_row, 3).text() == "UNSAFE"


@pytest.mark.requirement("TC-EQP-SAFE-020")
@pytest.mark.priority("P2")
def test_tc_eqp_safe_020_safe_readings_show_a_safe_verdict(window):
    """EQP-SAFE-020: a calm reading set shows SAFE verdicts, not just UNSAFE ones."""
    station = FakeWeatherStation(rain=0.0, wind_speed=5.0)
    _connect_weather(window, station)
    safety_page = window._build_safety_monitor_page()

    measures = safety_page.findChildren(QtWidgets.QTableWidget)[1]
    labels = [measures.item(row, 0).text() for row in range(measures.rowCount())]
    wind_row = labels.index("Wind Speed")
    assert measures.item(wind_row, 3).text() == "SAFE"


@pytest.mark.requirement("TC-EQP-SAFE-020")
@pytest.mark.priority("P2")
def test_tc_eqp_safe_020_trend_chart_offers_the_readings_actually_seen(window):
    """EQP-SAFE-020: the trend dropdown is populated from the Weather page's own history, including wind/temperature."""
    station = FakeWeatherStation(rain=0.0, wind_speed=12.0, temperature=4.5)
    _connect_weather(window, station)
    safety_page = window._build_safety_monitor_page()

    trend_combo = safety_page.findChildren(QtWidgets.QComboBox)[-1]
    choices = [trend_combo.itemText(i) for i in range(trend_combo.count())]
    assert any("Wind Speed" in c for c in choices)
    assert any("Temperature" in c for c in choices)
