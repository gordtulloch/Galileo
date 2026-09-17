"""SEQ — Sequencer (Basic) (TC-SEQ-010 … TC-SEQ-090)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def seq_service(minimal_sequence, mock_indi_camera, mock_indi_mount, tmp_path):
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    svc = seq_mod.BasicSequencer(
        camera=mock_indi_camera,
        mount=mock_indi_mount,
        output_dir=tmp_path,
    )
    return svc


# ---------------------------------------------------------------------------
# TC-SEQ-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-010")
@pytest.mark.priority("MVP")
def test_tc_seq_010_define_ordered_target_list():
    """SEQ-010: Allow definition of an ordered list of imaging targets with exposure count, time, filter, binning."""
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
# TC-SEQ-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-020")
@pytest.mark.priority("MVP")
def test_tc_seq_020_dynamic_file_naming_macros(tmp_path):
    """SEQ-020: Dynamic file-naming macros (target, filter, date, frame number, frame type) applied to saved files."""
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    namer = seq_mod.FileNamer(
        pattern="{target}_{filter}_{date}_{frame_number:04d}_{frame_type}.fits"
    )
    name = namer.format(target="M42", filter="Ha", date="2026-09-16", frame_number=1, frame_type="Light")
    assert name == "M42_Ha_2026-09-16_0001_Light.fits"


# ---------------------------------------------------------------------------
# TC-SEQ-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-030")
@pytest.mark.priority("MVP")
async def test_tc_seq_030_execute_sequence_without_interaction(seq_service, minimal_sequence):
    """SEQ-030: Execute a defined sequence start-to-finish without further user interaction."""
    import numpy as np
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)

    seq_service._camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))
    await seq_service.run(seq)

    assert seq_service.state == seq_mod.SequencerState.COMPLETED
    # 20 frames expected
    assert seq_service.frames_captured == 20


# ---------------------------------------------------------------------------
# TC-SEQ-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-040")
@pytest.mark.priority("MVP")
async def test_tc_seq_040_pause_resume_stop(seq_service, minimal_sequence):
    """SEQ-040: Allow a running sequence to be paused, resumed, and stopped by the user."""
    import numpy as np
    import asyncio
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)

    expose_event = asyncio.Event()

    async def slow_expose(**kwargs):
        expose_event.set()
        await asyncio.sleep(0.05)

    seq_service._camera.start_exposure = AsyncMock(side_effect=slow_expose)
    seq_service._camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))

    run_task = asyncio.create_task(seq_service.run(seq))
    await expose_event.wait()

    await seq_service.pause()
    assert seq_service.state == seq_mod.SequencerState.PAUSED

    await seq_service.resume()
    assert seq_service.state == seq_mod.SequencerState.RUNNING

    await seq_service.stop()
    run_task.cancel()
    assert seq_service.state == seq_mod.SequencerState.STOPPED


# ---------------------------------------------------------------------------
# TC-SEQ-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-050")
@pytest.mark.priority("MVP")
async def test_tc_seq_050_live_progress_display(seq_service, minimal_sequence):
    """SEQ-050: Display live sequence progress: current target, frame N of M, elapsed/remaining estimate."""
    import numpy as np
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)
    seq_service._camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))

    await seq_service.run(seq)
    progress = seq_service.get_progress()

    assert "current_target" in progress
    assert "frame_current" in progress
    assert "frame_total" in progress
    assert progress["frame_total"] == 20


# ---------------------------------------------------------------------------
# TC-SEQ-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-060")
@pytest.mark.priority("MVP")
def test_tc_seq_060_persist_sequence_to_file(minimal_sequence, tmp_path):
    """SEQ-060: Persist a sequence definition to a file for reuse across sessions."""
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)
    out_file = tmp_path / "M42.gseq"
    seq.save(out_file)
    assert out_file.exists()

    loaded = seq_mod.SequenceDef.load(out_file)
    assert loaded.name == seq.name
    assert len(loaded.targets) == len(seq.targets)


# ---------------------------------------------------------------------------
# TC-SEQ-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-070")
@pytest.mark.priority("MVP")
async def test_tc_seq_070_per_frame_sequence_metadata(seq_service, minimal_sequence, tmp_path):
    """SEQ-070: Record per-frame metadata sufficient to reconstruct which sequence step produced it."""
    import numpy as np
    from astropy.io import fits as astrofits
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)
    seq_service._camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))
    seq_service._output_dir = tmp_path

    await seq_service.run(seq)
    saved_files = list(tmp_path.glob("*.fits"))
    assert saved_files, "No FITS files were saved"

    with astrofits.open(saved_files[0]) as hdul:
        hdr = hdul[0].header
        assert "OBJECT" in hdr
        assert "FILTER" in hdr
        assert "EXPTIME" in hdr
        assert "IMAGETYP" in hdr


# ---------------------------------------------------------------------------
# TC-SEQ-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-080")
@pytest.mark.priority("MVP")
async def test_tc_seq_080_continue_on_non_fatal_capture_error(seq_service, minimal_sequence):
    """SEQ-080: Continue to the next step and log a recoverable error on a single non-fatal capture error."""
    import numpy as np
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    seq = seq_mod.SequenceDef.from_dict(minimal_sequence)

    call_count = 0

    async def flaky_expose(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise IOError("CCD readout timeout")

    seq_service._camera.start_exposure = AsyncMock(side_effect=flaky_expose)
    seq_service._camera.get_image_array = AsyncMock(return_value=np.zeros((10, 10), dtype=np.float32))

    await seq_service.run(seq)

    assert seq_service.state == seq_mod.SequencerState.COMPLETED
    assert len(seq_service.errors) >= 1
    assert seq_service.frames_captured >= 19  # at least 19 of 20 succeeded


# ---------------------------------------------------------------------------
# TC-SEQ-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-090")
@pytest.mark.priority("P3")
def test_tc_seq_090_parallel_multi_train_capture():
    """SEQ-090: Capture in parallel across two or more optical trains using lead/follower model."""
    seq_mod = pytest.importorskip("galileo.sequencer.basic")
    multi_train = pytest.importorskip("galileo.sequencer.multi_train")
    runner = multi_train.MultiTrainRunner.__new__(multi_train.MultiTrainRunner)
    assert hasattr(runner, "set_lead_train")
    assert hasattr(runner, "add_follower_train")
    assert hasattr(runner, "run")
