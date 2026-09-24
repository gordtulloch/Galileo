# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Solve screen (``galileo.ui.solve.SolvePage``), built offscreen (PLT-070).

The screen follows solves on the process-wide event bus, whoever started them. The tests start
solves the way another part of the application would — a ``PlateSolver`` running on its own thread
— for the display rules, and click the screen's own buttons for the capture-and-solve flow. The
solver, camera and mount are fakes; the frames are real FITS files.
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import threading
import time
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6 import QtCore

from galileo.bus import SolveCompleteEvent, SolveStartedEvent, get_bus
from galileo.observatory import (
    create_observatory,
    create_pier,
    delete_device_config,
    save_device_config,
)
from galileo.platesolve import (
    PlateSolver,
    SolveResult,
    mount_frame_to_j2000,
)

pytestmark = [pytest.mark.requirement("TC-PLT-070"), pytest.mark.priority("MVP")]

MOUNT_JNOW = (100.0, 20.0)         # where the fake mount says it points, in its own (JNow) frame


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "solve_page.db")
    import galileo.platform
    import galileo.ui.solve as solve_ui
    monkeypatch.setattr(galileo.platform, "get_cache_dir", lambda: tmp_path)       # frames go under tmp_path
    monkeypatch.setattr(solve_ui, "nearest_object_name", lambda ra, dec: "Polaris")  # no catalogue lookups
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
    win._window.show()
    yield win
    for timer in win._window.findChildren(QtCore.QTimer):
        timer.stop()
    win._window.close()
    win._window.deleteLater()
    app.processEvents()
    db.close()


@pytest.fixture(autouse=True)
def _log_tail(caplog):
    """Feed the on-screen log tail (LOG-020) from INFO records, as the running application does."""
    import logging

    from galileo import diagnostics
    diagnostics._ensure_tail_handler()
    caplog.set_level(logging.INFO)


@pytest.fixture
def page(window):
    from galileo.ui.solve import SolvePage
    return window._window.findChildren(SolvePage)[0]


def _section_index(section_id: str) -> int:
    from galileo.ui.app_window import PRIMARY_SECTIONS
    return [s[0] for s in PRIMARY_SECTIONS].index(section_id)


def _open(window, section_id: str = "solve") -> None:
    """Switch the window to a section, as clicking its sidebar button does."""
    window._current_primary_section = section_id
    window._primary_stack.setCurrentIndex(_section_index(section_id))
    window.app.processEvents()


