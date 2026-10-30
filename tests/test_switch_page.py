# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Equipment > Switches page (``AppWindow._build_switch_page``), built offscreen (EQP-SW-090, EQP-SW-110, EQP-SW-120).

Drives the real Qt widgets with a fake backend that returns a ready-made ``SwitchPanel``, the same pattern
``test_aux_page.py`` uses for the Aux page. The mapping from INDI/Alpaca onto the panel is covered in
``test_switches.py``; this file is about what the page does with a panel.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")

devices = pytest.importorskip("galileo.core.devices")
from galileo.core.switches import (
    SwitchChannel,
    SwitchGroup,
    SwitchPanel,
    SwitchSensor,
)


def make_panel() -> SwitchPanel:
    return SwitchPanel(
        groups=[
            SwitchGroup("DC", [
                SwitchChannel(id="dc1", label="Camera", on=True, current_a=1.5),
                SwitchChannel(id="always", label="12 V normally open", on=True, switchable=False, writable=False),
            ]),
            SwitchGroup("Dew heaters", [
                SwitchChannel(id="dew1", label="Dew A", kind="dew", on=True, duty=50.0, min=0.0, max=100.0, step=5.0),
            ]),
            SwitchGroup("Adjustable outputs", [
                SwitchChannel(id="var1", label="Regulator", kind="variable", on=True, volts=9.0, min=3.0, max=12.0, step=0.1),
            ]),
            SwitchGroup("Device", [
                SwitchChannel(id="cycle", label="Cycle power", kind="action"),
                SwitchChannel(id="over", label="Over-voltage limit (V)", kind="value", value=13.8, min=0.0, max=20.0, step=0.1),
            ]),
        ],
        sensors=[SwitchSensor(id="v", label="Voltage", value=12.1, unit="V"), SwitchSensor(id="t", label="Probe", value=None, unit="°C")],
        other=[devices.AuxPropertyGroup(name="Vendor", properties=[
            devices.AuxProperty(name="CALIB", label="Calibrate", kind="number", group="Vendor",
                                elements=[devices.AuxElement(name="X", label="X", value=1.0, min=0.0, max=9.0, step=1.0)]),
        ])],
        profile="Test Box",
    )


