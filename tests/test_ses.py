# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SES — Sessions (formerly `SEQ`/`SEQ-ADV`; TC-SES-010 … TC-SES-360).

Three sub-ranges, mirroring SRS Sections 4.5/4.5a/4.6:
  - SES-010..090:  execution engine (`galileo.sequencer.basic`)
  - SES-100..230:  Sessions screen authoring/lifecycle (`galileo.ui.sessions`)
  - SES-300..360:  nested instruction/condition/trigger blocks (`galileo.sequencer.advanced`)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def ses_service(minimal_sequence, mock_indi_camera, mock_indi_mount, tmp_path):
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    svc = seq_mod.BasicSequencer(
        camera=mock_indi_camera,
        mount=mock_indi_mount,
        output_dir=tmp_path,
    )
    return svc


@pytest.fixture
def adv_ses():
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    return seq_mod.AdvancedSequencer()


@pytest.fixture
def sessions_screen(minimal_profile):
    ui_mod = pytest.importorskip("galileo.ui.sessions")
    profile_mod = pytest.importorskip("galileo.equipment.profiles")
    profile = profile_mod.Profile.from_dict(minimal_profile)
    screen = ui_mod.SessionsScreen(profile=profile)
    return screen


# ===========================================================================
# SES-010..090 — Execution engine (galileo.sequencer.basic)
# ===========================================================================

# ---------------------------------------------------------------------------
# TC-SES-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-010")
@pytest.mark.priority("MVP")
def test_tc_ses_010_define_session_as_ordered_action_blocks():
    """SES-010: Allow definition of a session as an ordered list of action blocks, each contributing its own parameters (e.g. an Image block's exposure count, time, filter, binning)."""
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef(name="Test")
    seq.add_target(
        name="M42",
        ra_deg=83.8221,
        dec_deg=-5.3911,
        steps=[
            seq_mod.CaptureStep(filter="Ha", exposure=300.0, count=20, binning=1, frame_type="Light"),
            seq_mod.CaptureStep(filter="OIII", exposure=300.0, count=20, binning=1, frame_type="Light"),
        ],
    )
    assert len(seq.targets) == 1
    assert seq.targets[0].name == "M42"
    assert len(seq.targets[0].steps) == 2
    assert seq.targets[0].steps[0].filter == "Ha"


# ---------------------------------------------------------------------------
# TC-SES-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-020")
@pytest.mark.priority("MVP")
def test_tc_ses_020_dynamic_file_naming_macros(tmp_path):
    """SES-020: Support dynamic file-naming macros (target, filter, date, frame number, frame type) applied to saved files."""
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    namer = seq_mod.FileNamer(
        pattern="{target}_{filter}_{date}_{frame_number:04d}_{frame_type}.fits"
    )
    name = namer.format(target="M42", filter="Ha", date="2026-09-16", frame_number=1, frame_type="Light")
    assert name == "M42_Ha_2026-09-16_0001_Light.fits"


# ---------------------------------------------------------------------------
# TC-SES-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-030")
@pytest.mark.priority("MVP")
async def test_tc_ses_030_execute_session_without_interaction(ses_service, minimal_sequence):
    """SES-030: Execute a defined session start-to-finish without further user interaction, capturing and saving each configured frame."""
    import numpy as np
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)

    ses_service._camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))
    await ses_service.run(seq)

    assert ses_service.state == seq_mod.SequencerState.COMPLETED
    assert ses_service.frames_captured == 20


# ---------------------------------------------------------------------------
# TC-SES-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-040")
@pytest.mark.priority("MVP")
async def test_tc_ses_040_pause_resume_stop(ses_service, minimal_sequence):
    """SES-040: Allow a running session to be paused, resumed, and stopped by the user."""
    import numpy as np
    import asyncio
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)

    expose_event = asyncio.Event()

    async def slow_expose(**kwargs):
        expose_event.set()
        await asyncio.sleep(0.05)

    ses_service._camera.start_exposure = AsyncMock(side_effect=slow_expose)
    ses_service._camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))

    run_task = asyncio.create_task(ses_service.run(seq))
    await expose_event.wait()

    await ses_service.pause()
    assert ses_service.state == seq_mod.SequencerState.PAUSED

    await ses_service.resume()
    assert ses_service.state == seq_mod.SequencerState.RUNNING

    await ses_service.stop()
    run_task.cancel()
    assert ses_service.state == seq_mod.SequencerState.STOPPED


