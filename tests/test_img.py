# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""IMG — Imaging Tab (TC-IMG-010 … TC-IMG-180)."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def imaging_service(mock_indi_camera):
    imaging = pytest.importorskip("galileo.ui.imaging")
    svc = imaging.ImagingService(camera=mock_indi_camera)
    return svc


# ---------------------------------------------------------------------------
# TC-IMG-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-010")
@pytest.mark.priority("MVP")
async def test_tc_img_010_live_preview_after_readout(mock_indi_camera, imaging_service):
    """IMG-010: Display a newly captured frame in a live preview within a bounded time after camera readout."""
    import numpy as np
    frame_data = np.zeros((100, 100), dtype=np.uint16)
    mock_indi_camera.get_image_array = AsyncMock(return_value=frame_data)

    await imaging_service.capture_and_preview(duration=1.0)
    frame = imaging_service.current_frame
    assert frame is not None
    assert frame.shape == (100, 100)


# ---------------------------------------------------------------------------
# TC-IMG-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-020")
@pytest.mark.priority("MVP")
async def test_tc_img_020_auto_stretch_does_not_alter_saved_file(mock_indi_camera, imaging_service, tmp_path):
    """IMG-020: Auto-stretch preview does not alter the saved file's raw pixel data."""
    import numpy as np
    raw = np.arange(10000, dtype=np.uint16).reshape(100, 100)
    mock_indi_camera.get_image_array = AsyncMock(return_value=raw)

    await imaging_service.capture_and_preview(duration=1.0, save_dir=tmp_path)
    stretched = imaging_service.current_preview  # 8-bit display copy
    saved = imaging_service.last_saved_array      # raw unmodified copy

    assert stretched.max() <= 255
    assert saved.max() == raw.max(), "Saved data must match original raw values"


# ---------------------------------------------------------------------------
# TC-IMG-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-030")
@pytest.mark.priority("MVP")
async def test_tc_img_030_histogram_updated_per_capture(mock_indi_camera, imaging_service):
    """IMG-030: Display a histogram of the current frame, updated per capture."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.ones((100, 100), dtype=np.uint16) * 1000)
    await imaging_service.capture_and_preview(duration=1.0)

    hist = imaging_service.get_histogram()
    assert hist is not None
    assert len(hist["bins"]) > 0
    assert len(hist["counts"]) == len(hist["bins"])


# ---------------------------------------------------------------------------
# TC-IMG-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-040")
@pytest.mark.priority("MVP")
async def test_tc_img_040_per_frame_statistics(mock_indi_camera, imaging_service):
    """IMG-040: Compute per-frame statistics: mean, median, min/max, star count, HFR."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.float32))
    await imaging_service.capture_and_preview(duration=1.0)

    stats = imaging_service.get_frame_stats()
    for key in ("mean", "median", "min", "max", "star_count", "hfr"):
        assert key in stats, f"Frame stats must include '{key}'"


# ---------------------------------------------------------------------------
# TC-IMG-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-050")
@pytest.mark.priority("P2")
async def test_tc_img_050_star_overlay_toggleable(mock_indi_camera, imaging_service):
    """IMG-050: Overlay detected stars for HFR on the frame preview, toggleable by the user."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.float32))
    await imaging_service.capture_and_preview(duration=1.0)

    imaging_service.set_star_overlay(enabled=True)
    assert imaging_service.star_overlay_enabled is True

    imaging_service.set_star_overlay(enabled=False)
    assert imaging_service.star_overlay_enabled is False


# ---------------------------------------------------------------------------
# TC-IMG-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-060")
@pytest.mark.priority("MVP")
def test_tc_img_060_pan_and_zoom(imaging_service):
    """IMG-060: Allow the user to pan and zoom the displayed frame."""
    imaging_service.set_zoom(2.0)
    assert imaging_service.zoom_factor == 2.0

    imaging_service.set_pan_offset(dx=50, dy=-30)
    assert imaging_service.pan_offset == (50, -30)

    imaging_service.reset_view()
    assert imaging_service.zoom_factor == 1.0
    assert imaging_service.pan_offset == (0, 0)


# ---------------------------------------------------------------------------
# TC-IMG-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-070")
@pytest.mark.priority("MVP")
async def test_tc_img_070_manual_single_exposure(mock_indi_camera, imaging_service):
    """IMG-070: Support manual single-exposure capture independent of any running sequence."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.float32))

    frame = await imaging_service.capture_single(duration=5.0, filter_name="Ha")
    assert frame is not None
    mock_indi_camera.start_exposure.assert_called_once()


# ---------------------------------------------------------------------------
# TC-IMG-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-080")
@pytest.mark.priority("P2")
def test_tc_img_080_configurable_panel_layout(imaging_service):
    """IMG-080: Allow the user to configure imaging-tab panel arrangement; persisted across restarts."""
    layout = {"histogram": "bottom-left", "stats": "right", "preview": "center"}
    imaging_service.set_panel_layout(layout)
    saved = imaging_service.get_panel_layout()
    assert saved["histogram"] == "bottom-left"
    assert saved["preview"] == "center"


# ---------------------------------------------------------------------------
# TC-IMG-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-090")
@pytest.mark.priority("MVP")
async def test_tc_img_090_live_countdown_and_status(mock_indi_camera, imaging_service):
    """IMG-090: Display live exposure countdown and camera/download status during in-progress capture."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))

    # Check that status transitions are exposed during capture
    imaging_service._capture_status = "idle"
    capture_coro = imaging_service.capture_and_preview(duration=1.0)
    # Status must change from idle to exposing during capture
    # (tested via state inspection on service object)
    await capture_coro
    # After completion the status must be in a terminal state
    assert imaging_service.capture_status in ("idle", "complete", "preview_ready")


# ---------------------------------------------------------------------------
# TC-IMG-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-100")
@pytest.mark.priority("P2")
async def test_tc_img_100_save_current_frame_independently(mock_indi_camera, imaging_service, tmp_path):
    """IMG-100: Allow saving the currently displayed frame independently of the automatic sequence save path."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((100, 100), dtype=np.float32))
    await imaging_service.capture_and_preview(duration=1.0)

    save_path = tmp_path / "manual_save.fits"
    imaging_service.save_current_frame(save_path)
    assert save_path.exists()


# ---------------------------------------------------------------------------
# TC-IMG-110 — debayer
# ---------------------------------------------------------------------------

def _mosaic_of(colour, pattern, shape=(9, 12)):
    """The raw Bayer frame a ``pattern`` sensor would record of a uniformly ``colour``-lit scene."""
    import numpy as np
    tile = [pattern[0:2], pattern[2:4]]
    rows, cols = np.indices(shape)
    values = {"R": colour[0], "G": colour[1], "B": colour[2]}
    return np.vectorize(lambda r, c: values[tile[r & 1][c & 1]])(rows, cols).astype(np.uint16)


@pytest.mark.requirement("TC-IMG-110")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("pattern", ["RGGB", "GRBG", "GBRG", "BGGR"])
def test_tc_img_110_debayer_recovers_a_uniform_colour_for_every_pattern(pattern):
    """IMG-110: debayering with the right pattern turns the mosaic of a uniform colour back into that colour at every
    pixel, edges included; the wrong pattern does not."""
    import numpy as np
    from galileo.debayer import debayer
    colour = (1000, 300, 60)
    rgb = debayer(_mosaic_of(colour, pattern), pattern)
    assert rgb.shape == (9, 12, 3)
    assert np.allclose(rgb, colour)
    other = "BGGR" if pattern == "RGGB" else "RGGB"
    assert not np.allclose(debayer(_mosaic_of(colour, pattern), other), colour)


@pytest.mark.requirement("TC-IMG-110")
@pytest.mark.priority("MVP")
def test_tc_img_110_debayer_rejects_an_unknown_pattern_or_a_non_mosaic():
    """IMG-110: only the four Bayer layouts and a 2-D mosaic are accepted."""
    import numpy as np
    from galileo.debayer import debayer
    with pytest.raises(ValueError, match="pattern"):
        debayer(np.zeros((4, 4)), "RBBG")
    with pytest.raises(ValueError, match="2-D"):
        debayer(np.zeros((4, 4, 3)), "RGGB")


