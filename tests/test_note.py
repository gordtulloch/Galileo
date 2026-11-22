"""NOTE — event notices (TC-NOTE-010 … TC-NOTE-060)."""

from __future__ import annotations

import pytest

from galileo import notices
from galileo.bus import (
    DeviceConnectedEvent,
    DeviceDisconnectedEvent,
    EventBus,
    FocusCompleteEvent,
    SolveCompleteEvent,
    SolveStartedEvent,
)
from galileo.notices import NoticeEvent


@pytest.fixture
def bus():
    b = EventBus()
    seen: list[dict] = []
    b.subscribe(NoticeEvent, lambda e: seen.append(dict(e.payload)))
    b.seen = seen
    return b


@pytest.mark.requirement("TC-NOTE-020")
@pytest.mark.priority("MVP")
def test_tc_note_020_notice_text(monkeypatch):
    """NOTE-020: the text names what happened, with the values a person wants (duration, coordinates)."""
    got: list[tuple] = []
    monkeypatch.setattr(notices, "post_notice", lambda kind, title, message="", severity="info", **kw: got.append(
        (kind, title, message, severity)))
    notices.notice_for_command("Camera", "start_exposure", "ZWO", duration=30, frame_type="Light")
    notices.notice_for_command("Telescope", "slew_to_coordinates", "EQ6", ra=180.0, dec=-12.5)
    notices.notice_for_command("Telescope", "slewtocoordinatesasync", "M", RightAscension=3.0, Declination=40.0)
    notices.notice_for_command("Camera", "startexposure", "A", Duration=5, Light=False)
    notices.notice_for_command("Telescope", "move_axis", "EQ6", axis=0, deg_per_s=1.0)
    assert got[0] == ("exposure.started", "Exposure started", "30 s Light — Camera ZWO", "info")
    assert got[1][:2] == ("slew.started", "Slew started") and "RA 12h00.0m" in got[1][2] and "-12°30" in got[1][2]
    assert "RA 03h00.0m" in got[2][2], "an Alpaca body (hours) is shown the same way"
    assert "5 s Dark" in got[3][2]
    assert len(got) == 4, "continuous-motion commands are not announced"


@pytest.mark.requirement("TC-NOTE-020")
@pytest.mark.priority("MVP")
def test_tc_note_020_slew_end_is_posted_once(monkeypatch):
    """NOTE-020: 'Slew complete' is posted when a mount that was slewing stops, and only then."""
    got: list[str] = []
    monkeypatch.setattr(notices, "post_notice", lambda kind, *a, **k: got.append(kind))
    notices.note_slew_state("EQ6", False, False)
    notices.note_slew_state("EQ6", False, True)
    notices.note_slew_state("EQ6", True, True)
    notices.note_slew_state("EQ6", True, False)
    assert got == ["slew.ended"]


@pytest.mark.requirement("TC-NOTE-030")
@pytest.mark.priority("MVP")
def test_tc_note_030_bridge_turns_bus_events_into_notices(bus):
    """NOTE-030: device connect/disconnect, solve start/result and focus result published elsewhere become notices."""
    from types import SimpleNamespace

    notices.install_bridge(bus)
    try:
        bus.publish(DeviceConnectedEvent(source="camera", pier="p1", slot="primary"))
        bus.publish(DeviceDisconnectedEvent(source="mount", pier="p1", slot="primary"))
        bus.publish(SolveStartedEvent(source="platesolve", fits_path="/x/m31.fits"))
        bus.publish(SolveCompleteEvent(source="platesolve", fits_path="/x/m31.fits",
                                       result=SimpleNamespace(success=True, ra_deg=10.68, dec_deg=41.27)))
        bus.publish(SolveCompleteEvent(source="platesolve", fits_path="/x/m31.fits",
                                       result=SimpleNamespace(success=False, failure_reason="no stars")))
        bus.publish(FocusCompleteEvent(source="autofocus", result=SimpleNamespace(
            success=True, best_position=12345, sample_points=[(1, 2.0)] * 7)))
        bus.publish(FocusCompleteEvent(source="autofocus", result=SimpleNamespace(success=False, failure_reason="too few stars")))
    finally:
        notices.uninstall_bridge(bus)
    kinds = [n["kind"] for n in bus.seen]
    assert kinds == ["device.connected", "device.disconnected", "solve.started", "solve.resolved", "solve.failed",
                     "focus.result", "focus.failed"]
    assert bus.seen[0]["severity"] == "success" and bus.seen[1]["severity"] == "warning"
    assert bus.seen[2]["message"] == "m31.fits" and "RA 00h42.7m" in bus.seen[3]["message"]
    assert "12345" in bus.seen[5]["message"] and bus.seen[6]["message"] == "too few stars"
    bus.publish(DeviceConnectedEvent(source="camera"))
    assert len(bus.seen) == 7, "uninstalling stops the translation"


