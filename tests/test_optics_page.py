# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Optics Equipment page (``AppWindow._build_optics_page``), built offscreen.

PROF-100: the page defines the optical tube(s) on a Pier — focal length,
aperture, optical system, image alignment — and associates the Pier's other
saved devices with each tube. Persistence goes through the same throwaway
database the rotator-page tests use, never the user's.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from galileo.observatory import (  # noqa: E402
    create_observatory, create_pier, list_optical_tubes, save_device_config, save_optical_tubes,
)


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "optics_page.db")
    from galileo.ui.app_window import AppWindow

    boxes: list[str] = []
    for kind in ("information", "warning"):
        monkeypatch.setattr(QtWidgets.QMessageBox, kind, staticmethod(lambda *a, **k: boxes.append(a[1])))
    win = AppWindow()
    win.boxes = boxes
    win.app = app
    win.pier = create_pier(create_observatory("Test Obs"), "Pier A")
    win._current_pier = win.pier
    yield win
    win._window.close()
    db.close()


def _button(page, text, index=0):
    matches = [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == text]
    assert len(matches) > index, f"no QPushButton #{index} with text {text!r}"
    return matches[index]


def _titles(page):
    return [l.text() for l in page.findChildren(QtWidgets.QLabel) if l.text().startswith("Optical Tube")]


@pytest.mark.requirement("TC-PROF-100")
@pytest.mark.priority("MVP")
def test_tc_prof_100_optics_sits_directly_below_rotator_in_the_equipment_nav():
    """PROF-100: the Optics category is listed immediately after Rotator (Guiding is no longer an Equipment category)."""
    from galileo.ui.app_window import EQUIPMENT_CATEGORIES
    ids = [c[0] for c in EQUIPMENT_CATEGORIES]
    assert ids[ids.index("rotator") + 1] == "optics"


@pytest.mark.requirement("TC-PROF-100")
@pytest.mark.priority("MVP")
def test_tc_prof_100_plus_next_to_title_adds_a_tube(window):
    """PROF-100: one tube to start with; the title's "+" appends more, and only extras are removable."""
    page = window._build_optics_page()
    assert _titles(page) == ["Optical Tube 1"]
    _button(page, "+", 0).click()  # heading "+" comes first in layout order
    assert _titles(page) == ["Optical Tube 1", "Optical Tube 2"]
    _button(page, "Remove").click()
    assert _titles(page) == ["Optical Tube 1"]


@pytest.mark.requirement("TC-PROF-100")
@pytest.mark.priority("MVP")
def test_tc_prof_100_tube_offers_the_specified_optical_systems_and_alignment(window):
    """PROF-100: optical system choices and Reversed/Inverted alignment flags are per tube."""
    page = window._build_optics_page()
    combo = [c for c in page.findChildren(QtWidgets.QComboBox)][0]
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Newtonian", "Schmidt-Cassegrain", "Mak-Cassegrain", "Refractor", "Other",
    ]
    checks = [c.text() for c in page.findChildren(QtWidgets.QCheckBox)]
    assert checks == ["Reversed", "Inverted"]
    assert any(l.text() == "Associated:" for l in page.findChildren(QtWidgets.QLabel))


@pytest.mark.requirement("TC-PROF-100")
@pytest.mark.priority("MVP")
def test_tc_prof_100_save_and_reload_round_trips_tubes_and_associations(window, monkeypatch):
    """PROF-100: saved tubes (values, alignment, associated devices) reload per Pier."""
    save_device_config(window.pier, "camera", driver="Alpaca", server="h", port=1, device_name="ASI294")
    save_device_config(window.pier, "guider", driver="INDI", server="h", port=2, device_name="PHD2")
    page = window._build_optics_page()

    _button(page, "+", 0).click()  # second tube
    # Spin boxes contain their own internal QLineEdit, so pick the name fields by placeholder.
    names = [e for e in page.findChildren(QtWidgets.QLineEdit) if e.placeholderText()]
    names[0].setText("  Newt 8in  ")
    names[1].setText("Guide Scope")
    spins = page.findChildren(QtWidgets.QDoubleSpinBox)
    spins[0].setValue(1000.0)
    spins[1].setValue(200.0)
    spins[2].setValue(400.0)
    spins[3].setValue(80.0)
    combos = page.findChildren(QtWidgets.QComboBox)
    combos[0].setCurrentText("Newtonian")
    combos[1].setCurrentText("Refractor")
    checks = page.findChildren(QtWidgets.QCheckBox)
    checks[1].setChecked(True)   # tube 1 inverted
    checks[2].setChecked(True)   # tube 2 reversed

    picks = iter(["Camera: ASI294", "Guider: PHD2"])
    monkeypatch.setattr(
        QtWidgets.QInputDialog, "getItem", staticmethod(lambda *a, **k: (next(picks), True))
    )
    _button(page, "+", 1).click()  # tube 1's Associated "+"
    _button(page, "+", 1).click()
    _button(page, "Save").click()

    tubes = list_optical_tubes(window.pier)
    assert [(t.name, t.focal_length_mm, t.aperture_mm, t.optical_system) for t in tubes] == [
        ("Newt 8in", 1000.0, 200.0, "Newtonian"), ("Guide Scope", 400.0, 80.0, "Refractor"),
    ]
    assert [(t.image_reversed, t.image_inverted) for t in tubes] == [(False, True), (True, False)]
    assert tubes[0].associated == ["camera:primary", "guider:primary"]
    assert tubes[1].associated == []

    fresh = window._build_optics_page()
    assert _titles(fresh) == ["Optical Tube 1", "Optical Tube 2"]
    assert fresh.findChildren(QtWidgets.QDoubleSpinBox)[0].value() == 1000.0
    assert [e.text() for e in fresh.findChildren(QtWidgets.QLineEdit) if e.placeholderText()] == [
        "Newt 8in", "Guide Scope",
    ]
    labels = [l.text() for l in fresh.findChildren(QtWidgets.QLabel)]
    assert "Camera: ASI294" in labels and "Guider: PHD2" in labels