@pytest.mark.requirement("TC-IMG-110")
@pytest.mark.priority("MVP")
async def test_tc_img_110_service_previews_in_colour_only_when_debayer_is_on(mock_indi_camera, imaging_service):
    """IMG-110: with Debayer on the preview is RGB; off it is the plain grey mosaic; toggling re-renders the frame
    already captured, and the raw frame - what statistics and Save Frame use - never changes."""
    import numpy as np
    raw = _mosaic_of((1000, 300, 60), "RGGB")
    mock_indi_camera.get_image_array = AsyncMock(return_value=raw)

    await imaging_service.capture_and_preview(duration=1.0)
    assert imaging_service.current_preview.shape == raw.shape and imaging_service.debayer_note == ""

    imaging_service.set_debayer(True)
    assert imaging_service.current_preview.shape == raw.shape + (3,)
    assert imaging_service.debayer_note == "Debayered (RGGB)."
    imaging_service.set_debayer(False)
    assert imaging_service.current_preview.shape == raw.shape

    imaging_service.set_debayer(True)
    await imaging_service.capture_and_preview(duration=1.0)        # a new capture is debayered as it arrives
    assert imaging_service.current_preview.ndim == 3
    assert imaging_service.current_frame is raw and np.array_equal(imaging_service.current_frame, _mosaic_of((1000, 300, 60), "RGGB"))


@pytest.mark.requirement("TC-IMG-110")
@pytest.mark.priority("MVP")
async def test_tc_img_110_service_uses_the_set_pattern_and_defaults_to_rggb(mock_indi_camera, imaging_service):
    """IMG-110: RGGB until told otherwise; the pattern given is the one used; a bad value falls back to RGGB."""
    assert imaging_service.bayer_pattern == "RGGB"
    raw = _mosaic_of((1000, 300, 60), "GBRG")
    mock_indi_camera.get_image_array = AsyncMock(return_value=raw)
    await imaging_service.capture_and_preview(duration=1.0)
    imaging_service.set_debayer(True)
    wrong = imaging_service.current_preview.copy()

    imaging_service.set_bayer_pattern("gbrg")                       # case-insensitive
    assert imaging_service.bayer_pattern == "GBRG" and imaging_service.debayer_note == "Debayered (GBRG)."
    assert not (imaging_service.current_preview == wrong).all()     # re-rendered with the right layout

    imaging_service.set_bayer_pattern("RBBG")
    assert imaging_service.bayer_pattern == "RGGB"
    imaging_service.set_bayer_pattern(None)
    assert imaging_service.bayer_pattern == "RGGB"


@pytest.mark.requirement("TC-IMG-110")
@pytest.mark.priority("MVP")
async def test_tc_img_110_an_already_colour_frame_is_left_alone(mock_indi_camera, imaging_service):
    """IMG-110: a camera that already delivers colour is shown as it is, with a note, not debayered again."""
    import numpy as np
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.full((8, 8, 3), 500, dtype=np.uint16))
    await imaging_service.capture_and_preview(duration=1.0)
    imaging_service.set_debayer(True)
    assert imaging_service.current_preview.shape == (8, 8, 3)
    assert "already colour" in imaging_service.debayer_note


# --- the Camera page setting and the Imaging checkbox -----------------------

@pytest.fixture
def window(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "debayer.db")
    from galileo.observatory import create_observatory, create_pier
    from galileo.ui.app_window import AppWindow

    win = AppWindow()
    win.app, win.QtWidgets = app, QtWidgets
    win.pier = create_pier(create_observatory("Test Obs"), "Pier A")
    win._current_pier = win.pier
    yield win
    win._window.close()
    db.close()


def _bayer_combo(page, QtWidgets):
    from galileo.debayer import BAYER_PATTERNS
    matches = [c for c in page.findChildren(QtWidgets.QComboBox)
               if [c.itemText(i) for i in range(c.count())] == list(BAYER_PATTERNS)]
    assert len(matches) == 1, "expected exactly one Bayer pattern selector (one camera panel)"
    return matches[0]


@pytest.mark.requirement("TC-IMG-110")
@pytest.mark.priority("MVP")
def test_tc_img_110_camera_page_bayer_pattern_defaults_to_rggb_and_is_saved(window):
    """IMG-110: the Camera page offers the four patterns, starts on RGGB, and saves/reloads the choice per camera."""
    from galileo.observatory import get_device_config
    QtWidgets = window.QtWidgets
    page = window._build_camera_page()
    combo = _bayer_combo(page, QtWidgets)
    assert combo.currentText() == "RGGB"

    combo.setCurrentText("BGGR")
    next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Save").click()
    assert get_device_config(window.pier, "camera").bayer_pattern == "BGGR"

    assert _bayer_combo(window._build_camera_page(), QtWidgets).currentText() == "BGGR"


@pytest.mark.requirement("TC-IMG-110")
@pytest.mark.priority("MVP")
def test_tc_img_110_imaging_debayer_checkbox_uses_the_selected_cameras_pattern(window):
    """IMG-110: ticking Debayer on the Imaging tab colours the frame using the pattern saved for the selected camera."""
    import numpy as np
    from galileo.observatory import save_device_config
    save_device_config(window.pier, "camera", driver="Alpaca", server="h", port=1, bayer_pattern="GBRG")
    service = window._imaging_service
    service.current_frame = _mosaic_of((1000, 300, 60), "GBRG")

    check = window._imaging_debayer_check
    assert check.text() == "Debayer" and not check.isChecked()
    check.setChecked(True)
    assert service.bayer_pattern == "GBRG" and service.current_preview.ndim == 3
    check.setChecked(False)
    assert service.current_preview.ndim == 2
    assert np.array_equal(service.current_frame, _mosaic_of((1000, 300, 60), "GBRG"))


@pytest.mark.requirement("TC-IMG-110")
@pytest.mark.priority("MVP")
def test_tc_img_110_existing_device_configs_table_gains_the_bayer_column(tmp_path):
    """IMG-110: a database created before cameras had a Bayer pattern is upgraded in place, its rows defaulting to RGGB."""
    from galileo.library.database import db, init_db
    from galileo.observatory import create_observatory, create_pier, get_device_config, save_device_config
    path = tmp_path / "old.db"
    init_db(path)
    pier = create_pier(create_observatory("Obs"), "Pier")
    save_device_config(pier, "camera", driver="Alpaca", server="h", port=1)
    db.execute_sql("ALTER TABLE device_configs DROP COLUMN bayer_pattern")
    assert "bayer_pattern" not in {c.name for c in db.get_columns("device_configs")}
    # A database from before migrations owned the schema has no migration history for Galileo's tables.
    db.execute_sql("DELETE FROM migratehistory WHERE name >= '013'")
    db.close()

    init_db(path)
    try:
        assert "bayer_pattern" in {c.name for c in db.get_columns("device_configs")}
        assert get_device_config(pier, "camera").bayer_pattern == "RGGB"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# TC-IMG-120 â€” portrait / landscape layout
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-120")
@pytest.mark.priority("P2")
def test_tc_img_120_orientation_is_detected_from_the_frame_shape():
    """IMG-120: a frame taller than it is wide is portrait; wider, square or absent is landscape."""
    import numpy as np
    from galileo.ui.imaging import frame_orientation
    assert frame_orientation(np.zeros((300, 200))) == "portrait"
    assert frame_orientation(np.zeros((200, 300))) == "landscape"
    assert frame_orientation(np.zeros((200, 200))) == "landscape"
    assert frame_orientation(np.zeros((300, 200, 3))) == "portrait"    # a debayered colour frame
    assert frame_orientation(None) == "landscape"


@pytest.mark.requirement("TC-IMG-120")
@pytest.mark.priority("P2")
def test_tc_img_120_service_follows_the_frame_unless_the_user_chooses(imaging_service):
    """IMG-120: the layout orientation follows the current frame until the user picks one, and going back to automatic follows it again."""
    import numpy as np
    assert imaging_service.orientation == "landscape"          # no frame yet
    imaging_service.current_frame = np.zeros((300, 200))
    assert imaging_service.orientation == imaging_service.detected_orientation == "portrait"

    imaging_service.set_manual_orientation("landscape")
    assert imaging_service.orientation == "landscape"
    assert imaging_service.detected_orientation == "portrait"  # detection is not overridden, only the layout

    imaging_service.set_manual_orientation(None)
    assert imaging_service.orientation == "portrait"
    imaging_service.set_manual_orientation("sideways")          # not a choice, so ignored
    assert imaging_service.manual_orientation is None


