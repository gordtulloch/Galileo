# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Guider Equipment page (``galileo.ui.guider.GuiderPage``), built offscreen against a fake PHD2 (GUIDE-070 … 090).

The page polls the guiding model on a timer; tests call ``_tick()`` themselves
instead of waiting for it, and use the throwaway database the other page tests
use, never the user's.
"""

from __future__ import annotations

import base64
import os
import struct
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6 import QtCore

from galileo.observatory import (
    create_observatory,
    create_pier,
    get_device_config,
    save_device_config,
    save_optical_tubes,
)
from tests.phd2_fake_server import FakePhd2Server


@pytest.fixture
def phd2():
    server = FakePhd2Server()
    yield server
    server.close()


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "guider_page.db")
    from galileo.ui.app_window import AppWindow

    boxes: list[str] = []
    for kind in ("information", "warning"):
        monkeypatch.setattr(QtWidgets.QMessageBox, kind, staticmethod(lambda *a, **k: boxes.append(a[1])))
    win = AppWindow()
    win.boxes = boxes
    win.app = app
    win.observatory = create_observatory("Test Obs")
    win.pier = create_pier(win.observatory, "Pier A")
    win._current_pier = win.pier
    yield win
    # Every AppWindow owns polling timers; left running they keep firing (and slowing
    # every later test's event loop) after the window is gone.
    for timer in win._window.findChildren(QtCore.QTimer):
        timer.stop()
    win._window.close()
    win._window.deleteLater()
    db.close()


def _pump(window, condition, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def _connect(window, phd2):
    page = window._build_guider_page()
    page.host_edit.setText("127.0.0.1")
    page.port_spin.setValue(phd2.port)
    page.connect_btn.click()
    # sync_state (exposure list) is the last thing the connect worker does
    assert _pump(window, lambda: (s := page._service()) is not None and s.model.snapshot().exposure_options_ms)
    page._tick()
    return page, page._service()


def _step(frame: int, ra: float, dec: float) -> dict:
    return {"Event": "GuideStep", "Frame": frame, "Time": float(frame), "RADistanceRaw": ra, "DECDistanceRaw": dec,
            "RADuration": 120, "RADirection": "West", "DECDuration": 40, "DECDirection": "South",
            "SNR": 28.5, "StarMass": 4321, "HFD": 2.4}


def _texts(page):
    return [label.text() for label in page.findChildren(QtWidgets.QLabel)]


@pytest.mark.requirement("TC-GUIDE-070")
@pytest.mark.priority("MVP")
def test_tc_guide_070_guider_page_asks_for_a_host_not_a_device(window):
    """GUIDE-070: the Guider page has a PHD2 host and port, and no Alpaca/INDI driver choice or device scan."""
    page = window._build_guider_page()
    assert page.host_edit.text() == "localhost" and page.port_spin.value() == 4400
    combos = [[c.itemText(i) for i in range(c.count())] for c in page.findChildren(QtWidgets.QComboBox)]
    assert ["Alpaca", "INDI"] not in combos
    assert "PHD2 host" in _texts(page)
    assert not page.disconnect_btn.isEnabled()
    assert "Not connected to PHD2" in page.status_label.text()


@pytest.mark.requirement("TC-GUIDE-070")
@pytest.mark.priority("MVP")
def test_tc_guide_070_equipment_page_uses_the_guider_page(window):
    """GUIDE-070: Guiding is a top-level sidebar section, directly below Imaging, that shows the PHD2 page and takes part in Pier reloads."""
    from galileo.ui.app_window import EQUIPMENT_CATEGORIES, PRIMARY_SECTIONS
    ids = [s[0] for s in PRIMARY_SECTIONS]
    assert ids[ids.index("imaging") + 1] == "guiding"
    assert {s[0]: s[1] for s in PRIMARY_SECTIONS}["guiding"] == "Guiding"
    assert "guider" not in [c[0] for c in EQUIPMENT_CATEGORIES]
    from galileo.ui.guider import GuiderPage
    state = window._device_pages["guider"]
    assert set(state) == {"reload", "autoconnect", "disconnect", "connected", "get_service"}
    pages = list(window._window.findChildren(GuiderPage))
    assert len(pages) == 1


@pytest.mark.requirement("TC-GUIDE-070")
@pytest.mark.priority("MVP")
def test_tc_guide_070_connect_shows_phd2_state_and_choices(window, phd2):
    """GUIDE-070: Connect reads PHD2's version, exposure choices and Dec mode into the page."""
    page, _service = _connect(window, phd2)
    assert "Connected to PHD2 (PHD2 2.6.13)" in page.status_label.text() and "equipment connected" in page.status_label.text()
    assert not page.connect_btn.isEnabled() and page.disconnect_btn.isEnabled() and not page.host_edit.isEnabled()
    assert [page.exposure_combo.itemText(i) for i in range(page.exposure_combo.count())] == ["0.5 s", "1 s", "2 s", "3 s"]
    assert page.exposure_combo.currentText() == "2 s" and page.dec_combo.currentText() == "Auto"
    page.disconnect_btn.click()
    page._tick()
    assert page.connect_btn.isEnabled() and "Not connected" in page.status_label.text()


