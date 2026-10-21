# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SES — Sessions (formerly `SEQ`/`SEQ-ADV`; TC-SES-010 … TC-SES-360).

Three sub-ranges, mirroring SRS Sections 4.5/4.5a/4.6:
  - SES-010..090:  execution engine (`galileo.session_exec`; the run/pause/progress/error
                   tests live in `test_ses_exec.py`)
  - SES-100..230:  Sessions screen authoring/lifecycle (`galileo.ui.sessions`)
  - SES-300..360:  nested blocks, triggers, plugin blocks (`galileo.session_exec`, `galileo.ui.sessions`)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def sessions_screen(minimal_profile):
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    profile_mod = pytest.importorskip("galileo.equipment.profiles")
    profile = profile_mod.EquipmentProfile.from_dict(minimal_profile)
    screen = ui_mod.SessionsScreen(profile=profile)
    return screen


# ===========================================================================
# SES-010..090 — Execution engine (galileo.session_exec)
#
# SES-030/040/050/080 are verified in test_ses_exec.py against the real executor.
# ===========================================================================

_NOT_BUILT = "not implemented: the retired galileo.sequencer engine was the only code for it"


@pytest.mark.requirement("TC-SES-010")
@pytest.mark.priority("MVP")
def test_tc_ses_010_define_session_as_ordered_action_blocks():
    """SES-010: Allow definition of a session as an ordered list of action blocks, each contributing its own parameters (e.g. an Image block's exposure count, time, filter, binning)."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    region = ui_mod.SessionRegion(name="M42")
    region.blocks.append(ui_mod.TargetBlock(name="M42", ra_deg=83.8221, dec_deg=-5.3911))
    region.blocks.append(ui_mod.ImageBlock(filter="Ha", exposure=300.0, count=20, binning=1))
    region.blocks.append(ui_mod.ImageBlock(filter="OIII", exposure=300.0, count=20, binning=1))

    assert [type(b).__name__ for b in region.blocks] == ["TargetBlock", "ImageBlock", "ImageBlock"]
    assert region.blocks[1].filter == "Ha" and region.blocks[2].count == 20


@pytest.mark.requirement("TC-SES-020")
@pytest.mark.priority("MVP")
def test_tc_ses_020_dynamic_file_naming_macros():
    """SES-020: Support dynamic file-naming macros (target, filter, date, frame number, frame type) applied to saved files."""
    pytest.skip(_NOT_BUILT)


@pytest.mark.requirement("TC-SES-060")
@pytest.mark.priority("MVP")
def test_tc_ses_060_persist_session_for_reuse(sessions_screen):
    """SES-060: Persist a session definition for reuse (traces to the Save control, SES-110) — the Save/template round-trips are verified in TC-SES-110/180/190."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    assert hasattr(ui_mod.SessionRegion(name="x"), "save")


@pytest.mark.requirement("TC-SES-070")
@pytest.mark.priority("MVP")
def test_tc_ses_070_per_frame_session_metadata():
    """SES-070: Record, per captured frame, sufficient metadata to reconstruct which session and block produced it (traces to META)."""
    pytest.skip(_NOT_BUILT)


@pytest.mark.requirement("TC-SES-090")
@pytest.mark.priority("P3")
def test_tc_ses_090_parallel_multi_train_capture():
    """SES-090: Support running capture sessions in parallel across two or more optical trains sharing the same mount, using a lead/follower model."""
    pytest.skip("multi-train capture was never built")


# ===========================================================================
# SES-100..230 — Sessions screen authoring/lifecycle (galileo.ui.sessions)
# ===========================================================================

# ---------------------------------------------------------------------------
# TC-SES-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-100")
@pytest.mark.priority("MVP")
def test_tc_ses_100_sessions_scoped_per_pier(sessions_screen):
    """SES-100: Scope sessions per Pier — the Sessions screen shows only the currently-selected Pier's own sessions, and switching the active Pier switches the whole set of session regions shown."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    sessions_screen.add_session(ui_mod.SessionRegion(name="Pier-1 Session A"), pier_name="Pier-1")
    sessions_screen.add_session(ui_mod.SessionRegion(name="Pier-2 Session B"), pier_name="Pier-2")

    sessions_screen.set_active_pier("Pier-1")
    assert [r.name for r in sessions_screen.visible_sessions] == ["Pier-1 Session A"]

    sessions_screen.set_active_pier("Pier-2")
    assert [r.name for r in sessions_screen.visible_sessions] == ["Pier-2 Session B"]


# ---------------------------------------------------------------------------
# TC-SES-110
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-110")
@pytest.mark.priority("MVP")
def test_tc_ses_110_concurrent_session_regions_with_controls():
    """SES-110: Display multiple concurrent sessions as independently bounded, scrollable regions, each with its own Save, Save as Template, Load from Template, Schedule, and Delete controls."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = ui_mod.SessionRegion(name="M42 Session")
    for control in ("save", "save_as_template", "load_from_template", "schedule", "delete"):
        assert hasattr(region, control), f"SessionRegion missing control: {control}"