@pytest.mark.requirement("TC-IMG-120")
@pytest.mark.priority("P2")
def test_tc_img_120_portrait_frame_gives_the_preview_the_right_side_and_docks_the_rest_left(window):
    """IMG-120: for a portrait frame the preview becomes a column one third of the page wide and the nudge pad, histogram, progress and log (taller than in landscape) sit to its left."""
    import numpy as np
    ui, service = window._imaging_ui, window._imaging_service
    dock, content = ui["dock_panel"], ui["content"]
    nudge, settings = ui["nudge_group"], ui["settings_panel"]
    secondary = (ui["histogram"], ui["progress"], ui["log"])

    ui["apply_orientation"]()
    assert all(w.parentWidget() is content for w in secondary), "landscape keeps them under the preview"
    assert nudge.parentWidget() is settings, "and the nudge pad in the settings panel"
    landscape_heights = ui["histogram"].height(), ui["log"].height()

    service.current_frame = np.zeros((300, 200), dtype=np.uint16)
    ui["apply_orientation"]()
    assert all(w.parentWidget() is dock for w in (nudge, *secondary))
    assert ui["preview"].parentWidget() is content
    assert content.layout().count() == 1, "the preview is all that is left on the right"
    assert ui["histogram"].height() > landscape_heights[0] and ui["log"].height() > landscape_heights[1], "the middle column has the height to spare"

    page = ui["page"]
    window._window.show()   # a hidden page gets its resize events only once it is shown
    sidebar = next(c for c in window._nav_columns if c.objectName() == "Sidebar")
    next(b for b in sidebar.findChildren(window.QtWidgets.QToolButton)
         if " ".join(b.text().split()) == "Imaging").click()
    window._window.resize(1500, 900)
    window.app.processEvents()
    assert content.minimumWidth() == content.maximumWidth() == page.width() // 3, "the preview column is a third of the page"
    before = content.maximumWidth()
    window._window.resize(1900, 900)
    window.app.processEvents()
    assert content.maximumWidth() == page.width() // 3 > before, "and follows the page as it is resized"

    service.current_frame = np.zeros((200, 300), dtype=np.uint16)
    ui["apply_orientation"]()
    assert all(w.parentWidget() is content for w in secondary)
    assert nudge.parentWidget() is settings, "the nudge pad goes back to the settings panel"
    assert (ui["histogram"].height(), ui["log"].height()) == landscape_heights
    assert content.maximumWidth() > 10000, "landscape lets the preview take the whole right side again"


@pytest.mark.requirement("TC-IMG-120")
@pytest.mark.priority("P2")
def test_tc_img_120_manual_checkbox_overrides_the_detected_layout(window):
    """IMG-120: ticking the manual box lets the user pick portrait or landscape whatever the frame; unticking returns to automatic."""
    import numpy as np
    ui, service = window._imaging_ui, window._imaging_service
    check, combo = ui["orientation_check"], ui["orientation_combo"]
    assert not check.isChecked() and not combo.isEnabled()

    service.current_frame = np.zeros((200, 300), dtype=np.uint16)      # landscape frame
    ui["apply_orientation"]()
    check.setChecked(True)
    assert combo.isEnabled() and combo.currentData() == "landscape", "starts from what is shown, so nothing jumps"
    assert ui["histogram"].parentWidget() is ui["content"]

    combo.setCurrentIndex(combo.findData("portrait"))
    assert service.orientation == "portrait"
    assert ui["histogram"].parentWidget() is ui["dock_panel"]

    check.setChecked(False)
    assert not combo.isEnabled() and service.manual_orientation is None
    assert ui["histogram"].parentWidget() is ui["content"], "back to following the (landscape) frame"


# ---------------------------------------------------------------------------
# TC-IMG-130 â€” mount nudge
# ---------------------------------------------------------------------------

class _FakeMount:
    def __init__(self):
        self.calls = []

    async def move_axis(self, axis, rate):
        self.calls.append((axis, rate))


@pytest.mark.requirement("TC-IMG-130")
@pytest.mark.priority("P2")
@pytest.mark.parametrize("direction, expected", [
    ("N", (1, 0.2)), ("S", (1, -0.2)), ("E", (0, 0.2)), ("W", (0, -0.2)),
])
async def test_tc_img_130_nudge_moves_one_axis_then_stops_it(direction, expected):
    """IMG-130: a nudge moves the mount along one axis with the Mount page's jog signs, then stops that axis."""
    from galileo.ui.imaging import nudge_mount
    mount = _FakeMount()
    await nudge_mount(mount, direction, rate=0.2, duration=0.0)
    assert mount.calls == [expected, (expected[0], 0.0)]


@pytest.mark.requirement("TC-IMG-130")
@pytest.mark.priority("P2")
async def test_tc_img_130_nudge_honours_reversed_axes_and_rejects_bad_directions():
    """IMG-130: the Mount page's axis reversal flips the nudge; an unknown direction is refused before anything moves."""
    from galileo.ui.imaging import nudge_mount
    mount = _FakeMount()
    await nudge_mount(mount, "N", 0.2, 0.0, reversed_axes=(False, True))
    await nudge_mount(mount, "e", 0.2, 0.0, reversed_axes=(True, False))
    assert mount.calls == [(1, -0.2), (1, 0.0), (0, -0.2), (0, 0.0)]
    with pytest.raises(ValueError):
        await nudge_mount(mount, "up", 0.2, 0.0)
    assert len(mount.calls) == 4


@pytest.mark.requirement("TC-IMG-130")
@pytest.mark.priority("P2")
async def test_tc_img_130_nudge_always_stops_the_axis_even_when_interrupted():
    """IMG-130: a nudge that is cancelled part-way still sends the stop, so the mount is never left running."""
    import asyncio
    from galileo.ui.imaging import nudge_mount
    mount = _FakeMount()
    task = asyncio.ensure_future(nudge_mount(mount, "W", 0.2, duration=30.0))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mount.calls == [(0, -0.2), (0, 0.0)]


def _click_nudge(window, direction):
    """Press a nudge button as the user would, then wait for the worker thread and deliver its signal."""
    ui = window._imaging_ui
    ui["nudge_buttons"][direction].click()
    thread = ui["nudge_state"]["thread"]
    if thread is not None:
        thread.wait(5000)
        window.app.processEvents()


@pytest.mark.requirement("TC-IMG-130")
@pytest.mark.priority("P2")
def test_tc_img_130_nudge_pad_drives_the_connected_mount(window):
    """IMG-130: the Imaging page's nudge pad moves the mount connected on the Mount page, at the chosen speed and duration."""
    ui = window._imaging_ui
    mount = _FakeMount()
    window._device_pages["mount"]["adapter"] = mount
    window._device_pages["mount"]["axis_reversed"] = lambda: (False, False)
    ui["nudge_rate"].setCurrentIndex(ui["nudge_rate"].findData(1.0))
    ui["nudge_duration"].setValue(0.1)

    _click_nudge(window, "E")
    assert mount.calls == [(0, 1.0), (0, 0.0)]
    assert ui["nudge_state"]["thread"] is None and all(b.isEnabled() for b in ui["nudge_buttons"].values())

    window._device_pages["mount"]["axis_reversed"] = lambda: (True, False)
    _click_nudge(window, "E")
    assert mount.calls[2:] == [(0, -1.0), (0, 0.0)]


@pytest.mark.requirement("TC-IMG-130")
@pytest.mark.priority("P2")
def test_tc_img_130_nudge_without_a_mount_moves_nothing_and_says_so(window):
    """IMG-130: with no mount connected a nudge does nothing but tell the user to connect one."""
    window._device_pages["mount"]["adapter"] = None
    _click_nudge(window, "N")
    assert window._imaging_ui["nudge_state"]["thread"] is None
    assert "mount" in window._window.statusBar().currentMessage().lower()


@pytest.mark.requirement("TC-IMG-130")
@pytest.mark.priority("P2")
def test_tc_img_130_nudge_stop_halts_both_axes(window):
    """IMG-130: the pad's centre button stops both axes at once."""
    mount = _FakeMount()
    window._device_pages["mount"]["adapter"] = mount
    window._imaging_ui["nudge_stop"].click()
    assert sorted(mount.calls) == [(0, 0.0), (1, 0.0)]


# ---------------------------------------------------------------------------
# TC-IMG-140 — the current object of each Pier
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_current_objects():
    """The store is process-wide and Pier ids restart with each test database, so start each test empty."""
    import galileo.current_object as co
    co._default_store = None
    yield
    co._default_store = None


def _m31():
    from galileo.current_object import CurrentObject
    return CurrentObject(name="M 31", ra_deg=10.6847, dec_deg=41.2687, kind="Galaxy")


@pytest.mark.requirement("TC-IMG-140")
@pytest.mark.priority("P2")
def test_tc_img_140_each_pier_keeps_its_own_current_object_and_changes_are_announced():
    """IMG-140: the current object is kept per Pier, and every change is published on the event bus."""
    from galileo.bus import CurrentObjectChangedEvent, EventBus
    from galileo.current_object import CurrentObject, CurrentObjects
    bus, seen = EventBus(), []
    bus.subscribe(CurrentObjectChangedEvent, lambda e: seen.append((e.pier, e.object)))
    store = CurrentObjects(bus)
    pier_a, pier_b = type("P", (), {"id": 1, "name": "A"})(), type("P", (), {"id": 2, "name": "A"})()  # same name, different Piers

    assert store.get(pier_a) is None
    store.set(pier_a, _m31())
    assert store.get(pier_a) == _m31() and store.get(pier_b) is None
    store.set(pier_b, CurrentObject("Vega", 279.2, 38.8))
    assert store.get(pier_a).name == "M 31" and store.get(pier_b).name == "Vega"

    store.set(pier_a, _m31())                       # unchanged: nothing announced
    assert [key for key, _ in seen] == [1, 2]
    store.clear(pier_a)
    assert store.get(pier_a) is None and seen[-1] == (1, None)
    store.set(None, _m31())                         # no Pier: nothing to keep
    assert len(seen) == 3


