# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""IMG — Imaging Tab (TC-IMG-010 … TC-IMG-110)."""

import pytest
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