# ---------------------------------------------------------------------------
# TC-SES-120
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-120")
@pytest.mark.priority("MVP")
def test_tc_ses_120_action_palette_drag_insert_reorder():
    """SES-120: Provide a single right-hand action palette from which blocks are dragged into a session region, insertable before/after/between existing blocks, and freely reorderable afterward."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = ui_mod.SessionRegion(name="Test")
    target_block = ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4)
    image_block = ui_mod.ImageBlock(exposure=300.0, count=10, filter="Ha")
    autofocus_block = ui_mod.AutofocusBlock()

    region.insert_block(target_block)
    region.insert_block(image_block)
    region.insert_block(autofocus_block, before=image_block)

    assert region.blocks == [target_block, autofocus_block, image_block]

    region.reorder_block(autofocus_block, index=2)
    assert region.blocks == [target_block, image_block, autofocus_block]


def test_remove_block_deletes_it_and_refuses_on_a_locked_region():
    """A block can be deleted from its region directly (e.g. dragged outside
    the session panel) — refused, like every other authoring mutation, once
    the region is scheduled/locked."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = ui_mod.SessionRegion(name="Test")
    target_block = ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4)
    region.insert_block(target_block)
    region.remove_block(target_block)
    assert region.blocks == []

    region.insert_block(target_block)
    region.is_scheduled = True
    with pytest.raises(ui_mod.RegionLockedError):
        region.remove_block(target_block)
    assert region.blocks == [target_block]   # not removed


# ---------------------------------------------------------------------------
# TC-SES-130
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-130")
@pytest.mark.priority("MVP")
def test_tc_ses_130_minimum_action_block_palette():
    """SES-130: Minimum action-block palette: Target, Image (w/ Framing… control), Filter Change, Cool/Warm Camera, Autofocus, Plate Solve, Guide Start/Stop, Dither, Flat Capture, Park/Unpark Mount."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    expected_blocks = [
        "TargetBlock",
        "ImageBlock",
        "FilterChangeBlock",
        "CoolCameraBlock",
        "WarmCameraBlock",
        "AutofocusBlock",
        "PlateSolveBlock",
        "GuideStartBlock",
        "GuideStopBlock",
        "DitherBlock",
        "FlatCaptureBlock",
        "ParkMountBlock",
        "UnparkMountBlock",
    ]
    for cls_name in expected_blocks:
        assert hasattr(ui_mod, cls_name), f"Missing action block class: {cls_name}"

    assert hasattr(ui_mod.ImageBlock, "open_framing_assistant"), \
        "Image block must expose a Framing… control (traces to FRAME-070)"


# ---------------------------------------------------------------------------
# TC-SES-140
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-140")
@pytest.mark.priority("P2")
def test_tc_ses_140_additional_action_blocks():
    """SES-140: Provide, at minimum, the following additional action blocks: Meridian Flip and Dome Open/Close/Sync."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    for cls_name in ("MeridianFlipBlock", "DomeOpenBlock", "DomeCloseBlock", "DomeSyncBlock"):
        assert hasattr(ui_mod, cls_name), f"Missing action block class: {cls_name}"


# ---------------------------------------------------------------------------
# TC-SES-150
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-150")
@pytest.mark.priority("P3")
async def test_tc_ses_150_notification_block_uses_observatory_channels():
    """SES-150: Provide a Notification action block that sends an alert via the owning Observatory's configured contact channel(s) (traces to NOTIF-010, OBS-090)."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    notif_block = ui_mod.NotificationBlock(message="Meridian flip complete")
    notify_service = MagicMock()
    notify_service.emit = AsyncMock()

    context = MagicMock(notify_service=notify_service, observatory=MagicMock(name="Backyard"))
    await notif_block.execute(context)

    notify_service.emit.assert_called_once()


# ---------------------------------------------------------------------------
# TC-SES-160
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-160")
@pytest.mark.priority("MVP")
def test_tc_ses_160_auto_create_session_on_target_selection(sessions_screen):
    """SES-160: Create a new session pre-populated with a Target: <name> block when a target is selected on the Targets/Sky Atlas screen; provide an "Add Session" context-menu item for manual authoring."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = sessions_screen.create_session_for_target(name="M31", ra_deg=10.68, dec_deg=41.27)
    assert len(region.blocks) == 1
    assert isinstance(region.blocks[0], ui_mod.TargetBlock)
    assert region.blocks[0].name == "M31"

    empty_region = sessions_screen.add_session_from_context_menu()
    assert empty_region.blocks == []


# ---------------------------------------------------------------------------
# TC-SES-170
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-170")
@pytest.mark.priority("MVP")
def test_tc_ses_170_block_ordering_integrity_enforced():
    """SES-170: Enforce block-ordering integrity rules (e.g. a Plate Solve block requires a preceding Target block) at insertion time and/or session-run time."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = ui_mod.SessionRegion(name="Test")
    solve_block = ui_mod.PlateSolveBlock()

    with pytest.raises(ui_mod.BlockOrderError):
        region.insert_block(solve_block)

    region.insert_block(ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))
    region.insert_block(solve_block)  # now valid, a Target block precedes it
    assert solve_block in region.blocks


# ---------------------------------------------------------------------------
# TC-SES-180
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-180")
@pytest.mark.priority("P2")
def test_tc_ses_180_save_as_template_generalizes_target(tmp_path):
    """SES-180: Allow a session's blocks to be saved to a reusable template, storing its Target block as a generic placeholder rather than a specific target."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    from galileo.library.database import db, init_db
    init_db(tmp_path / "ses180.db")
    try:
        region = ui_mod.SessionRegion(name="M42 Session")
        region.insert_block(ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))
        region.insert_block(ui_mod.ImageBlock(exposure=300.0, count=10, filter="Ha"))

        region.save_as_template("HaSession")
        assert "HaSession" in ui_mod.SessionTemplate.list_names()

        template = ui_mod.SessionTemplate.load("HaSession")
        assert template.blocks[0].is_placeholder_target
        assert len(template.blocks) == 2
    finally:
        db.close()