@pytest.mark.requirement("TC-GUIDE-070")
@pytest.mark.priority("MVP")
def test_tc_guide_070_unreachable_phd2_is_reported_in_the_log_pane(window):
    """GUIDE-070: a failed connect re-enables Connect and says why in the page's log."""
    page = window._build_guider_page()
    page.host_edit.setText("127.0.0.1")
    page.port_spin.setValue(1)
    page.connect_btn.click()
    assert _pump(window, lambda: page._pier_key() not in page._connecting)
    page._tick()
    assert page.connect_btn.isEnabled() and "Could not connect to PHD2 at 127.0.0.1:1" in page.event_log.toPlainText()


@pytest.mark.requirement("TC-GUIDE-070")
@pytest.mark.priority("MVP")
def test_tc_guide_070_save_and_reload_round_trip_per_pier(window):
    """GUIDE-070: Save stores the PHD2 host/port for the Pier; an old INDI/Alpaca guider config is not mistaken for one."""
    page = window._build_guider_page()
    page.host_edit.setText("astro-pc.local")
    page.port_spin.setValue(4401)
    page.save_btn.click()
    cfg = get_device_config(window.pier, "guider")
    assert (cfg.driver, cfg.server, cfg.port) == ("PHD2", "astro-pc.local", 4401)

    page.host_edit.setText("elsewhere")
    page.port_spin.setValue(4402)
    page.reload()
    assert page.host_edit.text() == "astro-pc.local" and page.port_spin.value() == 4401

    other = create_pier(window.observatory, "Pier B")
    save_device_config(other, "guider", driver="INDI", server="old-host", port=7624, device_name="PHD2 Simulator")
    window._current_pier = other
    page.reload()
    assert page.host_edit.text() == "localhost" and page.port_spin.value() == 4400
    assert page._saved_phd2 is False


@pytest.mark.requirement("TC-GUIDE-070")
@pytest.mark.priority("MVP")
def test_tc_guide_070_saving_without_a_pier_warns(window):
    """GUIDE-070: Save with no Pier selected explains itself instead of failing silently."""
    page = window._build_guider_page()
    window._current_pier = None
    page.save_btn.click()
    assert window.boxes == ["No Pier selected"]


@pytest.mark.requirement("TC-GUIDE-060")
@pytest.mark.priority("P2")
def test_tc_guide_060_each_pier_has_its_own_guider_connection(window, phd2):
    """GUIDE-060: switching Pier shows that Pier's own (here: absent) PHD2 connection, and switching back restores it."""
    page, service = _connect(window, phd2)
    assert service.is_connected

    window._current_pier = create_pier(window.observatory, "Pier B")
    page._tick()
    assert page._service() is None and "Not connected" in page.status_label.text()

    window._current_pier = window.pier
    page._tick()
    assert page._service() is service and "Connected to PHD2" in page.status_label.text()


@pytest.mark.requirement("TC-GUIDE-080")
@pytest.mark.priority("MVP")
def test_tc_guide_080_page_displays_live_guiding_data(window, phd2):
    """GUIDE-080: guide steps show up as deltas, pulses, RMS, SNR, graph samples, state lamps and log lines."""
    page, service = _connect(window, phd2)
    phd2.push({"Event": "StartGuiding"})
    for frame, ra in enumerate((1.0, -1.0, 1.0, -1.0), start=1):
        phd2.push(_step(frame, ra, 0.5))
    assert _pump(window, lambda: len(service.model.snapshot().samples) == 4)
    page._tick()

    assert [label.text() for label in page.info["delta"]] == ["-2.00", "+1.00"]  # last step, in arcsec (2 ″/px)
    assert [label.text() for label in page.info["pulse"]] == ["+120", "-40"]
    assert [label.text() for label in page.info["rms"]] == ["2.00", "0.00"]
    assert page.info["total"][0].text() == "2.00 ″"
    assert page.info["snr"][0].text() == "28.5" and page.info["star"][0].text() == "4321 / 2.4"
    assert len(page.graph.samples) == 4 and len(page.scatter.points) == 4
    assert page.lamps["run"].styleSheet() != page.lamps["idle"].styleSheet()
    assert "State: Guiding" in page.state_label.text()
    assert "Guiding started." in page.event_log.toPlainText()

    phd2.push({"Event": "StarLost", "Frame": 5})
    assert _pump(window, lambda: service.model.app_state == "LostLock")
    page._tick()
    assert page.event_log.toPlainText().splitlines()[0].endswith("reducing pulse duration.")  # newest first


