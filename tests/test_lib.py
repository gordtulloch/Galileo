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

import datetime
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

def write_frame(folder, name, frame_type, obj, exposure, seed, *, filt="", date="2026-09-16T22:00:00", level=1000.0,
                 telescop="TestScope", instrume="TestCam"):
    """Write a small FITS frame with the headers the library sorts on."""
    np = pytest.importorskip("numpy")
    fits = pytest.importorskip("astropy.io.fits")
    hdr = fits.Header()
    hdr["IMAGETYP"], hdr["OBJECT"], hdr["EXPTIME"] = frame_type, obj, exposure
    if filt:
        hdr["FILTER"] = filt
    hdr["DATE-OBS"], hdr["CCD-TEMP"] = date, -10.0
    hdr["XBINNING"] = hdr["YBINNING"] = 1
    hdr["TELESCOP"], hdr["INSTRUME"], hdr["GAIN"], hdr["OFFSET"] = telescop, instrume, 100, 10
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
        assert {c.name for c in db.get_columns("device_configs")} >= {"bayer_pattern", "max_well_depth"}
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


@pytest.mark.requirement("TC-LIB-050")
@pytest.mark.priority("P2")
def test_tc_lib_050_master_validate_link_and_cleanup_use_the_masters_columns(library):
    """LIB-050: validating, linking and cleaning up masters works on the Masters/fitsSession columns that exist
    (``master_path``/``hash_value``, ``fits*Master``) - it used to read non-existent ``file_path``/``master_bias``."""
    from galileo.library.core.auto_calibration import create_master_frames
    from galileo.library.core.master_manager import MasterFrameManager
    from galileo.library.models import Masters, fitsSession

    assert create_master_frames(calibration_ready(library)) is True
    manager = MasterFrameManager()

    results = manager.validate_masters()
    assert results.get("valid_masters") == 3 and results["invalid_masters"] == 0 and results["missing_files"] == 0

    bias = Masters.get(Masters.master_type == "bias")
    session = fitsSession.select().first()
    assert manager.update_session_with_master(session.fitsSessionId, bias.id, "bias") is True
    assert fitsSession.get_by_id(session.fitsSessionId).fitsBiasMaster == bias.master_id

    stale = datetime.datetime(2000, 1, 1)
    Masters.update(creation_date=stale).execute()
    cleaned = manager.cleanup_masters(retention_days=30)
    assert "error" not in cleaned and cleaned["errors"] == []
    assert Masters.select().where(Masters.master_id == bias.master_id).count() == 1, "a master in use is kept"
    assert Masters.select().count() == 1 and cleaned["deleted_masters"] == 2


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


@pytest.mark.requirement("TC-LIB-060")
@pytest.mark.priority("P2")
def test_tc_lib_060_workflow_reports_the_real_calibrated_frame_count(library):
    """LIB-060: runAutoCalibrationWorkflow's light_frames_calibrated is the frames actually calibrated
    in this run, not a fixed placeholder count."""
    from galileo.library.core import fitsProcessing
    from galileo.library.core.auto_calibration import create_master_frames

    config = calibration_ready(library)
    assert create_master_frames(config) is True
    fitsProcessing().linkSessions()

    results = fitsProcessing().runAutoCalibrationWorkflow(operations=["calibrate"])

    assert results["status"] == "success" and not results["errors"]
    assert results["light_frames_calibrated"] == 3


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
# TC-LIB-170  (SFTP server source)
# ---------------------------------------------------------------------------

def _fake_sftp_server(tree, *, deleted=None, fail_on=()):
    """A stand-in ``paramiko`` whose server holds *tree* ({directory: [(name, size) | name/ for a folder]})."""
    import stat
    import types

    class Entry:
        def __init__(self, name, size, is_dir):
            self.filename, self.st_size = name, size
            self.st_mode = (stat.S_IFDIR if is_dir else stat.S_IFREG) | 0o755

    class Sftp:
        def listdir_attr(self, path):
            return [Entry(n.rstrip("/"), s, n.endswith("/")) for n, s in tree[path.rstrip("/") or "/"]]

        def get(self, remote, local, callback=None):
            if remote in fail_on:
                raise OSError("transfer failed")
            with open(local, "wb") as fh:
                fh.write(b"SIMPLE")
            if callback:
                callback(6, 6)

        def remove(self, remote):
            deleted.append(remote)

        def close(self):
            pass

    class SSHClient:
        def load_system_host_keys(self):
            pass

        def set_missing_host_key_policy(self, policy):
            pass

        def connect(self, **kwargs):
            SSHClient.connected_with = kwargs

        def open_sftp(self):
            return Sftp()

        def close(self):
            pass

    module = types.ModuleType("paramiko")
    module.SSHClient = SSHClient
    module.RejectPolicy = type("RejectPolicy", (), {})
    module.MissingHostKeyPolicy = type("MissingHostKeyPolicy", (), {})
    return module


@pytest.fixture
def sftp_settings(library, monkeypatch):
    """library.ini carrying an SFTP account; the keychain is faked so no test touches the real one."""
    library.ini.write_text(
        library.ini.read_text()
        + "sftp_username = astro\nsftp_remote_path = /data\nsftp_port = 2222\nsftp_key_path = /keys/id\n"
    )
    stored = {"password": "s3cret"}
    monkeypatch.setattr("galileo.library.config.get_sftp_password", lambda: stored["password"])
    monkeypatch.setattr("galileo.library.config.set_sftp_password", lambda pw: stored.update(password=pw))
    # the Options widget imported the two functions by name, so patch its references as well
    monkeypatch.setattr("galileo.ui.library.config_widget.get_sftp_password", lambda: stored["password"])
    monkeypatch.setattr("galileo.ui.library.config_widget.set_sftp_password", lambda pw: stored.update(password=pw))
    return stored


@pytest.mark.requirement("TC-LIB-170")
@pytest.mark.priority("P2")
def test_tc_lib_170_sftp_server_browse_download_and_delete(sftp_settings, tmp_path):
    """LIB-170: Browse and selectively download files from an SFTP server — every FITS file under the configured
    folder (recursively, skipping other files), downloaded with the configured account, key and port, and
    deletable from the server afterwards."""
    import sys
    from unittest.mock import patch
    from galileo.library.services.telescope import SmartTelescopeManager

    tree = {
        "/data": [("m42_001.fits", 10), ("notes.txt", 3), ("night1/", 0)],
        "/data/night1": [("m31_001.FIT", 20), ("m31_002.zip", 30), ("readme.md", 1)],
    }
    deleted = []
    module = _fake_sftp_server(tree, deleted=deleted)
    manager = SmartTelescopeManager()
    with patch.dict(sys.modules, {"paramiko": module}):
        files, error = manager.get_fits_files("SFTP", "observatory.example")
        assert error is None
        assert sorted(f["path"] for f in files) == ["/data/m42_001.fits", "/data/night1/m31_001.FIT", "/data/night1/m31_002.zip"]
        nested = next(f for f in files if f["name"] == "m31_001.FIT")
        assert (nested["size"], nested["folder_name"]) == (20, "night1")
        # the configured account, key, port and keychain password reached the connection
        assert module.SSHClient.connected_with["username"] == "astro"
        assert module.SSHClient.connected_with["key_filename"] == "/keys/id"
        assert module.SSHClient.connected_with["port"] == 2222
        assert module.SSHClient.connected_with["password"] == "s3cret"

        local = tmp_path / "out" / "m42_001.fits"
        ok, error = manager.download_file("SFTP", "observatory.example", files[0], str(local))
        assert ok and error is None and local.read_bytes() == b"SIMPLE"

        ok, error = manager.delete_file("SFTP", "observatory.example", files[0])
        assert ok and deleted == [files[0]["path"]]


@pytest.mark.requirement("TC-LIB-170")
@pytest.mark.priority("P2")
def test_tc_lib_170_sftp_failures_are_reported_and_cancel_leaves_no_partial_file(sftp_settings, tmp_path):
    """LIB-170: an unreachable server or failed transfer comes back as an error message (not an empty success), a
    cancelled download stops cleanly with no partial file, and an SFTP source is addressed by hostname, never scanned for."""
    import sys
    from unittest.mock import patch
    from galileo.library.services.telescope import SmartTelescopeManager

    manager = SmartTelescopeManager()
    assert manager.find_telescope("SFTP", hostname="observatory.example") == ("observatory.example", None)
    ip, error = manager.find_telescope("SFTP", network_range="10.0.0.0/24")
    assert ip is None and "hostname" in error

    module = _fake_sftp_server({"/data": [("a.fits", 1)]}, fail_on=("/data/a.fits",))
    module.SSHClient.connect = lambda self, **kw: (_ for _ in ()).throw(OSError("no route to host"))
    with patch.dict(sys.modules, {"paramiko": module}):
        files, error = manager.get_fits_files("SFTP", "203.0.113.9")
    assert files == [] and "no route to host" in error

    module = _fake_sftp_server({"/data": [("a.fits", 1)]}, fail_on=("/data/a.fits",))
    with patch.dict(sys.modules, {"paramiko": module}):
        ok, error = manager.download_file("SFTP", "h", {"name": "a.fits", "path": "/data/a.fits", "size": 1}, str(tmp_path / "a.fits"))
    assert not ok and "transfer failed" in error and not (tmp_path / "a.fits").exists()

    module = _fake_sftp_server({"/data": [("a.fits", 1)]})
    with patch.dict(sys.modules, {"paramiko": module}):
        ok, error = manager.download_file("SFTP", "h", {"name": "a.fits", "path": "/data/a.fits", "size": 1},
                                          str(tmp_path / "b.fits"), progress_callback=lambda done: False)
    assert not ok and "cancelled" in error.lower() and not (tmp_path / "b.fits").exists()