@pytest.mark.requirement("TC-SES-180")
@pytest.mark.priority("P2")
def test_tc_ses_180_add_session_from_template(tmp_path):
    """SES-180: A saved template can seed a brand-new session holding all its blocks."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    from galileo.library.database import db, init_db
    init_db(tmp_path / "ses180b.db")
    try:
        src = ui_mod.SessionRegion(name="M42 Session")
        src.insert_block(ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))
        src.insert_block(ui_mod.ImageBlock(exposure=300.0, count=10, filter="Ha"))
        src.save_as_template("HaSession")

        screen = ui_mod.SessionsScreen()
        region = screen.add_session_from_template("HaSession")
        assert region in screen.visible_sessions
        assert region.name == "HaSession Session"
        assert len(region.blocks) == 2
        assert region.blocks[0].is_placeholder_target
    finally:
        db.close()


# ---------------------------------------------------------------------------
# TC-SES-190
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-190")
@pytest.mark.priority("P2")
def test_tc_ses_190_load_from_template_substitutes_target(tmp_path):
    """SES-190: When Load from Template is used on a region that already has a concrete Target block, substitute the template's placeholder with that Target block and append the template's remaining blocks. Unavailable with no Target block yet."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    from galileo.library.database import db, init_db
    init_db(tmp_path / "ses190.db")
    try:
        template_region = ui_mod.SessionRegion(name="Template Source")
        template_region.insert_block(ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))
        template_region.insert_block(ui_mod.ImageBlock(exposure=300.0, count=10, filter="Ha"))
        template_region.save_as_template("HaSession")

        # No Target block yet -> unavailable.
        empty_region = ui_mod.SessionRegion(name="Empty")
        assert empty_region.can_load_from_template() is False
        with pytest.raises(ui_mod.BlockOrderError):
            empty_region.load_from_template("HaSession")

        # Concrete Target block present -> substitutes the placeholder, appends the rest.
        m31_region = ui_mod.SessionRegion(name="M31")
        m31_region.insert_block(ui_mod.TargetBlock(name="M31", ra_deg=10.68, dec_deg=41.27))
        assert m31_region.can_load_from_template() is True
        m31_region.load_from_template("HaSession")

        assert len(m31_region.blocks) == 2
        assert m31_region.blocks[0].name == "M31"  # existing target preserved, not overwritten
        assert isinstance(m31_region.blocks[1], ui_mod.ImageBlock)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# TC-SES-200
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-200")
@pytest.mark.priority("MVP")
def test_tc_ses_200_schedule_control_is_the_only_side_effect():
    """SES-200: Submit a session to the Scheduler only when its region's Schedule control is used; authoring a session, however fully built out, has no other side effect — it neither runs nor queues until Schedule is used."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    pytest.importorskip("galileo.scheduler")

    scheduler = MagicMock()
    scheduler.add_job = MagicMock()

    region = ui_mod.SessionRegion(name="M42 Session", scheduler=scheduler)
    region.insert_block(ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))
    region.insert_block(ui_mod.ImageBlock(exposure=300.0, count=10, filter="Ha"))

    scheduler.add_job.assert_not_called()  # authoring alone: no side effect

    region.schedule()
    scheduler.add_job.assert_called_once()


# ---------------------------------------------------------------------------
# TC-SES-210
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-210")
@pytest.mark.priority("MVP")
def test_tc_ses_210_scheduling_locks_region_and_swaps_control():
    """SES-210: Once scheduled, a region becomes read-only and its boundary renders distinctly (e.g. red); its Schedule control becomes Deschedule, which withdraws the job from SCHED and restores the region's normal, editable state."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    scheduler = MagicMock()
    scheduler.add_job = MagicMock()
    scheduler.remove_job = MagicMock()

    region = ui_mod.SessionRegion(name="M42 Session", scheduler=scheduler)
    region.insert_block(ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))

    assert region.is_editable is True
    assert region.is_scheduled is False

    region.schedule()
    assert region.is_editable is False
    assert region.is_scheduled is True
    assert region.boundary_style == "red"

    with pytest.raises(ui_mod.RegionLockedError):
        region.insert_block(ui_mod.AutofocusBlock())

    region.deschedule()
    scheduler.remove_job.assert_called_once()
    assert region.is_editable is True
    assert region.is_scheduled is False
    assert region.boundary_style != "red"


@pytest.mark.requirement("TC-SES-210")
@pytest.mark.priority("MVP")
async def test_tc_ses_210_completed_job_deletes_the_session_not_deschedules_it(sessions_screen):
    """SES-210: a job completing successfully deletes its session outright — unlike
    Deschedule (withdrawn manually), a completed session has nothing left to author,
    so it isn't handed back as an editable draft."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    sched_mod = pytest.importorskip("galileo.scheduler")

    scheduler = sched_mod.ObservatoryScheduler()
    sessions_screen.set_active_pier("Pier-1")
    region = sessions_screen.add_session(
        ui_mod.SessionRegion(name="M42 Session", scheduler=scheduler), pier_name="Pier-1")
    region.insert_block(ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))

    region.schedule()
    assert region in sessions_screen.visible_sessions

    job = region._job
    job.total_required = 5
    await scheduler.record_frames_captured(job, count=5)
    scheduler.reap_completed_jobs()

    assert region not in sessions_screen.visible_sessions   # deleted, not desecheduled-and-kept


# ---------------------------------------------------------------------------
# TC-SES-220
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-220")
@pytest.mark.priority("MVP")
def test_tc_ses_220_delete_control_removes_region(sessions_screen):
    """SES-220: Allow a session region to be deleted via its Delete control."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = sessions_screen.add_session(ui_mod.SessionRegion(name="M42 Session"), pier_name="Pier-1")
    sessions_screen.set_active_pier("Pier-1")
    assert region in sessions_screen.visible_sessions

    region.delete()
    assert region not in sessions_screen.visible_sessions


