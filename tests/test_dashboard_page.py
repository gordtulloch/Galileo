# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Observatory dashboard screen (``galileo.ui.dashboard``, ``galileo.dashboard_timeline``), OBS-060 / OBS-150.

``collect_dashboard`` and the timeline recorder are plain Python and are tested without Qt; the
page is built offscreen inside a real ``AppWindow``. The plugin-publishing tests are PLUG-180.
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
    assert [r["pier_key"] for r in rows] == [1, 2, 3] and [r["pier_id"] for r in rows] == [1, 2, 3]
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


@pytest.mark.requirement("TC-OBS-140")
@pytest.mark.priority("P2")
def test_tc_obs_140_dashboard_shows_every_piers_own_connection_state():
    """OBS-140: a Pier that is not selected but has live devices reads connected, not disconnected."""
    pytest.importorskip("PySide6.QtWidgets")
    from galileo.ui.dashboard import collect_dashboard

    records = [_record(1, "North"), _record(2, "South"), _record(3, "East")]
    rows = collect_dashboard(
        "Backyard", records, selected_key=1, selected_connected=True,
        queue_loader=lambda name: SimpleNamespace(jobs=[], active_job=None),
        is_connected=lambda record: record.id == 2,
    )
    assert [r["equipment_state"] for r in rows] == ["connected", "connected", "disconnected"]


@pytest.mark.requirement("TC-OBS-150")
@pytest.mark.priority("P2")
def test_tc_obs_150_timeline_records_lanes_from_pier_activity():
    """OBS-150: a Pier's activity becomes segments on the session/mount/guide/capture lanes, capture cut into one box per frame."""
    from galileo import dashboard_timeline as dt

    timeline = dt.PierTimeline("North")
    running = dt.PierActivity(session="running", session_label="M42", mount="tracking", guide="guiding",
                              capture=dt.LIGHT, frames_done=0, guide_error=(0.4, -0.2), guide_sample_id=1)
    timeline.record(running, 100.0)
    timeline.record(running, 130.0)                                         # nothing changed: no new segments
    running2 = dt.PierActivity(**{**running.__dict__, "frames_done": 1, "guide_sample_id": 2})
    timeline.record(running2, 160.0)                                        # a frame finished: capture is cut
    timeline.record(dt.PierActivity(mount="idle"), 200.0)                   # session over

    assert [(s.state, s.start, s.end) for s in timeline.segments(dt.SESSION)] == [(dt.OK, 100.0, 200.0)]
    assert timeline.segments(dt.SESSION)[0].label == "M42"
    assert [(s.start, s.end) for s in timeline.segments(dt.CAPTURE)] == [(100.0, 160.0), (160.0, 200.0)]
    assert [s.state for s in timeline.segments(dt.GUIDE)] == [dt.OK]
    assert timeline.segments(dt.MOUNT)[0].end == 200.0 and timeline.segments(dt.MOUNT)[0].state == dt.OK
    assert timeline.segments(dt.FLIP) == [] and timeline.segments(dt.FOCUS) == []
    # Both guide samples are kept: they are more than a second apart and carry different sample ids.
    assert [(round(ra, 1), round(dec, 1)) for _t, ra, dec in timeline.guide_samples()] == [(0.4, -0.2), (0.4, -0.2)]


@pytest.mark.requirement("TC-OBS-150")
@pytest.mark.priority("P2")
def test_tc_obs_150_timeline_trims_history_and_sizes_its_axis():
    """OBS-150: history older than the retention is dropped, and the time axis spans the recorded period (at least 15 minutes)."""
    from galileo import dashboard_timeline as dt

    timeline = dt.PierTimeline("North", retention_s=3600)
    assert timeline.window(1000.0) == (1000.0 - dt.MIN_SPAN_S, 1000.0)      # nothing recorded yet
    timeline.record(dt.PierActivity(session="running"), 0.0)
    timeline.record(dt.PierActivity(), 100.0)
    timeline.record(dt.PierActivity(session="paused"), 200.0)
    assert timeline.window(1000.0) == (0.0, 1000.0)
    timeline.record(dt.PierActivity(), 5000.0)                              # the first two runs are long past
    assert [s.state for s in timeline.segments(dt.SESSION)] == [dt.WARN]
    assert timeline.window(5000.0)[0] == 5000.0 - 3600


