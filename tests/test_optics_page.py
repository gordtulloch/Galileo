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
    # A database from before migrations owned the schema has no migration history for Galileo's tables.
    db.execute_sql("DELETE FROM migratehistory WHERE name >= '013'")
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


class _MovableWheel(_FakeWheel):
    def __init__(self, names, position=0, fail=False):
        super().__init__(names, position)
        self.moves, self.fail = [], fail

    async def move_to(self, index):
        if self.fail:
            raise RuntimeError("wheel jammed")
        self.moves.append(index)
        self.position = index


def _pick_filter(window, name):
    """Choose ``name`` in the Imaging Filter box as the user would, then wait for the move to finish."""
    combo = window._imaging_filter_combo
    combo.setCurrentText(name)
    combo.activated.emit(combo.findText(name))
    thread = window._imaging_filter_thread
    if thread is not None:
        thread.wait(5000)
        window.app.processEvents()      # deliver the queued finished/failed signal


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_imaging_filter_change_moves_the_wheel(window):
    """PROF-110: choosing a filter on the Imaging page moves the wheel to that slot, off the UI thread."""
    wheel = _MovableWheel(["L", "R", "G", "B"], position=0)
    window._device_pages["filter_wheel"]["adapter"] = wheel
    _open_section(window, "imaging")
    _pick_filter(window, "G")
    assert wheel.moves == [2]
    assert window._imaging_filter_thread is None


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_imaging_filter_does_not_move_the_wheel_needlessly(window):
    """PROF-110: re-picking the filter already in the beam, a blank, free text, or opening the page leaves the wheel alone."""
    wheel = _MovableWheel(["L", "R", "G"], position=1)
    window._device_pages["filter_wheel"]["adapter"] = wheel
    _open_section(window, "imaging")            # populating the list must not move it
    _pick_filter(window, "R")                   # already there
    _pick_filter(window, "")                    # "no filter"
    _pick_filter(window, "Custom label")        # not one of the wheel's filters
    assert wheel.moves == []
    assert window._imaging_filter_thread is None


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_imaging_filter_change_ignores_a_wheel_that_belongs_to_another_tube(window):
    """PROF-110: a tube with no wheel of its own never drives one associated with a different tube."""
    save_optical_tubes(window.pier, [
        {"name": "Newt", "associated": ["filter_wheel:primary"]},
        {"name": "Guide scope"},
    ])
    wheel = _MovableWheel(["Ha", "OIII"], position=0)
    window._device_pages["filter_wheel"]["adapter"] = wheel
    _open_section(window, "imaging")
    combo = window._optics_combo
    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    _pick_filter(window, "OIII")
    assert wheel.moves == []


@pytest.mark.requirement("TC-PROF-110")
@pytest.mark.priority("MVP")
def test_imaging_filter_move_failure_is_reported_not_raised(window):
    """PROF-110: a wheel that fails to move is reported on the status bar and does not block the next attempt."""
    wheel = _MovableWheel(["L", "R"], position=0, fail=True)
    window._device_pages["filter_wheel"]["adapter"] = wheel
    _open_section(window, "imaging")
    _pick_filter(window, "R")
    assert window._imaging_filter_thread is None
    assert "failed" in window._window.statusBar().currentMessage()


# --- The top-bar Camera selector (PROF-120) ---------------------------------

def _camera_selector_shown(window):
    return not window._camera_combo.isHidden() and not window._camera_label.isHidden()


def _cameras_shown(window):
    combo = window._camera_combo
    return [combo.itemText(i) for i in range(combo.count())]


@pytest.mark.requirement("TC-PROF-120")
@pytest.mark.priority("MVP")
def test_tc_prof_120_camera_selector_appears_wherever_the_optics_selector_does(window):
    """PROF-120: the Camera selector is shown on exactly the screens that choose the optics — an optical train is the tube and its camera."""
    save_device_config(window.pier, "camera", driver="Alpaca", server="h", port=1, device_name="ASI2600")
    for section in ("equipment", "planning", "framing", "imaging", "solve", "science"):
        _open_section(window, section)
        assert _camera_selector_shown(window) == _optics_selector_shown(window), section
    for section in ("framing", "imaging", "solve"):
        _open_section(window, section)
        assert _camera_selector_shown(window), f"{section} chooses the optics, so it chooses the camera"


