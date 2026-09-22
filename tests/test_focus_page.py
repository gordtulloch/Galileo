# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Focus screen (``galileo.ui.focus.FocusPage``), built offscreen (FOC-090).

The screen follows the autofocus events on the process-wide bus; the tests
publish those events directly for the display rules and run a real
``AutofocusService`` against a fake camera and focuser for the end-to-end case.
"""

from __future__ import annotations

import os
import time

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6 import QtCore

from galileo.autofocus import AutofocusResult
from galileo.bus import (
    FocusCompleteEvent,
    FocusFrameEvent,
    FocusStartedEvent,
    get_bus,
)

NO_STATS = "Stars: 0  HFR: -1.00  FWHM: --"


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "focus_page.db")
    from galileo.ui.app_window import AppWindow

    boxes: list[str] = []
    for kind in ("information", "warning"):
        monkeypatch.setattr(QtWidgets.QMessageBox, kind, staticmethod(lambda *a, **k: boxes.append(a[1])))
    win = AppWindow()
    win.boxes = boxes
    win.app = app
    yield win
    for timer in win._window.findChildren(QtCore.QTimer):
        timer.stop()
    win._window.close()
    win._window.deleteLater()
    app.processEvents()
    db.close()


@pytest.fixture
def page(window):
    from galileo.ui.focus import FocusPage
    return window._window.findChildren(FocusPage)[0]


def _pump(window, condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def _started(**extra):
    payload = {"positions": [4900, 5000, 5100], "initial_position": 5000, "step_size": 100, "num_points": 3}
    get_bus().publish(FocusStartedEvent(source="test", **{**payload, **extra}))


def _frame(position: int, hfr: float, stars: int = 9, fill: int = 1000):
    get_bus().publish(FocusFrameEvent(
        source="test", position=position, hfr=hfr, fwhm=hfr * 1.5, star_count=stars,
        frame=np.full((40, 60), fill, dtype=np.uint16),
    ))


def _complete(result):
    get_bus().publish(FocusCompleteEvent(source="test", result=result))


def _drawn(page) -> bool:
    return page.image_view.has_image


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_focus_is_a_primary_section_with_the_reference_controls(window, page):
    """FOC-090: Focus is a top-level section with focuser/camera controls, an image, statistics, a V-curve and a log."""
    from galileo.ui.app_window import PRIMARY_SECTIONS
    assert {s[0]: s[1] for s in PRIMARY_SECTIONS}["focus"] == "Focus"
    texts = {b.title() for b in page.findChildren(QtWidgets.QGroupBox)}
    assert {"Focuser", "Camera", "Tools"} <= texts
    assert page.autofocus_btn.text() == "Auto Focus" and page.stop_btn.text() == "Stop"
    assert page.stats_label.text() == NO_STATS
    assert not _drawn(page) and page.plot.points == []
    assert len(page.findChildren(QtWidgets.QPlainTextEdit)) == 1        # the log


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_idle_screen_offers_only_what_can_act(window, page):
    """FOC-090: with no run in progress Auto Focus is available and Stop is not."""
    assert page.autofocus_btn.isEnabled() and not page.stop_btn.isEnabled()
    assert page.clear_btn.isEnabled()


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_a_run_updates_image_statistics_and_curve(window, page):
    """FOC-090: each measured frame updates the image, star statistics and V-curve; the result adds the fit."""
    _started()
    assert not page.autofocus_btn.isEnabled() and not page.clear_btn.isEnabled()
    assert page.status_label.text().startswith("Focusing")

    _frame(4900, 3.2, stars=14)
    assert _drawn(page)
    assert page.stats_label.text() == "Stars: 14  HFR: 3.20  FWHM: 4.80"
    _frame(5000, 2.1, stars=17)
    _frame(5100, 3.0, stars=15)
    assert page.plot.points == [(4900, 3.2), (5000, 2.1), (5100, 3.0)]
    assert page.stats_label.text() == "Stars: 15  HFR: 3.00  FWHM: 4.50"
    assert page.position_label.text() == "5100"

    _complete(AutofocusResult(success=True, best_position=5020, curve_coefficients=(1e-4, -1.0, 2600.0)))
    assert page.plot.best_position == 5020 and page.plot.coefficients == (1e-4, -1.0, 2600.0)
    assert page.status_label.text() == "Focus complete — best position 5020."
    assert page.autofocus_btn.isEnabled() and page.clear_btn.isEnabled()


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_nothing_is_redrawn_outside_a_run(window, page):
    """FOC-090: a frame that arrives while no run is in progress leaves the screen alone, before a run and after one."""
    _frame(5000, 2.0)                      # e.g. a confirmation exposure with no run open
    assert not _drawn(page) and page.stats_label.text() == NO_STATS and page.plot.points == []

    _started()
    _frame(4900, 3.2)
    _complete(AutofocusResult(success=True, best_position=5000))
    shown = (page.stats_label.text(), list(page.plot.points), page.status_label.text())

    _frame(5000, 1.1, stars=30)            # the confirmation exposure after the run
    assert (page.stats_label.text(), list(page.plot.points), page.status_label.text()) == shown
    assert _drawn(page)                    # the last run stays on screen


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_failed_run_reports_why_and_keeps_what_was_measured(window, page):
    """FOC-090: a failed run says why on the screen and leaves the measured points visible."""
    _started()
    _frame(4900, 3.2)
    _complete(AutofocusResult(success=False, failure_reason="No valid HFR measurements"))
    assert page.status_label.text() == "Focus failed — No valid HFR measurements."
    assert page.plot.points == [(4900, 3.2)] and page.plot.best_position is None


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_a_new_run_starts_from_a_clean_screen(window, page):
    """FOC-090: starting the next run forgets the previous run's image, statistics and curve."""
    _started()
    _frame(4900, 3.2)
    _complete(AutofocusResult(success=True, best_position=5000, curve_coefficients=(1e-4, -1.0, 2600.0)))
    _started()
    assert not _drawn(page) and page.stats_label.text() == NO_STATS
    assert page.plot.points == [] and page.plot.coefficients is None
    _complete(AutofocusResult(success=False, failure_reason="Cancelled"))


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_clear_forgets_the_last_run_but_not_a_run_in_progress(window, page):
    """FOC-090: Clear empties the screen between runs and is unavailable during one."""
    _started()
    _frame(4900, 3.2)
    page.clear()
    assert page.plot.points == [(4900, 3.2)]          # ignored mid-run
    _complete(AutofocusResult(success=False, failure_reason="Cancelled"))
    page.clear_btn.click()
    assert not _drawn(page) and page.plot.points == [] and page.stats_label.text() == NO_STATS


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_auto_focus_needs_a_camera_and_a_focuser(window, page):
    """FOC-090: Auto Focus without connected equipment says what is missing and starts nothing."""
    page.autofocus_btn.click()
    assert window.boxes == ["Equipment not connected"]
    assert page._service is None and page.autofocus_btn.isEnabled()