@pytest.mark.requirement("TC-OBS-150")
@pytest.mark.priority("P2")
def test_tc_obs_150_activity_is_read_from_the_session_mount_and_guider():
    """OBS-150: the running block decides the capture/focus/align/flip lanes; mount and guider are read defensively."""
    from galileo import dashboard_timeline as dt

    class ImageBlock: ...
    class AutofocusBlock: ...
    class MeridianFlipBlock: ...
    class FlatCaptureBlock: ...

    def progress(block, state="running", frames=3):
        return SimpleNamespace(state=state, block=block(), frames_done=frames)

    a = dt.activity_from_progress(progress(ImageBlock), SimpleNamespace(is_slewing=False, is_tracking=True),
                                  session_name="M31")
    assert (a.session, a.session_label, a.capture, a.frames_done, a.mount) == ("running", "M31", dt.LIGHT, 3, "tracking")
    assert dt.activity_from_progress(progress(FlatCaptureBlock)).capture == dt.CAL
    assert dt.activity_from_progress(progress(AutofocusBlock)).focusing
    assert dt.activity_from_progress(progress(MeridianFlipBlock)).flipping
    paused = dt.activity_from_progress(progress(ImageBlock, state="paused"))
    assert paused.session == "paused" and paused.capture is None              # a paused session is not exposing
    assert dt.activity_from_progress(progress(ImageBlock, state="completed")).session is None
    idle = dt.activity_from_progress(None, SimpleNamespace(is_slewing=True), manual_focus=True, manual_align=True)
    assert (idle.session, idle.mount, idle.focusing, idle.aligning) == (None, "slewing", True, True)
    assert dt.activity_from_progress(None, None).mount is None                # not connected

    class Broken:
        is_connected = True

        @property
        def model(self):
            raise RuntimeError("PHD2 went away")

    assert dt.activity_from_progress(None, None, Broken()).guide is None

    from galileo.guiding import GuideModel
    model = GuideModel()
    model.apply_event({"Event": "AppState", "State": "Guiding"})
    guider = SimpleNamespace(is_connected=True, model=model)
    assert dt.activity_from_progress(None, None, guider).guide == "guiding"
    model.apply_event({"Event": "AppState", "State": "LostLock"})
    assert dt.activity_from_progress(None, None, guider).guide == "lost"


@pytest.mark.requirement("TC-OBS-150")
@pytest.mark.priority("P2")
def test_tc_obs_150_axis_ticks_and_guide_scale():
    """OBS-150: the time axis ticks fall on round clock times and the guide axis covers the largest error seen."""
    pytest.importorskip("PySide6.QtWidgets")
    from datetime import datetime

    from galileo.ui.dashboard import guide_scale, nice_ticks

    t0 = datetime(2026, 10, 23, 20, 7).timestamp()
    ticks = nice_ticks(t0, t0 + 3 * 3600)
    assert 2 <= len(ticks) <= 9
    assert all(datetime.fromtimestamp(t).minute % 30 == 0 for t in ticks)
    assert all(t0 <= t <= t0 + 3 * 3600 for t in ticks)
    assert len(nice_ticks(t0, t0 + 12 * 3600)) <= 9
    assert guide_scale([]) == 1.0
    assert guide_scale([(0.0, 0.3, -2.4)]) == 3.0


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


def _two_pier_observatory(window):
    from galileo.observatory import create_observatory, create_pier
    observatory = create_observatory("Dark Site", latitude=-33.9, longitude=151.2)
    create_pier(observatory, "Pier A")
    create_pier(observatory, "Pier B")
    window._current_observatory = observatory
    window._refresh_pier_combo()
    return observatory