def _pump(window, condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def _frame(tmp_path, name: str = "frame.fits"):
    """A small real FITS frame with a few bright stars."""
    from astropy.io import fits
    data = np.random.default_rng(3).normal(500, 20, (60, 80)).astype(np.float32)
    for y, x in ((10, 12), (30, 40), (45, 66)):
        data[y - 1:y + 2, x - 1:x + 2] += 3000
    path = tmp_path / name
    fits.PrimaryHDU(data).writeto(path)
    return path


def _solve_elsewhere(frame, result: SolveResult) -> threading.Thread:
    """Solve *frame* the way another workflow would: a PlateSolver on its own thread and event loop."""
    solver = PlateSolver(backend="astap", executable="unused")
    solver._run_solver = AsyncMock(return_value=result)
    thread = threading.Thread(target=lambda: asyncio.run(solver.solve(frame)))
    thread.start()
    return thread


def _texts(page, kind) -> list[str]:
    return [w.text() for w in page.findChildren(kind)]


GOOD = SolveResult(success=True, ra_deg=37.95, dec_deg=89.26, rotation_deg=1.5, scale_arcsec_px=3.0)


class _Devices:
    """A fake camera, mount and scripted solver installed on the window and page."""

    def __init__(self, window, page, solutions):
        self.calls: list = []
        self.camera = MagicMock(name="cam")
        self.camera.start_exposure = AsyncMock()
        self.camera.get_image_array = AsyncMock(return_value=np.random.default_rng(1).integers(0, 4000, (60, 80)).astype(np.uint16))
        self.camera.abort_exposure = AsyncMock()
        self.mount = MagicMock(name="mount")
        self.mount.get_status = AsyncMock(return_value={
            "right_ascension": MOUNT_JNOW[0] / 15.0, "declination": MOUNT_JNOW[1],
            "equatorial_system": "JNOW", "slewing": False})
        self.mount.sync_to_coordinates = AsyncMock(side_effect=lambda ra, dec: self.calls.append(("sync", ra, dec)))
        self.mount.slew_to_coordinates = AsyncMock(side_effect=lambda ra, dec: self.calls.append(("slew", ra, dec)))
        self.mount.abort_slew = AsyncMock()
        window._camera_backends["primary camera"] = self.camera
        window._device_pages["mount"]["adapter"] = self.mount
        self.solver = PlateSolver(backend="astap", executable="unused")
        self.solver._run_solver = AsyncMock(side_effect=solutions) if isinstance(solutions, list) else AsyncMock(return_value=solutions)
        page.make_solver = lambda: self.solver

    @staticmethod
    def near_mount(d_ra_deg: float = 0.0, d_dec_deg: float = 0.0) -> SolveResult:
        """A solution near where the fake mount points (given in J2000, which is what solvers return)."""
        ra, dec = mount_frame_to_j2000(*MOUNT_JNOW, "JNOW")
        return SolveResult(success=True, ra_deg=ra + d_ra_deg, dec_deg=dec + d_dec_deg, rotation_deg=0.0, scale_arcsec_px=3.0)


# ---------------------------------------------------------------------------
# The section and its layout
# ---------------------------------------------------------------------------

def test_tc_plt_070_solve_is_a_top_level_section(window):
    """PLT-070: Solve is a top-level sidebar section with its own icon, and gets a settings page under Options."""
    from galileo.ui.app_window import OPTIONS_ITEMS, PRIMARY_SECTIONS
    from galileo.ui.icons import ICONS, make_icon
    sections = {s[0]: s for s in PRIMARY_SECTIONS}
    assert sections["solve"] == ("solve", "Solve", "solve")
    assert [s[0] for s in PRIMARY_SECTIONS].index("solve") > [s[0] for s in PRIMARY_SECTIONS].index("imaging")
    assert ("solve", "Solve", "solve") in OPTIONS_ITEMS
    assert "solve" in ICONS and not make_icon("solve", "#ffffff").isNull()
    assert set(window._device_pages["solve"]) == {"reload", "refresh_target"}      # and no auto-connect


@pytest.mark.requirement("TC-PLT-060")
@pytest.mark.priority("P2")
def test_tc_plt_060_options_solve_page_saves_and_reloads_per_pier(window):
    """PLT-060: Options > Solve's Save button persists the current Pier's solver defaults, and
    switching Pier reloads the page's own fields from the newly selected one."""
    from galileo.observatory import create_observatory, create_pier, get_solver_settings

    from PySide6.QtWidgets import QDoubleSpinBox, QLineEdit, QPushButton, QSpinBox

    window._on_pier_changed()   # the window fixture sets _current_pier before this page's own refresh runs

    exe_edit = next(w for w in window._options_page.findChildren(QLineEdit)
                    if w.toolTip().startswith("Path to the ASTAP executable"))
    page = exe_edit.parentWidget()
    fov_spin = next(w for w in page.findChildren(QDoubleSpinBox) if w.toolTip().startswith("Field-of-view hint"))
    radius_spin = next(w for w in page.findChildren(QDoubleSpinBox) if w.toolTip().startswith("The solver searches"))
    downsample_spin = next(w for w in page.findChildren(QSpinBox) if w.toolTip().startswith("Downsample the frame"))
    save_btn = next(b for b in page.findChildren(QPushButton) if b.text() == "Save")

    exe_edit.setText("/usr/local/bin/astap")
    fov_spin.setValue(3.0)
    radius_spin.setValue(20.0)
    downsample_spin.setValue(2)
    save_btn.click()

    executable, params = get_solver_settings(window.pier)
    assert executable == "/usr/local/bin/astap"
    assert (params.fov_hint_deg, params.search_radius_deg, params.downsample) == (3.0, 20.0, 2)

    other_pier = create_pier(create_observatory("Obs PLT-060 UI"), "Pier PLT-060 UI")
    window._current_pier = other_pier
    window._on_pier_changed()
    assert exe_edit.text() == ""
    assert fov_spin.value() == 0.0


def test_tc_plt_070_screen_has_the_reference_elements(page):
    """PLT-070: The screen carries the elements of the reference layout (assets/samples/solve.png)."""
    QW = QtWidgets
    titles = [g.title() for g in page.findChildren(QW.QGroupBox)]
    assert titles == ["Solver Control", "Solver Action", "Telescope Coordinates (JNow)",
                      "Solution Coordinates (JNow)", "Plate Solve Capture Options", "Solver Mode"]
    buttons = _texts(page, QW.QPushButton)
    for label in ("Capture && Solve", "Load && Slew…", "Stop"):
        assert label in buttons
    assert "Manual" not in buttons and "Mount Model" not in buttons        # not offered
    assert buttons.count("Clear") == 1                                     # the results' Clear only; the log has none
    assert _texts(page, QW.QRadioButton) == ["Sync", "Slew to Target", "Nothing", "ASTAP"]    # ASTAP is the only solver
    tabs = page.findChild(QW.QTabWidget)
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Solution Results", "Polar Alignment"]
    assert [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())] == \
        ["RA", "DEC", "Obj Name", "Result", "dRA", "dDE"]
    assert set(page.solution) == {"ra", "dec", "err", "pix", "pa", "fov", "ratio", "fl", "fnum"}
    assert page.exposure_spin.value() == 5.0 and page.accuracy_spin.value() == 30 and page.settle_spin.value() == 1500