@pytest.mark.requirement("TC-PROF-120")
@pytest.mark.priority("MVP")
def test_tc_prof_120_a_single_camera_is_still_shown(window):
    """PROF-120: the selector is shown even with one camera, so which camera a screen will use is never left to be inferred."""
    save_device_config(window.pier, "camera", driver="Alpaca", server="h", port=1, device_name="ASI2600")
    _open_section(window, "solve")
    assert _camera_selector_shown(window) and window._camera_combo.isEnabled()
    assert len(_cameras_shown(window)) == 1
    assert "Primary Camera" in _cameras_shown(window)[0] and "ASI2600" in _cameras_shown(window)[0]


@pytest.mark.requirement("TC-PROF-120")
@pytest.mark.priority("MVP")
def test_tc_prof_120_selector_says_whether_the_camera_is_connected(window):
    """PROF-120: each entry says whether that camera is connected, so a screen that refuses to capture shows its reason."""
    save_device_config(window.pier, "camera", driver="Alpaca", server="h", port=1, device_name="ASI2600")
    _open_section(window, "solve")
    assert _cameras_shown(window) == ["Primary Camera — ASI2600 (not connected)"]

    window._camera_backends["primary camera"] = object()
    window._refresh_camera_combo()
    assert _cameras_shown(window) == ["Primary Camera — ASI2600"]


@pytest.mark.requirement("TC-PROF-120")
@pytest.mark.priority("MVP")
def test_tc_prof_120_with_no_camera_configured_the_selector_stays_but_is_disabled(window):
    """PROF-120: with no camera configured the selector remains visible but disabled, saying where to set one up."""
    _open_section(window, "solve")
    assert _camera_selector_shown(window) and not window._camera_combo.isEnabled()
    assert _cameras_shown(window) == ["None configured — see Equipment > Camera"]


@pytest.mark.requirement("TC-PROF-120")
@pytest.mark.priority("MVP")
def test_tc_prof_120_choosing_a_camera_changes_the_one_screens_use(window):
    """PROF-120: picking a camera in the selector is what the capture screens then use."""
    for slot in ("primary", "camera_2"):
        save_device_config(window.pier, "camera", driver="Alpaca", server="h", port=1,
                           device_name=f"cam {slot}", slot=slot)
    _open_section(window, "solve")
    combo = window._camera_combo
    assert combo.count() == 2 and window._active_camera_slot == "primary"
    # Primary first, whatever order the database hands the slots back in.
    assert [combo.itemData(i) for i in range(2)] == ["primary", "camera_2"]

    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert window._active_camera_slot == "camera_2"

    from galileo.ui.app_window import _camera_backend_key_for_slot
    second = object()
    window._camera_backends[_camera_backend_key_for_slot("camera_2")] = second
    from galileo.ui.solve import SolvePage
    assert SolvePage(window)._camera() is second, "the Solve screen uses the selected camera"


@pytest.mark.requirement("TC-PROF-120")
@pytest.mark.priority("MVP")
def test_tc_prof_120_the_no_camera_message_names_the_selected_camera(window):
    """PROF-120: refusing to capture says which camera is selected and what to do, not just "connect a camera"."""
    message = window.camera_not_connected_message()
    assert "Primary Camera" in message and "Equipment > Camera" in message
    assert "No Primary Camera is configured" in message, "nothing is saved for this Pier yet"

    save_device_config(window.pier, "camera", driver="Alpaca", server="h", port=1, device_name="ASI2600")
    message = window.camera_not_connected_message()
    assert "ASI2600" in message and "not connected" in message


@pytest.mark.requirement("TC-PROF-120")
@pytest.mark.priority("MVP")
def test_tc_prof_120_camera_slots_are_listed_primary_first(window):
    """PROF-120: saved slots come back in slot order, not the database's — "camera_2" must not sort ahead of "primary"."""
    from galileo.observatory import list_device_config_slots
    for slot in ("camera_3", "primary", "camera_2"):
        save_device_config(window.pier, "camera", driver="Alpaca", server="h", port=1,
                           device_name=f"cam {slot}", slot=slot)
    assert list_device_config_slots(window.pier, "camera") == ["primary", "camera_2", "camera_3"]

    _open_section(window, "solve")
    assert [c.split(" —")[0] for c in _cameras_shown(window)] == ["Primary Camera", "Camera 2", "Camera 3"]
    assert window._active_camera_slot == "primary"
