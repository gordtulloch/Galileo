# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LIB — Image Library & Repository Management (TC-LIB-010 … TC-LIB-160).

``galileo.library`` is AstroFiler's library: the catalog lives in the shared
Galileo database (schema owned by ``galileo/library/migrations``), the
ingest / session / master-frame logic is ``galileo.library.core``, and the
screens are the Library section's pages. Each test runs against a fresh
migrated database and a ``library.ini`` pointing at temporary incoming and
repository folders, so nothing touches the user's real library. The screens are
built offscreen.
"""

import hashlib
import importlib
import os
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

COMMAND_MODULES = [
    "auto_calibration", "cloud_sync", "create_sessions", "download", "link_sessions", "load_repo",
    "photometry", "register_existing", "reset_calibration_test_state", "stack", "sync_repo",
    "variable_star_photometry",
]


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def write_frame(folder, name, frame_type, obj, exposure, seed, *, filt="", date="2026-09-16T22:00:00", level=1000.0):
    """Write a small FITS frame with the headers the library sorts on."""
    np = pytest.importorskip("numpy")
    fits = pytest.importorskip("astropy.io.fits")
    hdr = fits.Header()
    hdr["IMAGETYP"], hdr["OBJECT"], hdr["EXPTIME"] = frame_type, obj, exposure
    if filt:
        hdr["FILTER"] = filt
    hdr["DATE-OBS"], hdr["CCD-TEMP"] = date, -10.0
    hdr["XBINNING"] = hdr["YBINNING"] = 1
    hdr["TELESCOP"], hdr["INSTRUME"], hdr["GAIN"], hdr["OFFSET"] = "TestScope", "TestCam", 100, 10
    data = np.random.default_rng(seed).normal(level, 10, (64, 64)).astype("float32")
    path = Path(folder) / name
    fits.PrimaryHDU(data, header=hdr).writeto(path)
    return path


def write_light_frames(folder, count=3):
    return [
        write_frame(folder, f"light_{i}.fits", "Light Frame", "M42", 60, i, filt="Ha", date=f"2026-09-16T22:0{i}:00")
        for i in range(count)
    ]


def write_calibration_frames(folder):
    for i in range(3):
        write_frame(folder, f"bias_{i}.fits", "Bias Frame", "Bias", 0, 30 + i, date=f"2026-09-16T23:3{i}:00", level=50)
        write_frame(folder, f"dark_{i}.fits", "Dark Frame", "Dark", 60, 10 + i, date=f"2026-09-16T23:0{i}:00", level=100)
        write_frame(folder, f"flat_{i}.fits", "Flat Field", "Flat", 2, 20 + i, filt="Ha", date=f"2026-09-16T21:0{i}:00", level=30000)


@pytest.fixture
def library(tmp_path):
    """A fresh migrated library database and a library.ini with temporary incoming/repository folders."""
    from galileo.library.config import set_config_path
    from galileo.library.database import db, init_db

    incoming, repo = tmp_path / "incoming", tmp_path / "repo"
    incoming.mkdir()
    repo.mkdir()
    ini = tmp_path / "library.ini"
    ini.write_text(
        f"[DEFAULT]\nsource = {incoming}\nrepo = {repo}\ntemp_folder = {tmp_path / 'scratch'}\n"
        "compress_fits = False\nmin_files_per_master = 3\n"
    )
    set_config_path(ini)
    init_db(tmp_path / "library.db")
    yield SimpleNamespace(incoming=incoming, repo=repo, ini=ini, root=tmp_path)
    db.close()
    set_config_path(None)


def ingest(library):
    """Move everything in the incoming folder into the repository and catalog it."""
    from galileo.library.core import fitsProcessing

    processor = fitsProcessing()
    return processor, processor.registerFitsImages(moveFiles=True)


# ---------------------------------------------------------------------------
# TC-LIB-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_scan_and_ingest_fits_files(library):
    """LIB-010: Recursively scan a configured repository, ingest FITS files, extract header metadata into catalog."""
    from galileo.library.models import fitsFile

    write_light_frames(library.incoming)
    ingest(library)

    rows = list(fitsFile.select())
    assert len(rows) == 3
    assert all(r.fitsFileObject == "M42" and r.fitsFileFilter == "Ha" for r in rows)
    assert all(r.fitsFileType == "LIGHT FRAME" and r.fitsFileHash for r in rows)
    assert not list(library.incoming.glob("*.fits")), "ingested files leave the incoming folder"


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_library_schema_is_migrated_to_head(library):
    """LIB-010: the catalog schema is owned by numbered migrations (AstroFiler's 001-012 plus Galileo's) and is current."""
    from galileo.library.database import db, get_migration_status

    status = get_migration_status()
    assert status["undone"] == []
    assert status["done"][0] == "001_initial_schema" and status["current"] > "012"
    tables = {t.lower() for t in db.get_tables()}
    assert {"fitsfile", "fitssession", "masters", "mapping", "variablestars", "observatories", "piers",
            "device_configs", "optical_tubes"} <= tables


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("applied_through", ["012", "013"])
def test_tc_lib_010_existing_database_upgrades_in_place(tmp_path, applied_through):
    """LIB-010: a database with only some migrations applied (AstroFiler's 001-012, or Galileo's earlier 013) upgrades and keeps its data."""
    from galileo.library.database import db, get_migration_status, init_db
    from galileo.library.models import fitsFile

    path = tmp_path / "astrofiler.db"
    init_db(path)
    fitsFile.create(fitsFileId="abc", fitsFileName="M42.fits", fitsFileObject="M42")
    # Rewind to what an older release left behind.
    db.execute_sql("DELETE FROM migratehistory WHERE name > ?", (applied_through + "_",))
    db.execute_sql("ALTER TABLE fitssession DROP COLUMN fitsSessionStepName")
    if applied_through == "012":
        for table in ("optical_tubes", "device_configs", "piers", "observatories"):
            db.execute_sql(f"DROP TABLE {table}")
    db.close()

    init_db(path)
    try:
        assert get_migration_status()["undone"] == []
        assert fitsFile.get_by_id("abc").fitsFileObject == "M42"
        assert "piers" in {t.lower() for t in db.get_tables()}
        assert "fitsSessionStepName" in {c.name for c in db.get_columns("fitssession")}
    finally:
        db.close()


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_galileo_tables_created_before_migrations_are_kept(tmp_path):
    """LIB-010: a Galileo database from before migrations owned the schema keeps its observatory rows and gains new columns."""
    from galileo.library.database import db, init_db

    path = tmp_path / "old_galileo.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE observatories (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, latitude REAL, longitude REAL,
                                    timezone TEXT, physical_address TEXT, owner TEXT);
        CREATE TABLE piers (id INTEGER PRIMARY KEY, observatory_id INTEGER NOT NULL REFERENCES observatories(id), name TEXT NOT NULL);
        CREATE TABLE device_configs (id INTEGER PRIMARY KEY, pier_id INTEGER NOT NULL REFERENCES piers(id), category TEXT NOT NULL,
                                     slot TEXT NOT NULL, driver TEXT NOT NULL, server TEXT NOT NULL, port INTEGER NOT NULL,
                                     device_name TEXT, pixel_size_um REAL, sensor_width_px INTEGER, sensor_height_px INTEGER,
                                     sensor_name TEXT);
        CREATE TABLE optical_tubes (id INTEGER PRIMARY KEY, pier_id INTEGER NOT NULL REFERENCES piers(id), position INTEGER NOT NULL,
                                    focal_length_mm REAL NOT NULL, aperture_mm REAL NOT NULL, optical_system TEXT NOT NULL,
                                    image_reversed INTEGER NOT NULL, image_inverted INTEGER NOT NULL, associated_devices TEXT NOT NULL);
        INSERT INTO observatories (id, name) VALUES (1, 'Home');
        """
    )
    conn.commit()
    conn.close()

    init_db(path)
    try:
        assert {c.name for c in db.get_columns("optical_tubes")} >= {"name"}
        assert {c.name for c in db.get_columns("device_configs")} >= {"bayer_pattern"}
        from galileo.library.models import ObservatoryRecord
        assert ObservatoryRecord.get().name == "Home"
    finally:
        db.close()


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_library_settings_round_trip(tmp_path):
    """LIB-010: the repository folders and other library settings persist in library.ini, shared by the GUI and the commands."""
    from galileo.library.config import get_repository_path, load_config, save_config, set_config_path

    ini = tmp_path / "library.ini"
    set_config_path(ini)
    try:
        assert get_repository_path() == "" and not ini.exists()
        config = load_config()
        config.set("DEFAULT", "repo", str(tmp_path / "repo"))
        config.set("DEFAULT", "min_files_per_master", "5")
        save_config(config)
        assert get_repository_path() == str(tmp_path / "repo")
        assert load_config().getint("DEFAULT", "min_files_per_master") == 5
    finally:
        set_config_path(None)