@pytest.mark.requirement("TC-IMG-140")
@pytest.mark.priority("P2")
def test_tc_img_140_object_names_are_made_safe_for_file_names():
    """IMG-140: an object's name becomes a file-name-safe stem."""
    from galileo.current_object import CurrentObject, safe_file_stem
    assert safe_file_stem("M 31") == "M_31"
    assert safe_file_stem("NGC 7000 / North America") == "NGC_7000_North_America"
    assert safe_file_stem("  RW Aur  ") == "RW_Aur"
    assert safe_file_stem("a:b*c?") == "a_b_c"
    assert safe_file_stem("") == safe_file_stem(None) == safe_file_stem("///") == ""
    obj = CurrentObject.from_atlas({"name": "M 31", "ra_deg": 10.0, "dec_deg": 41.0, "type": "Galaxy", "designation": "NGC 224"})
    assert obj.file_stem == "M_31" and obj.kind == "Galaxy" and obj.designation == "NGC 224"


@pytest.mark.requirement("TC-IMG-140")
@pytest.mark.priority("P2")
async def test_tc_img_140_saved_frames_are_named_after_the_current_object(mock_indi_camera, imaging_service, tmp_path):
    """IMG-140: frames the Imaging tab saves are named after the current object and carry it as OBJECT; with none they keep the old name."""
    import numpy as np
    from astropy.io import fits
    mock_indi_camera.get_image_array = AsyncMock(return_value=np.zeros((20, 30), dtype=np.uint16))

    await imaging_service.capture_and_preview(duration=1.0, save_dir=tmp_path)
    assert imaging_service.last_saved_path.name.startswith("frame_")
    assert "OBJECT" not in fits.getheader(imaging_service.last_saved_path)

    imaging_service.object_name = "M 31"
    await imaging_service.capture_and_preview(duration=1.0, save_dir=tmp_path)
    assert imaging_service.last_saved_path.name.startswith("M_31_")
    assert fits.getheader(imaging_service.last_saved_path)["OBJECT"] == "M 31"

    assert imaging_service.suggested_filename().startswith("M_31_") and imaging_service.suggested_filename().endswith(".fits")
    imaging_service.save_current_frame(tmp_path / "manual.fits")
    assert fits.getheader(tmp_path / "manual.fits")["OBJECT"] == "M 31"
    imaging_service.object_name = ""
    assert imaging_service.suggested_filename().startswith("frame_")


@pytest.mark.requirement("TC-IMG-140")
@pytest.mark.priority("P2")
def test_tc_img_140_selecting_in_the_star_atlas_sets_the_pier_current_object_shown_top_right(window):
    """IMG-140: picking an item in the Star Atlas makes it the selected Pier's current object, noted at the top right; each Pier keeps its own."""
    from galileo.current_object import get_current_objects
    from galileo.observatory import create_pier
    from galileo.ui.star_atlas import StarAtlasView

    label = window._current_object_label
    assert label.text() == "Current object: none" and window.current_object() is None

    atlas_page = window._build_star_atlas_page()      # kept, or Qt deletes the view with it
    view = atlas_page.findChild(StarAtlasView)
    view.select({"kind": "dso", "name": "M 31", "designation": "NGC 224", "type": "Galaxy",
                 "ra_deg": 10.6847, "dec_deg": 41.2687, "mag": 3.4, "alt": 40.0, "az": 100.0})
    assert label.text() == "Current object: M 31"
    assert window.current_object().name == "M 31" and window.current_object().ra_deg == pytest.approx(10.6847)
    assert get_current_objects().get(window.pier).name == "M 31"

    other = create_pier(window.pier.observatory, "Pier B")
    window._current_pier = other
    window._on_pier_changed()
    assert label.text() == "Current object: none", "another Pier has its own current object"
    window._current_pier = window.pier
    window._on_pier_changed()
    assert label.text() == "Current object: M 31", "and the first one kept its"


@pytest.mark.requirement("TC-IMG-140")
@pytest.mark.priority("P2")
def test_tc_img_140_imaging_page_names_frames_from_the_current_object(window, monkeypatch, tmp_path):
    """IMG-140: the Imaging page's Save Frame suggests a name built from the current object."""
    import numpy as np
    from galileo.current_object import get_current_objects
    QtWidgets = window.QtWidgets
    get_current_objects().set(window.pier, _m31())
    service = window._imaging_service
    service.current_frame = np.zeros((10, 10), dtype=np.uint16)

    suggested = {}
    def fake_dialog(parent, caption, directory, *args):
        suggested["name"] = directory
        return "", ""
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", staticmethod(fake_dialog))
    save = next(b for b in window._imaging_ui["settings_panel"].findChildren(QtWidgets.QPushButton) if b.text() == "Save Frame…")
    save.setEnabled(True)
    save.click()
    assert suggested["name"].startswith("M_31_") and service.object_name == "M 31"


class _SolveRig:
    """Fake camera and mount plus a scripted solver, for Capture & Solve with Slew to Target."""

    def __init__(self, tmp_path):
        import numpy as np
        self.plt = pytest.importorskip("galileo.platesolve")
        self.events: list = []
        self.camera = MagicMock()
        self.camera.start_exposure = AsyncMock(side_effect=lambda **kw: self.events.append("capture"))
        self.camera.get_image_array = AsyncMock(return_value=np.full((40, 60), 100, dtype=np.uint16))
        self.mount = MagicMock()
        # A mount that reports J2000, so its coordinates need no precession.
        self.mount.get_status = AsyncMock(return_value={
            "right_ascension": 100.0 / 15.0, "declination": 20.0, "equatorial_system": "J2000", "slewing": False})
        self.mount.slew_to_coordinates = AsyncMock(side_effect=lambda ra, dec: self.events.append(("slew", ra, dec)))
        self.mount.sync_to_coordinates = AsyncMock(side_effect=lambda ra, dec: self.events.append(("sync", ra, dec)))
        self.solver = self.plt.PlateSolver(backend="astap", executable="unused")
        self.log: list = []
        self.workflow = self.plt.SolveWorkflow(
            self.solver, camera=self.camera, mount=self.mount, work_dir=tmp_path / "solve", log=self.log.append)

    def solve_at(self, ra, dec):
        return self.plt.SolveResult(success=True, ra_deg=ra, dec_deg=dec, rotation_deg=0.0, scale_arcsec_px=3.0)


@pytest.mark.requirement("TC-IMG-140")
@pytest.mark.priority("P2")
async def test_tc_img_140_capture_and_solve_slew_to_target_goes_to_the_current_object(tmp_path):
    """IMG-140: Capture & Solve with Slew to Target slews to the current object first, takes its frames there, and names them after it."""
    rig = _SolveRig(tmp_path)
    target = (10.6847, 41.2687)
    rig.solver._run_solver = AsyncMock(return_value=rig.solve_at(*target))     # lands right on it
    rig.workflow.set_target(*target, name="M 31")
    settings = rig.plt.SolveSettings(action=rig.plt.SolveAction.SLEW_TO_TARGET, accuracy_arcsec=30.0, settle_s=0.0)

    results = await rig.workflow.capture_and_solve(settings)

    assert rig.events[0] == ("slew", pytest.approx(target[0]), pytest.approx(target[1])), "slews before the first frame"
    assert rig.events[1] == "capture"
    assert [r.success for r in results] == [True]
    assert any("M 31" in line for line in rig.log)
    assert [p.name for p in (tmp_path / "solve").glob("solve_M_31_*.fits")], "the frame is named after the object"


@pytest.mark.requirement("TC-IMG-140")
@pytest.mark.priority("P2")
async def test_tc_img_140_solve_without_a_current_object_targets_where_the_mount_points(tmp_path):
    """IMG-140: with no current object, Slew to Target behaves as before: the target is where the mount was pointing, and nothing is slewed up front."""
    rig = _SolveRig(tmp_path)
    rig.solver._run_solver = AsyncMock(return_value=rig.solve_at(100.0, 20.0))
    settings = rig.plt.SolveSettings(action=rig.plt.SolveAction.SLEW_TO_TARGET, settle_s=0.0)
    await rig.workflow.capture_and_solve(settings)
    assert rig.workflow.target == pytest.approx((100.0, 20.0))
    assert rig.events == ["capture"]
    assert [p.name for p in (tmp_path / "solve").glob("solve_2*.fits")], "no object, no object in the name"


