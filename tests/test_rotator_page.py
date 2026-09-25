# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Rotator Equipment page (``AppWindow._build_rotator_page``), built offscreen.

Drives the real Qt widgets with a fake rotator adapter — the first UI-level
tests in the suite — covering the parts a user sees and touches: the shared
connection line every Equipment page has, connect/status display, Goto,
Reverse, backlash availability, and the derotation target/rate readout. The
reference layout is assets/samples/rot.png; EQP-ROT-010 covers the position
display and move commands.
"""

from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from galileo import derotation  # noqa: E402
from galileo.exceptions import DevicePropertyError  # noqa: E402


class FakeRotator:
    """Records commands; reports a configurable status."""

    def __init__(self, backlash_supported: bool = False) -> None:
        self.calls: list[tuple] = []
        self.status = {
            "name": "Fake Rotator", "position": 158.29, "mechanical_position": 12.5,
            "is_moving": False, "reverse": False, "can_sync": True, "max_angle": 360.0,
            "backlash": 0.5 if backlash_supported else None, "backlash_supported": backlash_supported,
        }

    async def get_status(self):
        return dict(self.status)

    async def move_to_angle(self, angle):
        self.calls.append(("move_to_angle", angle))

    async def set_reverse(self, reverse):
        self.calls.append(("set_reverse", reverse))

    async def sync_position(self, angle):
        self.calls.append(("sync_position", angle))

    async def set_backlash(self, steps):
        self.calls.append(("set_backlash", steps))
        if not self.status["backlash_supported"]:
            raise DevicePropertyError("no backlash on this driver")


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "rotator_page.db")  # throwaway DB, never the user's
    from galileo.ui.app_window import AppWindow

    # A modal message box would hang a headless test; record it instead.
    boxes: list[str] = []
    for kind in ("information", "warning"):
        monkeypatch.setattr(QtWidgets.QMessageBox, kind, staticmethod(lambda *a, **k: boxes.append(a[1])))
    win = AppWindow()
    win.boxes = boxes
    win.app = app
    yield win
    win._window.close()
    db.close()


def _find(page, cls, text):
    matches = [w for w in page.findChildren(cls) if getattr(w, "text", lambda: None)() == text]
    assert matches, f"no {cls.__name__} with text {text!r}"
    return matches[0]


def _button(page, text):
    return _find(page, QtWidgets.QPushButton, text)


def _connect(window, adapter):
    """Build the page, and connect it to *adapter* through the real Connect button."""
    page = window._build_rotator_page()
    window._connect_device_adapter = lambda *a, **k: adapter
    device_combo = [c for c in page.findChildren(QtWidgets.QComboBox) if c.isEditable()][0]
    device_combo.setEditText("Fake Rotator")
    _button(page, "Connect").click()
    return page


@pytest.mark.requirement("TC-EQP-ROT-010")
@pytest.mark.priority("P2")
def test_tc_eqp_rot_010_page_keeps_the_shared_connection_line(window):
    """EQP-ROT-010: the rotator page keeps the Driver/Server/Port/Scan + Device/Connect line every Equipment page has."""
    page = window._build_rotator_page()
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    assert [table.horizontalHeaderItem(i).text() for i in range(4)] == ["Driver", "Server", "Port", ""]
    combos = page.findChildren(QtWidgets.QComboBox)
    assert [combos[0].itemText(i) for i in range(combos[0].count())] == ["Alpaca", "INDI"]
    for text in ("Scan", "Connect", "Save"):
        _button(page, text)
    # ...plus the derotation-screen controls from the reference layout.
    for text in ("Goto", "Set Current Position as Zero", "Start Derotation", "Browse Folder", "Sync"):
        _button(page, text)
    _find(page, QtWidgets.QCheckBox, "Reverse")


@pytest.mark.requirement("TC-EQP-ROT-010")
@pytest.mark.priority("P2")
def test_tc_eqp_rot_010_controls_are_disabled_until_connected(window):
    """EQP-ROT-010: device controls stay disabled with no rotator connected."""
    page = window._build_rotator_page()
    for text in ("Goto", "Set Current Position as Zero"):
        assert not _button(page, text).isEnabled()
    assert not _find(page, QtWidgets.QCheckBox, "Reverse").isEnabled()


@pytest.mark.requirement("TC-EQP-ROT-010")
@pytest.mark.priority("P2")
def test_tc_eqp_rot_010_connect_shows_position_and_sends_commands(window):
    """EQP-ROT-010: connecting shows mechanical/sky position; Goto, Reverse and Set-as-Zero reach the adapter."""
    rotator = FakeRotator()
    page = _connect(window, rotator)

    labels = [w.text() for w in page.findChildren(QtWidgets.QLabel)]
    assert "158.29" in labels                                 # the big position readout
    assert "Mechanical 12.50° · Sky 158.29°" in labels        # both angles, per EQP-ROT-010
    assert _button(page, "Goto").isEnabled()

    spin = [s for s in page.findChildren(QtWidgets.QDoubleSpinBox) if s.suffix() == "°"][0]
    assert spin.value() == pytest.approx(158.29)              # seeded from the live position
    spin.setValue(45.5)
    _button(page, "Goto").click()
    _find(page, QtWidgets.QCheckBox, "Reverse").click()
    _button(page, "Set Current Position as Zero").click()
    assert ("move_to_angle", 45.5) in rotator.calls
    assert ("set_reverse", True) in rotator.calls
    assert ("sync_position", 0.0) in rotator.calls


@pytest.mark.requirement("TC-EQP-ROT-010")
@pytest.mark.priority("P2")
def test_tc_eqp_rot_010_backlash_only_enabled_when_the_driver_supports_it(window):
    """EQP-ROT-010: the backlash slider is disabled (with an explanation) for a driver that has no backlash setting."""
    page = _connect(window, FakeRotator(backlash_supported=False))
    slider = [s for s in page.findChildren(QtWidgets.QSlider) if s.maximum() == 1000][0]
    assert not slider.isEnabled() and "no backlash" in slider.toolTip()

    rotator = FakeRotator(backlash_supported=True)
    page = _connect(window, rotator)
    slider = [s for s in page.findChildren(QtWidgets.QSlider) if s.maximum() == 1000][0]
    assert slider.isEnabled() and slider.value() == 5         # driver's 0.5 shown in tenths
    slider.setValue(25)
    # Two "OK" buttons: backlash (added first) and derotation-rate correction.
    [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "OK"][0].click()
    assert ("set_backlash", 2.5) in rotator.calls


@pytest.mark.priority("P3")
def test_derotation_target_gives_altaz_and_a_signed_rate_that_reverse_flips(window):
    """A target on the meridian 30° from the zenith reads alt 60°, and Ω·cos(lat)·cos(az)/cos(alt) = −Ω at lat 60°."""
    import datetime
    rotator = FakeRotator()
    page = _connect(window, rotator)

    lat, lon = [s for s in page.findChildren(QtWidgets.QDoubleSpinBox) if s.suffix() in ("° N", "° E")]
    lat.setValue(60.0)
    lon.setValue(0.0)
    lst_hours = derotation.local_sidereal_deg(datetime.datetime.now(datetime.UTC), 0.0) / 15.0
    _, h, m, s = derotation.to_sexagesimal(lst_hours)
    ints = [w for w in page.findChildren(QtWidgets.QSpinBox)]
    ra_h, ra_m, dec_d = [w for w in ints if w.suffix() == " h"][0], [w for w in ints if w.suffix() == " m"][0], \
        [w for w in ints if w.suffix() == " °"][0]
    ra_s = [w for w in page.findChildren(QtWidgets.QDoubleSpinBox) if w.suffix() == " s"][0]
    ra_h.setValue(h)
    ra_m.setValue(m)
    ra_s.setValue(s)
    dec_d.setValue(30)

    labels = [w.text() for w in page.findChildren(QtWidgets.QLabel)]
    assert any(re.fullmatch(r"60\.\d\d°", t) for t in labels)   # altitude
    assert any(t.startswith("-0.25") for t in labels)            # rate, deg/min

    _find(page, QtWidgets.QCheckBox, "Reverse").click()       # reversing flips the derotation direction
    labels = [w.text() for w in page.findChildren(QtWidgets.QLabel)]
    assert any(t.startswith("0.25") for t in labels)


@pytest.mark.priority("P3")
def test_start_derotation_needs_a_target_then_locks_goto_while_running(window):
    """Start with no target is refused; with a target it toggles to Stop and locks Goto/Set-as-Zero."""
    import datetime
    page = _connect(window, FakeRotator())
    _button(page, "Start Derotation").click()
    assert window.boxes and window.boxes[-1] == "No target"

    lat, lon = [s for s in page.findChildren(QtWidgets.QDoubleSpinBox) if s.suffix() in ("° N", "° E")]
    lat.setValue(60.0)
    lon.setValue(0.0)
    lst_hours = derotation.local_sidereal_deg(datetime.datetime.now(datetime.UTC), 0.0) / 15.0
    _, h, m, s = derotation.to_sexagesimal(lst_hours)
    ints = page.findChildren(QtWidgets.QSpinBox)
    [w for w in ints if w.suffix() == " h"][0].setValue(h)
    [w for w in ints if w.suffix() == " m"][0].setValue(m)
    [w for w in ints if w.suffix() == " °"][0].setValue(30)

    _button(page, "Start Derotation").click()
    stop = _button(page, "Stop Derotation")
    assert not _button(page, "Goto").isEnabled() and not _button(page, "Set Current Position as Zero").isEnabled()

    stop.click()
    _button(page, "Start Derotation")                          # button text is restored
    assert _button(page, "Goto").isEnabled() and _button(page, "Set Current Position as Zero").isEnabled()