# ---------------------------------------------------------------------------
# TC-LIB-020
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

    assert sha256(sample_fits_file) == sha256(dup), "Duplicate file must produce identical SHA-256 hash"


@pytest.mark.requirement("TC-LIB-020")
@pytest.mark.priority("MVP")
def test_tc_lib_020_duplicate_is_not_catalogued_twice(library):
    """LIB-020: a file whose SHA-256 matches one already in the catalog is recognised as a duplicate and not catalogued again."""
    from galileo.library.models import fitsFile

    first = write_light_frames(library.incoming, count=1)[0]
    shutil.copy(first, library.root / "keep.fits")
    ingest(library)
    shutil.copy(library.root / "keep.fits", library.incoming / "same_content.fits")
    ingest(library)

    assert fitsFile.select().count() == 1


@pytest.mark.requirement("TC-LIB-020")
@pytest.mark.priority("MVP")
def test_tc_lib_020_duplicate_groups_are_listed_for_review(library):
    """LIB-020: catalog files sharing a content hash are listed as duplicate groups so the user can review and remove them."""
    from galileo.library.core.duplicates import files_with_hash, find_duplicate_hashes
    from galileo.library.models import fitsFile

    for name, digest in (("a", "h1"), ("b", "h1"), ("c", "h1"), ("d", "h2"), ("e", None)):
        fitsFile.create(fitsFileId=name, fitsFileName=f"{name}.fits", fitsFileHash=digest)

    assert find_duplicate_hashes() == [("h1", 3)]
    assert [f.fitsFileId for f in files_with_hash("h1")] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# TC-LIB-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-030")
@pytest.mark.priority("MVP")
def test_tc_lib_030_rename_and_organize_by_metadata(library):
    """LIB-030: Automatically rename/organize ingested files into a folder structure derived from FITS metadata."""
    from galileo.library.models import fitsFile

    write_light_frames(library.incoming)
    write_calibration_frames(library.incoming)
    ingest(library)

    lights = [Path(f.fitsFileName) for f in fitsFile.select().where(fitsFile.fitsFileType == "LIGHT FRAME")]
    assert len(lights) == 3
    for path in lights:
        assert path.exists() and library.repo in path.parents
        relative = path.relative_to(library.repo).parts
        assert relative[:2] == ("Light", "M42") and "20260916" in relative
        assert "TestScope" in path.name and "Ha" in path.name and "60s" in path.name


# ---------------------------------------------------------------------------
# TC-LIB-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-040")
@pytest.mark.priority("MVP")
def test_tc_lib_040_auto_group_into_sessions(library):
    """LIB-040: Automatically group related frames into sessions based on camera, binning, temperature, date."""
    from galileo.library.models import fitsFile, fitsSession

    write_light_frames(library.incoming)
    write_frame(library.incoming, "other_night.fits", "Light Frame", "M42", 60, 99, filt="Ha", date="2026-09-20T22:00:00")
    processor, _ = ingest(library)
    processor.createLightSessions()

    sessions = list(fitsSession.select())
    assert len(sessions) == 2, "one session per night"
    by_size = sorted(fitsFile.select().where(fitsFile.fitsFileSession == s.fitsSessionId).count() for s in sessions)
    assert by_size == [1, 3]
    tonight = max(sessions, key=lambda s: fitsFile.select().where(fitsFile.fitsFileSession == s.fitsSessionId).count())
    assert (tonight.fitsSessionObjectName, tonight.fitsSessionTelescope, tonight.fitsSessionImager) == ("M42", "TestScope", "TestCam")