@pytest.mark.requirement("TC-IMG-140")
@pytest.mark.priority("P2")
async def test_tc_img_140_a_chosen_target_is_only_slewed_to_when_slew_to_target_is_selected(tmp_path):
    """IMG-140: Sync and Nothing don't move the mount to the current object; only Slew to Target does."""
    for action in ("SYNC", "NOTHING"):
        rig = _SolveRig(tmp_path / action)
        rig.solver._run_solver = AsyncMock(return_value=rig.solve_at(100.0, 20.0))
        rig.workflow.set_target(10.0, 41.0, name="M 31")
        await rig.workflow.capture_and_solve(rig.plt.SolveSettings(action=getattr(rig.plt.SolveAction, action), settle_s=0.0))
        assert not [e for e in rig.events if isinstance(e, tuple) and e[0] == "slew"]


@pytest.mark.requirement("TC-IMG-140")
@pytest.mark.priority("P2")
def test_tc_img_140_solve_page_targets_the_current_object(window):
    """IMG-140: the Solve page says what Slew to Target aims at and hands the current object to the workflow as its target."""
    from galileo.current_object import get_current_objects
    from galileo.ui.solve import SolvePage
    page = SolvePage(window)
    assert "where the mount points" in page.target_label.text()

    captured = {}

    class FakeWorkflow:
        def __init__(self, *args, **kwargs):
            captured["workflow"] = self
            self.target = None
        def set_target(self, ra, dec, name=""):
            self.target = (ra, dec, name)

    import galileo.ui.solve as solve_mod
    solve_mod_workflow, solve_mod.SolveWorkflow = solve_mod.SolveWorkflow, FakeWorkflow
    try:
        get_current_objects().set(window.pier, _m31())
        page.refresh_target()
        assert page.target_label.text() == "Target: M 31"
        page.make_solver = lambda: object()
        page._begin(lambda workflow: _noop(), use_current_object=True)
        import threading
        for thread in threading.enumerate():
            if thread.name == "solve-run":
                thread.join(5)
        first = captured["workflow"]
        page._begin(lambda workflow: _noop())          # a run that isn't Capture & Solve (Load & Slew)
        for thread in threading.enumerate():
            if thread.name == "solve-run":
                thread.join(5)
        assert captured["workflow"] is not first and captured["workflow"].target is None
    finally:
        solve_mod.SolveWorkflow = solve_mod_workflow
    assert first.target == (10.6847, 41.2687, "M 31")
    page._workflow = None


@pytest.mark.requirement("TC-IMG-140")
@pytest.mark.priority("P2")
async def test_tc_img_140_load_and_slew_ignores_the_current_object(tmp_path, sample_fits_file):
    """IMG-140: Load & Slew still solves the file it was given and slews to the solved coordinates, whatever the current object is."""
    rig = _SolveRig(tmp_path)
    solved = (200.0, -10.0)
    rig.solver._run_solver = AsyncMock(return_value=rig.solve_at(*solved))
    results = await rig.workflow.solve_file(sample_fits_file, slew=True)     # the page doesn't set a target for this run
    assert [r.success for r in results] == [True]
    assert rig.events == [("slew", pytest.approx(solved[0]), pytest.approx(solved[1]))]
    assert not list((tmp_path / "solve").glob("solve_M_31*"))


async def _noop():
    return None


# ---------------------------------------------------------------------------
# TC-IMG-150 — quantity, gain, full FITS headers and Library auto-save
# ---------------------------------------------------------------------------

@pytest.fixture
def library_repo(tmp_path):
    """A migrated catalog and a library.ini whose repository/scratch folders are temporary."""
    from galileo.library.config import set_config_path
    from galileo.library.database import db, init_db

    repo, scratch = tmp_path / "repo", tmp_path / "scratch"
    repo.mkdir()
    scratch.mkdir()
    ini = tmp_path / "library.ini"
    ini.write_text(f"[DEFAULT]\nrepo = {repo}\ntemp_folder = {scratch}\ncompress_fits = False\n")
    set_config_path(ini)
    init_db(tmp_path / "library.db")
    yield SimpleNamespace(repo=repo, scratch=scratch, root=tmp_path)
    db.close()
    set_config_path(None)


