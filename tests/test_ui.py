# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""UI — Customization & Theming (TC-UI-010 … TC-UI-030)."""

import pytest


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


@pytest.mark.requirement("TC-UI-010")
@pytest.mark.priority("P2")
def test_tc_ui_010_stylesheet_font_sizes_are_in_points_not_pixels():
    """UI-010: Themes size fonts in points — a pixel-only font reports pointSize() == -1, which Qt 6's
    Windows 11 style then feeds to QFont::setPointSize when it builds a combo-box popup, printing
    "QFont::setPointSize: Point size <= 0 (-1)" to the console."""
    import re

    theme_mod = pytest.importorskip("galileo.ui.theme")
    mgr = theme_mod.ThemeManager()
    for theme in (theme_mod.Theme.DARK, theme_mod.Theme.LIGHT, theme_mod.Theme.RED):
        mgr.set_theme(theme)
        sheet = mgr.stylesheet()
        assert re.search(r"font-size:\s*[\d.]+pt", sheet), "expected the theme to size fonts in points"
        assert not re.search(r"font-size:\s*[\d.]+px", sheet)


# ---------------------------------------------------------------------------
# TC-UI-011
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-UI-011")
@pytest.mark.priority("P2")
def test_tc_ui_011_red_night_vision_theme_selectable():
    """UI-011: Provide a red night-vision color theme, selectable by the user."""
    theme_mod = pytest.importorskip("galileo.ui.theme")
    mgr = theme_mod.ThemeManager()

    assert theme_mod.Theme.RED in mgr.available_themes()

    mgr.set_theme(theme_mod.Theme.RED)
    assert mgr.current_theme == theme_mod.Theme.RED


@pytest.mark.requirement("TC-UI-011")
@pytest.mark.priority("P2")
def test_tc_ui_011_red_theme_has_no_green_or_blue_channel():
    """UI-011: The red theme's tokens (and its accent) carry no green/blue component,
    so nothing rendered under it can reset a dark-adapted eye."""
    import re

    theme_mod = pytest.importorskip("galileo.ui.theme")
    mgr = theme_mod.ThemeManager()
    mgr.set_accent_color("#1E90FF")  # a deliberately non-red accent preference
    mgr.set_theme(theme_mod.Theme.RED)

    for token, value in mgr.palette().items():
        m = re.fullmatch(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})", value)
        assert m, f"palette token {token!r} is not a hex color: {value!r}"
        assert m.group(2) == "00" and m.group(3) == "00", (
            f"palette token {token!r} = {value!r} has a non-zero green/blue component"
        )

    accent = mgr.accent_color
    m = re.fullmatch(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})", accent)
    assert m, f"accent is not a hex color: {accent!r}"
    assert m.group(2) == "00" and m.group(3) == "00", (
        f"red theme accent {accent!r} has a non-zero green/blue component "
        "-- the user's saved accent preference must not leak through"
    )


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