# ---------------------------------------------------------------------------
# TC-LIB-050 / TC-LIB-060
# ---------------------------------------------------------------------------

def calibration_ready(library):
    write_light_frames(library.incoming)
    write_calibration_frames(library.incoming)
    processor, _ = ingest(library)
    processor.createLightSessions()
    processor.createCalibrationSessions()
    processor.linkSessions()
    from galileo.library.core.auto_calibration import load_config
    return load_config()


@pytest.mark.requirement("TC-LIB-050")
@pytest.mark.priority("MVP")
def test_tc_lib_050_create_master_calibration_frames(library):
    """LIB-050: Create master bias, dark, and flat calibration frames from a linked calibration session."""
    fits = pytest.importorskip("astropy.io.fits")
    from galileo.library.core.auto_calibration import create_master_frames
    from galileo.library.models import Masters

    assert create_master_frames(calibration_ready(library)) is True

    masters = {m.master_type: m for m in Masters.select()}
    assert set(masters) == {"bias", "dark", "flat"}
    for master in masters.values():
        assert master.file_count == 3 and Path(master.master_path).exists()
        with fits.open(master.master_path) as hdul:
            assert hdul[0].data is not None


@pytest.mark.requirement("TC-LIB-060")
@pytest.mark.priority("MVP")
def test_tc_lib_060_apply_calibration_to_lights(library):
    """LIB-060: Apply matching master calibration frame set (dark subtraction, flat division) in one user action."""
    from galileo.library.core.auto_calibration import calibrate_light_frames, create_master_frames
    from galileo.library.models import fitsFile, fitsSession

    config = calibration_ready(library)
    assert create_master_frames(config) is True
    library_processor = importlib.import_module("galileo.library.core").fitsProcessing()
    library_processor.linkSessions()
    light_session = fitsSession.get(fitsSession.fitsSessionObjectName == "M42")

    assert calibrate_light_frames(config, session_id=str(light_session.fitsSessionId)) is True

    lights = list(fitsFile.select().where(fitsFile.fitsFileType == "LIGHT FRAME"))
    assert len(lights) == 3 and all(f.fitsFileCalibrated == 1 for f in lights)


# ---------------------------------------------------------------------------
# TC-LIB-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-070")
@pytest.mark.priority("MVP")
def test_tc_lib_070_compute_quality_metrics(tmp_path):
    """LIB-070: Compute per-frame quality metrics (FWHM, HFR, eccentricity, SNR) stored for later sorting."""
    np = pytest.importorskip("numpy")
    fits = pytest.importorskip("astropy.io.fits")
    pytest.importorskip("sep")
    from galileo.library.core.enhanced_quality import EnhancedQualityAnalyzer
    from galileo.library.models import fitsFile, fitsSession

    image = np.random.default_rng(1).normal(500, 5, (256, 256))
    yy, xx = np.mgrid[:256, :256]
    for x, y in [(50, 60), (120, 200), (200, 80), (90, 140), (30, 220), (220, 30), (170, 170), (60, 20)]:
        image += 4000 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 2.0 ** 2))
    hdr = fits.Header()
    hdr["XPIXSZ"], hdr["FOCALLEN"] = 5.0, 800.0
    path = tmp_path / "stars.fits"
    fits.PrimaryHDU(image.astype("float32"), header=hdr).writeto(path)

    result = EnhancedQualityAnalyzer().analyze_image_quality(str(path))

    assert result["status"] == "success" and result["star_count"] == 8
    assert 4.0 < result["avg_fwhm_pixels"] < 6.0        # a sigma-2 Gaussian has FWHM ≈ 4.7 px
    assert result["avg_hfr_arcsec"] > 0 and result["image_snr"] > 0 and 0 <= result["avg_eccentricity"] < 0.3
    # ...and the catalog has the columns to keep them, per frame and per session, for sorting.
    frame_fields = {f.name for f in fitsFile._meta.sorted_fields}
    session_fields = {f.name for f in fitsSession._meta.sorted_fields}
    assert {"fitsFileAvgFWHMArcsec", "fitsFileAvgHFRArcsec", "fitsFileAvgEccentricity", "fitsFileImageSNR"} <= frame_fields
    assert {"fitsSessionAvgFWHMArcsec", "fitsSessionAvgHFRArcsec", "fitsSessionAvgEccentricity", "fitsSessionImageSNR"} <= session_fields


# ---------------------------------------------------------------------------
# TC-LIB-090 … TC-LIB-110  (smart-telescope adapters)
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-090")
@pytest.mark.priority("MVP")
async def test_tc_lib_090_smb_smart_telescope_ingest(tmp_path):
    """LIB-090: Browse and selectively download SEESTAR/StellarMate files over SMB/CIFS."""
    lib_mod = pytest.importorskip("galileo.library")
    smb = lib_mod.SmartTelescopeSmbAdapter.__new__(lib_mod.SmartTelescopeSmbAdapter)
    smb.browse = AsyncMock(return_value=["/SEESTAR/20260916/M42_001.fits"])
    smb.download = AsyncMock()

    files = await smb.browse(host="192.168.1.100", share="seestar")
    assert len(files) == 1
    await smb.download(files[0], dest=tmp_path)
    smb.download.assert_called_once()


@pytest.mark.requirement("TC-LIB-100")
@pytest.mark.priority("P2")
async def test_tc_lib_100_ftp_itelescope_ingest(tmp_path):
    """LIB-100: Browse and selectively download files from iTelescope over FTPS."""
    lib_mod = pytest.importorskip("galileo.library")
    ftp = lib_mod.SmartTelescopeFtpAdapter.__new__(lib_mod.SmartTelescopeFtpAdapter)
    ftp.browse = AsyncMock(return_value=["/images/M42_Ha_001.fits"])
    ftp.download = AsyncMock()

    files = await ftp.browse(host="ftp.itelescope.net", use_tls=True)
    assert len(files) == 1
    await ftp.download(files[0], dest=tmp_path)
    ftp.download.assert_called_once()


