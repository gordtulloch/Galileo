# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""HIST — Session History & Statistics (TC-HIST-010 … TC-HIST-040)."""

import pytest


@pytest.fixture
def history_service(tmp_path):
    hist_mod = pytest.importorskip("galileo.history")
    return hist_mod.SessionHistory(db_path=tmp_path / "history.db")


# ---------------------------------------------------------------------------
# TC-HIST-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-HIST-010")
@pytest.mark.priority("P2")
def test_tc_hist_010_record_hfr_star_count_guide_rms(history_service):
    """HIST-010: Record per-frame HFR, star count, and guide RMS with timestamp for the duration of a session."""
    history_service.start_session(name="M42 Session")
    history_service.record_frame(
        timestamp="2026-09-16T22:05:00",
        hfr=2.1,
        star_count=142,
        guide_rms_ra=0.45,
        guide_rms_dec=0.32,
    )
    history_service.record_frame(
        timestamp="2026-09-16T22:10:00",
        hfr=2.3,
        star_count=138,
        guide_rms_ra=0.48,
        guide_rms_dec=0.30,
    )

    frames = history_service.get_current_session_frames()
    assert len(frames) == 2
    assert frames[0]["hfr"] == 2.1
    assert frames[1]["star_count"] == 138


# ---------------------------------------------------------------------------
# TC-HIST-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-HIST-020")
@pytest.mark.priority("P2")
def test_tc_hist_020_display_metrics_as_chart_or_table(history_service):
    """HIST-020: Display session-history metrics as a chart/table, reviewable during and after a session."""
    history_service.start_session(name="Test Session")
    for i in range(5):
        history_service.record_frame(
            timestamp=f"2026-09-16T22:{i:02d}:00",
            hfr=2.0 + i * 0.05,
            star_count=140 - i,
            guide_rms_ra=0.4,
            guide_rms_dec=0.3,
        )

    report = history_service.get_session_report()
    assert "frames" in report
    assert "avg_hfr" in report
    assert "avg_star_count" in report
    assert len(report["frames"]) == 5


# ---------------------------------------------------------------------------
# TC-HIST-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-HIST-030")
@pytest.mark.priority("P2")
def test_tc_hist_030_retain_history_across_restarts(tmp_path):
    """HIST-030: Retain session-history data across application restarts, associated with the session."""
    hist_mod = pytest.importorskip("galileo.history")
    svc1 = hist_mod.SessionHistory(db_path=tmp_path / "history.db")
    svc1.start_session(name="Night 1")
    svc1.record_frame(timestamp="2026-09-16T22:00:00", hfr=2.1, star_count=140)
    svc1.end_session()

    svc2 = hist_mod.SessionHistory(db_path=tmp_path / "history.db")
    sessions = svc2.list_sessions()
    assert any(s["name"] == "Night 1" for s in sessions)

    frames = svc2.get_frames_for_session("Night 1")
    assert len(frames) == 1
    assert frames[0]["hfr"] == 2.1


# ---------------------------------------------------------------------------
# TC-HIST-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-HIST-040")
@pytest.mark.priority("P3")
def test_tc_hist_040_export_session_history_to_csv(history_service, tmp_path):
    """HIST-040: Allow exporting session-history data to a portable format (e.g. CSV) for external analysis."""
    history_service.start_session(name="Export Test")
    history_service.record_frame(timestamp="2026-09-16T22:00:00", hfr=2.0, star_count=150)
    history_service.end_session()

    csv_path = tmp_path / "history_export.csv"
    history_service.export_csv("Export Test", csv_path)

    assert csv_path.exists()
    content = csv_path.read_text()
    assert "hfr" in content.lower()
    assert "2.0" in content


# ---------------------------------------------------------------------------
# HIST-010 / HIST-020 — recording from a running session, and the History screen
# ---------------------------------------------------------------------------

def _run_session(history, guider=None, frame_type="Light"):
    import asyncio

    import numpy as np

    from galileo.ui import sessions
    from tests.test_ses_exec import FakeImaging, make_context
    from galileo.sequencer.session_exec import SessionExecutor

    class _Imaging(FakeImaging):
        current_frame = np.random.default_rng(1).normal(100, 5, (64, 64))

    log: list = []
    ctx, _ = make_context(log)
    ctx.make_imaging = lambda: _Imaging(log)
    ctx.history, ctx.guider = history, guider
    block = sessions.ImageBlock(exposure=5.0, count=3, frame_type=frame_type)
    return asyncio.run(SessionExecutor(ctx, name="M31 run").run([block]))


@pytest.mark.requirement("TC-HIST-010")
@pytest.mark.priority("P2")
def test_tc_hist_010_session_executor_records_each_light_frame(history_service):
    """HIST-010: the session executor records HFR, star count and guide RMS for every light frame."""
    class Guider:
        def get_rms(self):
            return {"ra": 0.5, "dec": 0.25, "total": 0.56}

    result = _run_session(history_service, guider=Guider())
    assert result.frames_captured == 3
    (session,) = history_service.list_sessions()
    assert session["name"].startswith("M31 run") and session["frame_count"] == 3
    frame = history_service.get_frames_for_session(session["name"])[0]
    assert frame["guide_rms_ra"] == 0.5 and frame["guide_rms_dec"] == 0.25 and frame["hfr"] > 0
    assert not history_service._current_session      # closed and saved at the end of the run


@pytest.mark.requirement("TC-HIST-010")
@pytest.mark.priority("P2")
def test_tc_hist_010_calibration_frames_are_not_recorded(history_service):
    """HIST-010: only light frames are logged, so a dark run leaves no history session behind."""
    _run_session(history_service, frame_type="Dark")
    assert history_service.list_sessions() == []


@pytest.mark.requirement("TC-HIST-020")
@pytest.mark.priority("P2")
def test_tc_hist_020_history_screen_lists_and_shows_a_session(history_service, tmp_path):
    """HIST-020: the History screen offers each recorded session and shows its frames as a table."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from galileo.ui.history import HistoryPageWidget, summarise

    history_service.start_session("Night A")
    history_service.record_frame("2026-09-16T22:00:00", 2.0, 100, 0.4, 0.3)
    history_service.record_frame("2026-09-16T22:05:00", 3.0, 80)
    history_service.end_session()
    page = HistoryPageWidget(history=history_service)
    assert page._session_combo.count() == 1
    assert page._table.rowCount() == 2
    assert page._table.item(1, 1).text() == "3.00"
    assert "2 frame(s)" in summarise(page._frames)
    page._delete_btn.setEnabled(True)
    history_service.delete_session("Night A")
    page.reload()
    assert page._table.rowCount() == 0 and app is not None
