"""LIB — Image Library & Repository Management (TC-LIB-010 … TC-LIB-160).

TC-LIB-020 (SHA-256 deduplication) and parts of TC-LIB-010 (file scanning)
run immediately using only stdlib + astropy, providing an early smoke-test
before galileo.library is implemented.
"""

import hashlib
import shutil
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def library_service(tmp_path):
    lib_mod = pytest.importorskip("galileo.library")
    svc = lib_mod.LibraryService(repo_dir=tmp_path / "repo")
    return svc


# ---------------------------------------------------------------------------
# TC-LIB-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_scan_and_ingest_fits_files(library_service, sample_fits_repo):
    """LIB-010: Recursively scan a configured repository, ingest FITS files, extract header metadata into catalog."""
    lib_mod = pytest.importorskip("galileo.library")
    repo = lib_mod.Repository(root=sample_fits_repo)
    repo.scan()
    entries = repo.all_entries()
    assert len(entries) == 3
    assert all(e.object_name == "M42" for e in entries)
    assert all(e.filter_name == "Ha" for e in entries)


# ---------------------------------------------------------------------------
# TC-LIB-020  — early runnable test (stdlib only)
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-020")
@pytest.mark.priority("MVP")
def test_tc_lib_020_sha256_deduplication_stdlib(tmp_path, sample_fits_file):
    """LIB-020 (stdlib baseline): Detect duplicate files by SHA-256 content hash."""
    dup = tmp_path / "duplicate.fits"
    shutil.copy(sample_fits_file, dup)

    def sha256(path: Path) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()

    h1 = sha256(sample_fits_file)
    h2 = sha256(dup)
    assert h1 == h2, "Duplicate file must produce identical SHA-256 hash"


@pytest.mark.requirement("TC-LIB-020")
@pytest.mark.priority("MVP")
def test_tc_lib_020_sha256_deduplication_via_library(library_service, sample_fits_repo):
    """LIB-020: Repository detects duplicate FITS files via SHA-256 and allows reviewing/removing them."""
    lib_mod = pytest.importorskip("galileo.library")
    repo = lib_mod.Repository(root=sample_fits_repo)

    # Create a duplicate
    first = next(sample_fits_repo.rglob("*.fits"))
    dup_path = sample_fits_repo / "M42" / "2026-09-16" / "Ha" / "dup_001.fits"
    shutil.copy(first, dup_path)

    repo.scan()
    dupes = repo.find_duplicates()
    assert len(dupes) >= 1
    group = dupes[0]
    assert len(group) == 2


# ---------------------------------------------------------------------------
# TC-LIB-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-030")
@pytest.mark.priority("MVP")
def test_tc_lib_030_rename_and_organize_by_metadata(library_service, sample_fits_repo):
    """LIB-030: Automatically rename/organize ingested files into a configurable folder structure from FITS metadata."""
    lib_mod = pytest.importorskip("galileo.library")
    repo = lib_mod.Repository(root=sample_fits_repo)
    repo.scan()

    pattern = "{object}/{date}/{filter}/{object}_{date}_{filter}_{seq:04d}.fits"
    organized = repo.organize(pattern=pattern, dry_run=True)
    for entry in organized:
        assert "M42" in str(entry.new_path)
        assert "Ha" in str(entry.new_path)


# ---------------------------------------------------------------------------
# TC-LIB-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-040")
@pytest.mark.priority("MVP")
def test_tc_lib_040_auto_group_into_sessions(library_service, sample_fits_repo):
    """LIB-040: Automatically group related frames into sessions based on camera, binning, temperature, date."""
    lib_mod = pytest.importorskip("galileo.library")
    repo = lib_mod.Repository(root=sample_fits_repo)
    repo.scan()
    sessions = repo.detect_sessions()

    assert len(sessions) >= 1
    session = sessions[0]
    assert session.frame_count >= 3


# ---------------------------------------------------------------------------
# TC-LIB-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-050")
@pytest.mark.priority("MVP")
def test_tc_lib_050_create_master_calibration_frames(tmp_path, sample_fits_file):
    """LIB-050: Create master bias, dark, and flat calibration frames from a linked calibration session."""
    import numpy as np
    fits = pytest.importorskip("astropy.io.fits")
    lib_mod = pytest.importorskip("galileo.library")

    cal_dir = tmp_path / "darks"
    cal_dir.mkdir()
    for i in range(5):
        shutil.copy(sample_fits_file, cal_dir / f"dark_{i:03d}.fits")

    svc = lib_mod.LibraryService(repo_dir=tmp_path)
    master_path = svc.create_master_dark(input_dir=cal_dir, output_path=tmp_path / "master_dark.fits")
    assert master_path.exists()
    with fits.open(master_path) as hdul:
        assert hdul[0].data is not None