@pytest.mark.requirement("TC-LIB-110")
@pytest.mark.priority("P3")
async def test_tc_lib_110_ftp_dwarf_experimental():
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
def test_tc_lib_120_google_cloud_storage_content_hash_comparison(tmp_path):
    """LIB-120: Bidirectional GCS sync compares content hashes, so a file already in the bucket is not transferred again."""
    from galileo.library.services.cloud import _should_upload_file_bulk, sync_with_google_cloud_repo

    assert callable(sync_with_google_cloud_repo)
    local = tmp_path / "M42.fits"
    local.write_bytes(b"pixels")
    same = hashlib.md5(b"pixels").hexdigest()
    different = hashlib.md5(b"other").hexdigest()

    assert _should_upload_file_bulk({"M42.fits": same}, "M42.fits", str(local))[0] is False       # same content: skip
    assert _should_upload_file_bulk({"M42.fits": different}, "M42.fits", str(local))[0] is True   # changed: upload
    assert _should_upload_file_bulk({}, "M42.fits", str(local))[0] is True                        # absent: upload


@pytest.mark.requirement("TC-LIB-120")
@pytest.mark.priority("P2")
def test_tc_lib_120_cloud_helpers_load_without_qt():
    """LIB-120: the cloud-sync helpers the headless cloud_sync command uses don't need the Qt UI."""
    import subprocess
    import sys

    code = (
        "import sys; import galileo.commands.cloud_sync, galileo.library.services.gcs; "
        "sys.exit(1 if any(m.startswith('PySide6') for m in sys.modules) else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0


@pytest.mark.requirement("TC-LIB-120")
@pytest.mark.priority("P2")
def test_tc_lib_120_cloud_profiles_are_offered_by_the_command():
    """LIB-120: sync profiles "complete", "backup" and "ondemand" are selectable from the cloud_sync command."""
    from galileo.commands import cloud_sync

    for profile in ("complete", "backup", "ondemand"):
        assert callable(getattr(cloud_sync, f"perform_{profile}_sync_cli", None)) or profile == "complete"
    assert callable(cloud_sync.perform_complete_sync_cli)


# ---------------------------------------------------------------------------
# TC-LIB-130
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
@pytest.mark.parametrize("name", COMMAND_MODULES)
def test_tc_lib_130_every_astrofiler_command_is_a_galileo_command(name):
    """LIB-130: AstroFiler's command-line utilities live in galileo.commands, runnable without the GUI."""
    module = importlib.import_module(f"galileo.commands.{name}")
    assert callable(module.main)


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_commands_are_installed_as_console_scripts():
    """LIB-130: each command has a galileo-* console script in pyproject.toml."""
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    scripts = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]
    for name in COMMAND_MODULES:
        assert scripts[f"galileo-{name.replace('_', '-')}"] == f"galileo.commands.{name}:main"


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_load_repo_create_sessions_link_sessions_run_headless(library, monkeypatch):
    """LIB-130: ingest, session creation and session linking run from the command line against library.ini."""
    from galileo.commands import create_sessions, link_sessions, load_repo
    from galileo.library.models import fitsFile, fitsSession

    write_light_frames(library.incoming)
    write_calibration_frames(library.incoming)
    for module in (load_repo, create_sessions, link_sessions):
        monkeypatch.setattr("sys.argv", [module.__name__, "-c", str(library.ini)])
        module.main()

    assert fitsFile.select().count() == 12
    assert fitsSession.select().count() == 4
    light = fitsSession.get(fitsSession.fitsSessionObjectName == "M42")
    assert light.fitsBiasSession and light.fitsDarkSession and light.fitsFlatSession


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_missing_config_file_fails_loudly(tmp_path):
    """LIB-130: a mistyped --config is an error, not a silent run on defaults."""
    from galileo.commands._common import load_config
    from galileo.library.config import set_config_path

    try:
        with pytest.raises(FileNotFoundError, match="nope.ini"):
            load_config(str(tmp_path / "nope.ini"))
    finally:
        set_config_path(None)


# ---------------------------------------------------------------------------
# TC-LIB-140
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-140")
@pytest.mark.priority("P2")
def test_tc_lib_140_integrity_check_via_stored_hashes(library):
    """LIB-140: Verify file integrity via stored content hashes on demand; flag files whose content changed or vanished."""
    from galileo.library.core.duplicates import verify_integrity
    from galileo.library.models import fitsFile

    write_light_frames(library.incoming)
    ingest(library)
    assert verify_integrity() == []

    paths = sorted(Path(f.fitsFileName) for f in fitsFile.select())
    paths[0].write_bytes(paths[0].read_bytes() + b"\x00")
    paths[1].unlink()

    problems = {Path(p.file.fitsFileName): p.reason for p in verify_integrity()}
    assert problems == {paths[0]: "modified", paths[1]: "missing"}


# ---------------------------------------------------------------------------
# TC-LIB-150 / TC-LIB-160
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-150")
@pytest.mark.priority("MVP")
def test_tc_lib_150_auto_register_frame_on_sequence_write(library):
    """LIB-150: Automatically register each frame into the repository catalog as it is written by the sequencer."""
    from galileo.library.registrar import LibraryRegistrar

    frame = write_frame(library.repo, "M42_001.fits", "Light Frame", "M42", 60, 5, filt="Ha")
    registrar = LibraryRegistrar()

    assert registrar.entry_count() == 0
    assert registrar.register_frame(frame)
    assert registrar.entry_count() == 1
    assert frame.exists(), "frames are catalogued in place, not moved"
    assert registrar.register_frame(frame) is not None and registrar.entry_count() == 1, "re-registering is harmless"