# ---------------------------------------------------------------------------
# TC-SES-230
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-230")
@pytest.mark.priority("P2")
def test_tc_ses_230_image_block_mosaic_follows_frame_090_execution_model():
    """SES-230: Where an Image block's Framing… control defines a mosaic grid, the system shall follow the mosaic capture execution model (FRAME-090) for that block's execution instead of single-target capture."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    frame_mod = pytest.importorskip("galileo.planning.framing")

    image_block = ui_mod.ImageBlock(exposure=300.0, count=4, filter="L")
    mosaic = MagicMock(spec=frame_mod.Mosaic)
    image_block.set_mosaic(mosaic)

    assert image_block.has_mosaic is True
    assert image_block.execution_model() == "mosaic_round_robin"  # FRAME-090, not single-target


# ---------------------------------------------------------------------------
# TC-SES-130/230 — block colours: a fixed, theme-muted identity per block type
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-130")
@pytest.mark.priority("P2")
def test_block_colors_are_consistent_per_type_and_muted_by_theme():
    """Every block type keeps a stable colour identity across calls (a set of
    colours stored per block type), and that colour is a subtle tint of the
    current theme's own surface tone rather than an independently bright,
    saturated hue (colours were "too bright/glaring" before this)."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    from galileo.ui.theme import Theme, ThemeManager

    # Stable per-type identity: repeated calls return the identical colour.
    color_a1 = ui_mod._block_color("ImageBlock")
    color_a2 = ui_mod._block_color("ImageBlock")
    assert color_a1.getRgb() == color_a2.getRgb()

    # Distinct types get distinguishable colours.
    color_b = ui_mod._block_color("FilterChangeBlock")
    assert color_a1.getRgb() != color_b.getRgb()

    # Muted: nowhere near the old fully-saturated fromHsv(hue, 150, 210) tiles —
    # every block colour stays close to the theme's own surface_alt tone.
    from PySide6.QtGui import QColor
    mgr = ThemeManager()
    mgr.set_theme(Theme.DARK)
    surface = QColor(mgr.palette()["surface_alt"])
    for cls_name in ui_mod._BLOCK_HUES:
        color = ui_mod._block_color(cls_name)
        distance = abs(color.red() - surface.red()) + abs(color.green() - surface.green()) \
            + abs(color.blue() - surface.blue())
        assert distance < 200, f"{cls_name}'s colour strayed too far from the theme's surface tone"


@pytest.mark.requirement("TC-SES-130")
@pytest.mark.priority("P2")
def test_night_vision_theme_block_colors_never_carry_green_or_blue():
    """UI-011: night-vision (Theme.RED) block colours vary only in red-channel
    intensity — a block's colour identity must never introduce a stray
    green/blue pixel that would reset a dark-adapted eye."""
    from galileo.ui.theme import Theme, ThemeManager

    mgr = ThemeManager()
    mgr.set_theme(Theme.RED)
    for hue in (0, 60, 120, 180, 240, 300, 359):
        r, g, b = mgr.block_tint_rgb(hue)
        assert g == 0 and b == 0, f"hue {hue} leaked a non-red channel: ({r}, {g}, {b})"


# ---------------------------------------------------------------------------
# Right-click "Edit Parameters…" dialogs
# ---------------------------------------------------------------------------

@pytest.fixture
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_has_parameters_reflects_which_block_types_are_editable(qapp):
    """A block type with no dataclass fields (e.g. Dither, Park Mount) has no
    parameter dialog registered — its "Edit Parameters…" menu entry should stay
    disabled instead of opening an empty dialog."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    dlg_mod = pytest.importorskip("galileo.ui.session_block_dialogs")

    assert dlg_mod.has_parameters(ui_mod.ImageBlock) is True
    assert dlg_mod.has_parameters(ui_mod.TargetBlock) is True
    assert dlg_mod.has_parameters(ui_mod.DitherBlock) is False
    assert dlg_mod.has_parameters(ui_mod.ParkMountBlock) is False


def test_edit_parameters_dialog_updates_image_block_fields(qapp, monkeypatch):
    """Right-click > Edit Parameters… on an Image block exposes exposure, count,
    filter, binning, gain, offset and frame type — accepting the dialog writes
    them back onto the block instance."""
    from PySide6.QtWidgets import QComboBox, QDialog, QDoubleSpinBox, QSpinBox
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    dlg_mod = pytest.importorskip("galileo.ui.session_block_dialogs")

    region = ui_mod.SessionRegion(name="Test")
    block = ui_mod.ImageBlock()
    region.insert_block(block)

    def fake_exec(self):
        if self.windowTitle() != "Image Parameters":
            return QDialog.DialogCode.Rejected
        self.findChild(QDoubleSpinBox, "exposure_spin").setValue(120.0)
        self.findChild(QSpinBox, "count_spin").setValue(5)
        self.findChild(QComboBox, "filter_combo").setCurrentText("Ha")
        self.findChild(QComboBox, "binning_combo").setCurrentText("2x2")
        self.findChild(QComboBox, "frame_type_combo").setCurrentText("Dark")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    changed = dlg_mod.open_block_parameter_dialog(None, block, region, window=None)

    assert changed is True
    assert block.exposure == 120.0
    assert block.count == 5
    assert block.filter == "Ha"
    assert block.binning == 2
    assert block.frame_type == "Dark"


def test_edit_parameters_dialog_framing_button_builds_a_mosaic(qapp, monkeypatch):
    """The Image block's own Framing / Mosaic… control (SES-130, FRAME-070) is
    reachable from its parameter dialog and, once a grid bigger than 1×1 is
    set, stores a real Mosaic on the block — not just a logged no-op."""
    from PySide6.QtWidgets import QDialog, QPushButton, QSpinBox
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    dlg_mod = pytest.importorskip("galileo.ui.session_block_dialogs")

    region = ui_mod.SessionRegion(name="Test")
    region.insert_block(ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))
    block = ui_mod.ImageBlock()
    region.insert_block(block)

    def fake_exec(self):
        if self.windowTitle() == "Framing / Mosaic":
            self.findChild(QSpinBox, "cols_spin").setValue(3)
            self.findChild(QSpinBox, "rows_spin").setValue(2)
            return QDialog.DialogCode.Accepted
        if self.windowTitle() == "Image Parameters":
            self.findChild(QPushButton, "framing_btn").click()
            return QDialog.DialogCode.Accepted
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    changed = dlg_mod.open_block_parameter_dialog(None, block, region, window=None)

    assert changed is True
    assert block.has_mosaic is True
    assert block.mosaic.cols == 3 and block.mosaic.rows == 2
    assert block.execution_model() == "mosaic_round_robin"


def test_right_click_opens_parameter_dialog_directly_with_no_menu(qapp, monkeypatch):
    """Right-clicking a block opens its parameter dialog directly — no
    intermediate context menu. A block with no fields (Dither) does nothing;
    an Image block opens its dialog immediately and updates the block."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = ui_mod.SessionRegion(name="Test")
    region.insert_block(ui_mod.DitherBlock())
    region.insert_block(ui_mod.ImageBlock())
    palette = ui_mod._build_palette()
    block_list = ui_mod.BlockListWidget(region, palette, on_changed=lambda err: None)

    from PySide6.QtWidgets import QDialog

    dialog_opened = {"count": 0}

    def fail_if_opened(self):
        dialog_opened["count"] += 1
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fail_if_opened)
    block_list._on_right_click(block_list.visualItemRect(block_list.item(0)).center())
    assert dialog_opened["count"] == 0   # DitherBlock has no fields — nothing opens

    from PySide6.QtWidgets import QComboBox

    def fake_exec(self):
        self.findChild(QComboBox, "filter_combo").setCurrentText("L")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    block_list._on_right_click(block_list.visualItemRect(block_list.item(1)).center())
    assert region.blocks[1].filter == "L"
    assert block_list.item(1).text() == region.blocks[1].display_text