class FakeSwitch:
    """Records writes; ``get_panel`` returns the panel, which ``set_channel`` then changes like a real driver."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.panel = make_panel()
        self.fail: str | None = None
        self.disconnected = False

    async def get_panel(self):
        if self.fail:
            raise RuntimeError(self.fail)
        return self.panel

    async def set_channel(self, channel_id, *, on=None, duty=None, volts=None, value=None):
        self.calls.append((channel_id, {k: v for k, v in {"on": on, "duty": duty, "volts": volts, "value": value}.items() if v is not None}))
        ch = self.panel.channel(channel_id)
        if on is not None:
            ch.on = on
        if duty is not None:
            ch.duty = duty
        if volts is not None:
            ch.volts = volts
        if value is not None:
            ch.value = value

    async def disconnect(self):
        self.disconnected = True


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "switch_page.db")  # throwaway DB, never the user's
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


def _toggles(obj):
    return [b for b in obj.findChildren(QtWidgets.QPushButton) if b.isCheckable() and b.text() in ("On", "Off")]


def _connect(window, adapter):
    """Build the page and connect it to *adapter* through the real Connect button."""
    page = window._build_switch_page("Switches")
    window._connect_device_adapter = lambda *a, **k: adapter
    device_combo = next(c for c in page.findChildren(QtWidgets.QComboBox) if c.isEditable())
    device_combo.setEditText("Power Sim")
    _button(page, "Connect").click()
    return page


@pytest.mark.requirement("TC-EQP-SW-090")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_090_page_keeps_the_shared_connection_line(window):
    """EQP-SW-090: the Switches page keeps the Driver/Server/Port/Scan + Device/Connect line every Equipment
    page has, and shows only a prompt until a device is connected."""
    page = window._build_switch_page("Switches")
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    assert [table.horizontalHeaderItem(i).text() for i in range(4)] == ["Driver", "Server", "Port", ""]
    combos = page.findChildren(QtWidgets.QComboBox)
    assert [combos[0].itemText(i) for i in range(combos[0].count())] == ["Alpaca", "INDI"]
    for text in ("Scan", "Connect", "Save"):
        _button(page, text)
    assert not _toggles(page) and not page.findChildren(QtWidgets.QGroupBox)
    assert _find(page, QtWidgets.QLabel, "Connect a device to show its controls.")


@pytest.mark.requirement("TC-EQP-SW-090")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_090_connect_renders_every_part_of_the_panel(window):
    """EQP-SW-090: a section per group; a toggle per switchable channel; a read-out, no toggle, for a
    display-only channel; a field per dew duty, voltage and generic value; readings; and the Other group."""
    page = _connect(window, FakeSwitch())
    titles = [g.title() for g in page.findChildren(QtWidgets.QGroupBox)]
    assert titles == ["DC", "Dew heaters", "Adjustable outputs", "Device", "Readings", "Other"]

    assert len(_toggles(page)) == 3                       # Camera, Dew A, Regulator — not the display-only port
    assert _find(page, QtWidgets.QLabel, "On (not switchable)")
    assert _find(page, QtWidgets.QLabel, "1.50 A")        # per-channel current

    spins = {type(w).__name__ for w in page.findChildren(QtWidgets.QAbstractSpinBox)}
    assert {"QSpinBox", "QDoubleSpinBox"} <= spins
    dew = next(s for s in page.findChildren(QtWidgets.QSpinBox) if s.suffix() == " %")
    assert dew.value() == 50 and (dew.minimum(), dew.maximum()) == (0, 100)
    volts = next(s for s in page.findChildren(QtWidgets.QDoubleSpinBox) if s.suffix() == " V")
    assert (volts.value(), volts.minimum(), volts.maximum()) == (9.0, 3.0, 12.0)

    assert _find(page, QtWidgets.QLabel, "12.10 V") and _find(page, QtWidgets.QLabel, "—")    # "no reading" is a dash
    assert _find(page, QtWidgets.QLabel, "Recognised as: Test Box")
    _button(page, "Run")                                   # the action channel


@pytest.mark.requirement("TC-EQP-SW-090")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_090_controls_write_through_the_controller(window):
    """EQP-SW-090/050: a toggle, a Set beside a dew duty, a regulator voltage and a generic value, and an
    action button each write the right thing, and the panel is refreshed in place afterwards."""
    adapter = FakeSwitch()
    page = _connect(window, adapter)
    first_toggle = _toggles(page)[0]

    first_toggle.click()                                   # Camera: On -> Off (no session running)
    assert adapter.calls[-1] == ("dc1", {"on": False})
    assert _toggles(page)[0] is first_toggle               # refreshed in place, not rebuilt
    assert first_toggle.text() == "Off" and not first_toggle.isChecked()

    dew = next(s for s in page.findChildren(QtWidgets.QSpinBox) if s.suffix() == " %")
    dew.setValue(75)
    next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Set" and b.parent() is dew.parent()).click()
    assert adapter.calls[-1] == ("dew1", {"duty": 75.0})

    volts = next(s for s in page.findChildren(QtWidgets.QDoubleSpinBox) if s.suffix() == " V")
    volts.setValue(11.0)
    next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Set" and b.parent() is volts.parent()).click()
    assert adapter.calls[-1] == ("var1", {"volts": 11.0})

    _button(page, "Run").click()
    assert adapter.calls[-1] == ("cycle", {"on": True})


@pytest.mark.requirement("TC-EQP-SW-110")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_110_switching_off_during_a_session_asks_first(window, monkeypatch):
    """EQP-SW-110: while a session runs on the Pier, switching a channel off asks for confirmation naming it;
    declining leaves it on and writes nothing, accepting writes. Switching *on* never asks."""
    from galileo.current_object import pier_key
    asked: list[str] = []
    answer = {"value": QtWidgets.QMessageBox.StandardButton.No}

    def question(parent, title, text, *a, **k):
        asked.append(text)
        return answer["value"]

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", staticmethod(question))
    running = {"on": True}
    monkeypatch.setattr(
        "galileo.ui.session_runner.get_session_controller",
        lambda win: SimpleNamespace(run_snapshot=lambda: {pier_key(window._current_pier): ("running", "S")} if running["on"] else {}),
    )

    adapter = FakeSwitch()
    page = _connect(window, adapter)
    toggle = _toggles(page)[0]

    toggle.click()                                         # declined
    assert asked and "'Camera'" in asked[0]
    assert adapter.calls == [] and toggle.isChecked() and toggle.text() == "On"

    answer["value"] = QtWidgets.QMessageBox.StandardButton.Yes
    toggle.click()                                         # accepted
    assert adapter.calls == [("dc1", {"on": False})]

    asked.clear()
    toggle.click()                                         # switching back on: no prompt
    assert not asked and adapter.calls[-1] == ("dc1", {"on": True})

    running["on"] = False                                  # no session: no prompt either
    toggle.click()
    assert not asked and adapter.calls[-1] == ("dc1", {"on": False})


@pytest.mark.requirement("TC-EQP-SW-090")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_090_refreshes_at_least_every_five_seconds(window):
    """EQP-SW-090: the page refreshes on an interval no longer than 5 s."""
    page = window._build_switch_page("Switches")
    intervals = [t.interval() for t in page.findChildren(QtCore.QTimer)]
    assert intervals and min(intervals) <= 5000


@pytest.mark.requirement("TC-EQP-SW-120")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_120_a_device_that_stops_answering_degrades_the_panel_only(window):
    """EQP-SW-120: when the device cannot be read (lost server), the panel shows why instead of raising, and
    a later good read rebuilds it."""
    adapter = FakeSwitch()
    page = _connect(window, adapter)
    assert _toggles(page)

    adapter.fail = "server gone"
    _toggles(page)[0].click()                              # the write succeeds, the refresh after it cannot read
    assert not _toggles(page)
    assert _find(page, QtWidgets.QLabel, "Cannot read the device right now: server gone")

    adapter.fail = None
    reconnected = _connect(window, adapter)                # reconnecting rebuilds from a good read
    assert _toggles(reconnected)


@pytest.mark.requirement("TC-EQP-SW-120")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_120_a_failed_write_is_reported_and_the_panel_resyncs(window):
    """EQP-SW-120/050: a write the device rejects shows its reason in the status bar and the panel then shows
    the device's real state, with no unhandled error."""
    from galileo.exceptions import DevicePropertyError
    adapter = FakeSwitch()

    async def refuse(channel_id, **kwargs):
        raise DevicePropertyError("driver says no")

    adapter.set_channel = refuse
    page = _connect(window, adapter)
    _toggles(page)[0].click()
    assert "driver says no" in window._window.statusBar().currentMessage()
    assert _toggles(page)[0].isChecked()                   # still On: the device's state, not the request