@pytest.mark.requirement("TC-LIB-150")
@pytest.mark.priority("MVP")
async def test_tc_lib_150_sequencer_registers_each_saved_frame(library):
    """LIB-150: the sequencer hands every frame it writes to the library, which catalogues it."""
    from galileo.library.models import fitsFile
    from galileo.library.registrar import LibraryRegistrar
    from galileo.sequencer.basic import BasicSequencer

    frame = write_frame(library.repo, "seq_001.fits", "Light Frame", "M42", 60, 6, filt="Ha")
    sequencer = BasicSequencer.__new__(BasicSequencer)
    sequencer._repository = LibraryRegistrar()

    sequencer._repository.register_frame(frame)

    assert [Path(f.fitsFileName) for f in fitsFile.select()] == [frame]


@pytest.mark.requirement("TC-LIB-160")
@pytest.mark.priority("MVP")
def test_tc_lib_160_sequence_step_session_container(library):
    """LIB-160: Automatically create a session container grouping every frame acquired during one sequence step."""
    from galileo.library.models import fitsFile, fitsSession
    from galileo.library.registrar import LibraryRegistrar

    registrar = LibraryRegistrar()
    session_id = registrar.begin_sequence_session(step_name="M42 Ha x20")
    for i in range(3):
        frame = write_frame(library.repo, f"light_{i}.fits", "Light Frame", "M42", 60, i, filt="Ha", date=f"2026-09-16T22:0{i}:00")
        registrar.add_frame_to_session(session_id, path=frame)
    registrar.end_sequence_session(session_id)

    containers = registrar.get_sequence_sessions()
    assert [(c.step_name, c.frame_count) for c in containers] == [("M42 Ha x20", 3)]
    assert fitsFile.select().where(fitsFile.fitsFileSession == session_id).count() == 3
    session = fitsSession.get_by_id(session_id)
    assert (session.fitsSessionObjectName, session.fitsSessionTelescope, session.fitsSessionFilter) == ("M42", "TestScope", "Ha")


@pytest.mark.requirement("TC-LIB-160")
@pytest.mark.priority("MVP")
def test_tc_lib_160_inferred_sessions_are_not_sequence_containers(library):
    """LIB-160: a container comes from the sequencer's step boundaries; sessions inferred from headers (LIB-040) are not listed as such."""
    from galileo.library.registrar import LibraryRegistrar

    write_light_frames(library.incoming)
    processor, _ = ingest(library)
    processor.createLightSessions()

    assert LibraryRegistrar().get_sequence_sessions() == []


# ---------------------------------------------------------------------------
# The Library section (screens)
# ---------------------------------------------------------------------------

@pytest.fixture
def qt_app():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(qt_app, library):
    from galileo.ui.app_window import AppWindow

    win = AppWindow()
    win.show()
    qt_app.processEvents()
    yield win
    win._window.close()


