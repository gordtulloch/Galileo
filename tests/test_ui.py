"""UI — Customization & Theming (TC-UI-010 … TC-UI-030)."""

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# TC-UI-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-UI-010")
@pytest.mark.priority("P2")
def test_tc_ui_010_light_and_dark_theme():
    """UI-010: Provide at least a light and a dark color theme, selectable by the user."""
    theme_mod = pytest.importorskip("galileo.ui.theme")
    mgr = theme_mod.ThemeManager()

    assert theme_mod.Theme.LIGHT in mgr.available_themes()
    assert theme_mod.Theme.DARK in mgr.available_themes()

    mgr.set_theme(theme_mod.Theme.DARK)
    assert mgr.current_theme == theme_mod.Theme.DARK

    mgr.set_theme(theme_mod.Theme.LIGHT)
    assert mgr.current_theme == theme_mod.Theme.LIGHT


# ---------------------------------------------------------------------------
# TC-UI-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-UI-020")
@pytest.mark.priority("P2")
def test_tc_ui_020_imaging_tab_panel_layout_persisted(tmp_path):
    """UI-020: Allow imaging-tab panel arrangement to be customized and persisted across restarts."""
    theme_mod = pytest.importorskip("galileo.ui.theme")
    layout_mgr = theme_mod.LayoutManager(config_path=tmp_path / "layout.json")

    layout = {
        "histogram": {"position": "bottom-left", "visible": True},
        "stats": {"position": "right", "visible": True},
        "preview": {"position": "center", "visible": True},
    }
    layout_mgr.save_layout("imaging", layout)

    layout_mgr2 = theme_mod.LayoutManager(config_path=tmp_path / "layout.json")
    loaded = layout_mgr2.load_layout("imaging")
    assert loaded["histogram"]["position"] == "bottom-left"
    assert loaded["preview"]["position"] == "center"


# ---------------------------------------------------------------------------
# TC-UI-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-UI-030")
@pytest.mark.priority("P3")
def test_tc_ui_030_accent_color_customization():
    """UI-030: Allow accent-color customization within a theme."""
    theme_mod = pytest.importorskip("galileo.ui.theme")
    mgr = theme_mod.ThemeManager()
    mgr.set_accent_color("#1E90FF")  # Dodger Blue
    assert mgr.accent_color == "#1E90FF"

    mgr.set_accent_color("#FF6347")  # Tomato
    assert mgr.accent_color == "#FF6347"