def test_right_click_does_nothing_on_a_scheduled_locked_session(qapp, monkeypatch):
    """A scheduled (locked) session region is read-only — right-clicking one of
    its blocks must not open a parameter dialog to edit it."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = ui_mod.SessionRegion(name="Test")
    region.insert_block(ui_mod.ImageBlock())
    region.is_scheduled = True
    palette = ui_mod._build_palette()
    block_list = ui_mod.BlockListWidget(region, palette, on_changed=lambda err: None)

    from PySide6.QtWidgets import QDialog

    dialog_opened = {"count": 0}

    def fail_if_opened(self):
        dialog_opened["count"] += 1
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fail_if_opened)
    block_list._on_right_click(block_list.visualItemRect(block_list.item(0)).center())
    assert dialog_opened["count"] == 0


@pytest.mark.requirement("TC-SES-170")
@pytest.mark.priority("MVP")
def test_dropping_a_block_that_violates_ordering_shows_a_visible_warning(qapp, monkeypatch):
    """SES-170: dropping a Plate Solve block with no preceding Target block in
    the region is refused (as already covered at the model level) — this also
    checks the drop is surfaced to the user via a visible warning dialog,
    not just a subtle status-label update, since it otherwise looks like the
    block "isn't placeable" rather than a same-region ordering rule."""
    from PySide6.QtCore import QPoint
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = ui_mod.SessionRegion(name="Test")
    palette = ui_mod._build_palette()
    block_list = ui_mod.BlockListWidget(region, palette, on_changed=lambda err: None)

    solve_item = next(
        palette.item(i) for i in range(palette.count())
        if palette.item(i).data(ui_mod._BLOCK_ROLE) is ui_mod.PlateSolveBlock
    )
    palette.setCurrentItem(solve_item)

    class _FakeDropEvent:
        def source(self):
            return palette

        def pos(self):
            return QPoint(0, 0)

        def acceptProposedAction(self):
            pass

    warned = {}
    monkeypatch.setattr(ui_mod.QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("called", True))

    block_list.dropEvent(_FakeDropEvent())
    assert warned.get("called") is True
    assert region.blocks == []   # rejected, not silently inserted


@pytest.mark.requirement("TC-SES-170")
@pytest.mark.priority("MVP")
def test_dropping_plate_solve_after_an_existing_target_block_succeeds(qapp):
    """Bug: dropping a Plate Solve block onto a session that already has a
    Target block, releasing in the lower half of that (only, tightly-fit)
    row to place it *after* the Target, was always read as "insert before
    this row" regardless of which half of the row was hovered — so it failed
    SES-170's ordering check even though a Target block was already present.
    The insertion point must follow which half of the hovered row the drop
    lands in."""
    from PySide6.QtCore import QPoint
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = ui_mod.SessionRegion(name="Test")
    region.insert_block(ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))
    palette = ui_mod._build_palette()
    block_list = ui_mod.BlockListWidget(region, palette, on_changed=lambda err: None)

    solve_item = next(
        palette.item(i) for i in range(palette.count())
        if palette.item(i).data(ui_mod._BLOCK_ROLE) is ui_mod.PlateSolveBlock
    )
    palette.setCurrentItem(solve_item)

    target_rect = block_list.visualItemRect(block_list.item(0))
    drop_point = QPoint(target_rect.center().x(), target_rect.bottom() - 1)

    class _FakeDropEvent:
        def source(self):
            return palette

        def pos(self):
            return drop_point

        def acceptProposedAction(self):
            pass

    block_list.dropEvent(_FakeDropEvent())

    assert [type(b).__name__ for b in region.blocks] == ["TargetBlock", "PlateSolveBlock"]


def test_dragging_a_block_outside_every_session_panel_deletes_it(qapp, monkeypatch):
    """Dragging a block out of the session panel (and releasing it somewhere
    that isn't the palette or any region's block list) removes it — the
    standard Qt behavior for a drag nothing accepts is to just leave the
    source list untouched, so this is new behavior layered on top of that."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDrag
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = ui_mod.SessionRegion(name="Test")
    block = ui_mod.ImageBlock()
    region.insert_block(block)
    palette = ui_mod._build_palette()
    block_list = ui_mod.BlockListWidget(region, palette, on_changed=lambda err: None)
    block_list.setCurrentItem(block_list.item(0))

    monkeypatch.setattr(QDrag, "exec", lambda self, *a, **k: Qt.DropAction.IgnoreAction)
    monkeypatch.setattr(ui_mod.BlockListWidget, "_is_outside_every_session_panel", lambda self, pos: True)

    block_list.startDrag(Qt.DropAction.MoveAction)

    assert region.blocks == []