@pytest.mark.requirement("TC-LIB-170")
@pytest.mark.priority("P2")
def test_tc_lib_170_sftp_is_offered_in_download_dialog_and_options(window, sftp_settings, monkeypatch):
    """LIB-170: the Download dialog lists an SFTP source (no network range needed) and Options > Library > Smart
    Telescopes holds its account, key, folder, port and host-key policy, with the password kept in the keychain."""
    from PySide6 import QtWidgets
    from galileo.library.config import load_config
    from galileo.ui.library.config_widget import ConfigWidget
    from galileo.ui.library.download_dialog import SmartTelescopeDownloadDialog

    dialog = SmartTelescopeDownloadDialog()
    names = [dialog.telescope_list.item(i).text() for i in range(dialog.telescope_list.count())]
    assert "SFTP" in names
    dialog.telescope_list.setCurrentRow(names.index("SFTP"))
    assert dialog.hostname_edit.text() == "" and not dialog.network_edit.isEnabled()
    dialog.telescope_list.setCurrentRow(0)
    assert dialog.network_edit.isEnabled()

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    window._open_library_settings()
    widget = window._window.findChildren(ConfigWidget)[0]
    assert (widget.sftp_username.text(), widget.sftp_remote_path.text(), widget.sftp_port.value()) == ("astro", "/data", 2222)
    assert widget.sftp_password.text() == "s3cret"
    widget.sftp_username.setText("newuser")
    widget.sftp_password.setText("changed")
    widget.sftp_strict_host_keys.setChecked(True)
    widget.save_settings()
    config = load_config()
    assert config.get("DEFAULT", "sftp_username") == "newuser"
    assert config.get("DEFAULT", "sftp_strict_host_keys") == "True"
    assert "changed" not in Path(library_ini_path(config)).read_text()    # never in the ini file
    assert sftp_settings["password"] == "changed"                      # went to the (fake) keychain


def library_ini_path(_config):
    from galileo.library.config import get_config_path
    return get_config_path()


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
        with pytest.raises(FileNotFoundError, match=r"nope\.ini"):
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
    """LIB-150: Automatically register each frame into the repository catalog as it is written by a session."""
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
async def test_tc_lib_150_session_registers_each_saved_frame(library):
    """LIB-150: the session executor hands every frame it writes to the library, which catalogues it."""
    from galileo.library.models import fitsFile
    from galileo.library.registrar import LibraryRegistrar

    frame = write_frame(library.repo, "seq_001.fits", "Light Frame", "M42", 60, 6, filt="Ha")
    LibraryRegistrar().register_frame(frame)

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
    """LIB-160: a container comes from the session executor's step boundaries; sessions inferred from headers (LIB-040) are not listed as such."""
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


def wait_for_library_loads(qt_app, root, timeout=10.0):
    """Pump the Qt loop until the Images/Sessions screens under *root* finish their background loads."""
    import time
    from galileo.ui.library.images_widget import ImagesWidget
    from galileo.ui.library.sessions_widget import SessionsWidget
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        trees = [w.file_tree for w in root.findChildren(ImagesWidget)] +                 [w.sessions_tree for w in root.findChildren(SessionsWidget)]
        if all(t.isEnabled() for t in trees):
            return
        time.sleep(0.01)
    raise AssertionError("Library screens did not finish loading")


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_library_images_and_sessions_screens_show_the_catalog(qt_app, window, library):
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
        wait_for_library_loads(qt_app, win._window)
        assert images.file_tree.topLevelItemCount() == 1        # one object: M42
        assert sessions.sessions_tree.topLevelItemCount() == 1   # one session
    finally:
        win._window.close()


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_library_images_screen_refreshes_when_reopened_after_new_frames(qt_app, window, library):
    """Frames registered while the Library is hidden (e.g. by a Session run) appear when it is reopened."""
    from galileo.ui.library.images_widget import ImagesWidget

    window.show()
    library_menu(window)._secondary_nav.select("images")
    qt_app.processEvents()
    images = window._window.findChildren(ImagesWidget)[0]
    assert images.file_tree.topLevelItemCount() == 0

    window._primary_nav.select("equipment")
    qt_app.processEvents()
    write_light_frames(library.incoming)
    ingest(library)
    assert images.file_tree.topLevelItemCount() == 0    # hidden: not reloaded behind the user's back

    library_menu(window)
    wait_for_library_loads(qt_app, window._window)
    assert images.file_tree.topLevelItemCount() == 1    # one object: M42


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


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("P2")
def test_mappings_apply_button_gates_each_effect_on_its_own_checkbox(window, library, monkeypatch):
    """The Mappings page's per-row Apply button gates the catalog update, the on-disk FITS header
    rewrite, and the file move independently on their own checkbox, rather than one combined flag."""
    from astropy.io import fits as astropy_fits
    from PySide6 import QtWidgets
    from galileo.library.models import fitsFile as FitsFileModel
    from galileo.ui.library.mappings_dialog import MappingsWidget

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *a, **k: QtWidgets.QMessageBox.Yes)

    write_frame(library.incoming, "a.fits", "Light Frame", "M42", 60, 1, telescop="ScopeA")
    write_frame(library.incoming, "b.fits", "Light Frame", "M42", 60, 2, telescop="ScopeB")
    write_frame(library.incoming, "c.fits", "Light Frame", "M42", 60, 3, telescop="ScopeC")
    ingest(library)

    def record_for(telescope):
        return FitsFileModel.get(FitsFileModel.fitsFileTelescop == telescope)

    page = library_menu(window)
    page._secondary_nav.select("mappings")
    mappings = window._window.findChildren(MappingsWidget)[0]

    def apply_row(current, replace, *, apply_to_db, update_headers, reorganize):
        row = mappings.mapping_rows[0]
        row.card_combo.setCurrentText("TELESCOP")
        row.current_combo.setCurrentText(current)
        row.replace_combo.setCurrentText(replace)
        mappings.apply_to_database_checkbox.setChecked(apply_to_db)
        mappings.update_files_checkbox.setChecked(update_headers)
        mappings.reorganize_files_checkbox.setChecked(reorganize)
        mappings.apply_single_mapping(row)

    # "Apply mappings to database" alone: the catalog record changes, the file on disk is untouched.
    old_path = record_for("ScopeA").fitsFileName
    apply_row("ScopeA", "NewA", apply_to_db=True, update_headers=False, reorganize=False)
    assert record_for("NewA").fitsFileName == old_path
    assert astropy_fits.getheader(old_path)["TELESCOP"] == "ScopeA"

    # "Update FITS headers on disk" alone: the file's header changes, the catalog record doesn't.
    old_path = record_for("ScopeB").fitsFileName
    apply_row("ScopeB", "NewB", apply_to_db=False, update_headers=True, reorganize=False)
    assert record_for("ScopeB").fitsFileName == old_path
    assert astropy_fits.getheader(old_path)["TELESCOP"] == "NewB"

    # "Reorganize repository folders" alone: the file moves and its catalog path follows, but
    # the TELESCOP field/header value itself is left alone.
    old_path = record_for("ScopeC").fitsFileName
    apply_row("ScopeC", "NewC", apply_to_db=False, update_headers=False, reorganize=True)
    moved = record_for("ScopeC")
    assert moved.fitsFileName != old_path
    assert "NewC" in moved.fitsFileName
    assert not os.path.exists(old_path)
    assert astropy_fits.getheader(moved.fitsFileName)["TELESCOP"] == "ScopeC"


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
    monkeypatch.setattr("galileo.ui.library.sessions_regenerate.fitsProcessing", forbidden)

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
def test_tc_lib_050_sigma_clipped_light_stack_keeps_its_edges(tmp_path):
    """LIB-050: the sigma-clip stacker behind the masters also stacks registered lights
    (``galileo.commands.stack``). Where frames drifted, a pixel covered by only some of them is
    stacked from those, not discarded, and nothing is written as a garbage NaN-to-integer cast."""
    import warnings
    np = pytest.importorskip("numpy")
    fits = pytest.importorskip("astropy.io.fits")
    pytest.importorskip("astroalign")
    from galileo.library.core.master_manager import MasterFrameManager

    size = 200
    stars = [(30, 40), (70, 120), (120, 60), (100, 100), (40, 150), (150, 150), (55, 80), (170, 30), (90, 170), (160, 90)]
    yy, xx = np.mgrid[:size, :size]
    paths = []
    for i, (dy, dx) in enumerate([(0, 0), (6, -8), (-5, 7), (3, 4)]):       # the reference is unshifted
        image = np.random.default_rng(i).normal(500, 5, (size, size))
        for n, (y, x) in enumerate(stars):
            image += (3000 + 400 * n) * np.exp(-((yy - y - dy) ** 2 + (xx - x - dx) ** 2) / (2 * 1.8 ** 2))
        path = tmp_path / f"light_{i}.fits"
        fits.PrimaryHDU(image.astype(np.uint16)).writeto(path)
        paths.append(str(path))

    out = tmp_path / "stack.fits"
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)              # e.g. "invalid value encountered in cast"
        assert MasterFrameManager.__new__(MasterFrameManager)._create_master_sigma_clip(paths, str(out), "light")

    with fits.open(out) as hdul:
        stacked, header = hdul[0].data.astype(float), hdul[0].header
    # The reference covers every pixel, so every pixel has data — the drifted edges included.
    assert header["NODATA"] == 0
    assert stacked.min() > 450 and 480 < np.median(stacked[:, :8]) < 520 and 480 < np.median(stacked[-6:, :]) < 520
    # And the stars are registered, not smeared: the brightest is as bright as in the reference.
    assert stacked.max() == pytest.approx(float(fits.getdata(paths[0]).max()), rel=0.05)


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


