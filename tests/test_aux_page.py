# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Aux Equipment page (``AppWindow._build_aux_page``), built offscreen (EQP-AUX-010).

Drives the real Qt widgets with a fake Aux backend exposing a driver-defined
property set (modeled on the INDI Dust Cover Simulator shown in the feature's
reference screenshot: a Connection switch, a Dust Cover park/unpark switch,
and a numeric Operation/Duration property), the same pattern
test_rotator_page.py uses for EQP-ROT-010.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

devices = pytest.importorskip("galileo.core.devices")


class FakeAux:
    """Records property writes; reports a configurable property-group set."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.groups = [
            devices.AuxPropertyGroup(name="Main Control", properties=[
                devices.AuxProperty(
                    name="CONNECTION", label="Connection", kind="switch",
                    group="Main Control", rule="OneOfMany", state="Ok",
                    elements=[
                        devices.AuxElement(name="CONNECT", label="Connect", value=True),
                        devices.AuxElement(name="DISCONNECT", label="Disconnect", value=False),
                    ],
                ),
                devices.AuxProperty(
                    name="CAP_PARK", label="Dust Cover", kind="switch",
                    group="Main Control", rule="OneOfMany", state="Ok",
                    elements=[
                        devices.AuxElement(name="PARK", label="Park", value=False),
                        devices.AuxElement(name="UNPARK", label="Unpark", value=True),
                    ],
                ),
                devices.AuxProperty(
                    name="CAP_DURATION", label="Operation", kind="number",
                    group="Main Control", state="Idle",
                    elements=[
                        devices.AuxElement(name="DURATION", label="Duration (s)",
                                            value=5.0, min=1.0, max=60.0, step=1.0),
                    ],
                ),
            ]),
        ]

    async def get_property_groups(self):
        return self.groups

    async def write_property(self, name, values):
        self.calls.append((name, values))
        for group in self.groups:
            for prop in group.properties:
                if prop.name == name:
                    for el in prop.elements:
                        if el.name in values:
                            el.value = values[el.name]


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "aux_page.db")  # throwaway DB, never the user's
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
    page = window._build_aux_page()
    window._connect_device_adapter = lambda *a, **k: adapter
    device_combo = [c for c in page.findChildren(QtWidgets.QComboBox) if c.isEditable()][0]
    device_combo.setEditText("Dust Cover Simulator")
    _button(page, "Connect").click()
    return page


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_page_keeps_the_shared_connection_line(window):
    """EQP-AUX-010: the Aux page keeps the Driver/Server/Port/Scan + Device/Connect line every Equipment page has."""
    page = window._build_aux_page()
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    assert [table.horizontalHeaderItem(i).text() for i in range(4)] == ["Driver", "Server", "Port", ""]
    combos = page.findChildren(QtWidgets.QComboBox)
    assert [combos[0].itemText(i) for i in range(combos[0].count())] == ["Alpaca", "INDI"]
    for text in ("Scan", "Connect", "Save"):
        _button(page, text)
    # No device connected yet: just the placeholder, no tabs.
    assert not page.findChildren(QtWidgets.QTabWidget)


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_connect_builds_one_tab_per_driver_group(window):
    """EQP-AUX-010: connecting builds one tab per driver-reported property group, with its own rows."""
    aux = FakeAux()
    page = _connect(window, aux)

    tabs = page.findChildren(QtWidgets.QTabWidget)
    assert len(tabs) == 1
    assert tabs[0].count() == 1
    assert tabs[0].tabText(0) == "Main Control"

    tab = tabs[0]
    for label_text in ("Connection", "Dust Cover", "Operation"):
        _find(tab, QtWidgets.QLabel, label_text)
    for btn_text in ("Connect", "Disconnect", "Park", "Unpark"):
        _button(tab, btn_text)
    _button(tab, "Set")  # the Operation/Duration row's Set button
    spin = [s for s in tab.findChildren(QtWidgets.QDoubleSpinBox)][0]
    assert spin.value() == pytest.approx(5.0)


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_switch_button_click_writes_the_property(window):
    """EQP-AUX-010: clicking a switch element's button writes that property through the adapter."""
    aux = FakeAux()
    page = _connect(window, aux)
    tab = page.findChildren(QtWidgets.QTabWidget)[0]

    _button(tab, "Park").click()
    assert ("CAP_PARK", {"PARK": True}) in aux.calls


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_number_set_button_writes_the_slider_value(window):
    """EQP-AUX-010: a number property's Set button writes its current spinbox value through the adapter."""
    aux = FakeAux()
    page = _connect(window, aux)
    tab = page.findChildren(QtWidgets.QTabWidget)[0]

    spin = tab.findChildren(QtWidgets.QDoubleSpinBox)[0]
    spin.setValue(12.0)
    _button(tab, "Set").click()
    assert ("CAP_DURATION", {"DURATION": 12.0}) in aux.calls


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_disconnect_clears_the_panel(window):
    """EQP-AUX-010: the Pier-level Disconnect path tears down the panel back to the placeholder."""
    aux = FakeAux()
    aux.disconnect = AsyncMock()
    page = _connect(window, aux)
    assert page.findChildren(QtWidgets.QTabWidget)

    window._device_pages["aux"]["disconnect"]()
    assert not page.findChildren(QtWidgets.QTabWidget)