def test_dragging_a_block_onto_another_region_does_not_delete_it(qapp, monkeypatch):
    """A drop rejected because it landed on another region's block list (an
    unsupported cross-region move, not "outside the session panel") must not
    delete the block — today it's just a no-op, matching pre-existing
    behavior for that case."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDrag
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = ui_mod.SessionRegion(name="Test")
    block = ui_mod.ImageBlock()
    region.insert_block(block)
    palette = ui_mod._build_palette()
    block_list = ui_mod.BlockListWidget(region, palette, on_changed=lambda err: None)
    block_list.setCurrentItem(block_list.item(0))

    monkeypatch.setattr(QDrag, "exec", lambda self, *a, **k: Qt.DropAction.IgnoreAction)
    monkeypatch.setattr(ui_mod.BlockListWidget, "_is_outside_every_session_panel", lambda self, pos: False)

    block_list.startDrag(Qt.DropAction.MoveAction)

    assert region.blocks == [block]   # untouched


def test_dragging_a_block_out_of_a_locked_session_shows_a_warning(qapp, monkeypatch):
    """Dragging a block out of a scheduled (locked) session must not delete
    it — refused with a visible warning, same as every other authoring
    mutation on a locked region."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDrag
    from PySide6.QtWidgets import QMessageBox
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    region = ui_mod.SessionRegion(name="Test")
    block = ui_mod.ImageBlock()
    region.insert_block(block)
    region.is_scheduled = True
    palette = ui_mod._build_palette()
    block_list = ui_mod.BlockListWidget(region, palette, on_changed=lambda err: None)
    block_list.setCurrentItem(block_list.item(0))

    monkeypatch.setattr(QDrag, "exec", lambda self, *a, **k: Qt.DropAction.IgnoreAction)
    monkeypatch.setattr(ui_mod.BlockListWidget, "_is_outside_every_session_panel", lambda self, pos: True)
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.setdefault("called", True))

    block_list.startDrag(Qt.DropAction.MoveAction)

    assert warned.get("called") is True
    assert region.blocks == [block]   # not removed


# ===========================================================================
# SES-300..360 — Nested blocks, triggers, plugin blocks
# ===========================================================================

@pytest.mark.requirement("TC-SES-300")
@pytest.mark.priority("P2")
def test_tc_ses_300_nested_blocks_among_ordinary_action_blocks():
    """SES-300: Allow instruction, condition, and trigger blocks to be nested within container blocks (e.g. a Loop block) placed among the ordinary action blocks in a session, rather than requiring a separate advanced-mode editor or screen."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    exec_mod = pytest.importorskip("galileo.session_exec")
    image = ui_mod.ImageBlock(filter="Ha", exposure=60.0, count=2)
    image.indent = 1
    blocks = [ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4), ui_mod.ForFilterBlock(), image]
    tree = exec_mod.build_tree(blocks)
    assert [type(c.block).__name__ for c in tree[1].children] == ["ImageBlock"]


@pytest.mark.requirement("TC-SES-310")
@pytest.mark.priority("P2")
def test_tc_ses_310_minimum_loop_wait_block_types():
    """SES-310: Provide, at minimum, the following loop/wait blocks: Loop For N, Loop Until Time, Wait Until Time, Wait For Altitude, loop-while-safe, and loop-while-above-horizon."""
    pytest.skip("only the FOR Filter / FOR Object loop blocks exist; " + _NOT_BUILT)


@pytest.mark.requirement("TC-SES-320")
@pytest.mark.priority("P2")
def test_tc_ses_320_minimum_trigger_block_types():
    """SES-320: Provide, at minimum, the following trigger blocks: Autofocus-on-Trigger (HFR increase, temperature change, time interval, filter change), Meridian-Flip-on-Trigger, and Wait-for-Safe/Abort-if-Unsafe."""
    pytest.skip(_NOT_BUILT)


@pytest.mark.requirement("TC-SES-330")
@pytest.mark.priority("P2")
def test_tc_ses_330_arbitrary_nesting_depth():
    """SES-330: Allow instruction, condition, and trigger blocks to be nested within container blocks to arbitrary depth."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    exec_mod = pytest.importorskip("galileo.session_exec")
    outer, middle = ui_mod.ForObjectBlock(), ui_mod.ForFilterBlock()
    inner = ui_mod.ImageBlock(filter="L", exposure=60.0, count=1)
    middle.indent, inner.indent = 1, 2
    tree = exec_mod.build_tree([outer, middle, inner])
    assert tree[0].children[0].children[0].block is inner