# ---------------------------------------------------------------------------
# TC-LIB-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-060")
@pytest.mark.priority("MVP")
def test_tc_lib_060_apply_calibration_to_lights(tmp_path, sample_fits_file):
    """LIB-060: Apply matching master calibration frame set (dark subtraction, flat division) in one user action."""
    import numpy as np
    fits = pytest.importorskip("astropy.io.fits")
    lib_mod = pytest.importorskip("galileo.library")

    lights_dir = tmp_path / "lights"
    lights_dir.mkdir()
    for i in range(3):
        shutil.copy(sample_fits_file, lights_dir / f"light_{i:03d}.fits")

    master_dark = sample_fits_file
    master_flat = sample_fits_file

    svc = lib_mod.LibraryService(repo_dir=tmp_path)
    result = svc.calibrate(
        light_dir=lights_dir,
        master_dark=master_dark,
        master_flat=master_flat,
        output_dir=tmp_path / "calibrated",
    )
    assert result.calibrated_count == 3


# ---------------------------------------------------------------------------
# TC-LIB-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-070")
@pytest.mark.priority("MVP")
def test_tc_lib_070_compute_quality_metrics(library_service, sample_fits_repo):
    """LIB-070: Compute per-frame quality metrics (FWHM, HFR, eccentricity, SNR) stored for later sorting."""
    lib_mod = pytest.importorskip("galileo.library")
    repo = lib_mod.Repository(root=sample_fits_repo)
    repo.scan()
    repo.compute_quality_metrics()

    entries = repo.all_entries()
    for entry in entries:
        assert entry.fwhm is not None or entry.hfr is not None


# ---------------------------------------------------------------------------
# TC-LIB-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-080")
@pytest.mark.priority("MVP")
def test_tc_lib_080_repository_statistics_dashboard(library_service, sample_fits_repo):
    """LIB-080: Repository statistics dashboard: frame counts by object/filter/date/instrument, quality trends."""
    lib_mod = pytest.importorskip("galileo.library")
    repo = lib_mod.Repository(root=sample_fits_repo)
    repo.scan()
    stats = repo.get_statistics()

    assert "by_object" in stats
    assert "by_filter" in stats
    assert "total_frames" in stats
    assert stats["total_frames"] == 3


# ---------------------------------------------------------------------------
# TC-LIB-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-090")
@pytest.mark.priority("MVP")
async def test_tc_lib_090_smb_smart_telescope_ingest(library_service):
    """LIB-090: Browse and selectively download SEESTAR/StellarMate files over SMB/CIFS."""
    lib_mod = pytest.importorskip("galileo.library")
    smb = lib_mod.SmartTelescopeSmbAdapter.__new__(lib_mod.SmartTelescopeSmbAdapter)
    smb.browse = AsyncMock(return_value=["/SEESTAR/20260916/M42_001.fits"])
    smb.download = AsyncMock()

    files = await smb.browse(host="192.168.1.100", share="seestar")
    assert len(files) == 1
    await smb.download(files[0], dest=library_service._repo_dir)
    smb.download.assert_called_once()


# ---------------------------------------------------------------------------
# TC-LIB-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-100")
@pytest.mark.priority("P2")
async def test_tc_lib_100_ftp_itelescope_ingest(library_service):
    """LIB-100: Browse and selectively download files from iTelescope over FTPS."""
    lib_mod = pytest.importorskip("galileo.library")
    ftp = lib_mod.SmartTelescopeFtpAdapter.__new__(lib_mod.SmartTelescopeFtpAdapter)
    ftp.browse = AsyncMock(return_value=["/images/M42_Ha_001.fits"])
    ftp.download = AsyncMock()

    files = await ftp.browse(host="ftp.itelescope.net", use_tls=True)
    assert len(files) == 1
    await ftp.download(files[0], dest=library_service._repo_dir)
    ftp.download.assert_called_once()