@pytest.mark.requirement("TC-LIB-070")
@pytest.mark.priority("P2")
def test_tc_lib_070_quality_assessment_writes_a_report_when_requested(library, monkeypatch, tmp_path):
    """LIB-070: passing generate_report writes a per-file CSV quality report, not just a log line."""
    import configparser
    import csv

    import galileo.platform
    from galileo.library.core import enhanced_quality
    from galileo.library.core.auto_calibration import perform_quality_assessment
    from galileo.library.models import fitsFile

    write_light_frames(library.incoming)
    ingest(library)
    total = fitsFile.select().where(fitsFile.fitsFileType == "LIGHT FRAME").count()

    reports_dir = tmp_path / "reports"

    def fake_get_reports_dir():
        reports_dir.mkdir(parents=True, exist_ok=True)
        return reports_dir

    monkeypatch.setattr(galileo.platform, "get_reports_dir", fake_get_reports_dir)

    class FakeAnalyzer:
        def analyze_and_update_file(self, path, file_id, progress_callback=None):
            return {"status": "success", "star_count": 42, "avg_hfr_arcsec": 1.5}

    monkeypatch.setattr(enhanced_quality, "EnhancedQualityAnalyzer", FakeAnalyzer)

    assert perform_quality_assessment(configparser.ConfigParser(), generate_report=True) is True

    reports = list(reports_dir.glob("quality-report-*.csv"))
    assert len(reports) == 1
    with open(reports[0], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    data_rows = [r for r in rows if r.get("file")]
    assert len(data_rows) == total + 1, "one row per analyzed file plus the summary row"
    assert all(r["star_count"] == "42" and r["avg_hfr_arcsec"] == "1.5" for r in data_rows[:-1])
    assert data_rows[-1]["file"] == "SUMMARY" and f"{total}/{total}" in data_rows[-1]["status"]


# ---------------------------------------------------------------------------
# TC-LIB-010  (XISF import reads an untrusted header)
# ---------------------------------------------------------------------------

def _write_xisf(path, header_xml: str):
    import struct
    body = header_xml.encode("utf-8")
    path.write_bytes(b"XISF0100" + struct.pack("<I", len(body)) + struct.pack("<I", 0) + body)
    return str(path)


_XISF_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
    '<Image geometry="4:4:1" sampleFormat="UInt16" location="attachment:100:32">'
    '<FITSKeyword name="OBJECT" value="M42" comment="target"/></Image></xisf>'
)


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xisf_header_is_parsed(tmp_path):
    """LIB-010: a well-formed XISF header is read (its FITS keywords come through) after the switch to a hardened XML parser."""
    from galileo.library.file_formats.xisfFile.xisf_converter import XISFConverter
    converter = XISFConverter(_write_xisf(tmp_path / "ok.xisf", _XISF_HEADER))
    assert converter.get_header_cards().get("OBJECT") == "M42"


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xisf_header_with_entity_expansion_is_rejected(tmp_path):
    """LIB-010: an imported XISF whose header declares XML entities (the billion-laughs / external-entity attacks) is refused rather than expanded."""
    from galileo.library.file_formats.xisfFile.xisf_converter import XISFConverter
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE xisf [<!ENTITY a "AAAAAAAAAA"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf"><Image geometry="4:4:1" sampleFormat="UInt16">'
        '<FITSKeyword name="OBJECT" value="&b;"/></Image></xisf>'
    )
    with pytest.raises(ValueError, match=r"(?i)entit|forbidden|Error reading XISF"):
        XISFConverter(_write_xisf(tmp_path / "bomb.xisf", bomb))



# ---------------------------------------------------------------------------
# One implementation per remote-source protocol (SDD §4.23 RemoteSourceAdapter)
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-090")
@pytest.mark.priority("MVP")
async def test_tc_lib_090_source_adapters_delegate_to_the_smart_telescope_manager(tmp_path, monkeypatch):
    """LIB-090/LIB-100/LIB-110: the SMB and FTP source adapters are RemoteSourceAdapter facades over SmartTelescopeManager — the only SMB/FTP code — choosing the telescope model from their arguments."""
    from galileo.library.adapters import RemoteSourceAdapter, SmartTelescopeFtpAdapter, SmartTelescopeSmbAdapter
    from galileo.library.services import telescope

    calls = []

    def fake_list(telescope_type, host, user=None, password=None):
        calls.append(("list", telescope_type, host))
        return [{"name": "M42.fits", "path": "/a/M42.fits", "size": 3}], None

    def fake_get(telescope_type, host, info, local_path, user=None, password=None, progress_callback=None):
        calls.append(("get", telescope_type, host))
        Path(local_path).write_bytes(b"abc")
        return True, None

    monkeypatch.setattr(telescope.smart_telescope_manager, "get_fits_files", fake_list)
    monkeypatch.setattr(telescope.smart_telescope_manager, "download_file", fake_get)

    smb = SmartTelescopeSmbAdapter("seestar.local")
    ftp = SmartTelescopeFtpAdapter("dwarf.local")
    assert isinstance(smb, RemoteSourceAdapter) and isinstance(ftp, RemoteSourceAdapter)

    assert await smb.browse() == ["/a/M42.fits"]
    got = await smb.download("/a/M42.fits", tmp_path)
    assert got.read_bytes() == b"abc"
    await ftp.browse(use_tls=False)
    await SmartTelescopeSmbAdapter("sm.local").browse(share="Pictures")
    await ftp.browse(use_tls=True)
    assert calls == [("list", "SeeStar", "seestar.local"), ("get", "SeeStar", "seestar.local"),
                     ("list", "DWARF 3", "dwarf.local"), ("list", "StellarMate", "sm.local"),
                     ("list", "iTelescope", "dwarf.local")]


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_library_catalog_queries_run_off_the_ui_thread(qt_app, library, monkeypatch):
    """ARCH concurrency model: the Images and Sessions screens read the catalog on a worker thread, not the UI thread."""
    import threading
    from galileo.ui.library.images_widget import ImagesWidget
    from galileo.ui.library.sessions_widget import SessionsWidget

    seen = []
    ui_thread = threading.get_ident()
    orig_groups = ImagesWidget._query_groups.__func__
    orig_fetch = SessionsWidget._fetch_sessions_data
    monkeypatch.setattr(ImagesWidget, "_query_groups",
                        classmethod(lambda cls, *a: (seen.append(threading.get_ident()), orig_groups(cls, *a))[1]))
    monkeypatch.setattr(SessionsWidget, "_fetch_sessions_data",
                        lambda self: (seen.append(threading.get_ident()), orig_fetch(self))[1])

    root = QtWidgets_root()
    images, sessions = ImagesWidget(), SessionsWidget()
    root.layout().addWidget(images)
    root.layout().addWidget(sessions)
    wait_for_library_loads(qt_app, root)
    assert len(seen) == 2 and ui_thread not in seen
    assert images.file_tree.isEnabled() and sessions.sessions_tree.isEnabled()


