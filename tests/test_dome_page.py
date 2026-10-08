# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Dome Equipment page (``AppWindow._build_dome_page``), built offscreen (EQP-DOME-010).

Drives the real Qt widgets with a fake Dome backend, the same pattern
test_aux_page.py/test_rotator_page.py use for their own device categories.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


class FakeDome:
    """Records commands; reports a configurable shutter/azimuth/park state."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.azimuth = 180.0
        self.shutter_state = "Open"
        self.is_at_park = False
        self.disconnect = AsyncMock()

    async def get_status(self) -> dict:
        return {"azimuth": self.azimuth, "shutter_state": self.shutter_state, "is_at_park": self.is_at_park}

    async def open_shutter(self) -> None:
        self.calls.append("open_shutter")
        self.shutter_state = "Open"

    async def close_shutter(self) -> None:
        self.calls.append("close_shutter")
        self.shutter_state = "Closed"

    async def park(self) -> None:
        self.calls.append("park")
        self.is_at_park = True

    async def abort_slew(self) -> None:
        self.calls.append("abort_slew")


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "dome_page.db")  # throwaway DB, never the user's
    from galileo.ui.app_window import AppWindow

    boxes: list[str] = []
    for kind in ("information", "warning"):
        monkeypatch.setattr(QtWidgets.QMessageBox, kind, staticmethod(lambda *a, **k: boxes.append(a[1])))
    win = AppWindow()
    win.boxes = boxes
    win.app = app
    yield win
    win._window.close()
    db.close()


def _find(obj, cls, text):
    matches = [w for w in obj.findChildren(cls) if getattr(w, "text", lambda: None)() == text]
    assert matches, f"no {cls.__name__} with text {text!r}"
    return matches[0]


def _button(obj, text):
    return _find(obj, QtWidgets.QPushButton, text)


def _connect(window, adapter):
    """Build the page, and connect it to *adapter* through the real Connect button."""
    page = window._build_dome_page()
    window._connect_device_adapter = lambda *a, **k: adapter
    device_combo = next(c for c in page.findChildren(QtWidgets.QComboBox) if c.isEditable())
    device_combo.setEditText("Dome Simulator")
    _button(page, "Connect").click()
    return page


@pytest.mark.requirement("TC-EQP-DOME-010")
@pytest.mark.priority("P2")
def test_tc_eqp_dome_010_page_keeps_the_shared_connection_line(window):
    """EQP-DOME-010: the Dome page keeps the Driver/Server/Port/Scan + Device/Connect line every Equipment page has."""
    page = window._build_dome_page()
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    assert [table.horizontalHeaderItem(i).text() for i in range(4)] == ["Driver", "Server", "Port", ""]
    combos = page.findChildren(QtWidgets.QComboBox)
    assert [combos[0].itemText(i) for i in range(combos[0].count())] == ["Alpaca", "INDI"]
    for text in ("Scan", "Connect", "Save", "Open", "Close", "Park", "Abort"):
        _button(page, text)


@pytest.mark.requirement("TC-EQP-DOME-010")
@pytest.mark.priority("P2")
def test_tc_eqp_dome_010_connect_shows_shutter_azimuth_and_park_chip(window):
    """EQP-DOME-010: connecting shows the shutter state, azimuth, and a Parked/Unparked chip."""
    dome = FakeDome()
    page = _connect(window, dome)

    shutter_labels = [w for w in page.findChildren(QtWidgets.QLabel) if w.text() == "Open"]
    assert shutter_labels
    azimuth_labels = [w for w in page.findChildren(QtWidgets.QLabel) if w.text() == "180.0°"]
    assert azimuth_labels
    _find(page, QtWidgets.QLabel, "Unparked")


@pytest.mark.requirement("TC-EQP-DOME-010")
@pytest.mark.priority("P2")
def test_tc_eqp_dome_010_open_close_park_abort_call_the_adapter(window):
    """EQP-DOME-010: Open/Close/Park/Abort each call straight through to the connected adapter."""
    dome = FakeDome()
    page = _connect(window, dome)

    _button(page, "Close").click()
    assert "close_shutter" in dome.calls
    _button(page, "Open").click()
    assert "open_shutter" in dome.calls
    _button(page, "Park").click()
    assert "park" in dome.calls
    _button(page, "Abort").click()
    assert "abort_slew" in dome.calls


@pytest.mark.requirement("TC-EQP-DOME-010")
@pytest.mark.priority("P2")
def test_tc_eqp_dome_010_observatory_status_reflects_dome_connection(window):
    """EQP-DOME-010: the Observatory Status panel's Dome row reflects this page's own connection state."""
    page = window._build_dome_page()
    _find(page, QtWidgets.QLabel, "Not connected")

    dome = FakeDome()
    window._connect_device_adapter = lambda *a, **k: dome
    device_combo = next(c for c in page.findChildren(QtWidgets.QComboBox) if c.isEditable())
    device_combo.setEditText("Dome Simulator")
    _button(page, "Connect").click()

    _find(page, QtWidgets.QLabel, "Connected")
    assert not [w for w in page.findChildren(QtWidgets.QLabel) if w.text() == "Not connected"]


@pytest.mark.requirement("TC-EQP-DOME-010")
@pytest.mark.priority("P2")
def test_tc_eqp_dome_010_observatory_status_reads_the_weather_page_without_a_second_connection(window):
    """EQP-DOME-010: the Weather row reads the existing Weather-page accessors (EQP-WX-020) rather than opening its own connection."""
    from galileo.safety import WeatherSafetyRule

    page = _connect(window, FakeDome())

    window._device_pages["weather"] = {
        "connected": lambda: True,
        "get_latest_readings": lambda: {"wind_speed": 5.0},
        "get_rules": lambda: [WeatherSafetyRule(parameter="wind_speed", operator=">=", threshold=20.0, safety_related=True)],
    }
    window._device_pages["dome"]["reload"]()
    _find(page, QtWidgets.QLabel, "Safe")

    window._device_pages["weather"]["get_latest_readings"] = lambda: {"wind_speed": 30.0}
    window._device_pages["dome"]["reload"]()
    unsafe_labels = [w for w in page.findChildren(QtWidgets.QLabel) if w.text().startswith("Unsafe")]
    assert unsafe_labels
