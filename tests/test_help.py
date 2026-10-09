# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""In-app help (HELP-010 .. HELP-060): content loading, control-to-section matching, tooltips.

Content parsing is tested without Qt; control matching builds the real Equipment >
Focuser and Focus pages offscreen, the same way test_dome_page.py does.
"""

from __future__ import annotations

import os

import pytest

from galileo import help as help_content

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.mark.requirement("TC-HELP-010")
@pytest.mark.priority("P2")
def test_tc_help_010_documents_parse_into_keyed_sections():
    """HELP-010: help is Markdown, one file per screen, one ``##`` section per control, keyed by the slug of its heading."""
    doc = help_content.load("equipment.focuser")
    assert doc is not None and doc.title == "Focuser"
    section = doc.get("position-target")
    assert section is not None and section.title == "Position (target)"
    assert section.summary.startswith("The position, in steps")
    assert help_content.slug("Position (target):") == "position-target"
    assert doc.get(help_content.OVERVIEW) is not None


@pytest.mark.requirement("TC-HELP-020")
@pytest.mark.priority("P2")
def test_tc_help_020_lookup_falls_back_to_parent_screen_then_common():
    """HELP-020: a control with no entry on its own screen resolves against the parent screen, then ``common``."""
    doc, _section = help_content.resolve("equipment.focuser", "driver")  # only in common.md
    assert doc.screen_id == help_content.COMMON
    doc, _section = help_content.resolve("equipment.focuser", "position-target")
    assert doc.screen_id == "equipment.focuser"
    assert help_content.resolve("equipment.focuser", "no-such-control") is None


@pytest.mark.requirement("TC-HELP-030")
@pytest.mark.priority("P2")
def test_tc_help_030_search_and_topic_list():
    """HELP-030: the help window can list every documented screen and search across all of them."""
    assert "focus" in help_content.screen_ids()
    hits = [(d.screen_id, s.key) for d, s in help_content.search("backlash")]
    assert ("focus", "backlash") in hits
    assert help_content.search("") == []


QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def window(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "help.db")  # throwaway DB, never the user's
    from galileo.ui.app_window import AppWindow

    win = AppWindow()
    win.app = app
    yield win
    win._window.close()
    db.close()


def _tagged(window, screen_id):
    from galileo.ui.help import SCREEN_PROPERTY
    return next(
        w for w in window._window.findChildren(QtWidgets.QWidget) if w.property(SCREEN_PROPERTY) == screen_id
    )


@pytest.mark.requirement("TC-HELP-040")
@pytest.mark.priority("P2")
def test_tc_help_040_controls_match_their_section_by_label_text(window):
    """HELP-040/HELP-060: every control on a documented screen resolves to its section from its label/caption/button text, with no per-page code."""
    from galileo.ui.help import lookup, audit

    page = _tagged(window, "equipment.focuser")
    spin = next(s for s in page.findChildren(QtWidgets.QSpinBox) if s.maximum() == 1_000_000)
    assert lookup(spin)[1].key == "position-target"        # form-row label
    move = next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Move")
    assert lookup(move)[1].key == "move"                   # own button text, not the row's label
    scan = next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Scan")
    assert lookup(scan)[0].screen_id == help_content.COMMON
    assert audit(page) == []