class _FakeFocuser:
    position = 5000
    temperature = 12.5

    async def move_to(self, position: int) -> None:
        self.position = position


class _FakeCamera:
    def __init__(self, focuser: _FakeFocuser) -> None:
        self._focuser = focuser
        self.exposures: list[float] = []

    async def start_exposure(self, duration: float, **kwargs) -> None:
        self.exposures.append(duration)

    async def get_image_array(self):
        return np.full((40, 60), self._focuser.position, dtype=np.float32)


@pytest.fixture
def rig(window, monkeypatch):
    """A fake camera and focuser wired into the window, and a V-curve centred on 5020."""
    from galileo import autofocus
    focuser = _FakeFocuser()
    camera = _FakeCamera(focuser)
    window._camera_backends["primary camera"] = camera
    window._device_pages["focuser"]["get_adapter"] = lambda: focuser
    monkeypatch.setattr(autofocus, "_measure_stars", lambda frame: (1.0 + ((float(frame[0, 0]) - 5020) / 300) ** 2, 11))
    return camera, focuser


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_auto_focus_button_runs_a_sweep_and_shows_it(window, page, rig):
    """FOC-090: Auto Focus runs the sweep with the entered step size, points and exposure, and the screen shows it."""
    camera, _focuser = rig
    page.step_spin.setValue(100)
    page.points_spin.setValue(7)
    page.exposure_spin.setValue(1.5)
    page.autofocus_btn.click()
    assert not page.autofocus_btn.isEnabled() and page.stop_btn.isEnabled()

    assert _pump(window, lambda: page._service is None and page.status_label.text().startswith("Focus complete"))
    assert [p for p, _ in page.plot.points] == [4700, 4800, 4900, 5000, 5100, 5200, 5300]
    # 7 sweep exposures plus 1 confirmation exposure at the computed best position (FOC-020)
    assert camera.exposures == [1.5] * 8
    assert abs(page.plot.best_position - 5020) < 50
    assert page.stats_label.text().startswith("Stars: 11")
    assert _drawn(page)
    assert page.autofocus_btn.isEnabled() and not page.stop_btn.isEnabled()


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_stop_ends_the_run_and_restores_the_focuser(window, page, rig):
    """FOC-090: Stop cancels the run it started; the focuser goes back to where it began."""
    import threading
    camera, focuser = rig
    original = camera.get_image_array
    exposing, release = threading.Event(), threading.Event()

    async def held_image():
        exposing.set()
        release.wait(5)                    # hold the first exposure until the user has pressed Stop
        return await original()

    camera.get_image_array = held_image
    page.points_spin.setValue(9)
    page.autofocus_btn.click()
    assert exposing.wait(5)
    page.stop_btn.click()
    assert page.status_label.text().startswith("Stopping")
    release.set()
    assert _pump(window, lambda: page._service is None and page.status_label.text().startswith("Focus failed"))
    assert page.status_label.text() == "Focus failed — Cancelled."
    assert focuser.position == 5000
    assert len(page.plot.points) < 9


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_a_run_started_elsewhere_is_followed(window, page, rig):
    """FOC-090: a run started by something other than this screen (a sequencer trigger) is displayed the same way."""
    import asyncio

    from galileo.autofocus import AutofocusService
    camera, focuser = rig

    asyncio.run(AutofocusService(camera=camera, focuser=focuser, exposure_s=0.5).run(step_size=100, num_points=5))
    assert [p for p, _ in page.plot.points] == [4800, 4900, 5000, 5100, 5200]
    assert page.status_label.text().startswith("Focus complete")
    assert page._service is None and page.autofocus_btn.isEnabled()


@pytest.mark.requirement("TC-FOC-090")
@pytest.mark.priority("MVP")
def test_tc_foc_090_a_deleted_page_stops_listening(window):
    """FOC-090: a page that has been deleted leaves no handlers behind on the process-wide bus."""
    from galileo.ui.focus import FocusPage
    bus = get_bus()
    before = {t: len(bus._handlers[t]) for t in (FocusStartedEvent, FocusFrameEvent, FocusCompleteEvent)}
    extra = FocusPage(window)
    assert all(len(bus._handlers[t]) == n + 1 for t, n in before.items())
    extra.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    assert {t: len(bus._handlers[t]) for t in before} == before