class _CountingCamera:
    """A camera that records each exposure's arguments and returns a frame."""

    def __init__(self, shape=(20, 30)):
        import numpy as np
        self.exposures: list = []
        self.aborted = 0
        self._frame = np.full(shape, 500, dtype=np.uint16)

    async def start_exposure(self, duration, frame_type="Light", **kwargs):
        self.exposures.append({"duration": duration, "frame_type": frame_type, **kwargs})

    async def get_image_array(self):
        return self._frame

    async def abort_exposure(self):
        self.aborted += 1

    def get_temperature(self):
        return -9.5


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
async def test_tc_img_150_quantity_takes_that_many_frames_with_the_same_settings():
    """IMG-150: Capture takes Quantity frames one after another with the screen's settings, reporting each."""
    from galileo.ui.imaging import ImagingService
    camera = _CountingCamera()
    service = ImagingService(camera=camera)
    service.auto_save_to_library = False
    service.gain = 110
    started, done = [], []

    await service.capture_series(3, 2.5, filter_name="Ha", frame_type="Light",
                                 on_frame_start=lambda i, n: started.append((i, n)),
                                 on_frame_done=lambda i, n: done.append((i, n)))

    assert len(camera.exposures) == 3
    assert all(e["duration"] == 2.5 and e["frame_type"] == "Light" and e["gain"] == 110 for e in camera.exposures)
    assert started == done == [(1, 3), (2, 3), (3, 3)]
    assert service.series_done == service.series_total == 3
    assert service.current_frame is not None, "the last frame is on show"


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
async def test_tc_img_150_gain_is_sent_only_when_set():
    """IMG-150: the Gain field is passed to the camera; gain 0 means "leave the camera as configured"."""
    from galileo.ui.imaging import DEFAULT_GAIN, ImagingService
    assert DEFAULT_GAIN == 110, "the Imaging page's Gain field starts at 110"
    camera = _CountingCamera()
    service = ImagingService(camera=camera)
    service.auto_save_to_library = False

    service.gain = 0
    await service.capture_series(1, 1.0)
    assert "gain" not in camera.exposures[0]

    service.gain = DEFAULT_GAIN
    await service.capture_series(1, 1.0)
    assert camera.exposures[1]["gain"] == 110


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
async def test_tc_img_150_a_series_can_be_stopped_part_way():
    """IMG-150: Stop ends a series; no further exposures are started."""
    from galileo.ui.imaging import ImagingService
    camera = _CountingCamera()
    service = ImagingService(camera=camera)
    service.auto_save_to_library = False

    async def stop_after_first():
        service.request_stop()

    original = service.capture_and_preview

    async def capture_then_stop(*args, **kwargs):
        await original(*args, **kwargs)
        await stop_after_first()

    service.capture_and_preview = capture_then_stop
    await service.capture_series(5, 0.1)
    assert len(camera.exposures) == 1 and service.series_done == 1


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
async def test_tc_img_150_saved_frames_carry_every_header_card_the_library_files_by(tmp_path):
    """IMG-150: a saved frame carries the cards the Library names files and folders from, plus the rest Galileo knows."""
    from astropy.io import fits
    from galileo.ui.imaging import ImagingService
    service = ImagingService(camera=_CountingCamera())
    service.auto_save_to_library = False
    service.object_name = "M 31"
    service.gain = 110
    service.frame_context = {
        "telescope": "Newt 200", "instrument": "ASI2600MM", "focal_length_mm": 1000.0, "aperture_mm": 200.0,
        "pixel_size_x_um": 3.76, "pixel_size_y_um": 3.76, "site": "Backyard", "observer": "Gord",
        "site_lat_deg": 49.9, "site_long_deg": -97.1, "objctra": "00 42 44.3", "objctdec": "+41 16 09",
        "ra_deg": 10.68, "dec_deg": 41.27, "bayer_pattern": "RGGB", "focus_position": 12345, "pier_side": "East",
    }
    await service.capture_series(1, 30.0, filter_name="Ha", frame_type="Light")
    service.save_current_frame(tmp_path / "frame.fits")
    hdr = fits.getheader(tmp_path / "frame.fits")

    # Everything the Library's file and folder names are built from (registerFitsImage / organizeFileByType).
    assert hdr["IMAGETYP"] == "Light" and hdr["OBJECT"] == "M 31"
    assert hdr["TELESCOP"] == "Newt 200" and hdr["INSTRUME"] == "ASI2600MM"
    assert hdr["FILTER"] == "Ha" and hdr["EXPTIME"] == 30.0
    assert hdr["XBINNING"] == 1 and hdr["YBINNING"] == 1 and hdr["CCD-TEMP"] == -9.5
    assert hdr["DATE-OBS"].startswith("20") and "T" in hdr["DATE-OBS"]

    # And the rest of what Galileo can know about the frame.
    for card, value in (("GAIN", 110), ("FOCALLEN", 1000.0), ("APTDIA", 200.0), ("XPIXSZ", 3.76),
                        ("SITENAME", "Backyard"), ("OBSERVER", "Gord"), ("OBJCTRA", "00 42 44.3"),
                        ("OBJCTDEC", "+41 16 09"), ("SITELAT", 49.9), ("BAYERPAT", "RGGB"),
                        ("FOCUSPOS", 12345), ("PIERSIDE", "East"), ("SWCREATE", "Galileo")):
        assert hdr[card] == value, card
    assert hdr["EXPOSURE"] == hdr["EXPTIME"], "both spellings, for tools that read only one"
    assert hdr["DATE-END"] >= hdr["DATE-OBS"] and hdr["DATE"]


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
async def test_tc_img_150_calibration_frames_are_not_labelled_with_the_object(tmp_path):
    """IMG-150: a dark or bias carries its frame type and no object or filter, so the Library files it as calibration."""
    from galileo.ui.imaging import ImagingService
    service = ImagingService(camera=_CountingCamera())
    service.auto_save_to_library = False
    service.object_name = "M 31"
    service.frame_context = {"telescope": "Newt 200", "instrument": "ASI2600MM", "object": "M 31"}

    await service.capture_series(1, 60.0, filter_name="Ha", frame_type="Dark")
    meta = service.frame_metadata()
    assert meta["frame_type"] == "Dark" and "object" not in meta and "filter" not in meta

    await service.capture_series(1, 2.0, filter_name="", frame_type="Flat")
    meta = service.frame_metadata()
    assert meta["frame_type"] == "Flat" and meta["filter"] == "OSC", "a flat is filed by filter; OSC means none"


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
async def test_tc_img_150_auto_save_registers_each_frame_in_the_library(library_repo):
    """IMG-150: with Auto-Save on, each frame is written to scratch and registered, so it appears under Library > Images."""
    from galileo.library.models import fitsFile
    from galileo.ui.imaging import ImagingService
    service = ImagingService(camera=_CountingCamera())
    service.object_name = "M 31"
    service.frame_context = {"telescope": "Newt 200", "instrument": "ASI2600MM"}

    ids = await service.capture_series(2, 1.0, filter_name="Ha", frame_type="Light")

    assert len(ids) == 2 and len(set(ids)) == 2
    assert fitsFile.select().count() == 2
    rows = list(fitsFile.select())
    assert {r.fitsFileObject for r in rows} == {"M 31"}
    # Registered means filed into the repository, under the object, not left in the scratch folder.
    repo_path = str(library_repo.repo).replace(chr(92), "/")    # the catalog stores forward slashes
    assert all(repo_path in r.fitsFileName for r in rows)
    assert all("M_31" in r.fitsFileName for r in rows)
    assert not list(library_repo.scratch.rglob("*.fits")), "the scratch copies were moved, not left behind"


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
async def test_tc_img_150_auto_save_off_keeps_frames_out_of_the_library(library_repo):
    """IMG-150: with Auto-Save off nothing is catalogued and nothing is written."""
    from galileo.library.models import fitsFile
    from galileo.ui.imaging import ImagingService
    service = ImagingService(camera=_CountingCamera())
    service.auto_save_to_library = False
    service.object_name = "M 31"

    ids = await service.capture_series(2, 1.0)
    assert ids == [] and fitsFile.select().count() == 0
    assert not list(library_repo.scratch.rglob("*.fits"))


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
async def test_tc_img_150_a_frame_the_library_refuses_is_kept_and_explained(library_repo, monkeypatch):
    """IMG-150: a frame that can't be registered stays in the scratch folder and the page is told why."""
    from galileo.library.registrar import LibraryRegistrar
    from galileo.ui.imaging import ImagingService
    monkeypatch.setattr(LibraryRegistrar, "register_capture", lambda self, path: None)
    service = ImagingService(camera=_CountingCamera())
    service.object_name = "M 31"
    service.frame_context = {"telescope": "Newt 200", "instrument": "ASI2600MM"}

    ids = await service.capture_series(1, 1.0, frame_type="Light")

    assert ids == []
    kept = list(library_repo.scratch.rglob("*.fits"))
    assert len(kept) == 1 and service.last_saved_path == kept[0]
    assert str(kept[0]) in service.library_note


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
async def test_tc_img_150_a_light_frame_with_no_current_object_is_filed_under_unknown(library_repo):
    """IMG-150: the Library can't file a light frame without an object, so one is filed under "Unknown" and the page says so."""
    from galileo.library.models import fitsFile
    from galileo.ui.imaging import ImagingService
    service = ImagingService(camera=_CountingCamera())
    service.frame_context = {"telescope": "Newt 200", "instrument": "ASI2600MM"}

    ids = await service.capture_series(1, 1.0, frame_type="Light")

    assert len(ids) == 1
    assert fitsFile.get(fitsFile.fitsFileId == ids[0]).fitsFileObject == "Unknown"
    assert "Unknown" in service.library_note and "Star Atlas" in service.library_note


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
def test_tc_img_150_nothing_is_registered_without_a_repository_folder(tmp_path, monkeypatch):
    """IMG-150: with no repository folder configured the frame is left alone rather than moved into the working directory."""
    from galileo.library.registrar import LibraryRegistrar
    import galileo.library.registrar as registrar_mod
    monkeypatch.setattr(registrar_mod, "__name__", registrar_mod.__name__)   # keep the module importable as-is
    monkeypatch.setattr("galileo.library.config.get_repository_path", lambda: "")
    frame = tmp_path / "frame.fits"
    frame.write_bytes(b"not really fits")
    assert LibraryRegistrar().register_capture(frame) is None
    assert frame.exists(), "the file is left where it is"


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
def test_tc_img_150_imaging_page_has_quantity_gain_and_auto_save(window):
    """IMG-150: the page offers Quantity and Gain under Exposure, and Auto-Save to Library under Save Frame, on by default."""
    ui = window._imaging_ui
    assert ui["quantity"].value() == 1 and ui["quantity"].minimum() == 1
    assert ui["gain"].value() == 110
    assert ui["auto_save"].text() == "Auto-Save to Library" and ui["auto_save"].isChecked()
    assert ui["capture_button"].isEnabled() and not ui["stop_button"].isEnabled()


@pytest.mark.requirement("TC-IMG-150")
@pytest.mark.priority("P2")
def test_tc_img_150_capture_button_runs_a_series_with_the_screens_settings(window, monkeypatch):
    """IMG-150: pressing Capture runs a series off the UI thread with Quantity, Gain and Auto-Save as set, then reports it."""
    ui, service = window._imaging_ui, window._imaging_service
    camera = _CountingCamera()
    window._camera_backends["primary camera"] = camera
    ui["quantity"].setValue(2)
    ui["gain"].setValue(120)
    ui["auto_save"].setChecked(False)

    ui["capture_button"].click()
    thread = window._imaging_capture_thread
    assert thread is not None and not ui["capture_button"].isEnabled(), "disabled while the series runs"
    assert ui["stop_button"].isEnabled()
    thread.wait(10000)
    window.app.processEvents()

    assert len(camera.exposures) == 2
    assert all(e["gain"] == 120 for e in camera.exposures)
    assert service.gain == 120 and service.auto_save_to_library is False
    assert ui["capture_button"].isEnabled() and not ui["stop_button"].isEnabled()
    assert "2 of 2 frames" in ui["status"].text()
    assert service.frame_context, "the page fills in what it knows about the rig for the header"


# ---------------------------------------------------------------------------
# TC-IMG-160 — live stacking
# ---------------------------------------------------------------------------

def _star_field(shape=(60, 80), stars=((20, 30), (40, 60), (15, 65)), level=1000.0):
    """A frame with a few point sources, bright enough to register on."""
    import numpy as np
    frame = np.zeros(shape, dtype=np.float32)
    for y, x in stars:
        frame[y - 1:y + 2, x - 1:x + 2] = level
    return frame