@pytest.mark.requirement("TC-OBS-060")
@pytest.mark.priority("P2")
def test_tc_obs_060_dashboard_screen_is_in_the_navigation(window):
    """OBS-060: the dashboard is a screen reachable from the sidebar."""
    from galileo.ui.app_window import PRIMARY_SECTIONS
    from galileo.ui.dashboard import DashboardPage
    from galileo.ui.help import SCREEN_PROPERTY

    assert ("dashboard", "Dashboard", "dashboard") in PRIMARY_SECTIONS
    pages = window._window.findChildren(DashboardPage)
    assert len(pages) == 1 and pages[0].property(SCREEN_PROPERTY) == "dashboard"


@pytest.mark.requirement("TC-OBS-150")
@pytest.mark.priority("P2")
def test_tc_obs_150_dashboard_draws_a_timeline_per_pier_without_blocking(window):
    """OBS-150: one timeline per Pier of the Observatory, filled in from a worker thread, with no Pier-picking button."""
    from galileo.observatory import list_piers
    from galileo.ui.dashboard import DashboardPage, PierTimelineWidget

    observatory = _two_pier_observatory(window)
    page = window._window.findChildren(DashboardPage)[0]

    page.reload()
    assert page._busy                              # collection runs off the UI thread
    assert _wait_for(window.app, lambda: len(page._widgets) == 2)
    shown = [page._piers.itemAt(i).widget() for i in range(2)]
    assert [w.title for w in shown] == [p.name for p in list_piers(observatory)]
    assert all(isinstance(w, PierTimelineWidget) for w in shown)
    assert not page.findChildren(QtWidgets.QPushButton)
    assert not page._busy
    page.grab()                                    # paints without error

    page.open_pier(page._rows[1]["pier_key"])
    assert window._current_pier.name == "Pier B"


@pytest.mark.requirement("TC-OBS-150")
@pytest.mark.priority("P2")
def test_tc_obs_150_dashboard_records_pier_activity_in_the_background(window):
    """OBS-150: sampling reads each Pier's own session progress and devices and records them whether or not the screen is showing."""
    from galileo import dashboard_timeline as dt
    from galileo.ui.dashboard import DashboardPage

    _two_pier_observatory(window)
    page = window._window.findChildren(DashboardPage)[0]
    page.reload()
    assert _wait_for(window.app, lambda: len(page._rows) == 2)

    class ImageBlock: ...

    key_a, key_b = page._rows[0]["pier_key"], page._rows[1]["pier_key"]
    window._session_controller = SimpleNamespace(
        progress_snapshot=lambda: {key_a: (SimpleNamespace(state="running", block=ImageBlock(), frames_done=0), "Orion")},
        run_snapshot=dict)
    window._device_pages["mount"] = {
        "adapter": None, "adapter_for": lambda key: SimpleNamespace(is_slewing=False, is_tracking=True) if key == key_b else None}
    page.sample()

    a = page._recorder.timeline(key_a)
    b = page._recorder.timeline(key_b)
    assert [s.state for s in a.segments(dt.CAPTURE)] == [dt.LIGHT] and a.segments(dt.SESSION)[0].label == "Orion"
    assert b.segments(dt.CAPTURE) == [] and [s.state for s in b.segments(dt.MOUNT)] == [dt.OK]
    del window._session_controller


class _DashboardPlugin:
    """The smallest plugin that publishes a Dashboard view."""
    name = "FakeDashboardPlugin"
    dashboard_label = "Fake view"
    options_label = "Fake"

    def __init__(self):
        self.built = 0

    def build_dashboard_widget(self):
        self.built += 1
        label = QtWidgets.QLabel("plugin view")
        label.setObjectName("FakePluginView")
        return label

    def build_options_page(self):
        return QtWidgets.QLabel("options")


def _install_fake_plugin(window):
    plugin = _DashboardPlugin()
    pm = window._plugin_manager
    pm._loaded[plugin.name] = plugin
    pm._active[plugin.name] = True
    pm.get_ui_registry().register_dashboard(plugin)
    return plugin


