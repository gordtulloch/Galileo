# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Options > Equipment (watchdog, SAFE-060), Guiding (dither/settle, GUIDE-030) and Science pages."""

import pytest

pytest.importorskip("PySide6")
from PySide6 import QtCore, QtWidgets


@pytest.fixture
def config_dir(tmp_path, monkeypatch, settings_db):
    """A throwaway config folder (for legacy files) and a throwaway settings database."""
    import galileo.platform as platform_mod
    monkeypatch.setattr(platform_mod, "get_config_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def window(tmp_path, config_dir):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "options_pages.db")
    from galileo.ui.app_window import AppWindow
    win = AppWindow()
    win.app = app
    yield win
    for timer in win._window.findChildren(QtCore.QTimer):
        timer.stop()
    win._window.close()
    win._window.deleteLater()
    db.close()


@pytest.mark.requirement("TC-GUIDE-030")
@pytest.mark.priority("P2")
def test_tc_guide_030_guiding_settings_defaults_and_clamping(config_dir):
    """GUIDE-030: the dither/settle options default sensibly and are clamped to a sane range."""
    from galileo.guiding_settings import DEFAULTS, load_guiding_settings, save_guiding_settings
    (config_dir / "guiding.json").write_text("not json")      # an unreadable legacy file is ignored
    assert load_guiding_settings() == DEFAULTS
    save_guiding_settings({"dither_amount_px": 999, "dither_ra_only": True, "settle_pixels": 0.0})
    loaded = load_guiding_settings()
    assert loaded["dither_amount_px"] == 30.0 and loaded["dither_ra_only"] is True
    assert loaded["settle_pixels"] == 0.1
    from galileo.settings_store import set_namespace
    set_namespace("guiding", {"dither_amount_px": "abc", "dither_ra_only": "yes"}, replace=True)
    assert load_guiding_settings() == DEFAULTS                 # wrongly-typed saved values are ignored


@pytest.mark.requirement("TC-GUIDE-030")
@pytest.mark.priority("P2")
def test_tc_guide_030_legacy_guiding_json_is_imported_once(config_dir):
    """GUIDE-030: an old guiding.json is imported into the database on first read and renamed, not deleted."""
    from galileo.guiding_settings import load_guiding_settings
    from galileo.settings_store import get_namespace
    (config_dir / "guiding.json").write_text('{"dither_amount_px": 7, "dither_ra_only": true}')
    assert load_guiding_settings()["dither_amount_px"] == 7.0
    assert not (config_dir / "guiding.json").exists() and (config_dir / "guiding.json.migrated").exists()
    assert get_namespace("guiding")["dither_ra_only"] is True


@pytest.mark.requirement("TC-GUIDE-030")
@pytest.mark.priority("P2")
async def test_tc_guide_030_saved_options_drive_the_dither_command(config_dir, mock_guider):
    """GUIDE-030: a dither uses the saved amount, RA-only flag and settle parameters unless told otherwise."""
    from unittest.mock import AsyncMock
    from galileo.guiding import GuidingService
    from galileo.guiding_settings import save_guiding_settings
    save_guiding_settings({"dither_amount_px": 5.0, "dither_ra_only": True, "settle_pixels": 0.8,
                           "settle_time_s": 12, "settle_timeout_s": 45})
    service = GuidingService()
    service._client = mock_guider
    mock_guider.dither = AsyncMock()
    mock_guider.wait_for_settle = AsyncMock(return_value=True)
    await service.dither_and_wait()
    mock_guider.dither.assert_called_once_with(
        amount_px=5.0, ra_only=True, settle_pixels=0.8, settle_time_s=12.0, settle_timeout_s=45.0)
    mock_guider.wait_for_settle.assert_called_once_with(45.0)


@pytest.mark.requirement("TC-GUIDE-030")
@pytest.mark.priority("P2")
def test_tc_guide_030_options_guiding_page_saves_as_you_change(window, config_dir):
    """GUIDE-030: Options > Guiding shows the saved values and saves a change immediately."""
    from galileo.guiding_settings import load_guiding_settings
    page = window._build_guiding_settings_page()
    spins = page.findChildren(QtWidgets.QDoubleSpinBox)
    assert len(spins) == 4 and spins[0].value() == 3.0
    spins[0].setValue(4.5)
    page.findChild(QtWidgets.QCheckBox).setChecked(True)
    saved = load_guiding_settings()
    assert saved["dither_amount_px"] == 4.5 and saved["dither_ra_only"] is True


@pytest.mark.requirement("TC-SAFE-060")
@pytest.mark.priority("MVP")
def test_tc_safe_060_options_equipment_page_edits_the_watchdog(window, config_dir):
    """SAFE-060: Options > Equipment shows the watchdog settings and saves a changed timeout / disabled state."""
    from galileo.watchdog_settings import load_watchdog_settings
    page = window._build_equipment_settings_page()
    check = page.findChild(QtWidgets.QCheckBox)
    spin = page.findChild(QtWidgets.QDoubleSpinBox)
    assert check.isChecked() and spin.value() == 300.0
    spin.setValue(120)
    assert load_watchdog_settings() == {"enabled": True, "timeout_s": 120.0}
    check.setChecked(False)
    assert load_watchdog_settings()["enabled"] is False and not spin.isEnabled()


@pytest.mark.requirement("TC-SAFE-060")
@pytest.mark.priority("MVP")
def test_tc_safe_060_save_watchdog_settings_clamps(config_dir):
    """SAFE-060: a saved watchdog timeout is clamped to the allowed range."""
    from galileo.watchdog_settings import MIN_TIMEOUT_S, load_watchdog_settings, save_watchdog_settings
    save_watchdog_settings({"enabled": True, "timeout_s": 1})
    assert load_watchdog_settings()["timeout_s"] == MIN_TIMEOUT_S


@pytest.mark.requirement("TC-UI-010")
@pytest.mark.priority("P2")
def test_tc_ui_010_equipment_guiding_science_options_are_no_longer_placeholders(window):
    """UI-010: the Options pages for Equipment, Guiding and Science are real pages, not the 'not implemented yet' stub."""
    for builder in (window._build_equipment_settings_page, window._build_guiding_settings_page,
                    window._build_science_settings_page):
        page = builder()
        assert not any("not implemented yet" in lbl.text() for lbl in page.findChildren(QtWidgets.QLabel))
    options = window._options_page
    for item_id in ("equipment", "guiding", "science"):
        titles = [t.text() for t in options.findChildren(QtWidgets.QLabel) if t.objectName() == "PageTitle"]
        assert f"{item_id.capitalize()} settings" in titles