@pytest.mark.requirement("TC-HELP-050")
@pytest.mark.priority("P2")
def test_tc_help_050_grid_captions_and_group_boxes_disambiguate(window):
    """HELP-040/HELP-060: hand-laid-out screens work too -- a caption beside a field names it, and the enclosing group box tells same-named controls apart."""
    from galileo.ui.help import lookup, audit

    page = _tagged(window, "focus")
    stop = [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Stop"]
    assert {lookup(b)[1].key for b in stop} == {"focuser-stop", "manual-focus-stop"}
    positions = [s for s in page.findChildren(QtWidgets.QSpinBox) if s.maximum() == 1_000_000]
    assert lookup(positions[0])[1].key == "manual-focus-position"
    assert audit(page) == []


@pytest.mark.requirement("TC-HELP-060")
@pytest.mark.priority("P2")
def test_tc_help_060_help_window_and_controller(window):
    """HELP-050/HELP-030: F1 / the sidebar ? open a help window on the current screen or the control, and hovering shows its tooltip."""
    from galileo.ui.help import HelpWindow

    ctrl = window._help
    page = _tagged(window, "focus")
    spin = next(s for s in page.findChildren(QtWidgets.QSpinBox) if s.suffix() == " steps")
    ctrl.help_for_widget(spin)
    win = ctrl.window()
    assert isinstance(win, HelpWindow) and win.isVisible()
    assert "Backlash" in win._browser.toPlainText() or "Step size" in win._browser.toPlainText()
    ctrl.help_for_widget(QtWidgets.QWidget())      # no screen: falls back, must not raise

    assert ctrl.apply_tooltips(page) > 10                  # documented controls get their help text as tooltip
    assert "focuser steps" in spin.toolTip() and "F1" in spin.toolTip()
    assert ctrl.apply_tooltips(page) == 0                  # already done: nothing to redo
    btn = next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Clear")
    btn.setText("Capture")                                 # a button whose text changes is matched again
    assert ctrl.apply_tooltips(page) == 1 and "exposure" in btn.toolTip().lower()


@pytest.mark.requirement("TC-HELP-030")
@pytest.mark.priority("P2")
def test_tc_help_030_every_screen_title_has_a_help_button(window):
    """HELP-030: a ? button sits beside each screen's title and opens that screen's help."""
    for screen_id in ("focus", "equipment.focuser"):
        page = _tagged(window, screen_id)
        buttons = [b for b in page.findChildren(QtWidgets.QToolButton) if b.objectName() == "HelpButton"]
        assert len(buttons) == 1, screen_id
        buttons[0].click()
        assert window._help.window().isVisible()
        assert window._help.window()._current == screen_id


@pytest.mark.requirement("TC-HELP-060")
@pytest.mark.priority("P3")
def test_tc_help_060_every_screen_and_control_is_documented(window):
    """HELP-060: the audit finds no control, on any screen, without a help entry -- the maintenance gate for new UI."""
    from galileo.ui.help import audit_window

    problems, screens = audit_window(window)
    assert screens > 30
    assert problems == [], "Undocumented controls (add a heading to the screen's file in galileo/help/content/):\n" + "\n".join(problems)


@pytest.mark.requirement("TC-HELP-010")
@pytest.mark.priority("P2")
def test_tc_help_010_every_help_file_belongs_to_a_screen(window):
    """HELP-010: no help file is orphaned -- each is named for a real screen (or a documented dialog), so renames are caught."""
    from galileo.ui.help import SCREEN_PROPERTY, audit_window

    audit_window(window)  # builds the lazily-built Library screens
    screens = {str(w.property(SCREEN_PROPERTY)) for w in window._window.findChildren(QtWidgets.QWidget)
               if w.property(SCREEN_PROPERTY)}
    dialogs = {"imaging.flats", "imaging.darks", "imaging.framing"}  # tagged when opened, not built up front
    orphans = set(help_content.screen_ids()) - screens - dialogs - {help_content.COMMON}
    assert orphans == set(), f"help files with no matching screen: {sorted(orphans)}"


@pytest.mark.requirement("TC-HELP-020")
@pytest.mark.priority("P2")
def test_tc_help_020_aliases_register_extra_keys_and_plugins_add_help(tmp_path):
    """HELP-020/HELP-060: a `keys` comment gives a section extra lookup keys; a plugin's help directory joins the lookup."""
    doc = help_content._parse("x", "# T\n\n## Solution RA\n<!-- keys: solution-coordinates-jnow-ra -->\nThe RA.\n\n## Other\nMore.\n")
    assert doc.get("solution-coordinates-jnow-ra") is doc.get("solution-ra")
    assert [s.key for s in doc.topics()] == ["solution-ra", "other"]
    assert "keys:" not in doc.markdown

    (tmp_path / "science.demo_plugin.md").write_text("# Demo\n\n## Gizmo\nDoes the gizmo thing.\n", encoding="utf-8")
    help_content.register_dir(tmp_path)
    try:
        hit = help_content.resolve("science.demo_plugin", "gizmo")
        assert hit is not None and hit[1].summary == "Does the gizmo thing."
    finally:
        help_content._extra_dirs.remove(tmp_path)
        help_content._load.cache_clear()
        help_content.screen_ids.cache_clear()