@pytest.mark.requirement("TC-GUIDE-080")
@pytest.mark.priority("MVP")
def test_tc_guide_080_scope_info_comes_from_the_selected_train_and_phd2_scale(window, phd2):
    """GUIDE-080: focal length, aperture, ratio come from the chosen optical tube; scale and FOV from PHD2."""
    from galileo.observatory import list_optical_tubes
    save_optical_tubes(window.pier, [{"name": "Guidescope", "focal_length_mm": 300.0, "aperture_mm": 50.0}])
    assert list_optical_tubes(window.pier)
    page, _service = _connect(window, phd2)
    page.refresh_tubes()
    page._tick()
    values = {key: label.text() for key, label in page.scope_values.items()}
    assert values["focal"] == "300 mm" and values["aperture"] == "50 mm" and values["ratio"] == "f/6.0"
    assert values["scale"] == "2.00 ″/px" and values["fov"] == "21.3′ × 16.0′"  # 640×480 px at 2 ″/px


@pytest.mark.requirement("TC-GUIDE-080")
@pytest.mark.priority("MVP")
def test_tc_guide_080_star_image_and_calibration_plot_are_fed(window, phd2):
    """GUIDE-080: the guide-star cut-out and the calibration steps reach their views."""
    pixels = base64.b64encode(struct.pack("<16H", *range(0, 1600, 100))).decode()
    phd2.responses["get_star_image"] = {"frame": 1, "width": 4, "height": 4, "star_pos": [2.0, 2.0], "pixels": pixels}
    page, service = _connect(window, phd2)
    phd2.push({"Event": "LoopingExposures", "Frame": 1})
    phd2.push({"Event": "StartCalibration", "Mount": "Mount"})
    phd2.push({"Event": "Calibrating", "dir": "West", "dx": 1.0, "dy": 0.1, "step": 1})
    assert _pump(window, lambda: service.model.snapshot().calibration_points)
    phd2.push({"Event": "LoopingExposures", "Frame": 2})  # back to looping so the star image is polled
    assert _pump(window, lambda: service.model.app_state == "Looping")
    service.poll(want_star_image=True)
    assert _pump(window, lambda: service.model.snapshot().star_image is not None)
    page._tick()
    assert page.star_view.has_image and page.star_view._item.pixmap().width() == 4
    assert len(page.calibration_plot.points) == 1
    # painting every plot must not raise, with and without data
    for widget in (page.graph, page.scatter, page.calibration_plot, page.star_view):
        widget.resize(400, 300)
        assert not widget.grab().isNull()


@pytest.mark.requirement("TC-GUIDE-090")
@pytest.mark.priority("MVP")
def test_tc_guide_090_buttons_follow_phd2_state(window, phd2):
    """GUIDE-090: controls are only offered when PHD2 could act on them."""
    page = window._build_guider_page()
    assert not any(b.isEnabled() for b in (page.loop_btn, page.guide_btn, page.stop_btn, page.find_btn, page.dither_btn))

    page, service = _connect(window, phd2)
    assert page.loop_btn.isEnabled() and page.guide_btn.isEnabled() and not page.stop_btn.isEnabled()
    assert page.equip_disconnect_btn.isEnabled() and not page.equip_connect_btn.isEnabled()

    phd2.push({"Event": "LoopingExposures", "Frame": 1})
    assert _pump(window, lambda: service.model.app_state == "Looping")
    page._tick()
    assert not page.loop_btn.isEnabled() and page.stop_btn.isEnabled() and page.find_btn.isEnabled()

    phd2.push({"Event": "StartGuiding"})
    assert _pump(window, lambda: service.model.app_state == "Guiding")
    page._tick()
    assert page.dither_btn.isEnabled() and not page.guide_btn.isEnabled() and not page.clear_cal_btn.isEnabled()


