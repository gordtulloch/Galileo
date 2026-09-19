# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""HIST — Session History & Statistics (TC-HIST-010 … TC-HIST-040)."""

import pytest
from unittest.mock import MagicMock


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