# ---------------------------------------------------------------------------
# TC-SES-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-050")
@pytest.mark.priority("MVP")
async def test_tc_ses_050_live_progress_display(ses_service, minimal_sequence):
    """SES-050: Display live session progress (current block, frame N of M, elapsed/remaining estimate)."""
    import numpy as np
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)
    ses_service._camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))

    await ses_service.run(seq)
    progress = ses_service.get_progress()

    assert "current_target" in progress
    assert "frame_current" in progress
    assert "frame_total" in progress
    assert progress["frame_total"] == 20


# ---------------------------------------------------------------------------
# TC-SES-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-060")
@pytest.mark.priority("MVP")
def test_tc_ses_060_persist_session_for_reuse(minimal_sequence, tmp_path):
    """SES-060: Persist a session definition for reuse (traces to the Save control, SES-110)."""
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)
    out_file = tmp_path / "M42.gseq"
    seq.save(out_file)
    assert out_file.exists()

    loaded = seq_mod.SequenceDef.load(out_file)
    assert loaded.name == seq.name
    assert len(loaded.targets) == len(seq.targets)


# ---------------------------------------------------------------------------
# TC-SES-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-070")
@pytest.mark.priority("MVP")
async def test_tc_ses_070_per_frame_session_metadata(ses_service, minimal_sequence, tmp_path):
    """SES-070: Record, per captured frame, sufficient metadata to reconstruct which session and block produced it (traces to META)."""
    import numpy as np
    from astropy.io import fits as astrofits
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)
    ses_service._camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))
    ses_service._output_dir = tmp_path

    await ses_service.run(seq)
    saved_files = list(tmp_path.glob("*.fits"))
    assert saved_files, "No FITS files were saved"

    with astrofits.open(saved_files[0]) as hdul:
        hdr = hdul[0].header
        assert "OBJECT" in hdr
        assert "FILTER" in hdr
        assert "EXPTIME" in hdr
        assert "IMAGETYP" in hdr


# ---------------------------------------------------------------------------
# TC-SES-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-080")
@pytest.mark.priority("MVP")
async def test_tc_ses_080_continue_on_non_fatal_capture_error(ses_service, minimal_sequence):
    """SES-080: Continue to the next block and log a recoverable error rather than terminate the session, on a single non-fatal capture error."""
    import numpy as np
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)

    call_count = 0

    async def flaky_expose(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise OSError("CCD readout timeout")

    ses_service._camera.start_exposure = AsyncMock(side_effect=flaky_expose)
    ses_service._camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))

    await ses_service.run(seq)

    assert ses_service.state == seq_mod.SequencerState.COMPLETED
    assert len(ses_service.errors) >= 1
    assert ses_service.frames_captured >= 19  # at least 19 of 20 succeeded


# ---------------------------------------------------------------------------
# TC-SES-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-090")
@pytest.mark.priority("P3")
def test_tc_ses_090_parallel_multi_train_capture():
    """SES-090: Support running capture sessions in parallel across two or more optical trains sharing the same mount, using a lead/follower model."""
    pytest.importorskip("galileo.sequencer.basic")
    multi_train = pytest.importorskip("galileo.sequencer.multi_train")
    runner = multi_train.MultiTrainRunner.__new__(multi_train.MultiTrainRunner)
    assert hasattr(runner, "set_lead_train")
    assert hasattr(runner, "add_follower_train")
    assert hasattr(runner, "run")


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

    region = ui_mod.SessionRegion(name="M42 Session")
    region.insert_block(ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))
    region.insert_block(ui_mod.ImageBlock(exposure=300.0, count=10, filter="Ha"))

    tpl_file = tmp_path / "HaSession.gstpl"
    region.save_as_template(tpl_file)
    assert tpl_file.exists()

    template = ui_mod.SessionTemplate.load(tpl_file)
    assert template.blocks[0].is_placeholder_target
    assert len(template.blocks) == 2