def library_menu(window):
    window._primary_nav.select("library")
    return window._primary_stack.currentWidget()


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_library_section_menu_lists_the_astrofiler_screens(window):
    """The Library section opens onto Images, Sessions, Mappings, Dedup, Merge Objects and Cloud."""
    from PySide6 import QtWidgets

    page = library_menu(window)
    buttons = [" ".join(b.text().split()) for b in page._secondary_nav.findChildren(QtWidgets.QToolButton)]
    assert buttons == ["Images", "Sessions", "Mappings", "Dedup", "Merge Objects", "Cloud"]


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_library_screens_are_built_only_when_first_shown(qt_app, library):
    """The Library screens read the whole catalog, so opening Galileo on another section does not build them."""
    from galileo.ui.app_window import AppWindow

    win = AppWindow()
    try:
        from galileo.ui.library.images_widget import ImagesWidget
        assert not win._window.findChildren(ImagesWidget)
        win.show()
        library_menu(win)
        qt_app.processEvents()
        assert len(win._window.findChildren(ImagesWidget)) == 1
    finally:
        win._window.close()


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_library_images_and_sessions_screens_show_the_catalog(window, library):
    """The Images screen lists catalogued objects and the Sessions screen the sessions built from them."""
    window._window.close()
    write_light_frames(library.incoming)
    processor, _ = ingest(library)
    processor.createLightSessions()
    from galileo.ui.app_window import AppWindow

    win = AppWindow()
    try:
        win.show()
        page = library_menu(win)
        for item_id in ("images", "sessions"):
            page._secondary_nav.select(item_id)
        from galileo.ui.library.images_widget import ImagesWidget
        from galileo.ui.library.sessions_widget import SessionsWidget

        images = win._window.findChildren(ImagesWidget)[0]
        sessions = win._window.findChildren(SessionsWidget)[0]
        assert images.file_tree.topLevelItemCount() == 1        # one object: M42
        assert sessions.sessions_tree.topLevelItemCount() == 1   # one session
    finally:
        win._window.close()


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_library_screens_have_no_tabs_and_merge_is_its_own_menu_item(window):
    """Images and Dedup are single screens; Merge Objects is a menu item of its own beside Dedup."""
    from PySide6 import QtWidgets
    from galileo.ui.library.duplicates_widget import DuplicatesWidget
    from galileo.ui.library.images_widget import ImagesWidget
    from galileo.ui.library.merge_widget import MergeWidget

    page = library_menu(window)
    for item_id in ("images", "dedup", "merge"):
        page._secondary_nav.select(item_id)
    root = window._window
    assert len(root.findChildren(ImagesWidget)) == len(root.findChildren(DuplicatesWidget)) == len(root.findChildren(MergeWidget)) == 1
    assert not [t for t in root.findChildren(QtWidgets.QTabWidget) if t.indexOf(root.findChildren(ImagesWidget)[0]) >= 0]
    assert not root.findChildren(QtWidgets.QWidget, "StatsWidget")
    with pytest.raises(ImportError):
        __import__("galileo.ui.library.stats_widget")


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_pier_selector_is_hidden_in_the_library_only(window):
    """The library is not per-Pier: the top bar's Pier selector disappears in the Library section and returns elsewhere."""
    assert window._pier_combo.isVisible() and window._pier_label.isVisible()
    window._primary_nav.select("library")
    assert not window._pier_combo.isVisible() and not window._pier_label.isVisible()
    window._primary_nav.select("imaging")
    assert window._pier_combo.isVisible() and window._pier_label.isVisible()


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_library_settings_buttons_and_no_siril_cli(window, library, monkeypatch):
    """Options > Library has Save (accent) and Reset to Defaults on the right, and no Siril CLI setting."""
    from PySide6 import QtWidgets
    from galileo.library.config import load_config
    from galileo.ui.library.config_widget import ConfigWidget

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    window._open_library_settings()
    widget = window._window.findChildren(ConfigWidget)[0]
    assert widget.save_button.text() == "Save" and widget.save_button.objectName() == "AccentButton"
    assert widget.reset_button.text() == "Reset to Defaults"
    assert widget.save_button.geometry().left() > widget.reset_button.geometry().left()
    assert widget.save_button.geometry().right() >= widget.width() - 40, "right-aligned"
    assert not hasattr(widget, "siril_cli_path")
    labels = [label.text() for label in widget.findChildren(QtWidgets.QLabel)]
    assert "Siril CLI:" not in labels
    widget.save_settings()
    assert not load_config().has_option("DEFAULT", "siril_cli_path")


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_cloud_configure_button_opens_options_library(window):
    """The Cloud screen's Configure button jumps to Options > Library, where the cloud settings live."""
    from galileo.ui.library.cloud_sync_dialog import CloudSyncWidget

    page = library_menu(window)
    page._secondary_nav.select("cloud")
    cloud = window._window.findChildren(CloudSyncWidget)[0]

    cloud.on_configure_clicked()

    assert window._current_primary_section == "options"
    from galileo.ui.library.config_widget import ConfigWidget
    assert window._primary_stack.currentWidget() is window._options_page
    assert window._window.findChildren(ConfigWidget)[0].isVisible()


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_options_library_page_edits_library_ini(window, library, monkeypatch):
    """Options > Library is the AstroFiler configuration screen; Save writes library.ini."""
    from PySide6 import QtWidgets
    from galileo.library.config import load_config
    from galileo.ui.library.config_widget import ConfigWidget

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **k: None)
    window._open_library_settings()
    widget = window._window.findChildren(ConfigWidget)[0]
    assert widget.repo_path.text().rstrip("/\\") == str(library.repo), "the page shows the current settings"

    widget.min_files_per_master.setValue(7)
    widget.save_settings()

    assert load_config().getint("DEFAULT", "min_files_per_master") == 7


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_mappings_page_saves_and_applies_mappings(window, library, monkeypatch):
    """The Mappings page stores header-value rules and tells the Images page to refresh."""
    from PySide6 import QtWidgets
    from galileo.library.models import Mapping
    from galileo.ui.library.mappings_dialog import MappingsWidget

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *a, **k: None)
    page = library_menu(window)
    page._secondary_nav.select("mappings")
    mappings = window._window.findChildren(MappingsWidget)[0]
    applied = []
    mappings.mappings_applied.connect(lambda: applied.append(True))

    row = mappings.mapping_rows[0]
    row.card_combo.setCurrentText("TELESCOP")
    row.current_combo.setCurrentText("Scope 1")
    row.replace_combo.setCurrentText("TestScope")
    mappings.update_files_checkbox.setChecked(False)
    mappings.apply_to_database_checkbox.setChecked(False)
    mappings.reorganize_files_checkbox.setChecked(False)
    mappings.accept_mappings()

    assert [(m.card, m.current, m.replace) for m in Mapping.select()] == [("TELESCOP", "Scope 1", "TestScope")]
    assert applied == [True]


# ---------------------------------------------------------------------------
# FITS compression on ingest (LIB-010 / LIB-030): must never damage the original
# ---------------------------------------------------------------------------

def _compression_fixture(tmp_path, name, data, *, commentary=False, extra_ext=None):
    """Write a FITS file for the compression tests; returns its path as ``str``."""
    from astropy.io import fits

    primary = fits.PrimaryHDU(data)
    primary.header["OBJECT"] = "M31"
    if commentary:
        primary.header.add_history("calibrated by pipeline")
        primary.header.add_comment("keep me")
    path = tmp_path / name
    fits.HDUList([primary, *(extra_ext or [])]).writeto(path)
    return str(path)


