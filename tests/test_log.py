# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LOG — Diagnostics & Logging (TC-LOG-010 … TC-LOG-060)."""

import pytest


@pytest.fixture
def diag_service(tmp_path):
    diag_mod = pytest.importorskip("galileo.diagnostics")
    return diag_mod.DiagnosticsService(log_dir=tmp_path)


# ---------------------------------------------------------------------------
# TC-LOG-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LOG-010")
@pytest.mark.priority("MVP")
def test_tc_log_010_structured_timestamped_logs_to_platform_dir(diag_service, tmp_path):
    """LOG-010: Write structured, timestamped application/session logs to a per-platform standard log directory."""
    diag_service.log_info("Test info message")
    diag_service.log_warning("Test warning")

    log_files = list(tmp_path.glob("*.log"))
    assert log_files, "At least one log file must be written"

    content = log_files[0].read_text()
    assert "Test info message" in content
    # Structured: each line must contain a timestamp component
    lines = [l for l in content.splitlines() if l.strip()]
    assert all(any(c.isdigit() for c in line) for line in lines), "Log lines must contain timestamps"


# ---------------------------------------------------------------------------
# TC-LOG-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LOG-020")
@pytest.mark.priority("MVP")
def test_tc_log_020_in_app_log_viewer_with_severity_filter(diag_service):
    """LOG-020: In-app log viewer with severity filtering (info/warning/error)."""
    diag_mod = pytest.importorskip("galileo.diagnostics")
    diag_service.log_info("An info event")
    diag_service.log_warning("A warning event")
    diag_service.log_error("An error event")

    viewer = diag_mod.LogViewer(service=diag_service)

    errors = viewer.get_entries(min_severity=diag_mod.Severity.ERROR)
    assert all(e.severity >= diag_mod.Severity.ERROR for e in errors)
    assert any(e.message == "An error event" for e in errors)

    all_entries = viewer.get_entries(min_severity=diag_mod.Severity.INFO)
    assert len(all_entries) >= 3


# ---------------------------------------------------------------------------
# TC-LOG-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LOG-030")
@pytest.mark.priority("MVP")
def test_tc_log_030_capture_unhandled_exceptions(diag_service):
    """LOG-030: Capture unhandled exceptions to the log with stack trace, active sequence step, device state."""
    diag_mod = pytest.importorskip("galileo.diagnostics")
    try:
        raise ValueError("Deliberate test crash")
    except ValueError as exc:
        diag_service.log_exception(exc, context={"active_step": "capture", "device": "SimCamera"})

    viewer = diag_mod.LogViewer(service=diag_service)
    errors = viewer.get_entries(min_severity=diag_mod.Severity.ERROR)
    assert any("Deliberate test crash" in e.message for e in errors)
    matched = [e for e in errors if "Deliberate test crash" in e.message]
    assert matched[0].stack_trace is not None


# ---------------------------------------------------------------------------
# TC-LOG-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LOG-040")
@pytest.mark.priority("P2")
def test_tc_log_040_export_support_bundle(diag_service, tmp_path):
    """LOG-040: Allow exporting a support bundle (recent logs + non-sensitive config) for bug reports."""
    diag_service.log_info("Session started")
    bundle_path = tmp_path / "support_bundle.zip"
    diag_service.export_support_bundle(bundle_path)

    assert bundle_path.exists()
    import zipfile
    with zipfile.ZipFile(bundle_path) as z:
        names = z.namelist()
        assert any(".log" in n for n in names), "Bundle must contain at least one log file"


# ---------------------------------------------------------------------------
# TC-LOG-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LOG-050")
@pytest.mark.priority("MVP")
def test_tc_log_050_log_file_resets_each_run_rather_than_appending(tmp_path):
    """LOG-050: The logging service shall reset (start a new, truncated) datestamped log file at the beginning of every application run, rather than appending to a prior run's log."""
    diag_mod = pytest.importorskip("galileo.diagnostics")

    first_run = diag_mod.DiagnosticsService(log_dir=tmp_path)
    first_run.log_info("Message from run 1")
    log_files = list(tmp_path.glob("*.log"))
    assert len(log_files) == 1
    log_path = log_files[0]
    assert "Message from run 1" in log_path.read_text()

    # A new run against the same datestamped file starts truncated, not appended.
    second_run = diag_mod.DiagnosticsService(log_dir=tmp_path)
    second_run.log_info("Message from run 2")

    content = log_path.read_text()
    assert "Message from run 2" in content
    assert "Message from run 1" not in content


# ---------------------------------------------------------------------------
# TC-LOG-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LOG-060")
@pytest.mark.priority("P2")
def test_tc_log_060_recent_log_pane_on_equipment_screens(diag_service):
    """LOG-060: Display, on every Equipment device-category screen, a scrollable pane showing the most recent log lines (at least the last 10 visible at once) without requiring the user to open a separate log viewer."""
    diag_mod = pytest.importorskip("galileo.diagnostics")

    for i in range(15):
        diag_service.log_info(f"Camera event {i}")

    pane = diag_mod.RecentLogPane(service=diag_service, min_visible_lines=10)

    assert pane.min_visible_lines >= 10
    visible = pane.get_visible_entries()
    assert len(visible) >= 10
    assert visible[-1].message == "Camera event 14", "most recent entries are shown"