# ---------------------------------------------------------------------------
# TC-SES-190
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-190")
@pytest.mark.priority("P2")
def test_tc_ses_190_load_from_template_substitutes_target(tmp_path):
    """SES-190: When Load from Template is used on a region that already has a concrete Target block, substitute the template's placeholder with that Target block and append the template's remaining blocks. Unavailable with no Target block yet."""
    ui_mod = pytest.importorskip("galileo.ui.sessions")

    template_region = ui_mod.SessionRegion(name="Template Source")
    template_region.insert_block(ui_mod.TargetBlock(name="M42", ra_deg=83.8, dec_deg=-5.4))
    template_region.insert_block(ui_mod.ImageBlock(exposure=300.0, count=10, filter="Ha"))
    tpl_file = tmp_path / "HaSession.gstpl"
    template_region.save_as_template(tpl_file)

    # No Target block yet -> unavailable.
    empty_region = ui_mod.SessionRegion(name="Empty")
    assert empty_region.can_load_from_template() is False
    with pytest.raises(ui_mod.BlockOrderError):
        empty_region.load_from_template(tpl_file)

    # Concrete Target block present -> substitutes the placeholder, appends the rest.
    m31_region = ui_mod.SessionRegion(name="M31")
    m31_region.insert_block(ui_mod.TargetBlock(name="M31", ra_deg=10.68, dec_deg=41.27))
    assert m31_region.can_load_from_template() is True
    m31_region.load_from_template(tpl_file)

    assert len(m31_region.blocks) == 2
    assert m31_region.blocks[0].name == "M31"  # existing target preserved, not overwritten
    assert isinstance(m31_region.blocks[1], ui_mod.ImageBlock)


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


# ===========================================================================
# SES-300..360 — Nested instruction/condition/trigger blocks (galileo.sequencer.advanced)
# ===========================================================================

# ---------------------------------------------------------------------------
# TC-SES-300
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-300")
@pytest.mark.priority("P2")
def test_tc_ses_300_nested_blocks_among_ordinary_action_blocks():
    """SES-300: Allow instruction, condition, and trigger blocks to be nested within container blocks (e.g. a Loop block) placed among the ordinary action blocks in a session, rather than requiring a separate advanced-mode editor or screen."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    root = seq_mod.InstructionGroup(name="Root")
    root.add_instruction(seq_mod.CaptureInstruction(filter="Ha", duration=300.0, count=5))
    root.add_condition(seq_mod.RepeatCountCondition(count=3))
    root.add_trigger(seq_mod.AutofocusTrigger(hfr_increase_threshold=0.2))

    assert len(root.instructions) == 1
    assert len(root.conditions) == 1
    assert len(root.triggers) == 1
    # No separate advanced-mode editor class: the same InstructionGroup composes
    # into an ordinary session region, it isn't a distinct screen/mode.
    assert not hasattr(seq_mod, "AdvancedModeEditor")


# ---------------------------------------------------------------------------
# TC-SES-310
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-310")
@pytest.mark.priority("P2")
def test_tc_ses_310_minimum_loop_wait_block_types():
    """SES-310: Provide, at minimum, the following loop/wait blocks: Loop For N, Loop Until Time, Wait Until Time, Wait For Altitude, loop-while-safe, and loop-while-above-horizon."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")

    for cls_name in (
        "RepeatCountCondition",          # Loop For N
        "LoopUntilTimeCondition",        # Loop Until Time
        "WaitUntilTimeCondition",        # Wait Until Time
        "WaitForAltitudeCondition",      # Wait For Altitude
        "LoopWhileSafeCondition",        # loop-while-safe
        "LoopWhileAboveHorizonCondition",  # loop-while-above-horizon
    ):
        assert hasattr(seq_mod, cls_name), f"Missing loop/wait block class: {cls_name}"