def test_tc_plt_070_controls_offer_only_what_can_act(page):
    """PLT-070: Idle, Stop is off; Nothing is the default action (the mount isn't moved unless asked); ASTAP is selected."""
    from galileo.platesolve import SolveAction
    assert page.capture_btn.isEnabled() and page.load_btn.isEnabled() and not page.stop_btn.isEnabled()
    assert page.action_radios[SolveAction.NOTHING].isChecked()
    assert page.astap_radio.isChecked()


def test_tc_plt_070_top_bar_selectors_follow_the_solve_screen(window):
    """PLT-070: Solve needs an optical train, so the top bar offers both the Optics and the Camera selector there — and neither off it."""
    for slot in ("primary", "camera_2"):
        save_device_config(window.pier, "camera", driver="Alpaca", server="x", port=1, device_name=f"cam {slot}", slot=slot)
    _open(window, "equipment")
    window._refresh_optics_combo()
    window._refresh_camera_combo()
    assert not window._optics_combo.isVisibleTo(window._window) and not window._camera_combo.isVisibleTo(window._window)
    _open(window, "solve")
    window._refresh_optics_combo()
    window._refresh_camera_combo()
    assert window._optics_combo.isVisibleTo(window._window) and window._camera_combo.isVisibleTo(window._window)

    # And with a single camera too: which camera Solve will use is never left to be inferred.
    delete_device_config(window.pier, "camera", slot="camera_2")
    window._refresh_camera_combo()
    assert window._camera_combo.isVisibleTo(window._window) and window._camera_combo.count() == 1


# ---------------------------------------------------------------------------
# Following solves — and only while in view
# ---------------------------------------------------------------------------

def test_tc_plt_070_shows_a_solve_started_elsewhere(window, page, tmp_path):
    """PLT-070: A solve started by another part of the application shows its frame and results on the screen."""
    _open(window)
    frame = _frame(tmp_path)
    _solve_elsewhere(frame, GOOD).join()
    assert _pump(window, lambda: page.table.rowCount() == 1 and page.image_view.has_image and page._rows[0].status == "solved")

    assert [page.table.item(0, c).text() for c in (2, 3)] == ["Polaris", "✔"]
    assert page.table.item(0, 0).text() != "" and page.table.item(0, 1).text() != ""
    assert page.solution["pix"].text() == '3.00″' and page.solution["pa"].text() == "1.50°"
    assert page.solution["ra"].text() != "—"
    assert "frame.fits" in page.frame_label.text() and "solved" in page.frame_label.text()
    assert page._shown_path == str(frame)
    assert page.table.item(0, 4).text() == ""            # nobody gave it a target, so there is no error to show


def test_tc_plt_070_shows_a_failed_solve_with_its_reason(window, page, tmp_path):
    """PLT-070: A failed solve is a row marked as failed, whose reason is on hover; it does not replace the last good solution."""
    _open(window)
    _solve_elsewhere(_frame(tmp_path, "a.fits"), GOOD).join()
    assert _pump(window, lambda: page._rows and page._rows[0].status == "solved")
    _solve_elsewhere(_frame(tmp_path, "b.fits"), SolveResult(success=False, failure_reason="Not enough stars.")).join()
    assert _pump(window, lambda: len(page._rows) == 2 and page._rows[1].status == "failed")
    assert page.table.item(1, 3).text() == "✘" and page.table.item(1, 3).toolTip() == "Not enough stars."
    assert page.solution["pix"].text() == '3.00″'          # still the earlier good solution