def QtWidgets_root():
    from PySide6 import QtWidgets
    root = QtWidgets.QWidget()
    QtWidgets.QVBoxLayout(root)
    return root


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_database_error_carries_code_and_file_path():
    """LIB-010: the shared DatabaseError accepts the AstroFiler error_code/file_path/details keywords.

    The ported file-processing code raises ``DatabaseError(msg, file_path=..., error_code=...)``;
    previously that was a ``TypeError`` which masked the underlying database failure.
    """
    from galileo.exceptions import DatabaseError, LibraryError
    from galileo.library.exceptions import FileProcessingError

    err = DatabaseError("constraint violated", file_path="a.fits", error_code="DB_INTEGRITY_ERROR", table="fitsFile")
    assert isinstance(err, LibraryError)
    assert err.file_path == "a.fits"
    assert err.error_code == "DB_INTEGRITY_ERROR"
    assert err.details == {"table": "fitsFile"}
    assert str(err) == "[DB_INTEGRITY_ERROR] constraint violated"
    assert str(DatabaseError("plain")) == "plain"
    assert str(FileProcessingError("bad", file_path="b.fits", error_code="X")) == "[X] bad"


# ---------------------------------------------------------------------------
# Session checkout (Library > Sessions > Check out)
# ---------------------------------------------------------------------------

class _TreeItem:
    """The bits of a QTreeWidgetItem the checkout workflow reads."""

    def __init__(self, texts, user_role=None, parent=None):
        self._texts, self._role, self._parent = texts, user_role, parent

    def text(self, column):
        return self._texts[column]

    def parent(self):
        return self._parent

    def data(self, column, role):
        return self._role


def _checkout_env(monkeypatch, tmp_path, qt_app, *, masters_only=False, copy_files=True):
    """Patch the checkout dialogs; returns the module and the list of message boxes shown."""
    from galileo.ui.library.sessions import checkout_workflow as cw
    from galileo.ui.library.sessions.checkout_options_dialog import CheckoutOptions

    dest = tmp_path / "checkout"
    dest.mkdir()
    shown = []
    monkeypatch.setattr(cw, "prompt_checkout_options", lambda parent, title: CheckoutOptions(
        dest_dir=str(dest), copy_files=copy_files, decompress=False, masters_only=masters_only))
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(cw.QMessageBox, kind, staticmethod(lambda parent, title, text, _k=kind: shown.append((_k, title, text))))
    monkeypatch.setattr(cw.QDesktopServices, "openUrl", staticmethod(lambda url: True))
    return cw, dest, shown


def _light_session():
    from galileo.library.models import fitsSession

    return fitsSession.select().where(fitsSession.fitsSessionObjectName == "M42").get()


@pytest.mark.requirement("TC-LIB-090")
@pytest.mark.priority("P2")
def test_tc_lib_090_checkout_single_session_links_lights_and_calibration(library, qt_app, monkeypatch, tmp_path):
    """LIB-090: checking out one session creates lights plus its darks, bias and flats in a per-session folder."""
    calibration_ready(library)
    cw, dest, shown = _checkout_env(monkeypatch, tmp_path, qt_app)
    session = _light_session()
    item = _TreeItem([None, None, str(session.fitsSessionDate)], parent=_TreeItem(["M42"]))

    cw.checkout_single_session(None, item)

    [session_dir] = list(dest.iterdir())
    names = {p.name: sorted(f.name for f in p.iterdir()) for p in session_dir.iterdir()}
    assert len(names["lights"]) == 3
    assert len(names["darks"]) == 3 and len(names["bias"]) == 3 and len(names["flats"]) == 3
    assert "masters" in names
    assert shown == [("information", "Checkout Complete", shown[0][2])] and "Created 12 files" in shown[0][2]


@pytest.mark.requirement("TC-LIB-090")
@pytest.mark.priority("P2")
def test_tc_lib_090_checkout_single_session_masters_only_skips_calibration_frames(library, qt_app, monkeypatch, tmp_path):
    """LIB-090: with 'masters only' ticked the lights are checked out but not the raw calibration frames."""
    calibration_ready(library)
    cw, dest, _shown = _checkout_env(monkeypatch, tmp_path, qt_app, masters_only=True)
    session = _light_session()
    item = _TreeItem([None, None, str(session.fitsSessionDate)], parent=_TreeItem(["M42"]))

    cw.checkout_single_session(None, item)

    [session_dir] = list(dest.iterdir())
    assert sorted(p.name for p in session_dir.iterdir()) == ["lights", "masters"]
    assert len(list((session_dir / "lights").iterdir())) == 3


@pytest.mark.requirement("TC-LIB-090")
@pytest.mark.priority("P2")
def test_tc_lib_090_checkout_single_session_unknown_session_warns(library, qt_app, monkeypatch, tmp_path):
    """LIB-090: a tree item with no matching session is reported, not crashed on."""
    cw, _dest, shown = _checkout_env(monkeypatch, tmp_path, qt_app)
    cw.checkout_single_session(None, _TreeItem([None, None, "1999-01-01"], parent=_TreeItem(["Nothing"])))
    assert shown and shown[0][0] == "warning" and "not found" in shown[0][2]


@pytest.mark.requirement("TC-LIB-090")
@pytest.mark.priority("P2")
def test_tc_lib_090_checkout_multiple_sessions_shares_one_folder(library, qt_app, monkeypatch, tmp_path):
    """LIB-090: several sessions are checked out into one tree, calibration folders created on demand."""
    calibration_ready(library)
    cw, dest, shown = _checkout_env(monkeypatch, tmp_path, qt_app)
    session = _light_session()
    good = _TreeItem([None, None, str(session.fitsSessionDate)], user_role=session.fitsSessionId, parent=_TreeItem(["M42"]))
    no_id = _TreeItem([None, None, "x"], user_role=None, parent=_TreeItem(["M42"]))

    cw.checkout_multiple_sessions(None, [good, no_id])

    [checkout_dir] = list(dest.iterdir())
    names = sorted(p.name for p in checkout_dir.iterdir())
    assert names == ["bias", "darks", "flats", "lights", "process"]
    assert len(list((checkout_dir / "lights").iterdir())) == 3
    assert shown[0][0] == "information"
    assert "Successfully processed 1 out of 2 sessions" in shown[0][2] and "Session item missing ID" in shown[0][2]


@pytest.mark.requirement("TC-LIB-090")
@pytest.mark.priority("P2")
def test_tc_lib_090_checkout_multiple_sessions_masters_only(library, qt_app, monkeypatch, tmp_path):
    """LIB-090: masters-only multi checkout creates only the lights and masters folders."""
    calibration_ready(library)
    cw, dest, _shown = _checkout_env(monkeypatch, tmp_path, qt_app, masters_only=True)
    session = _light_session()
    good = _TreeItem([None, None, str(session.fitsSessionDate)], user_role=session.fitsSessionId, parent=_TreeItem(["M42"]))

    cw.checkout_multiple_sessions(None, [good])

    [checkout_dir] = list(dest.iterdir())
    names = sorted(p.name for p in checkout_dir.iterdir())
    assert "darks" not in names and "flats" not in names and "bias" not in names and "lights" in names


# ---------------------------------------------------------------------------
# Object merge (Library > Merge)
# ---------------------------------------------------------------------------

def _merge_env(monkeypatch):
    from galileo.ui.library import merge_widget as mw

    shown = []
    monkeypatch.setattr(mw.QMessageBox, "question", staticmethod(lambda *a, **k: mw.QMessageBox.StandardButton.Yes))
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(mw.QMessageBox, kind, staticmethod(lambda parent, title, text, _k=kind: shown.append((_k, title, text))))
    return mw, shown


@pytest.mark.requirement("TC-LIB-100")
@pytest.mark.priority("P2")
def test_tc_lib_100_merge_renames_object_in_database_files_and_headers(library, qt_app, monkeypatch):
    """LIB-100: merging 'M42' into 'M31' updates the catalog, sessions, FITS headers and file/folder names."""
    from astropy.io import fits

    from galileo.library.models import fitsFile, fitsSession

    write_light_frames(library.incoming)
    processor, _ = ingest(library)
    processor.createLightSessions()
    mw, shown = _merge_env(monkeypatch)
    widget = mw.MergeWidget()
    widget.from_field.setText("M42")
    widget.to_field.setText("M31")
    widget.change_filenames.setChecked(True)

    widget.execute_merge()

    rows = list(fitsFile.select())
    assert len(rows) == 3 and all(r.fitsFileObject == "M31" for r in rows)
    assert all("M31" in Path(r.fitsFileName).name and Path(r.fitsFileName).exists() for r in rows)
    assert all(fits.getheader(r.fitsFileName)["OBJECT"] == "M31" for r in rows)
    assert (library.repo / "Light" / "M31").is_dir() and not (library.repo / "Light" / "M42").exists()
    assert [s.fitsSessionObjectName for s in fitsSession.select()] == ["M31"]
    text = widget.results_text.toPlainText()
    assert "Database records updated: 3" in text and "Files renamed on disk: 3" in text
    assert "Directories renamed: 1" in text and "Sessions updated: 1" in text and "Merge completed!" in text
    assert shown and shown[-1][1] == "Merge Successful"