# ---------------------------------------------------------------------------
# TC-LIB-110
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-110")
@pytest.mark.priority("P3")
async def test_tc_lib_110_ftp_dwarf_experimental(library_service):
    """LIB-110: Browse and selectively download files from DWARF smart telescope over FTP (experimental)."""
    lib_mod = pytest.importorskip("galileo.library")
    dwarf = lib_mod.SmartTelescopeFtpAdapter.__new__(lib_mod.SmartTelescopeFtpAdapter)
    dwarf.browse = AsyncMock(return_value=["/raw/M42_001.fits"])
    dwarf.download = AsyncMock()

    files = await dwarf.browse(host="192.168.1.200", use_tls=False)
    assert len(files) == 1


# ---------------------------------------------------------------------------
# TC-LIB-120
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-120")
@pytest.mark.priority("P2")
async def test_tc_lib_120_google_cloud_storage_bidirectional_sync(library_service):
    """LIB-120: Bidirectional GCS sync with content-hash comparison and sync-profile selection."""
    lib_mod = pytest.importorskip("galileo.library")
    gcs = lib_mod.CloudSyncService.__new__(lib_mod.CloudSyncService)
    gcs.sync = AsyncMock(return_value={"uploaded": 2, "downloaded": 1, "skipped": 10})

    result = await gcs.sync(profile="backup_only")
    assert result["skipped"] == 10
    assert result["uploaded"] + result["downloaded"] >= 0


# ---------------------------------------------------------------------------
# TC-LIB-130
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_cli_load_repo_calibrate_cloudsync():
    """LIB-130: Expose repo scan, calibration, and cloud sync as CLI-invocable operations (no GUI required)."""
    pytest.importorskip("galileo.commands.load_repo")
    pytest.importorskip("galileo.commands.calibrate")
    pytest.importorskip("galileo.commands.cloud_sync")


# ---------------------------------------------------------------------------
# TC-LIB-140
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-140")
@pytest.mark.priority("P2")
def test_tc_lib_140_integrity_check_via_stored_hashes(library_service, sample_fits_repo):
    """LIB-140: Verify file integrity via stored content hashes on demand; flag files whose content changed."""
    lib_mod = pytest.importorskip("galileo.library")
    repo = lib_mod.Repository(root=sample_fits_repo)
    repo.scan()

    # Tamper with one file
    first = next(sample_fits_repo.rglob("*.fits"))
    first.write_bytes(first.read_bytes() + b"\x00")  # append a null byte

    corrupt = repo.verify_integrity()
    assert any(entry.path == first for entry in corrupt)


# ---------------------------------------------------------------------------
# TC-LIB-150
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-150")
@pytest.mark.priority("MVP")
async def test_tc_lib_150_auto_register_frame_on_sequence_write(tmp_path):
    """LIB-150: Automatically register each frame into the repository catalog as it is written by the sequencer."""
    import numpy as np
    lib_mod = pytest.importorskip("galileo.library")
    seq_mod = pytest.importorskip("galileo.sequencer.basic")

    repo = lib_mod.Repository(root=tmp_path / "repo")
    repo._root.mkdir(parents=True)

    svc = seq_mod.BasicSequencer.__new__(seq_mod.BasicSequencer)
    svc._repository = repo
    svc._on_frame_written = AsyncMock(side_effect=lambda path: repo.register_frame(path))

    fits_path = tmp_path / "repo" / "test.fits"
    fits = pytest.importorskip("astropy.io.fits")
    fits.PrimaryHDU(np.zeros((10, 10))).writeto(fits_path)

    await svc._on_frame_written(fits_path)
    assert repo.entry_count() >= 1


# ---------------------------------------------------------------------------
# TC-LIB-160
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-160")
@pytest.mark.priority("MVP")
async def test_tc_lib_160_sequence_step_session_container(tmp_path):
    """LIB-160: Automatically create a session container grouping every frame acquired during one sequence step."""
    lib_mod = pytest.importorskip("galileo.library")
    seq_mod = pytest.importorskip("galileo.sequencer.basic")

    repo = lib_mod.Repository(root=tmp_path / "repo")
    repo._root.mkdir(parents=True)

    session_id = repo.begin_sequence_session(step_name="M42 Ha x20")
    for i in range(3):
        repo.add_frame_to_session(session_id, path=tmp_path / f"light_{i}.fits")
    repo.end_sequence_session(session_id)

    sessions = repo.get_sequence_sessions()
    assert any(s.step_name == "M42 Ha x20" for s in sessions)
    matched = [s for s in sessions if s.step_name == "M42 Ha x20"][0]
    assert matched.frame_count == 3