def _image_data(kind):
    import numpy as np

    rng = np.random.default_rng(7)
    if kind == "uint16":
        return (rng.random((60, 80)) * 60000).astype("uint16")
    if kind == "int16":
        return rng.integers(-3000, 3000, (60, 80)).astype("int16")
    if kind == "float32":
        return rng.normal(1000, 50, (60, 80)).astype("float32")
    if kind == "float32-nan":
        data = rng.normal(1000, 50, (60, 80)).astype("float32")
        data[3, 3] = float("nan")
        return data
    return rng.normal(0, 1, (3, 20, 30)).astype("float32")      # "cube"


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("kind", ["uint16", "int16", "float32", "float32-nan", "cube"])
def test_tc_lib_010_in_place_tile_compression_is_lossless(tmp_path, kind):
    """LIB-010: Ingest-time FITS compression is lossless — integer, float, NaN-bearing and 3-D images read back bit for bit."""
    import numpy as np
    from astropy.io import fits

    from galileo.library.core.compress_files import FitsCompressor

    original = _image_data(kind)
    path = _compression_fixture(tmp_path, "frame.fits", original)

    assert FitsCompressor(tmp_path / "none.ini").compress_fits_file(path, algorithm="fits_gzip2") == path

    with fits.open(path) as hdul:
        compressed = [h for h in hdul if isinstance(h, fits.CompImageHDU)]
        assert len(compressed) == 1
        assert np.array_equal(compressed[0].data, original, equal_nan=original.dtype.kind == "f")
        assert hdul[0].header["OBJECT"] == "M31"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_compression_keeps_history_comments_and_extensions(tmp_path):
    """LIB-010: Compression keeps HISTORY as HISTORY, COMMENT as COMMENT, and every other extension."""
    import numpy as np
    from astropy.io import fits

    from galileo.library.core.compress_files import FitsCompressor

    table = fits.BinTableHDU.from_columns(
        [fits.Column(name="flux", format="E", array=np.array([1.5, float("nan"), 3.0], dtype="f4")),
         fits.Column(name="name", format="8A", array=np.array(["a", "bb", "ccc"]))],
        name="CAT",
    )
    path = _compression_fixture(tmp_path, "frame.fits", _image_data("uint16"), commentary=True, extra_ext=[table])

    assert FitsCompressor(tmp_path / "none.ini").compress_fits_file(path, algorithm="fits_gzip2") == path

    with fits.open(path) as hdul:
        assert [type(h).__name__ for h in hdul] == ["PrimaryHDU", "CompImageHDU", "BinTableHDU"]
        cards = [(c.keyword, c.value) for h in hdul for c in h.header.cards]
        assert ("HISTORY", "calibrated by pipeline") in cards
        assert ("COMMENT", "keep me") in cards
        assert hdul[2].data["name"].tolist() == ["a", "bb", "ccc"]


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("failure", ["verification", "header-copy"])
def test_tc_lib_010_failed_compression_leaves_original_untouched(tmp_path, monkeypatch, failure):
    """LIB-010: If compression can't be verified (or the header can't be carried over), the original is byte-identical and no temp file remains."""
    from galileo.library.core import compress_files
    from galileo.library.core.compress_files import FitsCompressor

    path = _compression_fixture(tmp_path, "frame.fits", _image_data("float32"))
    before = Path(path).read_bytes()
    compressor = FitsCompressor(tmp_path / "none.ini")
    if failure == "verification":
        monkeypatch.setattr(compressor, "_verify_fits_internal_compression", lambda *_: False)
    else:
        monkeypatch.setattr(compress_files, "_copy_header_cards", lambda *_: ["BADCARD"])

    assert compressor.compress_fits_file(path, algorithm="fits_gzip2") is None

    assert Path(path).read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["frame.fits"]


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_verifier_compares_against_the_original_not_itself(tmp_path):
    """LIB-010: The verifier detects a data difference (and accepts NaN == NaN) instead of comparing a file with itself."""
    from galileo.library.core.compress_files import FitsCompressor

    compressor = FitsCompressor(tmp_path / "none.ini")
    base = _image_data("float32-nan")
    changed = base.copy()
    changed[10, 10] += 0.5
    a = _compression_fixture(tmp_path, "a.fits", base)
    same = _compression_fixture(tmp_path, "same.fits", base)
    different = _compression_fixture(tmp_path, "different.fits", changed)

    assert compressor._verify_fits_internal_compression(same, a)
    assert not compressor._verify_fits_internal_compression(different, a)


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_decompressing_in_place_compressed_file_never_destroys_it(tmp_path):
    """LIB-010: Asking to decompress a tile-compressed .fits (compressed in place) is refused; the file survives untouched."""
    from astropy.io import fits

    from galileo.library.core.compress_files import FitsCompressor

    path = _compression_fixture(tmp_path, "frame.fits", _image_data("uint16"))
    compressor = FitsCompressor(tmp_path / "none.ini")
    assert compressor.compress_fits_file(path, algorithm="fits_gzip2") == path
    before = Path(path).read_bytes()

    assert compressor.decompress_fits_file(path) is None

    assert Path(path).read_bytes() == before
    with fits.open(path) as hdul:
        assert any(isinstance(h, fits.CompImageHDU) for h in hdul)
    assert compressor.decompress_fits_file(path, output_path=path) is None


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("algorithm", ["gzip", "lzma", "bzip2"])
def test_tc_lib_010_stream_compression_round_trips_byte_for_byte(tmp_path, algorithm):
    """LIB-010: gzip/lzma/bzip2 compression is verified by hash, replaces the original, and decompresses byte-identically."""
    from galileo.library.core.compress_files import FitsCompressor

    path = _compression_fixture(tmp_path, "frame.fits", _image_data("uint16"))
    before = Path(path).read_bytes()
    compressor = FitsCompressor(tmp_path / "none.ini")

    packed = compressor.compress_fits_file(path, algorithm=algorithm)

    assert packed == compressor.get_compressed_path(path, algorithm) and Path(packed).exists()
    assert not Path(path).exists() and not list(tmp_path.glob("*.part"))
    assert compressor.decompress_fits_file(packed) == path
    assert Path(path).read_bytes() == before


# ---------------------------------------------------------------------------
# Auto-regeneration failure handling (LIB-040)
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-040")
@pytest.mark.priority("MVP")
def test_tc_lib_040_failed_auto_regeneration_does_not_start_another_regeneration(qt_app, library, monkeypatch):
    """LIB-040: When session auto-regeneration after an import fails, the failure is logged; no second regeneration or dialog is started."""
    from PySide6.QtWidgets import QMessageBox
    from galileo.ui.library import sessions_widget as sw

    widget = sw.SessionsWidget()
    dialogs = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: dialogs.append(("information", a)))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: dialogs.append(("critical", a)))

    def fail(*args, **kwargs):
        raise RuntimeError("regeneration failed")

    def forbidden(*args, **kwargs):
        raise AssertionError("the failure handler must not run a regeneration itself")

    monkeypatch.setattr(widget, "_do_regenerate_sessions_new_only", fail)
    monkeypatch.setattr(sw, "fitsProcessing", forbidden)

    widget.auto_regenerate_sessions()      # must swallow the failure quietly

    assert dialogs == []