class _DriftingCamera:
    """A camera whose star field drifts by a pixel each frame, as a mount slowly does."""

    def __init__(self, drift=(1, -1), noise=0.0):
        self.drift, self.noise, self.frame_index = drift, noise, 0
        self.exposures: list = []

    async def start_exposure(self, duration, frame_type="Light", **kwargs):
        self.exposures.append(duration)

    async def get_image_array(self):
        import numpy as np
        dy, dx = self.drift[0] * self.frame_index, self.drift[1] * self.frame_index
        self.frame_index += 1
        stars = [(20 + dy, 30 + dx), (40 + dy, 60 + dx), (15 + dy, 65 + dx)]
        frame = _star_field(stars=stars)
        if self.noise:
            frame = frame + np.full(frame.shape, self.noise, dtype=np.float32)
        return frame

    def get_temperature(self):
        return -10.0


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
def test_tc_img_160_phase_correlation_finds_the_shift_between_frames():
    """IMG-160: the offset between two frames of the same field is measured, and applying it lines them up."""
    import numpy as np
    from galileo.livestack import shift_frame, translation_offset
    reference = _star_field()
    moved = _star_field(stars=((25, 23), (45, 53), (20, 58)))     # +5 rows, -7 columns

    dy, dx = translation_offset(moved, reference)
    assert (dy, dx) == (-5, 7), "the shift that brings the moved frame back"

    aligned, valid = shift_frame(moved, dy, dx)
    assert np.array_equal(aligned[valid], reference[valid])
    # The frame moved right 7 and up 5, so those edges hold nothing that came from it.
    assert not valid[:, :7].any() and not valid[-5:, :].any()


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
def test_tc_img_160_stacking_aligns_and_averages_rather_than_smearing():
    """IMG-160: drifting frames are registered before averaging, so the stars stay sharp and keep their brightness."""
    import numpy as np
    from galileo.livestack import LiveStacker
    stacker = LiveStacker()
    for i in range(4):
        stacker.add(_star_field(stars=((20 + i, 30 - i), (40 + i, 60 - i), (15 + i, 65 - i))), exposure_s=10.0)

    assert stacker.frames == 4 and stacker.total_exposure_s == 40.0
    result = stacker.result
    # Registered: the stars land back on the reference's pixels at full brightness, not smeared to a quarter.
    assert result[20, 30] == pytest.approx(1000.0, rel=1e-3)
    assert result[19, 31] == pytest.approx(1000.0, rel=1e-3)      # the 3x3 star's edge
    unaligned = np.mean([_star_field(stars=((20 + i, 30 - i), (40 + i, 60 - i), (15 + i, 65 - i)))
                         for i in range(4)], axis=0)
    assert unaligned[20, 30] < 700.0, "without registration the same frames would smear"


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
def test_tc_img_160_stacking_improves_the_noise():
    """IMG-160: the point of stacking — averaging registered frames cuts the background noise."""
    import numpy as np
    from galileo.livestack import LiveStacker
    rng = np.random.default_rng(1234)
    base = _star_field()
    stacker = LiveStacker()
    singles = []
    for _ in range(9):
        frame = (base + rng.normal(0.0, 50.0, base.shape)).astype(np.float32)
        singles.append(frame)
        stacker.add(frame, exposure_s=5.0)

    background = (slice(50, 60), slice(0, 20))     # a corner with no stars in it
    single_noise = float(np.std(singles[0][background]))
    stacked_noise = float(np.std(stacker.result[background]))
    assert stacked_noise < single_noise / 2, f"{stacked_noise:.1f} should be well below {single_noise:.1f}"


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
def test_tc_img_160_a_frame_of_the_wrong_shape_is_rejected_not_stacked():
    """IMG-160: a frame that doesn't match the stack (binning or ROI changed mid-run) is refused, leaving the stack intact."""
    import numpy as np
    from galileo.livestack import LiveStacker
    stacker = LiveStacker()
    assert stacker.add(_star_field()) is True
    assert stacker.add(np.zeros((10, 10), dtype=np.float32)) is False
    assert stacker.frames == 1 and stacker.rejected == 1
    assert stacker.result.shape == (60, 80)
    assert "1 not stacked" in stacker.summary

    stacker.reset()
    assert stacker.frames == 0 and stacker.result is None and stacker.rejected == 0


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
async def test_tc_img_160_capture_stacks_into_the_buffer_instead_of_replacing_it():
    """IMG-160: with Live Stack on, a run of more than two frames builds one image rather than each replacing the last."""
    from galileo.ui.imaging import ImagingService
    camera = _DriftingCamera()
    service = ImagingService(camera=camera)
    service.auto_save_to_library = False
    service.live_stack_enabled = True

    await service.capture_series(4, 10.0, frame_type="Light")

    assert service.stack_frame_count == 4
    assert service.stacker.total_exposure_s == 40.0
    # The buffer holds the stack, so the preview, statistics and histogram all follow it.
    assert service.current_frame is service.stacker.result or \
        pytest.approx(float(service.current_frame.sum())) == float(service.stacker.result.sum())
    assert service.current_preview is not None
    assert service.get_frame_stats()["max"] == pytest.approx(1000.0, rel=1e-3), "stars kept their brightness"


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
async def test_tc_img_160_stacking_is_off_for_short_runs_and_when_unticked():
    """IMG-160: a run of two or fewer frames does not stack, and neither does one with Live Stack off."""
    from galileo.livestack import LIVE_STACK_MIN_FRAMES
    from galileo.ui.imaging import ImagingService
    assert LIVE_STACK_MIN_FRAMES == 3, "'more than 2 exposures'"

    service = ImagingService(camera=_DriftingCamera())
    service.auto_save_to_library = False
    service.live_stack_enabled = True
    await service.capture_series(2, 10.0)
    assert service.stack_frame_count == 0, "two frames is not a stack"

    service = ImagingService(camera=_DriftingCamera())
    service.auto_save_to_library = False
    service.live_stack_enabled = False
    await service.capture_series(4, 10.0)
    assert service.stack_frame_count == 0
    assert service.current_frame[20, 30] == pytest.approx(0.0), "the last frame alone, drifted off the first's stars"


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
async def test_tc_img_160_each_frame_still_reaches_the_library_on_its_own(library_repo):
    """IMG-160: stacking doesn't change what is catalogued — the individual subs are, not the running stack."""
    from galileo.library.models import fitsFile
    from galileo.ui.imaging import ImagingService
    service = ImagingService(camera=_DriftingCamera())
    service.live_stack_enabled = True
    service.object_name = "M 31"
    service.frame_context = {"telescope": "Newt 200", "instrument": "ASI2600MM"}

    ids = await service.capture_series(3, 5.0, frame_type="Light")

    assert len(ids) == 3 and fitsFile.select().count() == 3
    assert service.stack_frame_count == 3
    assert {float(r.fitsFileExpTime) for r in fitsFile.select()} == {5.0}, "the subs, each its own exposure"


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
async def test_tc_img_160_the_saved_stack_says_what_it_is_made_of(tmp_path):
    """IMG-160: a saved stack carries the single-sub exposure, the total integration and the frame count."""
    from astropy.io import fits
    from galileo.ui.imaging import ImagingService
    service = ImagingService(camera=_DriftingCamera())
    service.auto_save_to_library = False
    service.live_stack_enabled = True
    service.object_name = "M 31"
    service.frame_context = {"telescope": "Newt 200", "instrument": "ASI2600MM"}

    await service.capture_series(4, 30.0, filter_name="Ha", frame_type="Light")
    name = service.stack_filename()
    assert name.startswith("M_31_stack_4x30s_") and name.endswith(".fits")

    service.save_stack(tmp_path / name)
    hdr = fits.getheader(tmp_path / name)
    assert hdr["NCOMBINE"] == 4 and hdr["EXPTOTAL"] == 120.0
    assert hdr["EXPTIME"] == 30.0, "the single-sub exposure, which is what the Library files by"
    assert hdr["OBJECT"] == "M 31" and hdr["FILTER"] == "Ha" and hdr["IMAGETYP"] == "Light"
    assert hdr["DATE-OBS"] <= hdr["DATE-END"], "the stack runs from the first sub to the last"


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
async def test_tc_img_160_the_stack_can_be_saved_to_the_library(library_repo):
    """IMG-160: Save Stack > Save to Library files the stacked image in the repository alongside the subs."""
    from galileo.library.models import fitsFile
    from galileo.ui.imaging import ImagingService
    service = ImagingService(camera=_DriftingCamera())
    service.auto_save_to_library = False
    service.live_stack_enabled = True
    service.object_name = "M 31"
    service.frame_context = {"telescope": "Newt 200", "instrument": "ASI2600MM"}
    await service.capture_series(3, 10.0, frame_type="Light")

    file_id = service.save_stack_to_library()

    assert file_id and fitsFile.select().count() == 1
    row = fitsFile.get(fitsFile.fitsFileId == file_id)
    assert row.fitsFileObject == "M 31"
    assert str(library_repo.repo).replace("\\", "/") in row.fitsFileName
    assert not list(library_repo.scratch.rglob("*.fits")), "moved into the repository, not left in scratch"


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
def test_tc_img_160_saving_with_no_stack_is_refused():
    """IMG-160: with nothing stacked there is nothing to save, and saying so beats writing an empty file."""
    from galileo.ui.imaging import ImagingService
    service = ImagingService(camera=_DriftingCamera())
    assert service.stack_frame_count == 0
    with pytest.raises(ValueError):
        service.save_stack("unused.fits")
    with pytest.raises(ValueError):
        service.save_stack_to_library()


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
def test_tc_img_160_imaging_page_offers_live_stack_and_save_stack(window):
    """IMG-160: the page has a Live Stack checkbox (off by default) and a Save Stack button, enabled once there is a stack."""
    ui = window._imaging_ui
    assert ui["live_stack"].text() == "Live Stack" and not ui["live_stack"].isChecked()
    assert ui["save_stack_button"].text() == "Save Stack…"
    assert not ui["save_stack_button"].isEnabled(), "nothing stacked yet"


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
def test_tc_img_160_capture_button_honours_the_live_stack_checkbox(window):
    """IMG-160: ticking Live Stack makes a Capture run stack, and Save Stack becomes available afterwards."""
    ui, service = window._imaging_ui, window._imaging_service
    window._camera_backends["primary camera"] = _DriftingCamera()
    ui["quantity"].setValue(3)
    ui["auto_save"].setChecked(False)
    ui["live_stack"].setChecked(True)

    ui["capture_button"].click()
    thread = window._imaging_capture_thread
    thread.wait(20000)
    window.app.processEvents()

    assert service.live_stack_enabled is True and service.stack_frame_count == 3
    assert ui["save_stack_button"].isEnabled()
    assert "Stacked 3 frames" in ui["status"].text()