def test_tc_plt_070_does_not_change_while_not_in_view(window, page, tmp_path):
    """PLT-070: While another section is showing, a solve changes nothing on the screen — no image decoded, no widget touched,
    no mount polling — and the screen catches up when it is shown again."""
    _open(window, "equipment")
    assert not page.isVisible() and not page._mount_timer.isActive()
    frame = _frame(tmp_path)
    _solve_elsewhere(frame, GOOD).join()
    assert _pump(window, lambda: len(page._rows) == 1 and page._rows[0].status == "solved")   # the result is recorded…

    assert page.table.rowCount() == 0                         # …but nothing was drawn
    assert not page.image_view.has_image and page._loading_path is None and page._shown_path is None
    assert page.solution["ra"].text() == "—" and page.frame_label.text() == "No frame yet"

    _open(window)                                              # back on the Solve screen
    assert page._mount_timer.isActive()
    assert page.table.rowCount() == 1 and page.table.item(0, 3).text() == "✔"
    assert page.solution["pix"].text() == '3.00″'
    assert _pump(window, lambda: page.image_view.has_image)    # the frame is loaded on return
    assert page._shown_path == str(frame)

    _open(window, "equipment")
    assert not page._mount_timer.isActive()


def test_tc_plt_070_log_is_the_live_application_log_tail_and_only_runs_in_view(window, page):
    """PLT-070: The bottom pane is the application's live log tail, the full width of the page (as on the Equipment screens),
    and is refreshed only while the screen is in view."""
    import logging
    _open(window, "equipment")
    assert not page._log_timer.isActive()
    logging.getLogger("galileo.test").info("written while the Solve screen was hidden")
    window.app.processEvents()
    assert "written while the Solve screen was hidden" not in page.log_pane.toPlainText()   # the pane wasn't touched
    _open(window)                                                            # showing it catches up at once
    assert page._log_timer.isActive()
    assert "written while the Solve screen was hidden" in page.log_pane.toPlainText()

    logging.getLogger("galileo.test").info("written while the Solve screen was showing")
    page._log_timer.timeout.emit()
    assert "written while the Solve screen was showing" in page.log_pane.toPlainText()

    assert page.log_pane.width() == page.image_view.width()                  # no side buttons; full width
    _open(window, "equipment")
    assert not page._log_timer.isActive()


def test_tc_plt_070_screen_updates_through_a_solve_in_progress(window, page, tmp_path):
    """PLT-070: A solve shows as in progress from its start event, and is completed in place by its complete event."""
    _open(window)
    frame = str(_frame(tmp_path))
    get_bus().publish(SolveStartedEvent(source="test", fits_path=frame))
    assert _pump(window, lambda: page.table.rowCount() == 1)
    assert page.table.item(0, 3).text() == "…" and "solving" in page.frame_label.text()
    assert _pump(window, lambda: page.image_view.has_image)   # the frame is shown while it is being solved
    get_bus().publish(SolveCompleteEvent(source="test", fits_path=frame, result=GOOD))
    assert _pump(window, lambda: page.table.item(0, 3).text() == "✔")
    assert page.table.rowCount() == 1


# ---------------------------------------------------------------------------
# Capture & Solve, Load & Slew, Stop
# ---------------------------------------------------------------------------

def test_tc_plt_070_capture_and_solve_fills_the_screen(window, page):
    """PLT-070: Capture & Solve takes a frame, solves it, and shows the frame, the solution, its error against
    the target (where the mount pointed), and a timestamped log with the newest line first."""
    _open(window)
    devices = _Devices(window, page, _Devices.near_mount(d_ra_deg=0.01))     # ~34″ east of the mount's pointing
    page.poll_mount()                                                        # (the screen polls on a timer; don't wait for it)
    assert _pump(window, lambda: page.scope_ra.text() != "")                 # the mount's position is on show
    page.exposure_spin.setValue(2.0)
    page.capture_btn.click()
    assert page._running and not page.capture_btn.isEnabled() and page.stop_btn.isEnabled()
    assert _pump(window, lambda: not page._running and page.table.rowCount() == 1 and page._rows[0].status == "solved")

    devices.camera.start_exposure.assert_awaited_once()
    assert devices.camera.start_exposure.await_args.kwargs["duration"] == 2.0
    assert devices.calls == []                                               # default action: leave the mount alone
    row = page._rows[0]
    assert row.d_ra_arcsec == pytest.approx(0.01 * np.cos(np.radians(20.0)) * 3600, rel=0.02)
    assert row.d_dec_arcsec == pytest.approx(0.0, abs=0.1)
    assert page.table.item(0, 4).text().startswith("+") and page.table.item(0, 5).text() != ""
    assert re.match(r"33\.\d″ +\(dRA \+33\.\d″, dDE [+-]0\.\d″\)", page.solution["err"].text())
    assert _pump(window, lambda: page.image_view.has_image)
    assert page.capture_btn.isEnabled() and not page.stop_btn.isEnabled() and not page.busy.isVisible()

    page._refresh_log()                                                      # (the screen does this on a timer)
    lines = [line for line in page.log_pane.toPlainText().splitlines() if "galileo.ui.solve" in line]
    joined = "\n".join(lines)                                                # the application log, oldest first
    assert joined.index("Setting target") < joined.index("Capturing image") < joined.index("Solver completed")