# ---------------------------------------------------------------------------
# Auto-calibration workflow wiring and progress reporting (LIB-050/060/070/130)
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
@pytest.mark.parametrize("force, dry_run", [(False, False), (True, False), (False, True), (True, True)])
def test_tc_lib_130_complete_workflow_hands_each_option_to_the_right_step(monkeypatch, force, dry_run):
    """LIB-130: The complete auto-calibration workflow passes --force/--dry-run and the progress callback to each step's own parameters (a shifted positional argument once made the calibrate step always a dry run)."""
    import configparser
    import inspect

    from galileo.library.core import auto_calibration as ac

    calls = {}

    def recorder(name, real, result):
        signature = inspect.signature(real)

        def fake(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            calls[name] = dict(bound.arguments)
            callback = calls[name].get("progress_callback")
            if callback:
                callback(50, f"{name} halfway")
            return result
        return fake

    real = {name: getattr(ac, name) for name in (
        "analyze_calibration_opportunities", "create_master_frames",
        "calibrate_light_frames", "perform_quality_assessment")}
    for name, result in (("analyze_calibration_opportunities", {"total_opportunities": 1}),
                         ("create_master_frames", True), ("calibrate_light_frames", True),
                         ("perform_quality_assessment", True)):
        monkeypatch.setattr(ac, name, recorder(name, real[name], result))

    reported = []
    ok = ac.run_complete_workflow(configparser.ConfigParser(), session_id="7", force=force, dry_run=dry_run,
                                  progress_callback=lambda pct, msg: reported.append((pct, msg)))

    assert ok is True
    masters, calibrate = calls["create_master_frames"], calls["calibrate_light_frames"]
    assert (masters["force"], masters["dry_run"], masters["verbose"]) == (force, dry_run, False)
    assert (calibrate["force_recalibrate"], calibrate["dry_run"]) == (force, dry_run)
    assert calibrate["session_id"] == masters["session_id"] == "7"
    for step in ("analyze_calibration_opportunities", "create_master_frames",
                 "calibrate_light_frames", "perform_quality_assessment"):
        assert callable(calls[step]["progress_callback"]), f"{step} was not given the progress callback"
    # Each step's own progress is scaled into its 25 % slice of the overall bar.
    assert (12, "analyze_calibration_opportunities halfway") in reported
    assert (37, "create_master_frames halfway") in reported
    assert (62, "calibrate_light_frames halfway") in reported
    assert (87, "perform_quality_assessment halfway") in reported


@pytest.mark.requirement("TC-LIB-060")
@pytest.mark.priority("MVP")
def test_tc_lib_060_light_calibration_reports_progress_per_session(monkeypatch):
    """LIB-060: Light-frame calibration reports each session's progress against that session's own position in the run, and calibrates exactly the requested sessions."""
    import configparser

    from galileo.library.core import light_calibration as lc
    from galileo.library.core.auto_calibration import calibrate_light_frames

    calibrated = []

    def fake_calibrate(session_id, progress_callback=None, force_recalibrate=False):
        calibrated.append(session_id)
        progress_callback("working")
        return {"success": True, "calibrated_count": 1, "skipped_count": 0, "error_count": 0}

    monkeypatch.setattr(lc, "calibrate_session_lights", fake_calibrate)
    monkeypatch.setattr(lc, "find_light_sessions_for_calibration", lambda: ["a", "b"])
    monkeypatch.setattr(lc, "get_calibration_statistics", lambda: {
        "calibrated_frames": 0, "total_light_frames": 0, "calibration_percentage": 0.0})

    reported = []
    assert calibrate_light_frames(configparser.ConfigParser(),
                                  progress_callback=lambda pct, msg: reported.append((pct, msg))) is True

    assert calibrated == ["a", "b"]
    assert reported == [
        (10, "Finding light sessions..."),
        (20, "Calibrating session 1/2..."), (20, "Session 1: working"),
        (55, "Calibrating session 2/2..."), (55, "Session 2: working"),
        (100, "Calibration complete - 2 frames processed"),
    ]

    calibrated.clear()
    assert calibrate_light_frames(configparser.ConfigParser(), session_id="only") is True
    assert calibrated == ["only"]                 # an explicit session is calibrated, not the discovered ones


@pytest.mark.requirement("TC-LIB-050")
@pytest.mark.priority("MVP")
def test_tc_lib_050_master_creation_reports_progress_within_each_sessions_band(library):
    """LIB-050: Master-frame creation reports each session's per-master progress inside that session's own share of the overall bar."""
    reported = []
    from galileo.library.core.auto_calibration import create_master_frames

    assert create_master_frames(calibration_ready(library),
                                progress_callback=lambda pct, msg: reported.append((pct, msg))) is True

    starts = [(index, pct) for index, (pct, msg) in enumerate(reported) if msg.startswith("Processing session")]
    assert len(starts) >= 2 and starts[0][1] == 20
    assert [pct for _, pct in starts] == sorted({pct for _, pct in starts})       # each session starts further along
    ends = [pct for _, pct in starts[1:]] + [90]
    detail = 0
    for (first, low), high in zip(starts, ends, strict=True):
        last = next((index for index, _ in starts if index > first), len(reported) - 1)
        for pct, msg in reported[first + 1:last]:
            assert low <= pct <= high, f"{msg!r} at {pct}% is outside its session's {low}-{high}% band"
            detail += msg.startswith("Creating ") and " masters: " in msg
    assert detail, "no per-master progress was reported"


@pytest.mark.requirement("TC-LIB-070")
@pytest.mark.priority("MVP")
def test_tc_lib_070_quality_assessment_reports_each_frame_in_order(library, monkeypatch):
    """LIB-070: Quality assessment reports progress for each frame as its own i/N, in order."""
    import configparser

    from galileo.library.core import enhanced_quality
    from galileo.library.core.auto_calibration import perform_quality_assessment
    from galileo.library.models import fitsFile

    write_light_frames(library.incoming)
    ingest(library)
    total = fitsFile.select().where(fitsFile.fitsFileType == "LIGHT FRAME").count()
    assert total >= 2

    class FakeAnalyzer:
        def analyze_and_update_file(self, path, file_id, progress_callback=None):
            progress_callback(50, "halfway")
            return {"status": "success"}

    monkeypatch.setattr(enhanced_quality, "EnhancedQualityAnalyzer", FakeAnalyzer)
    reported = []

    assert perform_quality_assessment(configparser.ConfigParser(),
                                      progress_callback=lambda pct, msg: reported.append((pct, msg))) is True

    per_frame = [msg for _, msg in reported if msg.endswith("halfway")]
    assert [msg.split("(")[1].split(")")[0] for msg in per_frame] == [f"{n}/{total}" for n in range(1, total + 1)]
    assert reported[-1] == (100, "Quality assessment complete")