@pytest.mark.requirement("TC-PLUG-180")
@pytest.mark.priority("P2")
def test_tc_plug_180_publish_on_dashboard_option_controls_the_plugin_view(window):
    """PLUG-180: Galileo adds 'Publish on Dashboard' to the plugin's Options page; ticking it shows the plugin's view above the timelines, unticking removes it."""
    from galileo.plugins import is_published_on_dashboard
    from galileo.ui.dashboard import DashboardPage

    plugin = _install_fake_plugin(window)
    page = window._window.findChildren(DashboardPage)[0]
    page.sync_plugins()
    assert plugin.built == 0 and page._strip.isHidden()                     # not published until ticked

    options = window._build_plugin_options_page(plugin)
    box = next(c for c in options.findChildren(QtWidgets.QCheckBox) if c.text() == "Publish on Dashboard")
    assert not box.isChecked()
    box.setChecked(True)
    assert is_published_on_dashboard(plugin)
    assert plugin.built == 1 and not page._strip.isHidden()
    assert page._strip.findChild(QtWidgets.QLabel, "FakePluginView") is not None
    page.sync_plugins()
    assert plugin.built == 1                                                # the view is built once, not per refresh

    box.setChecked(False)
    assert not is_published_on_dashboard(plugin)
    assert page._plugin_widgets == {} and page._strip.isHidden()


@pytest.mark.requirement("TC-PLUG-180")
@pytest.mark.priority("P2")
def test_tc_plug_180_plugins_without_a_dashboard_view_get_no_option(window):
    """PLUG-180: a plugin that has no dashboard_label gets no 'Publish on Dashboard' box and never publishes."""
    from galileo.plugins import is_published_on_dashboard, set_published_on_dashboard

    plugin = _DashboardPlugin()
    plugin.dashboard_label = ""
    options = window._build_plugin_options_page(plugin)
    assert not [c for c in options.findChildren(QtWidgets.QCheckBox) if c.text() == "Publish on Dashboard"]
    set_published_on_dashboard(plugin, True)
    assert not is_published_on_dashboard(plugin)


@pytest.mark.requirement("TC-PLUG-180")
@pytest.mark.priority("P2")
def test_tc_plug_180_failing_or_disabled_plugin_view_is_skipped(window):
    """PLUG-180: a view that fails to build, or belongs to a disabled plugin, is skipped without breaking the Dashboard."""
    from galileo.plugins import set_published_on_dashboard
    from galileo.ui.dashboard import DashboardPage

    plugin = _install_fake_plugin(window)
    set_published_on_dashboard(plugin, True)
    page = window._window.findChildren(DashboardPage)[0]

    def boom():
        raise RuntimeError("no view today")

    plugin.build_dashboard_widget = boom
    page.sync_plugins()
    assert page._plugin_widgets == {} and page._strip.isHidden()

    del plugin.build_dashboard_widget
    window._plugin_manager._active[plugin.name] = False
    page.sync_plugins()
    assert page._plugin_widgets == {}
    window._plugin_manager._active[plugin.name] = True
    page.sync_plugins()
    assert list(page._plugin_widgets) == [plugin.name]


@pytest.mark.requirement("TC-OBS-150")
@pytest.mark.priority("P2")
def test_tc_obs_150_plugin_strip_leaves_every_pier_timeline_visible(window):
    """OBS-150: the plugin area takes the height the Pier timelines leave free, so all timelines are in view."""
    from galileo.plugins import set_published_on_dashboard
    from galileo.ui.dashboard import MIN_PLUGIN_STRIP_H, DashboardPage, PierTimelineWidget

    _two_pier_observatory(window)
    plugin = _install_fake_plugin(window)
    set_published_on_dashboard(plugin, True)
    page = window._window.findChildren(DashboardPage)[0]
    page.reload()
    assert _wait_for(window.app, lambda: len(page._widgets) == 2)
    page.sync_plugins()

    page.resize(900, 900)
    page._fit_strip()
    timelines = 2 * (PierTimelineWidget.HEIGHT + page._piers.spacing())
    roomy = page._strip.height()
    assert roomy >= MIN_PLUGIN_STRIP_H
    assert roomy + timelines <= 900                                         # strip + both timelines fit the page

    page.resize(900, 300)                                                   # too small: the strip keeps its minimum
    page._fit_strip()
    assert page._strip.height() == MIN_PLUGIN_STRIP_H