@pytest.mark.requirement("TC-LIB-100")
@pytest.mark.priority("P2")
def test_tc_lib_100_merge_database_only_leaves_files_alone(library, qt_app, monkeypatch):
    """LIB-100: with 'change filenames' off only the catalog records change."""
    from galileo.library.models import fitsFile

    write_light_frames(library.incoming)
    ingest(library)
    before = sorted(r.fitsFileName for r in fitsFile.select())
    mw, _shown = _merge_env(monkeypatch)
    widget = mw.MergeWidget()
    widget.from_field.setText("M42")
    widget.to_field.setText("M31")
    widget.change_filenames.setChecked(False)

    widget.execute_merge()

    assert {r.fitsFileObject for r in fitsFile.select()} == {"M31"}
    assert sorted(r.fitsFileName for r in fitsFile.select()) == before
    assert "Files renamed on disk" not in widget.results_text.toPlainText()


@pytest.mark.requirement("TC-LIB-100")
@pytest.mark.priority("P2")
def test_tc_lib_100_merge_validates_input(library, qt_app, monkeypatch):
    """LIB-100: empty, identical or unknown object names are reported and change nothing."""
    mw, shown = _merge_env(monkeypatch)
    widget = mw.MergeWidget()

    widget.execute_merge()
    widget.from_field.setText("A")
    widget.to_field.setText("A")
    widget.execute_merge()
    widget.to_field.setText("B")
    widget.execute_merge()

    assert [s[:2] for s in shown] == [("warning", "Input Error"), ("information", "No Changes"), ("warning", "Object Not Found")]


# ---------------------------------------------------------------------------
# Session calibration from the Sessions screen
# ---------------------------------------------------------------------------

def _calibration_widget(library, qt_app, monkeypatch):
    """A SessionsWidget plus the tree item of the M42 light session, with masters built."""
    from galileo.library.core.auto_calibration import create_master_frames
    from galileo.ui.library import sessions_widget as sw

    assert create_master_frames(calibration_ready(library)) is True
    session = _light_session()
    shown = []
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(sw.QMessageBox, kind, staticmethod(lambda parent, title, text, _k=kind: shown.append((_k, title, text))))
    widget = sw.SessionsWidget()
    item = _TreeItem([None, None, str(session.fitsSessionDate)], user_role=session.fitsSessionId, parent=_TreeItem(["M42"]))
    return widget, item, session, shown


@pytest.mark.requirement("TC-LIB-060")
@pytest.mark.priority("P2")
def test_tc_lib_060_sessions_screen_calibrates_lights_with_masters(library, qt_app, monkeypatch):
    """LIB-060: Calibrate on the Sessions screen writes cal_ frames, catalogs them and soft-deletes the sources."""
    from astropy.io import fits

    from galileo.library.models import fitsFile

    widget, item, session, shown = _calibration_widget(library, qt_app, monkeypatch)

    result = widget.calibrate_session(item, confirm=False, show_results=True)

    assert result == {"total": 3, "calibrated": 3, "skipped": 0, "errors": 0}
    calibrated = list(fitsFile.select().where(fitsFile.fitsFileCalibrated == 1, fitsFile.fitsFileSession == session.fitsSessionId))
    assert len(calibrated) == 3 and all(Path(f.fitsFileName).name.startswith("cal_") for f in calibrated)
    sources = list(fitsFile.select().where(fitsFile.fitsFileSoftDelete == True, fitsFile.fitsFileType == "LIGHT FRAME"))
    assert len(sources) >= 3
    header = fits.getheader(calibrated[0].fitsFileName)
    assert header["CALIBRAT"] is True and "CALDATE" in header
    assert any("Bias corrected" in str(h) for h in header["HISTORY"])
    assert shown and shown[-1][:2] == ("information", "Calibration Complete")


@pytest.mark.requirement("TC-LIB-060")
@pytest.mark.priority("P2")
def test_tc_lib_060_sessions_screen_calibration_rejects_bad_requests(library, qt_app, monkeypatch):
    """LIB-060: no session id, a calibration session, or no matching masters are reported, not attempted."""
    from galileo.ui.library import sessions_widget as sw

    shown = []
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(sw.QMessageBox, kind, staticmethod(lambda parent, title, text, _k=kind: shown.append((_k, title, text))))
    widget = sw.SessionsWidget()

    assert widget.calibrate_session(_TreeItem([None, None, "d"], user_role=None), confirm=False) == {"error": "Session ID not found"}

    calibration_ready(library)           # catalogued, but no masters built yet
    session = _light_session()
    item = _TreeItem([None, None, str(session.fitsSessionDate)], user_role=session.fitsSessionId, parent=_TreeItem(["M42"]))
    result = widget.calibrate_session(item, confirm=False, show_results=False)
    assert result["error"] == "No matching master frames found"

    flat_item = _TreeItem([None, None, "d"], user_role=session.fitsSessionId, parent=_TreeItem(["Flat"]))
    assert widget.calibrate_session(flat_item, confirm=False, show_results=False) == {
        "error": "Calibration not applicable to calibration sessions"}