@pytest.mark.requirement("TC-GUIDE-090")
@pytest.mark.priority("MVP")
def test_tc_guide_090_buttons_send_commands_to_phd2(window, phd2):
    """GUIDE-090: Loop / Guide (with Recalibrate) / Stop / Auto Star / Dither / Exp / Dec / Clear / equipment all reach PHD2."""
    for method in ("loop", "stop_capture", "find_star", "guide", "dither", "set_exposure", "set_dec_guide_mode",
                   "clear_calibration", "set_connected"):
        phd2.responses[method] = 0
    page, service = _connect(window, phd2)

    def sent(method):
        assert phd2.wait_for_request(method), method
        return next(p for m, p in reversed(phd2.received) if m == method)

    page.loop_btn.click()
    sent("loop")
    phd2.push({"Event": "LoopingExposures", "Frame": 1})
    assert _pump(window, lambda: service.model.app_state == "Looping")
    page._tick()
    page.find_btn.click()
    sent("find_star")
    page.recal_check.setChecked(True)
    page.guide_btn.click()
    assert sent("guide")[1] is True
    page.stop_btn.click()
    sent("stop_capture")

    page.exposure_combo.setCurrentIndex(1)
    page.exposure_combo.activated.emit(1)
    assert sent("set_exposure") == [1000]
    page.dec_combo.setCurrentText("South")
    page.dec_combo.activated.emit(page.dec_combo.currentIndex())
    assert sent("set_dec_guide_mode") == ["South"]
    page.clear_cal_btn.click()
    assert sent("clear_calibration") == ["both"]

    phd2.push({"Event": "StartGuiding"})
    assert _pump(window, lambda: service.model.app_state == "Guiding")
    page._tick()
    page.dither_btn.click()
    assert len(sent("dither")) == 3

    page.equip_disconnect_btn.click()
    assert sent("set_connected") == [False]


@pytest.mark.requirement("TC-GUIDE-090")
@pytest.mark.priority("MVP")
def test_tc_guide_090_rejected_command_is_visible_in_the_log(window, phd2):
    """GUIDE-090: when PHD2 refuses a command the user sees why in the log pane."""
    page, service = _connect(window, phd2)
    page.loop_btn.click()  # the fake has no "loop" handler, so it answers with an error
    assert _pump(window, lambda: any("rejected loop" in line for line in service.model.snapshot().log))
    page._tick()
    assert "PHD2 rejected loop" in page.event_log.toPlainText()


@pytest.mark.requirement("TC-GUIDE-050")
@pytest.mark.priority("MVP")
def test_tc_guide_050_page_shows_a_lost_connection(window, phd2):
    """GUIDE-050: if PHD2 goes away the page goes back to Not connected and offers Connect again."""
    page, service = _connect(window, phd2)
    assert phd2.wait_for_client()
    phd2.drop_clients()
    assert _pump(window, lambda: not service.is_connected and not service.model.snapshot().connected)
    page._tick()
    assert page.connect_btn.isEnabled() and "Not connected" in page.status_label.text()
    assert "Lost connection to PHD2." in page.event_log.toPlainText()


def _snapshot(**kw):
    from galileo.guiding import GuideSnapshot

    base = {"version": 1, "connected": True, "phd_version": "2.6.13", "app_state": "Stopped", "phase": "", "settling": False,
                "equipment_connected": True, "exposure_ms": 2000.0, "exposure_options_ms": [1000.0, 2000.0], "dec_mode": "Auto",
                "pixel_scale": 1.5, "frame_size": (640, 480), "star_pos": None, "star_image": None, "samples": [],
                "calibration_points": [], "calibration": None, "log": ["first", "second"], "unit": "arcsec",
                "rms_ra": 0.4, "rms_dec": 0.3, "rms_total": 0.5}
    base.update(kw)
    return GuideSnapshot(**base)