@pytest.mark.requirement("TC-EQP-SW-090")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_090_plugin_panels_are_still_hosted_on_the_page(window):
    """EQP-SW-090/PLUG-070: panels plugins contribute for the Switches page (Kasa, Relay, SwitchBot) still
    sit on it, above the generic section."""
    plugin = SimpleNamespace(name="KasaSwitchPlugin")
    registry = SimpleNamespace(get_equipment_panels=lambda cat: [SimpleNamespace(plugin=plugin, label="Kasa Switches")] if cat == "switch" else [])
    window._plugin_manager = SimpleNamespace(get_ui_registry=lambda: registry)
    window._build_plugin_page = lambda p, label: QtWidgets.QLabel(f"PLUGIN PANEL: {label}")
    page = window._build_switch_page("Switches")
    assert _find(page, QtWidgets.QLabel, "PLUGIN PANEL: Kasa Switches")


@pytest.mark.requirement("TC-EQP-SW-090")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_090_save_needs_a_pier_and_disconnect_clears_the_panel(window):
    """EQP-SW-090: Save without a Pier explains why; the Pier-level disconnect drops the connection and the panel."""
    adapter = FakeSwitch()
    page = _connect(window, adapter)
    assert window._current_pier is None
    _button(page, "Save").click()
    assert window.boxes[-1] == "No Pier selected"

    window._device_pages["switch"]["disconnect"]()
    assert adapter.disconnected and not _toggles(page)
    assert _find(page, QtWidgets.QLabel, "Connect a device to show its controls.")