@pytest.mark.requirement("TC-LIB-090")
@pytest.mark.priority("P2")
def test_tc_lib_090_sessions_context_menu_offers_and_runs_actions(library, qt_app, monkeypatch):
    """LIB-090: the Sessions tree's right-click menu offers the actions that fit the selection and runs the chosen one."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMenu, QTreeWidgetItem

    from galileo.ui.library import sessions_widget as sw

    widget = sw.SessionsWidget()
    tree = widget.sessions_tree
    tree.clear()
    objects = {}
    items = {}
    for name, sid in (("M42", "sess-1"), ("M31", "sess-2"), ("Flat", "sess-3")):
        top = QTreeWidgetItem([name])
        tree.addTopLevelItem(top)
        child = QTreeWidgetItem(top, [name, "", "2026-09-16"])
        child.setData(0, Qt.ItemDataRole.UserRole, sid)
        objects[name], items[name] = top, child

    calls, offered = [], []
    monkeypatch.setattr(widget, "checkout_session", lambda it: calls.append(("checkout", it.text(0))))
    monkeypatch.setattr(widget, "checkout_multiple_sessions", lambda its: calls.append(("checkout_many", len(its))))
    monkeypatch.setattr(widget, "calibrate_session", lambda it: calls.append(("calibrate", it.text(0))))
    monkeypatch.setattr(tree, "itemAt", lambda pos: items["M42"])

    chosen = {"label": ""}

    class FakeMenu(QMenu):
        """A QMenu whose exec() picks the action named by ``chosen`` instead of blocking on the user."""

        def exec(self, *_args):
            offered.append([a.text() for a in self.actions()])
            return next((a for a in self.actions() if chosen["label"] in a.text()), None)

    monkeypatch.setattr("galileo.ui.library.sessions_menu.QMenu", FakeMenu)

    def right_click(selection, label):
        tree.clearSelection()
        for it in selection:
            it.setSelected(True)
        chosen["label"] = label
        widget.show_context_menu(tree.viewport().rect().center())

    right_click([items["M42"]], "Check out")
    right_click([items["M42"], items["M31"]], "Check out (2 sessions)")
    right_click([items["M42"]], "Calibrate")
    QApplication.clipboard().clear()
    right_click([items["M42"]], "Copy Session ID")

    assert calls == [("checkout", "M42"), ("checkout_many", 2), ("calibrate", "M42")]
    assert QApplication.clipboard().text() == "sess-1"
    single, multi, _, _ = offered
    assert any("Calibrate" in t for t in single) and any("Stack (photometric)" in t for t in single)
    assert not any("Calibrate" in t for t in multi), "per-session actions are single-selection only"

    offered.clear()
    right_click([items["Flat"]], "nothing-matches")
    assert not any("Check out" in t or "Calibrate" in t for t in offered[0]), "calibration sessions are not checked out"


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("P2")
def test_map_fits_header_applies_stored_mappings(library):
    """LIB-010: ``mapFitsHeader`` rewrites header values using the Mapping table's ``card``/``current``/``replace``
    columns (it used to read non-existent ``old_value``/``header_field``/``new_value`` and so never mapped anything)."""
    from galileo.library.core.utils import clearMappingCache, mapFitsHeader
    from galileo.library.models import Mapping

    Mapping.create(card="TELESCOP", current="my scope", replace="Askar 103")
    Mapping.create(card="INSTRUME", current="blank replace", replace=None)
    clearMappingCache()
    hdr = {"TELESCOP": "My Scope", "INSTRUME": "blank replace", "OBJECT": "M42"}
    assert mapFitsHeader(hdr, "x.fits") is True
    assert hdr == {"TELESCOP": "Askar 103", "INSTRUME": "blank replace", "OBJECT": "M42"}
    assert mapFitsHeader({"TELESCOP": "other"}, "y.fits") is False
    clearMappingCache()


@pytest.mark.requirement("TC-LIB-050")
@pytest.mark.priority("P2")
def test_register_masters_scans_registers_moves_and_stops(library):
    """LIB-050: ``registerMasters`` registers only ``IMAGETYP`` MASTER dark/flat/bias frames, honours ``recursive``,
    can move them into a destination folder (renaming on a clash), and stops when the progress callback says so."""
    from galileo.library.core import fitsProcessing
    from galileo.library.models import Masters

    scan = library.root / "scan"
    (scan / "sub").mkdir(parents=True)
    write_frame(scan, "md.fits", "Master Dark", "Dark", 60, 1)
    write_frame(scan, "mf.fits", "Master Flat", "Flat", 2, 2, filt="Ha")
    write_frame(scan, "light.fits", "Light Frame", "M42", 60, 3)        # not a master
    write_frame(scan, "bias_plain.fits", "Bias Frame", "Bias", 0, 4)    # calibration, but not MASTER
    write_frame(scan / "sub", "mb.fits", "Master Bias", "Bias", 0, 5)
    (scan / "notes.txt").write_text("not a fits file")
    processor = fitsProcessing()

    seen = []
    flat_ids = processor.registerMasters(source_folder=str(scan), recursive=False,
                                         progress_callback=lambda cur, total, path: seen.append(Path(path).name) or True)
    assert len(flat_ids) == 2 and Masters.select().count() == 2
    assert "mb.fits" not in seen and "notes.txt" not in seen and {"md.fits", "mf.fits", "light.fits"} <= set(seen)

    all_ids = processor.registerMasters(source_folder=str(scan))            # recursive: finds the bias too
    assert len(all_ids) == 3 and Masters.select().count() == 3

    stopped = processor.registerMasters(source_folder=str(scan), progress_callback=lambda *a: False)
    assert stopped == []

    dest = library.root / "masters_out"
    (dest).mkdir()
    (dest / "md.fits").write_bytes(b"clash")                                 # forces the _1 rename
    moved = processor.registerMasters(source_folder=str(scan), moveFiles=True, destination_folder=str(dest))
    assert len(moved) == 3
    assert not (scan / "md.fits").exists() and (dest / "md.fits").read_bytes() == b"clash"
    assert (dest / "md_1.fits").exists() and (dest / "mf.fits").exists() and (dest / "mb.fits").exists()
    assert (scan / "light.fits").exists(), "non-masters are left where they were"


def _write_array(path, array, **header):
    fits = pytest.importorskip("astropy.io.fits")
    hdr = fits.Header()
    for key, value in header.items():
        hdr[key] = value
    fits.PrimaryHDU(array, header=hdr).writeto(path)
    return str(path)


@pytest.mark.requirement("TC-LIB-050")
@pytest.mark.priority("P2")
def test_calibrate_light_frame_applies_bias_corrected_dark_and_normalised_flat(tmp_path):
    """LIB-050: (Light - (Dark - Bias)) / (Flat / median(Flat)); a negative result is shifted positive (|min| + 100) and noted in HISTORY."""
    np = pytest.importorskip("numpy")
    fits = pytest.importorskip("astropy.io.fits")
    from galileo.library.core.light_calibration import calibrate_light_frame

    light = _write_array(tmp_path / "light.fits", np.full((4, 4), 1000.0, "float32"), EXPTIME=60)
    dark = _write_array(tmp_path / "dark.fits", np.full((4, 4), 120.0, "float32"), EXPTIME=60)
    bias = _write_array(tmp_path / "bias.fits", np.full((4, 4), 20.0, "float32"))
    flat_data = np.full((4, 4), 2.0, "float32")
    flat_data[0, 0] = 1.0                                         # normalised to 0.5 by the median of 2.0
    flat = _write_array(tmp_path / "flat.fits", flat_data)
    messages = []

    result = calibrate_light_frame(light, dark, flat, bias, output_path=str(tmp_path / "out" / "cal.fits"),
                                   progress_callback=messages.append)
    assert result["success"] is True and Path(result["output_path"]).exists()
    assert result["calibration_steps"][0].startswith("DARK: dark.fits (60.0s) - BIAS corrected")
    assert result["calibration_steps"][1].startswith("FLAT: flat.fits (median: 2.0)")
    assert result["data_max"] == pytest.approx(1800.0) and result["data_min"] == pytest.approx(900.0)
    assert messages[0].startswith("Starting calibration") and messages[-1].startswith("Calibration complete")
    with fits.open(result["output_path"]) as hdul:
        assert hdul[0].header["CALMETOD"] == "Numpy"

    # Bias only (no dark): the bias is subtracted from the light.
    only_bias = calibrate_light_frame(light, bias_master=bias, output_path=str(tmp_path / "b.fits"))
    assert only_bias["calibration_steps"] == ["BIAS: bias.fits"] and only_bias["data_max"] == pytest.approx(980.0)

    # Dark without a bias still applies, flagged as uncorrected.
    no_bias = calibrate_light_frame(light, dark, output_path=str(tmp_path / "d.fits"))
    assert no_bias["calibration_steps"] == ["DARK: dark.fits (60.0s) - NO BIAS CORRECTION"]
    assert no_bias["data_max"] == pytest.approx(880.0)

    # A negative result is shifted positive by |min| + 100 and recorded in BZERO.
    dark_big = _write_array(tmp_path / "dark_big.fits", np.full((4, 4), 1500.0, "float32"), EXPTIME=60)
    shifted = calibrate_light_frame(light, dark_big, output_path=str(tmp_path / "s.fits"))
    assert shifted["data_min"] == pytest.approx(-500.0)
    with fits.open(shifted["output_path"]) as hdul:
        assert any("Applied BZERO offset of 600.00" in str(h) for h in hdul[0].header["HISTORY"])
        assert float(hdul[0].data.min()) == pytest.approx(100.0)


@pytest.mark.requirement("TC-LIB-050")
@pytest.mark.priority("P2")
def test_calibrate_light_frame_tolerates_bad_masters_and_reports_missing_input(tmp_path):
    """LIB-050: a master that does not match the light is reported and skipped; a missing light is an error dict;
    a flat with a tiny pixel is clamped rather than blowing up."""
    np = pytest.importorskip("numpy")
    from galileo.library.core.light_calibration import calibrate_light_frame

    assert "not found" in calibrate_light_frame(str(tmp_path / "nope.fits"))["error"]

    light = _write_array(tmp_path / "light.fits", np.full((4, 4), 500.0, "float32"))
    wrong_dark = _write_array(tmp_path / "dark.fits", np.full((2, 2), 10.0, "float32"))
    messages = []
    result = calibrate_light_frame(light, wrong_dark, output_path=str(tmp_path / "o1.fits"), progress_callback=messages.append)
    assert result["success"] is True and result["calibration_steps"] == []
    assert any(m.startswith("Warning: Failed to apply dark correction") for m in messages)

    flat_data = np.full((4, 4), 1.0, "float32")
    flat_data[0, 0] = 0.01                                        # below the 0.1 clamp
    flat = _write_array(tmp_path / "flat.fits", flat_data)
    clamped = calibrate_light_frame(light, flat_master=flat, output_path=str(tmp_path / "o2.fits"))
    assert clamped["data_max"] == pytest.approx(5000.0) and clamped["data_min"] == pytest.approx(500.0)   # 500 / 0.1
    assert clamped["calibration_steps"][0].startswith("FLAT: flat.fits")


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("P2")
def test_sessions_resources_status_summarises_masters_and_calibration_frames(monkeypatch):
    """LIB-010: the Sessions table's Resources column shows masters / calibration-frame counts for a light session,
    the available master types for a calibration session, and "Precalibrated" for iTelescope/Seestar data."""
    pytest.importorskip("PySide6")
    import galileo.library.core.master_manager as mm_mod
    from galileo.ui.library.sessions_widget import SessionsWidget

    class NoMasters:
        def find_matching_master(self, session_data, cal_type):
            return None

    monkeypatch.setattr(mm_mod, "get_master_manager", lambda: NoMasters())

    def make(**kw):
        base = {"fitsSessionId": "L1", "fitsSessionObjectName": "M42", "fitsSessionTelescope": "Home", "fitsSessionImager": "ASI",
                    "fitsBiasSession": None, "fitsDarkSession": None, "fitsFlatSession": None,
                    "fitsBiasMaster": None, "fitsDarkMaster": None, "fitsFlatMaster": None}
        base.update(kw)
        return SimpleNamespace(**base)

    def status(session, counts=None, masters=None):
        host = SimpleNamespace(_session_file_counts=counts or {}, _master_types_by_source_session_id=masters or {},
                               _matched_master_types_by_session_id={})
        return SessionsWidget._build_resources_status(host, session)

    nothing = status(make())
    assert nothing["text"] == "Dark: None, Flat: None, Bias: None" and nothing["percentage"] == 0
    assert nothing["has_masters"] is False and nothing["tooltip"].startswith("Calibration Resources (0% ready):\n✗ No dark")

    mixed = status(make(fitsDarkMaster="m.fits", fitsFlatSession="F1", fitsBiasSession="B1"), counts={"F1": 12})
    assert mixed["text"] == "MasterDark, Flat: 12, Bias: Available"
    assert mixed["percentage"] == 100 and (mixed["has_dark"], mixed["has_flat"], mixed["has_bias"]) == (True, True, True)
    assert mixed["has_masters"] is True
    assert mixed["tooltip"].splitlines()[1:] == ["✓ Dark master frame available", "✓ 12 flat frames available",
                                                  "✓ Bias frames available"]

    via_source = status(make(fitsDarkSession="D1", fitsBiasSession="B1"), counts={"D1": 5},
                        masters={"D1": {"dark"}, "B1": {"bias", "flat"}})
    assert via_source["text"] == "MasterDark, Flat: None, MasterBias" and round(via_source["percentage"]) == 67

    pre = status(make(fitsSessionTelescope="iTelescope T5"))
    assert pre["text"] == "Precalibrated" and pre["percentage"] == 100 and pre["tooltip"] == "Pre-calibrated images from iTelescope T5"
    assert status(make(fitsSessionImager="Seestar S30"))["tooltip"] == "Pre-calibrated images from Seestar S30"

    calib = make(fitsSessionId="C1", fitsSessionObjectName="Dark")
    assert status(calib)["text"] == ""
    got = status(calib, masters={"C1": {"flat", "dark"}})
    assert got["text"] == "MasterDark, MasterFlat" and got["tooltip"] == "Masters available: MasterDark, MasterFlat"
    assert (got["has_dark"], got["has_flat"], got["has_bias"], got["has_masters"]) == (True, True, False, True)


@pytest.mark.requirement("TC-LIB-060")
@pytest.mark.priority("P2")
def test_tc_lib_060_sessions_screen_photometric_stack(library, qt_app, monkeypatch):
    """LIB-060: Photometric stack calibrates a session with no calibrated frames first, stacks the calibrated lights
    (best-HFR frame as the reference), opens the result, and reports calibration-session / too-few / failed cases."""
    import galileo.library.core.master_manager as mm_mod
    from galileo.library.models import fitsFile

    widget, item, session, shown = _calibration_widget(library, qt_app, monkeypatch)
    opened, stacks = [], []

    real_manager = mm_mod.get_master_manager()

    class FakeMasterManager:
        ok = True

        def __getattr__(self, name):                      # everything but the stacker (e.g. calibration) is real
            return getattr(real_manager, name)

        def _create_light_stack_photometric_mean(self, **kw):
            stacks.append(kw)
            kw["progress_callback"](1, 4, "stacking")
            if self.ok:
                Path(kw["output_path"]).write_bytes(b"stack")
            return self.ok

    fake = FakeMasterManager()
    monkeypatch.setattr(mm_mod, "get_master_manager", lambda: fake)
    monkeypatch.setattr(widget, "_open_path_in_external_viewer", opened.append)
    monkeypatch.setattr(widget, "load_sessions_data", lambda: opened.append("reloaded"))

    # A calibration session is not stackable.
    flat_item = _TreeItem([None, None, "d"], user_role=session.fitsSessionId, parent=_TreeItem(["Flat"]))
    widget.photometric_stack_session(flat_item)
    assert shown[-1][:2] == ("information", "Not Applicable")

    widget.photometric_stack_session(item)               # no calibrated frames yet -> calibrate, then stack
    calibrated = list(fitsFile.select().where(fitsFile.fitsFileCalibrated == 1, fitsFile.fitsFileSession == session.fitsSessionId))
    assert len(calibrated) == 3 and len(stacks) == 1
    assert sorted(stacks[0]["file_paths"]) == sorted(f.fitsFileName for f in calibrated)
    assert Path(stacks[0]["output_path"]).name.startswith("photometric_stack_M42_")
    assert stacks[0]["thumbnail_session_id"] == str(session.fitsSessionId) and stacks[0]["reference_path"] is None
    assert opened[-2:] == [stacks[0]["output_path"], "reloaded"]     # (calibrating reloaded the table once already)

    opened.clear()
    stacks.clear()
    for hfr, frame in zip((3.0, 1.2, 2.0), calibrated, strict=True):
        fitsFile.update(fitsFileAvgHFRArcsec=hfr).where(fitsFile.fitsFileId == frame.fitsFileId).execute()
    widget.photometric_stack_session(item)
    assert stacks[0]["reference_path"] == calibrated[1].fitsFileName

    fake.ok = False
    Path(stacks[0]["output_path"]).unlink()
    widget.photometric_stack_session(item)
    assert shown[-1][:2] == ("warning", "Stack Failed")

    for frame in calibrated[1:]:
        fitsFile.update(fitsFileSoftDelete=True).where(fitsFile.fitsFileId == frame.fitsFileId).execute()
    widget.photometric_stack_session(item)
    assert shown[-1][:2] == ("information", "Not Enough Frames")


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("P2")
def test_options_library_page_loads_every_setting_from_library_ini(window, library, monkeypatch):
    """LIB-010: Options > Library shows each library.ini value in its control (booleans in any spelling, a numeric
    port with a fallback, the old compression names mapped to gzip2, the sync profile by its data value), and falls
    back to the documented defaults for what is not in the file."""
    import configparser

    from PySide6 import QtWidgets
    from galileo.ui.library.config_widget import ConfigWidget

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    window._open_library_settings()
    widget = window._window.findChildren(ConfigWidget)[0]

    def load(**values):
        parser = configparser.ConfigParser()
        parser.read(library.ini)
        for key, value in values.items():
            parser["DEFAULT"][key] = value
        with open(library.ini, "w") as handle:
            parser.write(handle)
        widget.load_settings()

    load(source="/in", repo="/repo", temp_folder="/tmp/x", refresh_on_startup="no", save_modified_headers="yes",
         fits_viewer_path="/bin/viewer", suppress_delete_warnings="On", cloud_vendor="Google Cloud Storage",
         bucket_url="my-bucket", auth_file_path="/auth.json", sync_profile="ondemand", auto_cleanup_backed_files="1",
         min_files_per_master="5", auto_calibration_progress="false", itelescope_username="scope",
         itelescope_verify_tls="False", sftp_username="astro", sftp_key_path="/k", sftp_remote_path="/data",
         sftp_port="2222", sftp_strict_host_keys="true", compress_fits="TRUE", compression_algorithm="fits_rice",
         compression_level="8", verify_compression="off", min_compression_size="2048")
    assert (widget.source_path.text(), widget.repo_path.text(), widget.temp_path.text()) == ("/in", "/repo", "/tmp/x")
    assert (widget.refresh_on_startup.isChecked(), widget.save_modified_headers.isChecked()) == (False, True)
    assert widget.fits_viewer_path.text() == "/bin/viewer" and widget.suppress_delete_warnings.isChecked()
    assert (widget.bucket_url.text(), widget.auth_file_path.text()) == ("my-bucket", "/auth.json")
    assert widget.cloud_vendor.currentText() == "Google Cloud Storage" and widget.sync_profile.currentData() == "ondemand"
    assert widget.auto_cleanup_backed_files.isChecked() and widget.min_files_per_master.value() == 5
    assert not widget.auto_calibration_progress.isChecked() and widget.itelescope_username.text() == "scope"
    assert not widget.itelescope_verify_tls.isChecked()
    assert (widget.sftp_username.text(), widget.sftp_key_path.text(), widget.sftp_remote_path.text()) == ("astro", "/k", "/data")
    assert widget.sftp_port.value() == 2222 and widget.sftp_strict_host_keys.isChecked()
    assert widget.compress_fits.isChecked() and widget.compression_algorithm.currentText() == "fits_gzip2"
    assert widget.compression_level.value() == 8 and not widget.verify_compression.isChecked()
    assert widget.min_compression_size.value() == 2048

    parser = configparser.ConfigParser()
    parser.read(library.ini)
    for key in ("suppress_delete_warnings", "sftp_port"):
        parser.remove_option("DEFAULT", key)
    with open(library.ini, "w") as handle:
        parser.write(handle)
    widget.load_settings()
    assert not widget.suppress_delete_warnings.isChecked() and widget.sftp_port.value() == 22
    load(sftp_port="abc")
    assert widget.sftp_port.value() == 22


@pytest.mark.requirement("TC-LIB-100")
@pytest.mark.priority("P2")
def test_telescope_download_worker_downloads_registers_deletes_and_reports(library, qt_app, monkeypatch, tmp_path):
    """LIB-100: the download worker scans for the telescope and its FITS files, downloads each (folder structure kept,
    flat for iTelescope), sets Seestar OBJECT/MOSAIC headers, registers each file, optionally deletes it from the
    telescope, and ends with a summary; it reports the failure paths and honours a stop request."""
    from galileo.ui.library import download_dialog as dd

    class FakeManager:
        ip, find_error = "10.0.0.5", None
        files, list_error = [], None
        failing, deleted = set(), []
        credentials = ("user", "pw")

        def find_telescope(self, telescope_type, network_range=None, hostname=None):
            return self.ip, self.find_error

        def get_itelescope_credentials(self):
            return self.credentials

        def get_fits_files(self, telescope_type, ip, username, password):
            return self.files, self.list_error

        def download_file(self, telescope_type, ip, info, local_path, username, password, progress_callback=None):
            assert progress_callback(10) is True
            if info["name"] in self.failing:
                return False, "boom"
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            write_frame(Path(local_path).parent, Path(local_path).name, "Light Frame", "M42", 10, 1)
            return True, None

        def delete_file(self, telescope_type, ip, info):
            self.deleted.append(info["name"])
            return True, None

    registered = []

    class FakeProcessor:
        def registerFitsImage(self, root_dir, file_name, moveFiles=False):
            registered.append((root_dir, file_name, moveFiles))
            return f"id-{len(registered)}"

    manager = FakeManager()
    monkeypatch.setattr(dd, "smart_telescope_manager", manager)
    monkeypatch.setattr(dd, "fitsProcessing", FakeProcessor)

    def run(telescope="SeeStar", delete=False, stop=False):
        out = SimpleNamespace(progress=[], percent=[], done=[], errors=[])
        worker = dd.TelescopeDownloadWorker(telescope, "host", "", str(tmp_path / "dl"), delete_files=delete)
        worker.progress_updated.connect(out.progress.append)
        worker.progress_percent_updated.connect(out.percent.append)
        worker.download_completed.connect(out.done.append)
        worker.error_occurred.connect(out.errors.append)
        worker._stop_requested = stop
        worker.run()
        return out

    assert run(stop=True).progress == []

    manager.find_error, manager.ip = "no route", None
    assert run().errors == ["Failed to find telescope: no route"]
    manager.find_error, manager.ip = None, "10.0.0.5"

    assert run().done == ["No FITS files found on telescope"]
    manager.list_error = "denied"
    assert run().errors == ["Failed to get file list: denied"]
    manager.list_error = None

    manager.files = [{"name": "a.fits", "folder_name": "M31_sub"}, {"name": "b.fits", "folder_name": "M42_mosaic_sub"}]
    out = run(delete=True)
    assert out.errors == [] and out.percent[:2] == [5, 10] and out.percent[-2:] == [95, 100]
    assert out.progress[0].startswith("Scanning network for SeeStar telescope (SMB)")
    assert "Connected to SeeStar at 10.0.0.5" in out.progress and "Processing b.fits (2/2)..." in out.progress
    assert out.done[0].startswith("Download completed!\n\nDownloaded: 2 files\nRegistered in database: 2 files\n")
    assert out.done[0].endswith("\nDeleted from telescope: 2 files\n\nFiles processed and moved to repository structure")
    assert manager.deleted == ["a.fits", "b.fits"]
    assert [r[1:] for r in registered] == [("a.fits", True), ("b.fits", True)]
    assert Path(registered[0][0]) == tmp_path / "dl" / "M31_sub"
    from astropy.io import fits as pyfits
    header = pyfits.getheader(tmp_path / "dl" / "M42_mosaic_sub" / "b.fits")
    assert header["OBJECT"] == "M42" and header["MOSAIC"] is True
    assert pyfits.getheader(tmp_path / "dl" / "M31_sub" / "a.fits")["MOSAIC"] is False

    manager.files = [{"name": f"f{i}.fits", "folder_name": "x"} for i in range(7)]
    manager.failing = {f"f{i}.fits" for i in range(7)}
    summary = run().done[0]
    assert "Failed: 7 files\nFailed files:\nf0.fits: boom" in summary and summary.endswith(
        "\n... and 2 more\n\nFiles processed and moved to repository structure")

    manager.files, manager.failing = [{"name": "t.fits", "folder_name": "ignored"}], set()
    registered.clear()
    run(telescope="iTelescope")
    assert (tmp_path / "dl" / "t.fits").exists() and not (tmp_path / "dl" / "ignored").exists()
    manager.credentials = (None, None)
    assert run(telescope="iTelescope").errors[0].startswith("iTelescope credentials not configured")

    monkeypatch.setattr(dd, "get_sftp_settings", lambda: {"username": ""})
    assert run(telescope="SFTP").errors[0].startswith("SFTP account not configured")


@pytest.mark.requirement("TC-LIB-110")
@pytest.mark.priority("P2")
def test_cloud_complete_sync_downloads_missing_and_uploads_unbacked_files(library, qt_app, monkeypatch):
    """LIB-110: Complete Sync lists the bucket, downloads files missing locally (not those already catalogued by name,
    cloud URL or filename timestamp) and registers them, uploads local files without a cloud URL and records the URL,
    then summarises; it stops quietly on Cancel and refuses an unconfigured repository."""
    from PySide6 import QtWidgets
    from galileo.library.models import fitsFile
    from galileo.ui.library import cloud_sync_complete as cc          # where Complete Sync (and its gcs calls) lives
    from galileo.ui.library import cloud_sync_dialog as cs

    write_frame(library.incoming, "local_a-20240116031554s.fits", "Light Frame", "M42", 60, 1)
    write_frame(library.incoming, "local_b.fits", "Light Frame", "M42", 60, 2)
    write_frame(library.incoming, "local_c.fits", "Light Frame", "M42", 60, 3)
    ingest(library)
    rows = sorted(fitsFile.select(), key=lambda f: f.fitsFileName)
    assert len(rows) == 3
    fitsFile.update(fitsFileCloudURL="gs://bkt/Light/known.fits").where(fitsFile.fitsFileId == rows[0].fitsFileId).execute()
    stamped = Path(rows[1].fitsFileName).with_name("stamped-20240116031554s.fits")   # the "same timestamp" file
    shutil.move(rows[1].fitsFileName, stamped)
    fitsFile.update(fitsFileName=str(stamped)).where(fitsFile.fitsFileId == rows[1].fitsFileId).execute()

    shown, downloads, uploads = [], [], []
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes))
    for kind in ("information", "critical", "warning"):
        monkeypatch.setattr(QtWidgets.QMessageBox, kind, staticmethod(lambda parent, title, text, _k=kind: shown.append((_k, title, text))))
    monkeypatch.setattr(cc, "list_gcs_bucket_files", lambda bucket, auth: [
        {"name": "Light/new_one.fits"},                       # missing locally -> downloaded and registered
        {"name": "Light/other-20240116031554s.fits"},        # same timestamp as local_a -> considered present
        {"name": "Light/known.fits"},                        # already catalogued by cloud URL
        {"name": "Light/notes.txt"},                         # downloaded but not a FITS -> not registered
    ])

    def fake_download(bucket, auth, name, dest):
        downloads.append(name)
        if name.endswith(".fits"):
            write_frame(Path(dest).parent, Path(dest).name, "Light Frame", "M31", 60, 9)
        else:
            Path(dest).write_text("x")
        return True, "ok"

    def fake_upload(bucket, auth, full_path, relative_path):
        uploads.append(relative_path)
        return True, f"gs://{bucket}/{relative_path}", "File uploaded"

    monkeypatch.setattr(cc, "download_file_from_gcs", fake_download)
    monkeypatch.setattr(cc, "upload_file_to_backup", fake_upload)

    widget = cs.CloudSyncWidget()
    widget.cloud_config = {"bucket_url": "gs://bkt", "auth_file_path": "/auth.json", "vendor": "Google Cloud Storage"}
    widget.perform_complete_sync()

    assert downloads == ["Light/new_one.fits", "Light/notes.txt"]
    kind, title, text = shown[-1]
    assert (kind, title) == ("information", "Complete Sync Finished")
    assert "Cloud files checked: 4" in text and "Files downloaded: 2" in text and "Files registered: 1" in text
    assert "Files uploaded: 3" in text and "Database records updated: 3" in text and "Errors: 0" in text
    assert len(uploads) == 3 and all(not u.startswith("..") for u in uploads)
    assert all(f.fitsFileCloudURL for f in fitsFile.select())
    assert fitsFile.select().count() == 4, "the new FITS was registered; the non-FITS download was not"

    shown.clear()
    monkeypatch.setattr(QtWidgets.QProgressDialog, "wasCanceled", lambda self: True)
    widget.perform_complete_sync()
    assert shown == [], "cancelling before the first phase ends quietly"
    monkeypatch.undo()

    from galileo.library.config import set_config_path
    bad = library.root / "bad.ini"
    bad.write_text("[DEFAULT]\nrepo = /does/not/exist\n")
    set_config_path(bad)
    shown.clear()
    for kind in ("information", "critical"):
        monkeypatch.setattr(QtWidgets.QMessageBox, kind, staticmethod(lambda parent, title, text, _k=kind: shown.append((_k, title, text))))
    widget.perform_complete_sync()
    assert shown[0][:2] == ("critical", "Configuration Error")