@pytest.mark.requirement("TC-GUIDE-090")
@pytest.mark.priority("P2")
def test_tc_guide_090_refresh_view_enables_controls_per_state_and_connection(window):
    """GUIDE-090: refresh_view enables each control for the PHD2 state (Loop/Guide/Stop/Find star/Dither/Clear
    calibration), the connection controls follow connected/connecting, and the status/state/log text follow the snapshot."""
    page = window._build_guider_page()

    def enabled(snap):
        page.refresh_view(snap)
        return {name: getattr(page, name).isEnabled() for name in (
            "connect_btn", "disconnect_btn", "equip_connect_btn", "equip_disconnect_btn", "loop_btn", "guide_btn",
            "stop_btn", "find_btn", "dither_btn", "clear_cal_btn", "exposure_combo", "dec_combo", "host_edit", "port_spin")}

    off = enabled(None)
    assert off == dict.fromkeys(off, False) | {"connect_btn": True, "host_edit": True, "port_spin": True}
    assert page.status_label.text().startswith("Not connected to PHD2.") and page.state_label.text() == ""
    assert page.event_log.toPlainText() == ""

    table = {  # state: (loop, guide, stop, find, dither, clear_cal)
        "Stopped": (True, True, False, False, False, True),
        "Selected": (True, True, True, True, False, True),
        "Looping": (False, True, True, True, False, True),
        "Guiding": (False, False, True, False, True, False),
        "Calibrating": (False, False, True, False, False, False),
        "LostLock": (True, True, True, True, False, True),
        "Paused": (True, True, True, False, False, True),
    }
    for state, expected in table.items():
        got = enabled(_snapshot(app_state=state))
        assert (got["loop_btn"], got["guide_btn"], got["stop_btn"], got["find_btn"], got["dither_btn"],
                got["clear_cal_btn"]) == expected, state
        assert got["equip_disconnect_btn"] and not got["equip_connect_btn"] and got["exposure_combo"] and got["dec_combo"]
        assert got["disconnect_btn"] and not got["connect_btn"] and not got["host_edit"] and not got["port_spin"]

    no_equipment = enabled(_snapshot(equipment_connected=False))
    assert no_equipment["equip_connect_btn"] and not any(no_equipment[k] for k in (
        "equip_disconnect_btn", "loop_btn", "guide_btn", "stop_btn", "find_btn", "dither_btn", "clear_cal_btn"))
    assert page.status_label.text() == "Connected to PHD2 (PHD2 2.6.13) — equipment not connected — use Connect Equipment."

    page.refresh_view(_snapshot(app_state="Guiding", settling=True, phase="guiding"))
    assert page.state_label.text() == "State: Guiding (settling)"
    assert page.status_label.text() == "Connected to PHD2 (PHD2 2.6.13) — equipment connected."
    assert page.event_log.toPlainText() == "second\nfirst", "newest first"
    assert [page.exposure_combo.itemText(i) for i in range(page.exposure_combo.count())] == ["1 s", "2 s"]
    assert page.exposure_combo.currentText() == "2 s"

    page._connecting.add(page._pier_key())
    assert enabled(None)["connect_btn"] is False and page.connect_btn.text() == "Connecting…"
    page._connecting.discard(page._pier_key())


@pytest.mark.requirement("TC-GUIDE-080")
@pytest.mark.priority("P2")
def test_tc_guide_080_drift_graph_draws_only_the_enabled_series():
    """GUIDE-080: the guide graph paints the RA / Dec / SNR traces and correction bars in their colours only when
    those series are enabled, and still paints (axes, legend) with no samples or a tiny canvas."""
    from types import SimpleNamespace

    from PySide6.QtGui import QColor

    from galileo.ui.guider import _DEC, _RA, _SNR, DriftGraph

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    samples = [SimpleNamespace(t=float(i), ra=(i % 5 - 2) / 2, dec=(i % 3 - 1) / 2, snr=20 + i % 7,
                               ra_pulse_ms=(i % 9 - 4) * 20, dec_pulse_ms=(i % 7 - 3) * 20) for i in range(60)]

    def colours(**series):
        graph = DriftGraph()
        graph.resize(500, 260)
        graph.series = {"ra": False, "dec": False, "snr": False, "corr_ra": False, "corr_dec": False, "rms": False, **series}
        graph.set_data(samples, 1.0, "px", 0.5, 0.5)
        image = graph.grab().toImage()
        seen = {image.pixelColor(x, y).rgb() for x in range(image.width()) for y in range(image.height())}
        return {name: any(abs(QColor(rgb).red() - c.red()) + abs(QColor(rgb).green() - c.green())
                          + abs(QColor(rgb).blue() - c.blue()) < 40 for rgb in seen)
                for name, c in (("ra", _RA), ("dec", _DEC), ("snr", _SNR))}

    assert colours() == {"ra": False, "dec": False, "snr": False}
    assert colours(ra=True) == {"ra": True, "dec": False, "snr": False}
    assert colours(dec=True, snr=True) == {"ra": False, "dec": True, "snr": True}
    def render(**series):
        graph = DriftGraph()
        graph.resize(500, 260)
        graph.series = {"ra": False, "dec": False, "snr": False, "corr_ra": False, "corr_dec": False, "rms": False, **series}
        graph.set_data(samples, 1.0, "px", 0.5, 0.5)
        return bytes(graph.grab().toImage().constBits())

    assert render(corr_ra=True) != render() and render(corr_dec=True) != render(corr_ra=True)   # translucent bars

    empty = DriftGraph()
    empty.resize(10, 10)
    assert not empty.grab().isNull()                      # too small to plot: just the background
    empty.resize(400, 200)
    empty.set_data([], None, "px", 0.0, 0.0)
    assert not empty.grab().isNull()