# ---------------------------------------------------------------------------
# TC-SES-320
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-320")
@pytest.mark.priority("P2")
def test_tc_ses_320_minimum_trigger_block_types():
    """SES-320: Provide, at minimum, the following trigger blocks: Autofocus-on-Trigger (HFR increase, temperature change, time interval, filter change), Meridian-Flip-on-Trigger, and Wait-for-Safe/Abort-if-Unsafe."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")

    for cls_name in (
        "AutofocusHfrTrigger",
        "AutofocusTemperatureTrigger",
        "AutofocusTimeTrigger",
        "AutofocusFilterChangeTrigger",
        "MeridianFlipTrigger",
        "SafetyAbortTrigger",
    ):
        assert hasattr(seq_mod, cls_name), f"Missing trigger class: {cls_name}"


# ---------------------------------------------------------------------------
# TC-SES-330
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-330")
@pytest.mark.priority("P2")
def test_tc_ses_330_arbitrary_nesting_depth():
    """SES-330: Allow instruction, condition, and trigger blocks to be nested within container blocks to arbitrary depth."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")

    outer = seq_mod.InstructionGroup(name="Outer")
    middle = seq_mod.InstructionGroup(name="Middle")
    inner = seq_mod.InstructionGroup(name="Inner")
    inner.add_instruction(seq_mod.CaptureInstruction(filter="L", duration=60.0, count=1))
    middle.add_group(inner)
    outer.add_group(middle)

    assert outer.groups[0].name == "Middle"
    assert outer.groups[0].groups[0].name == "Inner"
    assert outer.groups[0].groups[0].instructions[0].filter == "L"


# ---------------------------------------------------------------------------
# TC-SES-340
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-340")
@pytest.mark.priority("P2")
def test_tc_ses_340_plugin_registers_block_type():
    """SES-340: Allow a plugin to register a new instruction, condition, or trigger block type that appears alongside built-in ones in the palette (traces to PLUG-020)."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    plugins = pytest.importorskip("galileo.plugins")

    class MyInstruction(seq_mod.BaseInstruction):
        label = "MyPluginInstruction"
        async def execute(self, context): pass

    ctx = plugins.PluginContext.__new__(plugins.PluginContext)
    ctx.register_instruction_type(MyInstruction)
    registry = seq_mod.InstructionRegistry.instance()
    assert MyInstruction in registry.available_instructions()


# ---------------------------------------------------------------------------
# TC-SES-350
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-350")
@pytest.mark.priority("P2")
async def test_tc_ses_350_visual_current_block_indicator(adv_ses):
    """SES-350: Visually indicate the currently executing block during a running session."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    root = seq_mod.InstructionGroup(name="Root")
    instr = seq_mod.CaptureInstruction(filter="Ha", duration=0.01, count=1)
    root.add_instruction(instr)

    executing = []
    original_execute = instr.execute

    async def track_execute(ctx):
        executing.append(adv_ses.current_instruction)
        await original_execute(ctx)

    instr.execute = track_execute
    seq = seq_mod.AdvancedSequenceDef(name="Test", root=root)
    await adv_ses.run(seq)

    assert len(executing) > 0
    assert executing[0] is instr


# ---------------------------------------------------------------------------
# TC-SES-360
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SES-360")
@pytest.mark.priority("P3")
async def test_tc_ses_360_edit_remaining_blocks_while_running(adv_ses):
    """SES-360: Allow editing of a session's not-yet-executed blocks while the session is running."""
    import asyncio
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    root = seq_mod.InstructionGroup(name="Root")
    instr1 = seq_mod.WaitInstruction(duration_s=0.2)
    instr2 = seq_mod.CaptureInstruction(filter="L", duration=0.01, count=1)
    root.add_instruction(instr1)
    root.add_instruction(instr2)

    seq = seq_mod.AdvancedSequenceDef(name="Test", root=root)
    run_task = asyncio.create_task(adv_ses.run(seq))
    await asyncio.sleep(0.05)  # let instr1 start

    new_instr = seq_mod.MessageInstruction(message="Inserted at runtime")
    adv_ses.insert_instruction_before(instr2, new_instr)

    await run_task
    assert new_instr in adv_ses.executed_instructions or new_instr in root.instructions