@pytest.mark.requirement("TC-NOTE-050")
@pytest.mark.priority("P2")
def test_tc_note_050_identical_notices_in_a_moment_are_one(bus):
    """NOTE-050: the same notice posted twice at once (a command seen by two layers) is shown once."""
    notices.post_notice("a", "Same", "thing", bus=bus)
    notices.post_notice("a", "Same", "thing", bus=bus)
    notices.post_notice("a", "Same", "other", bus=bus)
    assert [n["message"] for n in bus.seen] == ["thing", "other"]
    notices.post_notice("a", "Bad severity", severity="bogus", bus=bus)
    assert bus.seen[-1]["severity"] == "info"


@pytest.mark.requirement("TC-NOTE-060")
@pytest.mark.priority("MVP")
def test_tc_note_060_nothing_is_announced_during_startup(bus):
    """NOTE-060: while the gate is closed (start-up) notices are dropped, not queued; they flow once it opens."""
    notices.set_notices_enabled(False)
    notices.post_notice("device.connected", "Connected", "camera", bus=bus)
    notices.set_notices_enabled(True)
    assert bus.seen == [], "nothing is replayed when the gate opens"
    notices.post_notice("device.connected", "Connected", "camera", bus=bus)
    assert len(bus.seen) == 1


@pytest.mark.requirement("TC-NOTE-040")
@pytest.mark.priority("MVP")
def test_tc_note_040_notices_reach_the_engine_feed():
    """NOTE-040: the engine feed forwards NoticeEvent, which is how the mobile apps hear of them."""
    from galileo.control_surface.feed import FEED_EVENTS

    assert NoticeEvent in FEED_EVENTS


# -- the desktop panel -------------------------------------------------------------------------------------

@pytest.fixture
def qapp():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.requirement("TC-NOTE-010")
@pytest.mark.priority("MVP")
def test_tc_note_010_panels_stack_top_right_close_on_x_and_on_timeout(qapp):
    """NOTE-010: a notice shows as a panel in the window's top-right corner; the X closes it, a timer closes it
    after the timeout, at most five show at once, and a night-vision theme gets a red-only accent."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMainWindow

    from galileo.ui.notice_toast import MAX_VISIBLE, TIMEOUT_MS, NoticeToasts
    from galileo.ui.theme import ThemeManager

    assert TIMEOUT_MS == 10_000
    window = QMainWindow()
    window.resize(1000, 700)
    window.show()
    theme = ThemeManager()
    toasts = NoticeToasts(window, theme.palette, lambda: True, timeout_ms=400)
    try:
        toasts.notify("Exposure started", "30 s Light", "info")
        qapp.processEvents()
        panel = toasts.panels[0]
        assert panel.title_label.text() == "Exposure started" and panel.message_label.text() == "30 s Light"
        assert panel.x() + panel.width() <= window.width() and panel.x() > window.width() // 2, "right side"
        assert panel.y() < 40, "top"
        assert theme.palette()["text_bright"] in panel.styleSheet(), "night vision: accent from the palette, not a colour"

        toasts.notify("Slew complete")
        second = toasts.panels[1]
        assert second.y() > panel.y(), "newest below the older one"
        panel.close_button.click()
        qapp.processEvents()
        assert len(toasts.panels) == 1

        for i in range(8):
            toasts.notify(f"n{i}")
        assert len(toasts.panels) == MAX_VISIBLE

        QTimer.singleShot(900, qapp.quit)
        qapp.exec()
        assert toasts.panels == [], "they close themselves after the timeout"
    finally:
        toasts.close()
        window.close()


@pytest.mark.requirement("TC-NOTE-010")
@pytest.mark.priority("MVP")
def test_tc_note_010_bus_notices_are_shown_and_gated(qapp):
    """NOTE-010/NOTE-060: a notice posted on the bus (from any thread) appears; one posted while gated does not."""
    import threading

    from PySide6.QtWidgets import QMainWindow

    from galileo.ui.notice_toast import NoticeToasts
    from galileo.ui.theme import ThemeManager

    window = QMainWindow()
    window.show()
    toasts = NoticeToasts(window, ThemeManager().palette)
    try:
        notices.set_notices_enabled(False)
        notices.post_notice("device.connected", "Connected", "camera")
        qapp.processEvents()
        assert toasts.panels == []
        notices.set_notices_enabled(True)
        worker = threading.Thread(target=notices.post_notice, args=("solve.resolved", "Plate solve resolved", "M31"))
        worker.start()
        worker.join()
        qapp.processEvents()
        assert [p.title_label.text() for p in toasts.panels] == ["Plate solve resolved"]
    finally:
        toasts.close()
        window.close()


@pytest.mark.requirement("TC-NOTE-010")
@pytest.mark.priority("MVP")
def test_tc_note_010_screens_have_no_log_pane(qapp):
    """NOTE-010: the per-screen log panes are gone (notices replace them); only the View Log dialog remains."""
    from galileo.ui.app_window import AppWindow, _widgets

    assert not hasattr(AppWindow, "_build_log_pane") and not hasattr(AppWindow, "set_log_pane_text")
    assert not hasattr(_widgets, "_LogPane")