@pytest.mark.requirement("TC-PROF-100")
@pytest.mark.priority("MVP")
def test_tc_prof_100_associate_with_no_saved_devices_explains_why(window):
    """PROF-100: nothing to associate -> an explanatory message, not an empty picker."""
    page = window._build_optics_page()
    _button(page, "+", 1).click()
    assert window.boxes == ["No devices to associate"]


@pytest.mark.requirement("TC-PROF-100")
@pytest.mark.priority("MVP")
def test_tc_prof_100_dissociate_and_dangling_association(window):
    """PROF-100: an association to a since-removed device shows as unconfigured and can be removed."""
    save_optical_tubes(window.pier, [{"associated": ["focuser:primary"]}])
    page = window._build_optics_page()
    assert any("not configured" in l.text() for l in page.findChildren(QtWidgets.QLabel))
    _button(page, "Remove").click()
    assert not any("not configured" in l.text() for l in page.findChildren(QtWidgets.QLabel))


@pytest.mark.requirement("TC-PROF-100")
@pytest.mark.priority("MVP")
def test_tc_prof_100_existing_optical_tubes_table_gains_the_name_column(tmp_path):
    """PROF-100: a database created before tubes had a name is upgraded in place, keeping its rows."""
    from galileo.library.database import db, init_db
    path = tmp_path / "old.db"
    init_db(path)
    db.execute_sql("DROP TABLE optical_tubes")
    db.execute_sql(
        "CREATE TABLE optical_tubes (id INTEGER PRIMARY KEY, pier_id INTEGER NOT NULL, position INTEGER NOT NULL,"
        " focal_length_mm REAL NOT NULL, aperture_mm REAL NOT NULL, optical_system TEXT NOT NULL,"
        " image_reversed INTEGER NOT NULL, image_inverted INTEGER NOT NULL, associated_devices TEXT NOT NULL)"
    )
    pier = create_pier(create_observatory("Old Obs"), "Pier")
    db.execute_sql(
        "INSERT INTO optical_tubes (pier_id, position, focal_length_mm, aperture_mm, optical_system,"
        " image_reversed, image_inverted, associated_devices) VALUES (?, 0, 500, 100, 'Refractor', 0, 0, '[]')",
        (pier.id,),
    )
    try:
        init_db(path)
        (tube,) = list_optical_tubes(pier)
        assert (tube.name, tube.focal_length_mm) == ("", 500.0)
    finally:
        db.close()


def _open_section(window, section_id):
    """Click a primary-sidebar button, as a user switching tabs would.

    Found by section id (its label comes from ``PRIMARY_SECTIONS``), so renaming a tab doesn't break
    the tests; long labels wrap onto two lines, hence the whitespace normalisation.
    """
    from galileo.ui.app_window import PRIMARY_SECTIONS
    label = next(label for sid, label, _icon in PRIMARY_SECTIONS if sid == section_id)
    sidebar = next(c for c in window._nav_columns if c.objectName() == "Sidebar")
    buttons = sidebar.findChildren(QtWidgets.QToolButton)
    next(b for b in buttons if " ".join(b.text().split()) == label).click()