@pytest.mark.requirement("TC-SES-340")
@pytest.mark.priority("P2")
def test_tc_ses_340_plugin_registers_block_type():
    """SES-340: Allow a plugin to register a new instruction, condition, or trigger block type that appears alongside built-in ones in the palette (traces to PLUG-020)."""
    exec_mod = pytest.importorskip("galileo.session_exec")
    plugins = pytest.importorskip("galileo.plugins")

    class MyBlock:
        async def execute(self, context): pass

    ctx = plugins.PluginContext.__new__(plugins.PluginContext)
    ctx.register_instruction_type(MyBlock)
    registry = exec_mod.BlockRegistry.instance()
    assert MyBlock in registry.available_blocks()
    assert registry.find("MyBlock") is MyBlock


@pytest.mark.requirement("TC-SES-350")
@pytest.mark.priority("P2")
def test_tc_ses_350_visual_current_block_indicator():
    """SES-350: Visually indicate the currently executing block during a running session — the executor names the running block in each progress snapshot (TC-SES-050, test_ses_exec.py) and the block list marks it."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    assert hasattr(ui_mod.BlockListWidget, "set_running_block")


@pytest.mark.requirement("TC-SES-360")
@pytest.mark.priority("P3")
def test_tc_ses_360_edit_remaining_blocks_while_running():
    """SES-360: Allow editing of a session's not-yet-executed blocks while the session is running."""
    pytest.skip(_NOT_BUILT)


# ---------------------------------------------------------------------------
# Loop blocks (FOR Filter / FOR Object) and indentation
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-140")
@pytest.mark.priority("P2")
def test_loop_blocks_nest_indent_and_unindent():
    """FOR Filter / FOR Object own the blocks indented beneath them; indent is
    only valid under a loop, and a loop moves/indents together with its body."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    region = ui_mod.SessionRegion(name="Loops")
    loop = ui_mod.ForFilterBlock(filters=["L", "R"])
    image = ui_mod.ImageBlock()
    dither = ui_mod.DitherBlock()
    region.insert_block(loop)
    region.insert_block(image)           # dropped under a loop -> in its body
    assert image.indent == 1 and region.body_of(loop) == [image]
    region.insert_block(dither)          # inherits the body's depth
    assert dither.indent == 1
    region.set_indent(dither, 0)         # unindent
    assert dither.indent == 0 and region.body_of(loop) == [image]
    region.set_indent(dither, 5)         # clamped to the body block above it
    assert dither.indent == 1
    region.set_indent(dither, 0)
    outer = ui_mod.ForObjectBlock(objects=[{"name": "M31", "ra_deg": 10.68, "dec_deg": 41.27}])
    region.insert_block(outer, before=loop)
    region.set_indent(loop, 1)           # loop and body shift together
    assert (loop.indent, image.indent) == (1, 2)
    assert "L, R" in loop.display_text and "M31" in outer.display_text
    region.remove_block(outer)           # body stays, clamped back out
    assert (loop.indent, image.indent) == (0, 1)


@pytest.mark.requirement("TC-SES-140")
@pytest.mark.priority("P2")
def test_loop_blocks_in_palette_and_round_trip_indent():
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    assert ui_mod.ForFilterBlock in ui_mod._PALETTE_BLOCK_TYPES
    assert ui_mod.ForObjectBlock in ui_mod._PALETTE_BLOCK_TYPES
    loop = ui_mod.ForFilterBlock(filters=["Ha"], indent=0)
    child = ui_mod.ImageBlock(indent=1)
    for b in (loop, child):
        restored = ui_mod._block_from_dict(ui_mod._block_to_dict(b))
        assert restored == b


def test_flat_and_dark_capture_blocks_mirror_imaging_assistants():
    """Flat Capture carries the Flats Assistant's fields, Dark Capture the Darks
    Assistant's; both are on the palette and round-trip, and a template saved with
    the old Flat Capture shape (target_adu) still loads."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    assert ui_mod.DarkCaptureBlock in ui_mod._PALETTE_BLOCK_TYPES
    flat = ui_mod.FlatCaptureBlock(method="Sky Flats", exposure=0.5, count=5, filter="L",
                                   adu_method="Median", exposure_increment=0.2)
    dark = ui_mod.DarkCaptureBlock(filter="Ha", exposures=[5.0, 30.0], close_cover=True)
    for b in (flat, dark):
        assert ui_mod._block_from_dict(ui_mod._block_to_dict(b)) == b
    old = ui_mod._block_from_dict({"_type": "FlatCaptureBlock", "count": 3, "target_adu": 30000.0, "indent": 0})
    assert old.count == 3 and old.filter == "All"


def test_for_object_dialog_search_adds_and_x_removes(qapp, monkeypatch):
    """FOR Object's dialog: typing searches the catalog, picking a result adds
    it to the list (once), and its ✕ removes it."""
    from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QToolButton
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    dlg_mod = pytest.importorskip("galileo.ui.session_block_dialogs")
    block = ui_mod.ForObjectBlock()
    region = ui_mod.SessionRegion(name="T")
    region.insert_block(block)

    def fake_exec(self):
        search = self.findChild(QLineEdit, "search_edit")
        results = self.findChild(QListWidget, "results_list")
        objects = self.findChild(QListWidget, "objects_list")
        for query in ("M31", "M42", "M31"):
            search.setText(query)
            assert results.count() > 0
            results.itemClicked.emit(results.item(0))
        assert objects.count() == 2  # duplicate M31 ignored
        objects.itemWidget(objects.item(0)).findChild(QToolButton).click()
        assert objects.count() == 1
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    assert dlg_mod.open_block_parameter_dialog(None, block, region, window=None) is True
    assert len(block.objects) == 1 and {"name", "ra_deg", "dec_deg"} <= block.objects[0].keys()


