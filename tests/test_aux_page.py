# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Control Panel page (``AppWindow._build_aux_page``), built offscreen (EQP-AUX-010, EQP-AUX-020).

The page is an INDI server browser: Connect opens the server, every reported device becomes a tab and every
INDI property group a sub-tab (the layout of the EKOS INDI Control Panel). Drives the real Qt widgets with a
fake server-level panel, the same pattern test_rotator_page.py uses for EQP-ROT-010. The property set is
modeled on the INDI Dust Cover Simulator: a Connection switch, a Dust Cover park/unpark switch and a numeric
Operation/Duration property.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

devices = pytest.importorskip("galileo.core.devices")


def _dust_cover_groups():
    return [
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


class FakeServer:
    """A server-level INDI panel reporting two devices, like the EKOS INDI Control Panel's device tabs."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.connected = False
        self.disconnected = False
        options = devices.AuxPropertyGroup(name="Options", properties=[
            devices.AuxProperty(
                name="UPLOAD_MODE", label="Upload", kind="switch", group="Options", rule="OneOfMany",
                elements=[devices.AuxElement(name="UPLOAD_CLIENT", label="Client", value=True)],
            ),
        ])
        self.snapshot = {
            "CCD Simulator": [*_dust_cover_groups(), options],
            "Focuser Simulator": [devices.AuxPropertyGroup(name="Main Control", properties=[
                devices.AuxProperty(
                    name="ABS_FOCUS_POSITION", label="Absolute Position", kind="number", group="Main Control",
                    elements=[devices.AuxElement(name="FOCUS_ABSOLUTE_POSITION", label="Steps",
                                                 value=500.0, min=0.0, max=100000.0, step=1.0)],
                ),
            ])],
        }

    async def connect(self):
        self.connected = True

    async def list_devices(self):
        return list(self.snapshot)

    async def get_all_property_groups(self):
        return self.snapshot

    async def write_property(self, device, name, values):
        self.calls.append((device, name, values))

    async def disconnect(self):
        self.disconnected = True


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


def _connect(window, server):
    """Build the page and connect it to *server* through the real Connect button."""
    page = window._build_aux_page()
    window._make_aux_server_panel = lambda host, port: server
    _button(page, "Connect").click()
    return page


def _device_tabs(page):
    """The outer tab widget: one tab per device."""
    return next(t for t in page.findChildren(QtWidgets.QTabWidget) if t.tabText(0) == "CCD Simulator")


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_page_is_one_connection_line_with_a_log_tail(window):
    """EQP-AUX-010: the page has a single Server/Port/Connect line at the top, Save, a log tail, and no tabs until connected."""
    page = window._build_aux_page()
    labels = {w.text() for w in page.findChildren(QtWidgets.QLabel)}
    assert {"Server", "Port", "Log"} <= labels
    assert not (labels & {"Driver", "Device"})  # INDI only: no driver choice, no single-device picker
    assert not page.findChildren(QtWidgets.QComboBox)
    for text in ("Connect", "Save"):
        _button(page, text)
    assert not [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Scan"]
    assert page.findChildren(QtWidgets.QPlainTextEdit)  # the shared log pane
    assert not page.findChildren(QtWidgets.QTabWidget)  # nothing connected yet: just the placeholder


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_rows_are_generated_from_the_driver_properties(window):
    """EQP-AUX-010: each driver-reported property becomes a labelled row with the control its kind needs."""
    page = _connect(window, FakeServer())
    tab = _device_tabs(page).widget(0)
    for label_text in ("Connection", "Dust Cover", "Operation"):
        _find(tab, QtWidgets.QLabel, label_text)
    for btn_text in ("Connect", "Disconnect", "Park", "Unpark"):
        _button(tab, btn_text)
    _button(tab, "Set")  # the Operation/Duration row's Set button
    assert tab.findChildren(QtWidgets.QDoubleSpinBox)[0].value() == pytest.approx(5.0)


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_switch_button_click_writes_the_property(window):
    """EQP-AUX-010: clicking a switch element's button writes that property to the device."""
    server = FakeServer()
    page = _connect(window, server)
    _button(_device_tabs(page).widget(0), "Park").click()
    assert ("CCD Simulator", "CAP_PARK", {"PARK": True}) in server.calls


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_number_set_button_writes_the_spinbox_value(window):
    """EQP-AUX-010: a number property's Set button writes its current spinbox value."""
    server = FakeServer()
    page = _connect(window, server)
    tab = _device_tabs(page).widget(0)
    tab.findChildren(QtWidgets.QDoubleSpinBox)[0].setValue(12.0)
    _button(tab, "Set").click()
    assert ("CCD Simulator", "CAP_DURATION", {"DURATION": 12.0}) in server.calls


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_non_finite_number_does_not_break_panel(window):
    """EQP-AUX-010: a driver-reported NaN is rendered as an editable finite value instead of crashing the panel."""
    server = FakeServer()
    server.snapshot["CCD Simulator"][0].properties[2].elements[0].value = float("nan")
    page = _connect(window, server)
    tab = _device_tabs(page).widget(0)
    spin = tab.findChildren(QtWidgets.QDoubleSpinBox)[0]
    assert spin.value() == pytest.approx(1.0)
    assert "non-finite value" in spin.toolTip()
    _button(tab, "Set").click()
    assert ("CCD Simulator", "CAP_DURATION", {"DURATION": 1.0}) in server.calls


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_very_small_driver_step_uses_bounded_slider(window):
    """EQP-AUX-010: tiny driver increments do not overflow the integer-backed Qt slider."""
    server = FakeServer()
    duration = server.snapshot["CCD Simulator"][0].properties[2].elements[0]
    duration.min, duration.max, duration.step, duration.value = -16_384_000_000.0, 16_384_000_000.0, 1e-7, 0.0
    page = _connect(window, server)
    slider = _device_tabs(page).widget(0).findChildren(QtWidgets.QSlider)[0]
    assert slider.minimum() == 0
    assert slider.maximum() == 10_000


@pytest.mark.requirement("TC-EQP-AUX-010")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_010_property_controls_start_in_one_left_aligned_column(window):
    """EQP-AUX-010: every property's controls start at the same x, beside a fixed-width label column (not right-aligned)."""
    page = _connect(window, FakeServer())
    page.resize(1200, 800)
    page.show()
    window.app.processEvents()
    tab = _device_tabs(page).widget(0)
    starts = {_button(tab, text).mapTo(page, _button(tab, text).rect().topLeft()).x() for text in ("Connect", "Park")}
    assert len(starts) == 1


# --- EQP-AUX-020: INDI server view (a tab per device, a sub-tab per property group) -------------------------------


@pytest.mark.requirement("TC-EQP-AUX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_020_connect_builds_a_tab_per_device_with_group_subtabs(window):
    """EQP-AUX-020: connecting to an INDI server loads every reported device as a tab, each holding a tab per property group."""
    server = FakeServer()
    page = _connect(window, server)
    assert server.connected

    outer = _device_tabs(page)
    assert [outer.tabText(i) for i in range(outer.count())] == ["CCD Simulator", "Focuser Simulator"]
    inner = outer.widget(0).findChildren(QtWidgets.QTabWidget)[0]
    assert [inner.tabText(i) for i in range(inner.count())] == ["Main Control", "Options"]
    _button(outer.widget(1), "Set")  # the focuser's number property


@pytest.mark.requirement("TC-EQP-AUX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_020_edit_writes_to_that_device(window):
    """EQP-AUX-020: an edit made in a device's tab is written to that device, not to another one on the server."""
    server = FakeServer()
    page = _connect(window, server)
    outer = _device_tabs(page)
    outer.setCurrentIndex(1)
    outer.widget(1).findChildren(QtWidgets.QDoubleSpinBox)[0].setValue(750.0)
    _button(outer.widget(1), "Set").click()
    assert ("Focuser Simulator", "ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": 750.0}) in server.calls


@pytest.mark.requirement("TC-EQP-AUX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_020_disconnect_closes_the_server(window):
    """EQP-AUX-020: Disconnect releases the INDI server connection and clears the device tabs."""
    server = FakeServer()
    page = _connect(window, server)
    window._device_pages["aux"]["disconnect"]()
    assert server.disconnected
    assert not page.findChildren(QtWidgets.QTabWidget)


@pytest.mark.requirement("TC-EQP-AUX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_020_new_properties_rebuild_only_that_device(window):
    """EQP-AUX-020: a driver defining more properties after connect rebuilds its tabs while keeping the open category."""
    server = FakeServer()
    page = _connect(window, server)
    inner = _device_tabs(page).widget(0).findChildren(QtWidgets.QTabWidget)[0]
    inner.setCurrentIndex(1)  # Options
    server.snapshot["CCD Simulator"].append(devices.AuxPropertyGroup(name="WCS", properties=[
        devices.AuxProperty(name="WCS_CONTROL", label="WCS", kind="switch", group="WCS", rule="OneOfMany",
                            elements=[devices.AuxElement(name="WCS_ENABLE", label="Enable", value=False)]),
    ]))
    window._device_pages["aux"]["refresh"]()  # the page's 2 s timer tick
    inner = next(t for t in page.findChildren(QtWidgets.QTabWidget) if t.tabText(0) == "Main Control"
                 and t.count() == 3)
    assert inner.tabText(inner.currentIndex()) == "Options"


@pytest.mark.requirement("TC-EQP-AUX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_020_many_devices_do_not_grow_the_window(window):
    """EQP-AUX-020: a server with many devices and wide property rows must not raise the page's minimum size."""
    page = window._build_aux_page()
    before = page.minimumSizeHint().width()
    server = FakeServer()
    for n in range(40):
        server.snapshot[f"A Device With A Rather Long Name {n}"] = _dust_cover_groups()
    window._make_aux_server_panel = lambda host, port: server
    _button(page, "Connect").click()
    assert page.minimumSizeHint().width() <= before + 50


@pytest.mark.requirement("TC-EQP-AUX-020")
@pytest.mark.priority("P2")
def test_tc_eqp_aux_020_save_keeps_only_server_and_port(window):
    """EQP-AUX-020: Save stores INDI, the server and the port for the Pier, with no device name."""
    from galileo.observatory import create_observatory, create_pier, get_device_config
    page = window._build_aux_page()
    window._current_pier = create_pier(create_observatory("Aux Obs"), "Pier A")
    next(e for e in page.findChildren(QtWidgets.QLineEdit) if e.placeholderText()).setText("stellarmate.local")
    _button(page, "Save").click()
    cfg = get_device_config(window._current_pier, "aux")
    assert (cfg.driver, cfg.server, cfg.device_name) == ("INDI", "stellarmate.local", None)