def test_tc_plt_070_the_chosen_action_is_carried_out(window, page):
    """PLT-070: The Solver Action radio decides whether the solved position is synced to the mount."""
    from galileo.platesolve import SolveAction
    _open(window)
    devices = _Devices(window, page, _Devices.near_mount(d_ra_deg=0.01))
    page.action_radios[SolveAction.SYNC].setChecked(True)
    page.capture_btn.click()
    assert _pump(window, lambda: not page._running)
    assert [c[0] for c in devices.calls] == ["sync"]
    ra, dec = devices.calls[0][1:]         # sent in the mount's own frame: 0.01° east of where it pointed
    assert ra == pytest.approx(MOUNT_JNOW[0] + 0.01, abs=1e-3) and dec == pytest.approx(MOUNT_JNOW[1], abs=1e-3)


def test_tc_plt_070_stop_ends_a_run_in_progress(window, page):
    """PLT-070: Stop cancels a run mid-exposure, aborts the camera, and puts the controls back."""
    _open(window)
    devices = _Devices(window, page, _Devices.near_mount())
    started = threading.Event()

    async def long_exposure(**kwargs):
        started.set()
        await asyncio.Event().wait()
    devices.camera.start_exposure = long_exposure
    page.capture_btn.click()
    assert _pump(window, started.is_set) and page.stop_btn.isEnabled()
    page.stop_btn.click()
    assert _pump(window, lambda: not page._running)
    devices.camera.abort_exposure.assert_awaited()
    page._refresh_log()
    assert "Stopped." in page.log_pane.toPlainText()
    assert page.capture_btn.isEnabled() and not page.stop_btn.isEnabled()
    assert page.table.rowCount() == 0                          # nothing was solved


def test_tc_plt_070_capture_without_a_camera_asks_for_one(window, page):
    """PLT-070: With no camera connected Capture & Solve says so instead of starting."""
    _open(window)
    window._camera_backends.clear()
    page.capture_btn.click()
    assert window.boxes == ["No camera connected"] and not page._running


def test_tc_plt_070_solving_without_astap_says_where_to_get_it(window, page, monkeypatch):
    """PLT-070: With ASTAP missing, Capture & Solve explains that rather than failing later in the log."""
    _open(window)
    _Devices(window, page, _Devices.near_mount())
    monkeypatch.setattr(PlateSolver, "_find_executable", staticmethod(lambda backend: ""))
    page.make_solver = page._default_solver
    page.capture_btn.click()
    assert window.boxes == ["ASTAP not found"] and not page._running


@pytest.mark.requirement("TC-PLT-060")
@pytest.mark.priority("P2")
def test_tc_plt_060_default_solver_uses_the_current_piers_saved_settings(window, page, monkeypatch):
    """PLT-060: Options > Solve's saved executable path and search parameters, for the
    currently selected Pier, are what a real Capture & Solve/Load & Slew run actually builds
    its PlateSolver from — not always the auto-detected executable and hardcoded defaults."""
    from galileo.observatory import save_solver_settings
    from galileo.platesolve import SolverParams

    monkeypatch.setattr(PlateSolver, "_find_executable", staticmethod(lambda backend: ""))
    save_solver_settings(window.pier, "/opt/astap/astap",
                         SolverParams(fov_hint_deg=1.5, search_radius_deg=12.0, downsample=3))

    solver = page._default_solver()
    assert solver is not None
    assert solver.executable == "/opt/astap/astap"
    assert (solver.params.fov_hint_deg, solver.params.search_radius_deg, solver.params.downsample) == (1.5, 12.0, 3)


def test_tc_plt_070_load_and_slew_solves_the_chosen_file(window, page, tmp_path, monkeypatch):
    """PLT-070: Load & Slew solves the FITS file picked in the dialog and slews the mount to its position."""
    _open(window)
    frame = _frame(tmp_path, "picked.fits")
    devices = _Devices(window, page, GOOD)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(frame), "")))
    page.load_btn.click()
    assert _pump(window, lambda: not page._running and page.table.rowCount() == 1)
    assert [c[0] for c in devices.calls] == ["slew"]
    assert page._rows[0].status == "solved"