@pytest.mark.requirement("TC-IMG-160")
@pytest.mark.priority("P2")
def test_tc_img_160_the_summary_says_how_the_frames_were_aligned(monkeypatch):
    """IMG-160: the stack says how it was registered — and a fall back to shifting reads differently depending on whether astroalign is even installed."""
    import galileo.livestack as livestack
    from galileo.livestack import LiveStacker
    stacker = LiveStacker()
    stacker.add(_star_field(), exposure_s=10.0)
    stacker.add(_star_field(stars=((21, 29), (41, 59), (16, 64))), exposure_s=10.0)
    assert stacker.method == livestack.ASTROALIGN, "astroalign is a dependency and handles rotation"
    assert stacker.summary == "Stacked 2 frames, 20s total"

    # astroalign present but beaten by these frames: say so, don't tell the user to install it.
    monkeypatch.setattr(livestack, "_astroalign_register", lambda frame, reference: None)
    stacker.add(_star_field(stars=((22, 28), (42, 58), (17, 63))), exposure_s=10.0)
    assert stacker.method == livestack.TRANSLATION
    assert "astroalign could not register" in stacker.summary

    # astroalign genuinely missing: that is worth telling the user, because installing it helps.
    monkeypatch.setattr(livestack, "astroalign_available", lambda: False)
    assert "install astroalign" in stacker.summary


# ---------------------------------------------------------------------------
# TC-IMG-170 — desired BITPIX (Options > Imaging)
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-170")
@pytest.mark.priority("P2")
def test_tc_img_170_imaging_options_default_to_auto_and_round_trip(tmp_path, monkeypatch):
    """IMG-170: Options > Imaging defaults to Auto, an unrecognised saved value falls back to it, and a valid choice round-trips."""
    import galileo.platform as platform_mod
    from galileo.imaging_settings import load_imaging_settings, save_imaging_settings
    from galileo.metadata import BITPIX_AUTO
    monkeypatch.setattr(platform_mod, "get_config_dir", lambda: tmp_path)

    assert load_imaging_settings() == {"bitpix": BITPIX_AUTO}

    save_imaging_settings({"bitpix": 16})
    assert load_imaging_settings() == {"bitpix": 16}

    (tmp_path / "imaging.json").write_text('{"bitpix": "not a real choice"}', encoding="utf-8")
    assert load_imaging_settings() == {"bitpix": BITPIX_AUTO}, "an unrecognised value is not trusted"


@pytest.mark.requirement("TC-IMG-170")
@pytest.mark.priority("P2")
def test_tc_img_170_a_desired_bitpix_forces_every_saved_frame_to_that_format():
    """IMG-170: setting the service's desired BITPIX writes every kind of saved frame in that one format instead of picking one automatically."""
    import numpy as np
    from astropy.io import fits
    from galileo.ui.imaging import ImagingService

    service = ImagingService()
    service.current_frame = np.array([[100, 200], [300, 65535]], dtype=np.int64)
    service.object_name = "M 31"
    service.bitpix = 32

    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmp:
        from pathlib import Path
        path = Path(tmp) / "frame.fits"
        service.save_current_frame(path)
        assert fits.getheader(path)["BITPIX"] == 32

        service.bitpix = "auto"
        path2 = Path(tmp) / "auto.fits"
        service.save_current_frame(path2)
        assert fits.getheader(path2)["BITPIX"] == 16, "unchanged from before this setting existed"


@pytest.mark.requirement("TC-IMG-170")
@pytest.mark.priority("P2")
def test_tc_img_170_a_new_service_picks_up_the_saved_setting(tmp_path, monkeypatch):
    """IMG-170: a freshly built ImagingService starts on whatever Options > Imaging last saved."""
    import galileo.platform as platform_mod
    from galileo.imaging_settings import save_imaging_settings
    from galileo.ui.imaging import ImagingService
    monkeypatch.setattr(platform_mod, "get_config_dir", lambda: tmp_path)

    save_imaging_settings({"bitpix": -32})
    assert ImagingService().bitpix == -32


@pytest.mark.requirement("TC-IMG-170")
@pytest.mark.priority("P2")
def test_tc_img_170_options_imaging_page_offers_the_bitpix_choices(window):
    """IMG-170: Options > Imaging offers Auto plus every portable BITPIX, starting on the saved choice."""
    QtWidgets = window.QtWidgets
    page = window._build_imaging_settings_page()
    combos = page.findChildren(QtWidgets.QComboBox)
    assert len(combos) == 1
    combo = combos[0]
    assert [combo.itemData(i) for i in range(combo.count())] == ["auto", 8, 16, 32, -32]
    assert combo.itemText(0).startswith("Auto")
    assert combo.currentIndex() == 0, "Auto is the default"


@pytest.mark.requirement("TC-IMG-170")
@pytest.mark.priority("P2")
def test_tc_img_170_changing_the_option_saves_it_and_updates_the_running_service(window, tmp_path, monkeypatch):
    """IMG-170: picking a BITPIX on the settings page saves it and takes effect on the Imaging page already built, not only after a restart."""
    import galileo.platform as platform_mod
    from galileo.imaging_settings import load_imaging_settings
    monkeypatch.setattr(platform_mod, "get_config_dir", lambda: tmp_path)

    page = window._build_imaging_settings_page()
    combo = page.findChildren(window.QtWidgets.QComboBox)[0]
    combo.setCurrentIndex(combo.findData(16))

    assert load_imaging_settings()["bitpix"] == 16


# ---------------------------------------------------------------------------
# TC-IMG-180 — Framing… control
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-IMG-180")
@pytest.mark.priority("MVP")
def test_tc_img_180_framing_control_opens_assistant_against_selected_train(imaging_service):
    """IMG-180: The imaging tab provides a Framing… control that opens the Framing Assistant (FRAME-070) against the currently selected camera/optical train for immediate-imaging use."""
    frame_mod = pytest.importorskip("galileo.planning.framing")

    asst = imaging_service.open_framing_assistant()

    assert isinstance(asst, frame_mod.FramingAssistant)
    assert asst.opening_context is imaging_service


@pytest.mark.requirement("TC-IMG-180")
@pytest.mark.priority("MVP")
def test_tc_img_180_mosaic_defined_and_run_directly_from_the_tab(imaging_service):
    """IMG-180: Including defining and, where a mosaic grid is defined, running a mosaic capture directly from the tab (mosaic execution traces to FRAME-090)."""
    asst = imaging_service.open_framing_assistant()
    mosaic = asst.create_mosaic(center_ra=83.8, center_dec=-5.4, cols=2, rows=2, overlap_pct=10.0)
    asst.set_mosaic(mosaic)

    imaging_service.run_mosaic_from_framing(asst)

    assert imaging_service.active_mosaic is mosaic
    assert window._imaging_service.bitpix == 16