def _optics_selector_shown(window):
    return not window._optics_combo.isHidden() and not window._optics_label.isHidden()


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_tc_prof_110_optics_selector_only_on_framing_and_imaging(window):
    """PROF-110: the top-bar Optics selector is shown on Framing and Imaging, and nowhere else."""
    shown = {}
    for section in ("equipment", "planning", "framing", "imaging", "science"):
        _open_section(window, section)
        shown[section] = _optics_selector_shown(window)
    assert shown == {
        "equipment": False, "planning": False, "framing": True, "imaging": True, "science": False,
    }


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_tc_prof_110_selector_lists_the_piers_tubes_and_tracks_the_choice(window):
    """PROF-110: the selector lists the Pier's tubes (named, or numbered if unnamed) and the pick is the active tube."""
    save_optical_tubes(window.pier, [
        {"name": "Newt 8in", "focal_length_mm": 1000, "aperture_mm": 200},
        {"focal_length_mm": 400},
    ])
    _open_section(window, "imaging")
    combo = window._optics_combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["Newt 8in — 1000 mm f/5.0", "Optical Tube 2"]
    assert combo.isEnabled()
    assert window.active_optical_tube().name == "Newt 8in"

    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert window.active_optical_tube().focal_length_mm == 400
    _open_section(window, "framing")  # the choice survives a tab switch
    assert combo.currentIndex() == 1


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_tc_prof_110_selector_is_disabled_when_no_tubes_are_defined(window):
    """PROF-110: with no tubes, the selector stays visible but disabled and there is no active tube."""
    _open_section(window, "framing")
    assert _optics_selector_shown(window)
    assert not window._optics_combo.isEnabled()
    assert window.active_optical_tube() is None


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_tc_prof_110_saving_optics_refreshes_the_selector(window):
    """PROF-110: tubes saved on the Optics page appear in the selector without a restart."""
    page = window._build_optics_page()
    [e for e in page.findChildren(QtWidgets.QLineEdit) if e.placeholderText()][0].setText("Refractor")
    _button(page, "Save").click()
    combo = window._optics_combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["Refractor"]
    assert combo.isEnabled()


# --- Imaging filter selector follows the optics' filter wheel ----------------

class _FakeWheel:
    def __init__(self, names, position=0):
        self.filter_names, self.position = names, position


def _filters_shown(window):
    combo = window._imaging_filter_combo
    return [combo.itemText(i) for i in range(combo.count())]


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_imaging_filters_come_from_the_wheel_associated_with_the_optics(window):
    """PROF-110: the Imaging Filter selector lists the connected wheel's filters (blank first) and starts on the one in the beam."""
    save_optical_tubes(window.pier, [{"name": "Newt", "associated": ["filter_wheel:primary"]}])
    window._device_pages["filter_wheel"]["adapter"] = _FakeWheel(["L", "R", "G", "B"], position=2)
    _open_section(window, "imaging")
    assert _filters_shown(window) == ["", "L", "R", "G", "B"]
    assert window._imaging_filter_combo.currentText() == "G"


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_imaging_filters_follow_the_selected_tube(window):
    """PROF-110: a wheel associated with one tube is offered for that tube only, and switching the Optics selector updates the list."""
    save_optical_tubes(window.pier, [
        {"name": "Newt", "associated": ["filter_wheel:primary"]},
        {"name": "Guide scope"},
    ])
    window._device_pages["filter_wheel"]["adapter"] = _FakeWheel(["Ha", "OIII"], position=0)
    _open_section(window, "imaging")
    assert _filters_shown(window) == ["", "Ha", "OIII"]

    combo = window._optics_combo
    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert _filters_shown(window) == [""]          # the wheel belongs to the other tube

    combo.setCurrentIndex(0)
    combo.activated.emit(0)
    assert _filters_shown(window) == ["", "Ha", "OIII"]


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_imaging_filters_offer_an_unassigned_wheel_and_tolerate_none(window):
    """PROF-110: a wheel no tube has claimed is offered to the selected tube; with no wheel connected the list is just the blank."""
    save_optical_tubes(window.pier, [{"name": "Only tube"}])
    _open_section(window, "imaging")
    assert _filters_shown(window) == [""]

    window._device_pages["filter_wheel"]["adapter"] = _FakeWheel(["L", "R"], position=0)
    _open_section(window, "framing")
    _open_section(window, "imaging")
    assert _filters_shown(window) == ["", "L", "R"]


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_imaging_filter_choice_survives_a_refresh(window):
    """PROF-110: refreshing the list keeps the filter the user picked rather than snapping back to the wheel's position."""
    window._device_pages["filter_wheel"]["adapter"] = _FakeWheel(["L", "R", "G"], position=0)
    _open_section(window, "imaging")
    window._imaging_filter_combo.setCurrentText("G")
    _open_section(window, "framing")
    _open_section(window, "imaging")
    assert window._imaging_filter_combo.currentText() == "G"
