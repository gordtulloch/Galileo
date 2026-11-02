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
    from galileo.session_exec import SessionExecutor

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


# ---------------------------------------------------------------------------
# TC-HIST-050 — transfer form
# ---------------------------------------------------------------------------

def _record(svc, session, stamps, hfr=2.0):
    svc.start_session(name=session)
    for i, ts in enumerate(stamps):
        svc.record_frame(timestamp=ts, hfr=hfr + i, star_count=100 + i)
    svc.end_session()


@pytest.mark.requirement("TC-HIST-050")
@pytest.mark.priority("MVP")
def test_tc_hist_050_records_are_identified_by_origin_node_and_local_key(tmp_path):
    """HIST-050: history exports in a transfer form identified by (origin_node_id, local_key); a Master
    imports every node's history with no key collision and an import is an idempotent upsert."""
    from galileo.history import SessionHistory
    spoke_a, spoke_b = SessionHistory(tmp_path / "a.json"), SessionHistory(tmp_path / "b.json")
    master = SessionHistory(tmp_path / "m.json")
    _record(spoke_a, "M42", ["2026-11-01T22:00:00", "2026-11-01T22:05:00"])
    _record(spoke_b, "M42", ["2026-11-01T22:00:00"], hfr=3.5)          # same session name and time, other node
    _record(master, "M42", ["2026-11-01T22:00:00"], hfr=1.1)
    batch_a, batch_b = spoke_a.export_records("node-a"), spoke_b.export_records("node-b")
    assert {(r["origin_node_id"], r["local_key"]) for r in batch_a} == {
        ("node-a", "M42|2026-11-01T22:00:00"), ("node-a", "M42|2026-11-01T22:05:00")}
    assert master.import_records("node-m", batch_a) == {"added": 2, "updated": 0, "skipped": 0}
    assert master.import_records("node-m", batch_b) == {"added": 1, "updated": 0, "skipped": 0}
    assert master.import_records("node-m", batch_a + batch_b) == {"added": 0, "updated": 0, "skipped": 0}
    names = [s["name"] for s in master.list_sessions()]
    assert len(names) == 3 and "M42" in names                         # the local session is untouched
    assert master.get_frames_for_session("M42")[0]["hfr"] == 1.1
    assert sorted(f["hfr"] for n in names for f in master.get_frames_for_session(n)) == [1.1, 2.0, 3.0, 3.5]


@pytest.mark.requirement("TC-HIST-050")
@pytest.mark.priority("MVP")
def test_tc_hist_050_changes_update_in_place_and_the_master_can_pass_history_on(tmp_path):
    """HIST-050: a changed record replaces the earlier one under the same key; records the Master imported
    keep their origin when it exports them, so a third node receives them as the first node's."""
    from galileo.history import SessionHistory
    a, master, third = (SessionHistory(tmp_path / f"{n}.json") for n in "amt")
    _record(a, "NGC7000", ["2026-11-02T01:00:00"])
    master.import_records("node-m", a.export_records("node-a"))
    a._sessions["NGC7000"].frames[0].hfr = 9.9                         # corrected at the source
    assert master.import_records("node-m", a.export_records("node-a")) == {"added": 0, "updated": 1, "skipped": 0}
    relayed = master.export_records("node-m")
    assert [(r["origin_node_id"], r["session"]) for r in relayed] == [("node-a", "NGC7000")]
    assert relayed[0]["frame"]["hfr"] == 9.9 and "origin_node_id" not in relayed[0]["frame"]
    assert third.import_records("node-t", relayed)["added"] == 1
    assert master.import_records("node-m", relayed) == {"added": 0, "updated": 0, "skipped": 0}    # a no-op
    assert third.import_records("node-a", relayed)["skipped"] == 1       # node-a's own records are not re-imported


@pytest.mark.requirement("TC-HIST-050")
@pytest.mark.priority("MVP")
def test_tc_hist_050_since_filters_and_bad_records_are_skipped_and_import_persists(tmp_path):
    """HIST-050: export can be limited to what is newer than a time; malformed records are skipped, not
    fatal; imported history survives a restart."""
    from galileo.history import SessionHistory
    a, master = SessionHistory(tmp_path / "a.json"), SessionHistory(tmp_path / "m.json")
    _record(a, "S", ["2026-11-01T22:00:00", "2026-11-01T23:00:00", "2026-11-02T00:00:00"])
    assert len(a.export_records("node-a", since="2026-11-01T22:30:00")) == 2
    good = a.export_records("node-a")[0]
    result = master.import_records("node-m", [good, {"origin_node_id": "x"}, {"frame": 1}, "junk"])  # type: ignore[list-item]
    assert result == {"added": 1, "updated": 0, "skipped": 3}
    reopened = SessionHistory(tmp_path / "m.json")
    assert reopened.export_records("node-m")[0]["origin_node_id"] == "node-a"
