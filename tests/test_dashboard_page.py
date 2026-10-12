# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Observatory dashboard screen (``galileo.ui.dashboard``), OBS-060.

``collect_dashboard`` is plain Python and is tested without Qt; the page is built
offscreen inside a real ``AppWindow``.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _record(pier_id, name):
    return SimpleNamespace(id=pier_id, name=name)


def _job(name, run_state="pending"):
    return SimpleNamespace(name=name, run_state=run_state)


@pytest.mark.requirement("TC-OBS-060")
@pytest.mark.priority("P2")
def test_tc_obs_060_dashboard_rows_cover_equipment_sequence_and_scheduler():
    """OBS-060: the dashboard has one row per Pier with equipment, sequence and scheduler state."""
    pytest.importorskip("PySide6.QtWidgets")
    from galileo.ui.dashboard import collect_dashboard, describe_scheduler

    records = [_record(1, "North"), _record(2, "South"), _record(3, "East")]
    schedulers = {
        "North": SimpleNamespace(jobs=[_job("M42", "running"), _job("M31")], active_job=None),
        "South": SimpleNamespace(jobs=[_job("M13"), _job("M57")], active_job=None),
    }
    rows = collect_dashboard(
        "Backyard", records, selected_key=1, selected_connected=True,
        runs={1: ("paused", "M42 LRGB")}, schedulers=schedulers,
        queue_loader=lambda name: SimpleNamespace(jobs=[], active_job=None),
    )
    assert [r["pier_name"] for r in rows] == ["North", "South", "East"]
    north, south, east = rows
    assert (north["equipment_state"], north["sequence_state"], north["selected"]) == ("connected", "paused", True)
    assert describe_scheduler(north) == "running: M42 (+1 queued)"
    assert (south["equipment_state"], south["sequence_state"], south["selected"]) == ("disconnected", "idle", False)
    assert describe_scheduler(south) == "2 queued"
    assert describe_scheduler(east) == "idle"      # queue read through the loader


@pytest.mark.requirement("TC-OBS-060")
@pytest.mark.priority("P2")
def test_tc_obs_060_unreadable_queue_does_not_break_the_dashboard():
    """OBS-060: a Pier whose job queue cannot be read still gets a row (shown idle)."""
    pytest.importorskip("PySide6.QtWidgets")
    from galileo.ui.dashboard import collect_dashboard

    def broken(_name):
        raise RuntimeError("database locked")

    rows = collect_dashboard("Backyard", [_record(1, "North")], queue_loader=broken)
    assert rows[0]["scheduler_state"] == "idle"


QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6 import QtCore


@pytest.fixture
def window(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "dashboard_page.db")
    from galileo.ui.app_window import AppWindow

    win = AppWindow()
    win.app = app
    yield win
    for timer in win._window.findChildren(QtCore.QTimer):
        timer.stop()
    win._window.close()
    win._window.deleteLater()
    app.processEvents()
    db.close()


def _wait_for(app, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.mark.requirement("TC-OBS-060")
@pytest.mark.priority("P2")
def test_tc_obs_060_dashboard_screen_is_in_the_navigation(window):
    """OBS-060: the multi-Pier dashboard is a screen reachable from the sidebar."""
    from galileo.ui.app_window import PRIMARY_SECTIONS
    from galileo.ui.dashboard import DashboardPage
    from galileo.ui.help import SCREEN_PROPERTY

    assert ("dashboard", "Dashboard", "dashboard") in PRIMARY_SECTIONS
    pages = window._window.findChildren(DashboardPage)
    assert len(pages) == 1 and pages[0].property(SCREEN_PROPERTY) == "dashboard"


@pytest.mark.requirement("TC-OBS-060")
@pytest.mark.priority("P2")
def test_tc_obs_060_dashboard_screen_lists_every_pier_without_blocking(window):
    """OBS-060: the screen lists all Piers of the Observatory, filled in from a worker thread, and Open Pier selects one."""
    from galileo.observatory import create_observatory, create_pier, list_piers
    from galileo.ui.dashboard import DashboardPage

    observatory = create_observatory("Dark Site", latitude=-33.9, longitude=151.2)
    create_pier(observatory, "Pier A")
    create_pier(observatory, "Pier B")
    window._current_observatory = observatory
    window._refresh_pier_combo()
    page = window._window.findChildren(DashboardPage)[0]

    page.reload()
    assert page._busy                              # collection runs off the UI thread
    assert _wait_for(window.app, lambda: page._table.rowCount() == 2)
    assert [page._rows[i]["pier_name"] for i in range(2)] == [p.name for p in list_piers(observatory)]
    assert page._table.item(0, 0).text().endswith("(selected)")
    assert not page._busy

    page.open_pier(1)
    assert window._current_pier.name == "Pier B"