def test_tc_plt_070_cancelling_the_file_dialog_does_nothing(window, page, monkeypatch):
    """PLT-070: Dismissing the Load & Slew file dialog starts nothing."""
    _open(window)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    page.load_btn.click()
    assert not page._running and page.table.rowCount() == 0


# ---------------------------------------------------------------------------
# Results table and plot
# ---------------------------------------------------------------------------

def _add_result(page, path: str, result: SolveResult, target=None) -> None:
    page._on_solve_started({"path": path})
    if target is not None:
        page._workflow = type("W", (), {"target": target})()
        page._run_target_active = True
    page._on_solve_finished({"path": path, "result": result, "size": (80, 60), "name": "Polaris"})
    page._run_target_active = False


def test_tc_plt_070_results_can_be_cleared_removed_and_saved(window, page, tmp_path, monkeypatch):
    """PLT-070: Clear empties the table, Remove drops the selected rows, and Save writes the rest as CSV."""
    _open(window)
    for i in range(3):
        _add_result(page, f"f{i}.fits", GOOD, target=(37.95, 89.26 + 0.001 * i))
    assert page.table.rowCount() == 3

    page.table.selectRow(0)
    page.remove_btn.click()
    assert page.table.rowCount() == 2

    out = tmp_path / "out.csv"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    page.save_btn.click()
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["fits_path"] for r in rows] == ["f1.fits", "f2.fits"]
    assert float(rows[0]["ra_deg_j2000"]) == pytest.approx(37.95) and rows[0]["solved"] == "True"

    page.clear_results_btn.click()
    assert page.table.rowCount() == 0 and page.solution["ra"].text() == "—"


def test_tc_plt_070_error_plot_shows_solutions_that_have_a_target(window, page):
    """PLT-070: Only solutions that were compared with a target reach the error plot, and its rings follow Accuracy."""
    _open(window)
    _add_result(page, "a.fits", GOOD)                                          # no target: nothing to plot
    _add_result(page, "b.fits", GOOD, target=(37.95 + 0.01, 89.26))
    assert len(page.error_plot.points) == 1
    d_ra, d_dec = page.error_plot.points[0]
    assert d_ra != 0.0 or d_dec != 0.0
    page.accuracy_spin.setValue(45)
    assert page.error_plot.ring == 45.0
    page.error_plot.grab()                                                     # paints without error


def test_tc_plt_070_focal_length_and_scale_ratio_use_the_camera_and_train(window, page):
    """PLT-070: With the optical train and camera pixel size known, the solution shows the solved focal length, f-ratio and
    how far the solved pixel scale is from the one the train predicts."""
    from galileo.observatory import save_optical_tubes
    save_optical_tubes(window.pier, [{"name": "Scope", "focal_length_mm": 500.0, "aperture_mm": 100.0}])
    save_device_config(window.pier, "camera", driver="Alpaca", server="x", port=1, device_name="cam", slot="primary",
                       pixel_size_um=3.76)
    _open(window)
    expected_scale = 206.265 * 3.76 / 500.0                                    # 1.551″/px
    _add_result(page, "a.fits", SolveResult(success=True, ra_deg=10.0, dec_deg=20.0, rotation_deg=0.0,
                                            scale_arcsec_px=expected_scale * 1.02))
    assert page.solution["ratio"].text() == "1.02x"
    assert page.solution["fl"].text().endswith("(500)") and page.solution["fl"].text().startswith("490")
    assert page.solution["fnum"].text().startswith("4.9") and page.solution["fnum"].text().endswith("(5.0)")


# ---------------------------------------------------------------------------
# Bus housekeeping
# ---------------------------------------------------------------------------

def test_tc_plt_070_page_stops_listening_once_deleted(window, page):
    """PLT-070: A deleted page unsubscribes from the bus, so long-lived solves don't call into freed widgets."""
    bus = get_bus()
    handlers = list(page._bus_handlers)
    assert all(h in bus._handlers[t] for t, h in handlers)
    page.setParent(None)
    page.deleteLater()
    window.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    window.app.processEvents()
    assert not any(h in bus._handlers[t] for t, h in handlers)
    bus.publish(SolveStartedEvent(source="test", fits_path="x.fits"))          # nothing left to call into