def test_palette_omits_dither_and_meridian_flip_but_old_sessions_still_load():
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    assert ui_mod.DitherBlock not in ui_mod._PALETTE_BLOCK_TYPES
    assert ui_mod.MeridianFlipBlock not in ui_mod._PALETTE_BLOCK_TYPES
    for cls in (ui_mod.DitherBlock, ui_mod.MeridianFlipBlock):
        assert isinstance(ui_mod._block_from_dict(ui_mod._block_to_dict(cls())), cls)


async def test_dark_capture_close_cover_closes_and_reopens_panel():
    """SES: Dark Capture's Close Cover closes the flat panel/dust cover for the darks, then reopens it."""
    from unittest.mock import AsyncMock, MagicMock
    from galileo.session_exec import SessionExecutor
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    panel = MagicMock()
    panel.close_cover, panel.open_cover = AsyncMock(), AsyncMock()
    ex = SessionExecutor.__new__(SessionExecutor)
    ex.context = MagicMock(flat_panel=panel)
    ex._need = MagicMock()
    ex._select_filter = AsyncMock()
    ex._new_imaging = MagicMock()
    ex._checkpoint = AsyncMock()
    ex._expose = AsyncMock(return_value=True)
    ex._record = MagicMock()
    ex.current_filter = ""
    await ex._do_DarkCaptureBlock(ui_mod.DarkCaptureBlock(exposures=[5.0], close_cover=True))
    panel.close_cover.assert_awaited_once()
    panel.open_cover.assert_awaited_once()


@pytest.mark.requirement("TC-SES-140")
@pytest.mark.priority("P2")
def test_dragging_a_body_block_left_unindents_it_out_of_the_loop(qapp):
    """SES-140: dragging a loop-body tile to the left (and back right) on its own
    row unindents/indents it; the list also accepts such a same-row drag."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    from PySide6.QtCore import QPoint

    region = ui_mod.SessionRegion(name="Loops")
    loop, image = ui_mod.ForFilterBlock(filters=["L"]), ui_mod.ImageBlock()
    region.insert_block(loop)
    region.insert_block(image)
    assert image.indent == 1
    palette = ui_mod._build_palette()
    block_list = ui_mod.BlockListWidget(region, palette, on_changed=lambda err: None)

    class FakeEvent:
        def __init__(self, source, pos):
            self._source, self._pos, self.accepted = source, pos, False
        def source(self): return self._source
        def pos(self): return self._pos
        def acceptProposedAction(self): self.accepted = True

    block_list.setCurrentRow(1)
    rect = block_list.visualItemRect(block_list.item(1))
    start = rect.center()
    block_list._drag_start_x = start.x()
    move = FakeEvent(block_list, start)
    block_list.dragMoveEvent(move)
    assert move.accepted
    block_list.dropEvent(FakeEvent(block_list, QPoint(start.x() - 2 * ui_mod._INDENT_PX, start.y())))
    assert image.indent == 0 and region.body_of(loop) == []
    block_list._drag_start_x = start.x()
    block_list.dropEvent(FakeEvent(block_list, QPoint(start.x() + 2 * ui_mod._INDENT_PX, start.y())))
    assert image.indent == 1


@pytest.mark.requirement("TC-SES-115")
@pytest.mark.priority("MVP")
def test_tc_ses_115_a_session_belongs_to_one_camera(qapp, monkeypatch):
    """SES-115: a session is bound to one camera; its run uses that camera whatever the
    top-bar selector is on, and the camera is saved with the session and shown while it runs."""
    import json
    from types import SimpleNamespace
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    runner = pytest.importorskip("galileo.ui.session_runner")

    region = ui_mod.SessionRegion(name="Wide")
    assert region.camera_slot == "primary"
    region.camera_slot = "camera_2"
    saved = {}
    monkeypatch.setattr(ui_mod.SessionRegion, "_store_path", lambda self: SimpleNamespace(
        parent=SimpleNamespace(mkdir=lambda **k: None),
        write_text=lambda text, encoding=None: saved.update(json.loads(text))))
    region.save()
    assert saved["camera_slot"] == "camera_2"

    primary, wide = object(), object()
    window = SimpleNamespace(
        _current_pier=None, _active_camera_slot="primary", _device_pages={},
        _camera_backends={"primary camera": primary, "camera 2": wide})
    assert runner.build_session_context(window).camera is primary          # top-bar selection
    assert runner.build_session_context(window, camera_slot="camera_2").camera is wide


def test_run_conflict_dialog_is_not_parented_to_the_session_card(qapp, monkeypatch):
    """The overlap warning shown after Run must outlive the card: a finishing run rebuilds
    (deletes) the cards while the modal dialog is open, which crashed the app natively."""
    from types import SimpleNamespace
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    region = ui_mod.SessionRegion(name="Busy")
    palette = ui_mod._build_palette()
    from PySide6.QtWidgets import QWidget
    host = QWidget()
    card = ui_mod._RegionWidget(region, palette, lambda err: None, window=SimpleNamespace(), parent=host)
    card._controller = SimpleNamespace(
        start_region=lambda r: ([], [SimpleNamespace(name="Other")]), run_for=lambda r: None)
    parents = []
    monkeypatch.setattr(ui_mod.QMessageBox, "warning", lambda parent, *a, **k: parents.append(parent))
    card._run_now()
    assert parents and parents[0] is not card


async def test_run_blocking_works_on_a_thread_with_a_running_loop():
    """The safety check polls devices from the UI thread, whose event loop is already running;
    asyncio.run would raise there and leave an un-awaited coroutine behind."""
    from galileo.ui.app_window._weather_page import _run_blocking

    async def poll():
        return 42

    assert _run_blocking(poll) == 42


def test_run_blocking_works_without_a_running_loop():
    from galileo.ui.app_window._weather_page import _run_blocking

    async def poll():
        return 7

    assert _run_blocking(poll) == 7
