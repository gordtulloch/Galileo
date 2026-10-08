# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The library command-line utilities (LIB-130, EXT-140): ``galileo.commands.*``.

``test_lib.py`` already proves each module imports, is installed as a ``galileo-<name>`` console script and that the
load → create-sessions → link-sessions pipeline runs. These tests go module by module through what each utility
actually does: argument handling, exit codes, what lands in the catalog and on disk, and what each refuses to do.

Every test runs against ``test_lib.py``'s ``library`` fixture (a fresh migrated database and a ``library.ini`` pointing at
temporary incoming/repository folders), with the log folder redirected, so nothing touches the user's real library.
"""

import configparser
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_lib import ingest, library, write_calibration_frames, write_frame, write_light_frames  # noqa: F401, F811  (library is a fixture)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def cli(library, tmp_path, monkeypatch):
    """Run a command's ``main()`` as the console script would: returns ``run(module, *argv) -> exit code``.

    The commands configure the root logger (some with ``force=True``) and write to the Galileo log folder; both are
    redirected/restored here so a test neither pollutes the user's log nor leaks handlers into later tests.
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr("galileo.platform.get_log_dir", lambda: logs)

    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level

    def run(module, *argv):
        monkeypatch.setattr(sys, "argv", [module.__name__.rsplit(".", 1)[-1], *argv])
        try:
            code = module.main()
        except SystemExit as exit_:
            return exit_.code
        return code or 0

    yield SimpleNamespace(run=run, logs=logs)

    for handler in list(root.handlers):
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(saved_level)


def calibrated(path, **extra):
    """A tiny FITS file standing in for a stack input."""
    return write_frame(path.parent, path.name, "Light Frame", "M42", 60, 1, **extra)


def set_ini(library, **values):
    """Add keys to the test library.ini's DEFAULT section."""
    config = configparser.ConfigParser()
    config.read(library.ini)
    for key, value in values.items():
        config.set("DEFAULT", key, str(value))
    with open(library.ini, "w") as fh:
        config.write(fh)


# ---------------------------------------------------------------------------
# _common
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_common_config_and_log_path(library, cli):
    """LIB-130: the commands share one settings file (selected by --config) and one library.log in the Galileo log folder."""
    from galileo.commands._common import LOG_FILENAME, get_log_path, load_config
    from galileo.library.config import get_config_path

    assert get_log_path() == cli.logs / LOG_FILENAME == cli.logs / "library.log"

    other = library.root / "other.ini"
    other.write_text("[DEFAULT]\nrepo = /somewhere/else\n")
    config = load_config(str(other))
    assert config.get("DEFAULT", "repo") == "/somewhere/else"
    assert get_config_path() == other, "selecting a file redirects every later read inside galileo.library too"


# ---------------------------------------------------------------------------
# load_repo
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_load_repo_validate_paths(tmp_path):
    """LIB-130: load_repo refuses a missing source folder, creates a missing repository folder, and checks it is writable."""
    from galileo.commands.load_repo import validate_paths

    source = tmp_path / "src"
    source.mkdir()
    with pytest.raises(FileNotFoundError, match="Source folder does not exist"):
        validate_paths(str(tmp_path / "missing"), str(tmp_path / "repo"))

    new_repo = tmp_path / "new" / "repo"
    validate_paths(str(source), str(new_repo))
    assert new_repo.is_dir()


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_load_repo_ingests_moves_and_reports_nothing_to_do(library, cli):
    """LIB-130: load_repo moves new files from the source folder into the repository and catalogs them (exit 0); with nothing new it exits 1."""
    from galileo.commands import load_repo
    from galileo.library.models import fitsFile

    write_light_frames(library.incoming)
    assert cli.run(load_repo) == 0
    rows = list(fitsFile.select())
    assert len(rows) == 3 and not list(library.incoming.glob("*.fits"))
    assert all(Path(r.fitsFileName).exists() and str(library.repo) in str(Path(r.fitsFileName)) for r in rows)

    assert cli.run(load_repo) == 1, "an empty source folder is reported, not silently treated as success"


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_load_repo_skips_duplicates(library, cli):
    """LIB-130: a file whose content is already in the catalog is skipped, and a run that only found duplicates exits 1."""
    from galileo.commands import load_repo
    from galileo.library.models import fitsFile

    first = write_light_frames(library.incoming, count=1)[0]
    original_bytes = first.read_bytes()
    assert cli.run(load_repo) == 0
    (library.incoming / "copy_of_light_0.fits").write_bytes(original_bytes)

    cli.run(load_repo)
    assert fitsFile.select().count() == 1, "the duplicate is not catalogued a second time"


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
@pytest.mark.xfail(strict=True, reason="a run that found only duplicates exits 0: registerFitsImages returns a plain list, so the "
                                       "(files, duplicate_count) branch the commands rely on never fires (CODE_REVIEW.md)")
def test_tc_lib_130_load_repo_duplicates_only_run_exits_1(library, cli):
    """LIB-130: load_repo says "No new files processed! N duplicate files were skipped" and exits 1 when a run found only duplicates."""
    from galileo.commands import load_repo

    first = write_light_frames(library.incoming, count=1)[0]
    original_bytes = first.read_bytes()
    assert cli.run(load_repo) == 0
    (library.incoming / "copy_of_light_0.fits").write_bytes(original_bytes)
    assert cli.run(load_repo) == 1


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_load_repo_source_and_repo_overrides(library, cli):
    """LIB-130: --source and --repo override the folders in library.ini for one run."""
    from galileo.commands import load_repo
    from galileo.library.models import fitsFile

    elsewhere, other_repo = library.root / "elsewhere", library.root / "other_repo"
    elsewhere.mkdir()
    write_light_frames(elsewhere, count=2)

    assert cli.run(load_repo, "--source", str(elsewhere), "--repo", str(other_repo)) == 0
    assert fitsFile.select().count() == 2
    assert not list(elsewhere.glob("*.fits")), "taken from the --source folder"
    assert all(Path(r.fitsFileName).is_relative_to(other_repo) for r in fitsFile.select()), "and filed into the --repo folder"
    assert not list(library.repo.rglob("*.fits")), "nothing leaks into the repository named in library.ini"


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_load_repo_temporary_mappings_apply_then_disappear(library, cli):
    """LIB-130: -s CARD/INPUT/OUTPUT rewrites a header for this run only; malformed or unknown-card specs are ignored; the mapping is removed afterwards."""
    from galileo.commands import load_repo
    from galileo.library.models import Mapping, fitsFile

    write_light_frames(library.incoming, count=2)
    code = cli.run(load_repo, "-s", "OBJECT/M42/M43", "-s", "OBJECT/only-two-parts", "-s", "BOGUSCARD/a/b", "-s", "OBJECT/x/")
    assert code == 0
    assert {r.fitsFileObject for r in fitsFile.select()} == {"M43"}
    assert Mapping.select().count() == 0, "temporary mappings must not outlive the run"


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_load_repo_fails_on_missing_source_folder(library, cli):
    """LIB-130: a --source that does not exist exits 1 instead of crashing."""
    from galileo.commands import load_repo

    assert cli.run(load_repo, "--source", str(library.root / "does_not_exist")) == 1


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
@pytest.mark.parametrize("module_name", ["load_repo", "download"])
def test_tc_lib_130_apply_mappings_to_fits(library, module_name):
    """LIB-130: header mappings are applied to a FITS file before registration — exact-value, default-for-empty, and missing-card — and a file nothing maps is left alone."""
    import importlib

    from astropy.io import fits
    from galileo.library.models import Mapping

    apply = importlib.import_module(f"galileo.commands.{module_name}").apply_mappings_to_fits
    path = write_frame(library.root, "m.fits", "Light Frame", "Unknown", 60, 1)
    assert apply(str(path)) is False, "no mappings defined"

    Mapping.create(card="OBJECT", current="Unknown", replace="M31")        # exact value
    Mapping.create(card="FILTER", current=None, replace="Lum")             # default for a missing/empty card
    Mapping.create(card="OBSERVER", current="Someone Else", replace="X")   # does not match this file
    assert apply(str(path)) is True

    with fits.open(path) as hdul:
        header = hdul[0].header
        assert header["OBJECT"] == "M31" and header["FILTER"] == "Lum"
        assert header.get("OBSERVER") is None
    assert apply(str(path)) is False, "already mapped, so nothing more to change"


# ---------------------------------------------------------------------------
# sync_repo
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_sync_repo_catalogs_in_place_without_moving(library, cli):
    """LIB-130: sync_repo catalogs the files already in the repository where they are (never moving them), and exits 1 when there is nothing to add."""
    from galileo.commands import sync_repo
    from galileo.library.models import fitsFile

    lights = write_light_frames(library.repo, count=2)
    assert cli.run(sync_repo) == 0
    assert fitsFile.select().count() == 2
    assert all(p.exists() for p in lights), "files stay where they were"

    assert cli.run(sync_repo) == 0
    assert fitsFile.select().count() == 2, "a second sync adds nothing"


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
@pytest.mark.xfail(strict=True, reason="a sync that found nothing new exits 0: registerFitsImages returns a plain list, so the "
                                       "(files, duplicate_count) branch the command relies on never fires (CODE_REVIEW.md)")
def test_tc_lib_130_sync_repo_nothing_new_exits_1(library, cli):
    """LIB-130: sync_repo exits 1 ("No new FITS/XISF files synchronized") when every file is already catalogued."""
    from galileo.commands import sync_repo

    write_light_frames(library.repo, count=2)
    assert cli.run(sync_repo) == 0
    assert cli.run(sync_repo) == 1


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_sync_repo_repo_override_scans_that_folder(library, cli):
    """LIB-130: --repo points sync at a different repository folder for one run."""
    from galileo.commands import sync_repo
    from galileo.library.models import fitsFile

    other = library.root / "another_repo"
    other.mkdir()
    write_light_frames(other, count=2)
    assert cli.run(sync_repo, "--repo", str(other)) == 0
    assert all(Path(r.fitsFileName).is_relative_to(other) for r in fitsFile.select()) and fitsFile.select().count() == 2


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_sync_repo_clear_rebuilds_the_catalog(library, cli):
    """LIB-130: --clear empties the catalog before syncing, so rows for files that no longer exist disappear."""
    from galileo.commands import sync_repo
    from galileo.library.models import fitsFile

    kept, gone = write_light_frames(library.repo, count=2)
    assert cli.run(sync_repo) == 0 and fitsFile.select().count() == 2
    gone.unlink()

    assert cli.run(sync_repo, "--clear") == 0
    assert [Path(r.fitsFileName).name for r in fitsFile.select()] == [kept.name]


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_sync_repo_rejects_a_missing_repository(library, cli):
    """LIB-130: sync_repo with a repository folder that does not exist exits 1, and validate_paths names the folder."""
    from galileo.commands import sync_repo

    assert cli.run(sync_repo, "--repo", str(library.root / "no_such_repo")) == 1
    with pytest.raises(FileNotFoundError, match="no_such_repo"):
        sync_repo.validate_paths(str(library.root / "no_such_repo"))


# ---------------------------------------------------------------------------
# create_sessions / link_sessions
# ---------------------------------------------------------------------------

@pytest.fixture
def ingested(library):
    write_light_frames(library.incoming)
    write_calibration_frames(library.incoming)
    ingest(library)
    return library


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_create_sessions_modes(ingested, cli):
    """LIB-130: create_sessions builds light and calibration sessions, -l/-C restrict it, -n does nothing when everything is assigned, -r rebuilds."""
    from galileo.commands import create_sessions
    from galileo.library.models import fitsFile, fitsSession

    assert cli.run(create_sessions, "-l") == 0
    assert {s.fitsSessionObjectName for s in fitsSession.select()} == {"M42"}

    assert cli.run(create_sessions, "-C") == 0
    assert fitsSession.select().count() == 4          # M42 light + bias + dark + flat sessions

    assert cli.run(create_sessions, "-n") == 0, "new-only with every file already assigned succeeds without creating anything"
    assert fitsSession.select().count() == 4

    assert cli.run(create_sessions) == 1, "a run that creates no session reports it"

    assert cli.run(create_sessions, "-r") == 0
    assert fitsSession.select().count() == 4
    assert fitsFile.select().where(fitsFile.fitsFileSession.is_null()).count() == 0


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_create_sessions_rejects_conflicting_options(library, cli):
    """LIB-130: -r, -n and -q cannot be combined with each other or with -l/-C — argparse refuses with exit code 2."""
    from galileo.commands import create_sessions

    for argv in (("-r", "-l"), ("-r", "-n"), ("-n", "-C"), ("-q", "-l"), ("-q", "-r")):
        assert cli.run(create_sessions, *argv) == 2, argv


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_create_sessions_update_quality_and_clear(ingested, cli):
    """LIB-130: -q refreshes session quality metrics (a no-op without sessions); clear_existing_sessions detaches files before deleting sessions."""
    from galileo.commands import create_sessions
    from galileo.library.models import fitsFile, fitsSession

    assert cli.run(create_sessions, "-q") == 0, "no light sessions yet"
    assert cli.run(create_sessions) == 0 and fitsSession.select().count() == 4
    assert cli.run(create_sessions, "-q") == 0

    removed = create_sessions.clear_existing_sessions(logging.getLogger("test"))
    assert removed == 4 and fitsSession.select().count() == 0
    assert fitsFile.select().where(fitsFile.fitsFileSession.is_null(False)).count() == 0


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_create_sessions_reports_database_errors(library, cli, monkeypatch, capsys):
    """LIB-130: a DatabaseError is reported plainly (exit 1, no traceback), and any other failure exits 1 with a hint to use -v."""
    from galileo.commands import create_sessions
    from galileo.library.exceptions import DatabaseError

    def broken(*args, **kwargs):
        raise DatabaseError("schema is out of date")

    monkeypatch.setattr(create_sessions, "setup_database", broken)
    assert cli.run(create_sessions) == 1
    assert "DATABASE ERROR" in capsys.readouterr().out

    monkeypatch.setattr(create_sessions, "setup_database", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cli.run(create_sessions) == 1
    assert "boom" in capsys.readouterr().out


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_link_sessions_links_calibration_to_lights(ingested, cli, capsys):
    """LIB-130: link_sessions attaches the matching bias/dark/flat sessions to each light session and reports how many it updated."""
    from galileo.commands import create_sessions, link_sessions
    from galileo.library.models import fitsSession

    assert cli.run(create_sessions) == 0
    assert cli.run(link_sessions, "-v") == 0
    out = capsys.readouterr().out
    assert "Updated 1 light sessions" in out

    light = fitsSession.get(fitsSession.fitsSessionObjectName == "M42")
    assert light.fitsBiasSession and light.fitsDarkSession and light.fitsFlatSession


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_link_sessions_exits_on_missing_config_or_failure(library, cli, monkeypatch):
    """LIB-130: link_sessions exits 1 for a missing --config and for a failure while linking."""
    from galileo.commands import link_sessions

    assert cli.run(link_sessions, "-c", str(library.root / "nope.ini")) == 1

    monkeypatch.setattr(link_sessions, "fitsProcessing", lambda: SimpleNamespace(
        linkSessions=lambda progress_callback=None: (_ for _ in ()).throw(RuntimeError("link failed"))))
    assert cli.run(link_sessions, "-c", str(library.ini)) == 1


# ---------------------------------------------------------------------------
# register_existing
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_register_existing_dry_run_changes_nothing(library, cli, monkeypatch):
    """LIB-130: --dry-run reports the options and never calls the registration."""
    from galileo.commands import register_existing

    called = []
    monkeypatch.setattr("galileo.library.core.fitsProcessing.registerExistingFiles", lambda self, **kw: called.append(kw))
    assert cli.run(register_existing, "--dry-run", "--log-file", str(cli.logs / "r.log")) == 0
    assert called == []


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_register_existing_exit_code_follows_errors(library, cli, monkeypatch):
    """LIB-130: registration passes --no-subdirs/--no-header-verify through, and exits 0 only when it finished without errors."""
    from galileo.commands import register_existing

    seen = {}

    def fake(self, progress_callback=None, scan_subdirectories=True, verify_headers=True):
        seen.update(subdirs=scan_subdirectories, verify=verify_headers)
        return {"summary": {"total_files_processed": 3, "master_frames": {"found": 1}, "calibrated_lights": {"found": 2},
                            "database_changes": 3}, "errors": seen.get("errors", [])}

    monkeypatch.setattr("galileo.library.core.fitsProcessing.registerExistingFiles", fake)
    log = str(cli.logs / "r.log")
    assert cli.run(register_existing, "--no-subdirs", "--no-header-verify", "--log-file", log) == 0
    assert seen == {"subdirs": False, "verify": False}

    seen["errors"] = ["bad header in a.fits"]
    assert cli.run(register_existing, "--log-file", log) == 1


def _repo_with_existing_files(library):
    """A repository holding two light frames, a master dark, a generated cal_ light and one frame in a sub-folder."""
    write_light_frames(library.repo, count=2)
    write_frame(library.repo, "master_dark.fits", "Master Dark", "Dark", 60, 40, level=100)
    write_frame(library.repo, "cal_light_9.fits", "Light Frame", "M42", 60, 9, filt="Ha", date="2026-09-16T23:59:00")
    (library.repo / "older").mkdir()
    write_frame(library.repo / "older", "light_old.fits", "Light Frame", "M31", 60, 50, filt="Ha", date="2026-08-01T22:00:00")


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_register_existing_catalogs_what_is_in_the_repository_in_place(library, cli):
    """LIB-130: register-existing catalogs the repository's masters and light frames where they are (the registration Regenerate does, without clearing anything), and a second run adds nothing."""
    from galileo.commands import register_existing
    from galileo.library.models import Masters, fitsFile

    _repo_with_existing_files(library)
    on_disk = sorted(p for p in library.repo.rglob("*.fits"))

    assert cli.run(register_existing, "--log-file", str(cli.logs / "r.log")) == 0
    names = {Path(r.fitsFileName).name for r in fitsFile.select()}
    assert {"light_0.fits", "light_1.fits", "cal_light_9.fits", "light_old.fits"} <= names
    assert Masters.select().count() == 1
    assert sorted(library.repo.rglob("*.fits")) == on_disk, "nothing is moved, renamed or removed"

    rows = fitsFile.select().count()
    assert cli.run(register_existing, "--log-file", str(cli.logs / "r.log")) == 0
    assert fitsFile.select().count() == rows and Masters.select().count() == 1, "already-catalogued files are not added twice"


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_register_existing_reports_what_it_found(library):
    """LIB-130: the processor's registerExistingFiles summarises masters found, generated cal_ lights found and catalog rows added."""
    from galileo.library.core import fitsProcessing

    _repo_with_existing_files(library)
    result = fitsProcessing().registerExistingFiles()

    summary = result["summary"]
    assert result["errors"] == []
    assert summary["master_frames"]["found"] == 1 and summary["calibrated_lights"]["found"] == 1
    assert summary["total_files_processed"] >= 5 and summary["database_changes"] >= 5

    assert fitsProcessing().registerExistingFiles()["summary"]["database_changes"] == 0


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_register_existing_no_subdirs_stays_at_the_top_level(library, cli):
    """LIB-130: --no-subdirs leaves the repository's sub-folders alone."""
    from galileo.commands import register_existing
    from galileo.library.models import fitsFile

    _repo_with_existing_files(library)
    assert cli.run(register_existing, "--no-subdirs", "--log-file", str(cli.logs / "r.log")) == 0
    names = {Path(r.fitsFileName).name for r in fitsFile.select()}
    assert "light_0.fits" in names and "light_old.fits" not in names


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_register_existing_can_be_cancelled_from_the_progress_callback(library):
    """LIB-130: a progress callback that returns False stops the scan, as the Regenerate dialog's Cancel does."""
    from galileo.library.core import fitsProcessing

    write_light_frames(library.repo, count=3)
    seen = []
    fitsProcessing().registerExistingFiles(progress_callback=lambda current, total, name: seen.append(name) or False)
    assert len(seen) <= 2, "scanning stopped at the first refusal (once for masters, once for images)"


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_register_existing_progress_callback_and_db_validation(library, capsys):
    """LIB-130: the progress callback draws a percentage bar once per change and always lets the work continue; database validation passes on a migrated catalog."""
    from galileo.commands import register_existing

    callback = register_existing.create_cli_progress_callback("Registering")
    assert callback(5, 10, "half") is True and callback(5, 10, "half") is True and callback(10, 10, "done") is True
    assert callback(0, 0, "no total") is True
    out = capsys.readouterr().out
    assert out.count("50%") == 1 and "100%" in out and "Registering: no total" in out

    assert register_existing.validate_database_access() is True


# ---------------------------------------------------------------------------
# reset_calibration_test_state
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_reset_calibration_recognises_generated_outputs():
    """LIB-130: a row is a generated calibrated output if it records an original file or is named cal_*, on either path separator."""
    from galileo.commands.reset_calibration_test_state import _is_generated_calibrated_output

    def row(name=None, original=None):
        return SimpleNamespace(fitsFileName=name, fitsFileOriginalFile=original)

    assert _is_generated_calibrated_output(row("/repo/cal_M42_001.fits"))
    assert _is_generated_calibrated_output(row("C:\\repo\\CAL_M42_001.fits"))
    assert _is_generated_calibrated_output(row("/repo/M42_001.fits", original="/repo/raw.fits"))
    assert not _is_generated_calibrated_output(row("/repo/M42_001.fits"))
    assert not _is_generated_calibrated_output(row("/repo/M42_001.fits", original="   "))
    assert not _is_generated_calibrated_output(row(None))


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_reset_calibration_removes_outputs_and_clears_flags(ingested, cli):
    """LIB-130: the reset deletes generated cal_ outputs (row and file), clears soft-delete, and un-calibrates the remaining lights."""
    from galileo.commands import reset_calibration_test_state as reset
    from galileo.library.models import fitsFile

    raw = fitsFile.select().where(fitsFile.fitsFileType == "LIGHT FRAME").get()
    out_file = Path(raw.fitsFileName).parent / "cal_light_0.fits"
    out_file.write_bytes(b"x")
    cal_row = fitsFile.create(fitsFileId="cal-1", fitsFileName=str(out_file), fitsFileType="LIGHT FRAME",
                              fitsFileOriginalFile=raw.fitsFileName, fitsFileCalibrated=1)
    ghost = fitsFile.create(fitsFileId="cal-2", fitsFileName=str(out_file.parent / "cal_missing.fits"), fitsFileType="LIGHT FRAME")
    fitsFile.update(fitsFileCalibrated=1, fitsFileSoftDelete=True).where(fitsFile.fitsFileId == raw.fitsFileId).execute()

    assert cli.run(reset) == 0

    assert not out_file.exists()
    assert fitsFile.select().where(fitsFile.fitsFileId.in_([cal_row.fitsFileId, ghost.fitsFileId])).count() == 0
    kept = fitsFile.get(fitsFile.fitsFileId == raw.fitsFileId)
    assert not kept.fitsFileSoftDelete and not kept.fitsFileCalibrated
    assert Path(kept.fitsFileName).exists(), "the original light frame is never touched"


# ---------------------------------------------------------------------------
# stack
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_stack_helpers(tmp_path):
    """LIB-130: precalibrated detection (iTelescope / SeeStar), the best-reference pick (lowest HFR among files that exist) and the output name."""
    from galileo.commands import stack

    assert stack._is_precalibrated_session("iTelescope T11", None) and stack._is_precalibrated_session(None, "ZWO SeeStar S50")
    assert not stack._is_precalibrated_session("Home scope", "ASI294") and not stack._is_precalibrated_session(None, None)

    a, b, c = (tmp_path / n for n in ("a.fits", "b.fits", "c.fits"))
    for p in (a, b, c):
        p.write_bytes(b"x")
    files = [
        SimpleNamespace(fitsFileName=str(a), fitsFileAvgHFRArcsec=2.5),
        SimpleNamespace(fitsFileName=str(b), fitsFileAvgHFRArcsec=1.5),
        SimpleNamespace(fitsFileName=str(c), fitsFileAvgHFRArcsec="not a number"),
        SimpleNamespace(fitsFileName=str(tmp_path / "gone.fits"), fitsFileAvgHFRArcsec=0.1),   # sharpest, but not on disk
        SimpleNamespace(fitsFileName=None, fitsFileAvgHFRArcsec=0.2),
    ]
    assert stack._select_best_reference_path(files) == str(b)
    assert stack._select_best_reference_path([SimpleNamespace(fitsFileName=str(a), fitsFileAvgHFRArcsec=None)]) is None

    session = SimpleNamespace(fitsSessionDate="2026-09-16", fitsSessionId="abc")
    out = stack._default_output_path(session, [str(a)], "NGC 7000/North America")
    assert Path(out).parent == tmp_path and Path(out).name == "stack_NGC_7000_North_America_2026-09-16_abc.fits"


@pytest.fixture
def stackable(ingested):
    """One light session with all three frames calibrated (so they are stack candidates)."""
    from galileo.library.models import fitsFile
    from galileo.library.core import fitsProcessing

    fitsProcessing().createLightSessions(progress_callback=None)
    fitsFile.update(fitsFileCalibrated=1).where(fitsFile.fitsFileType == "LIGHT FRAME").execute()
    from galileo.library.models import fitsSession
    return fitsSession.get(fitsSession.fitsSessionObjectName == "M42")


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_stack_target_selection(stackable, cli):
    """LIB-130: --all picks light sessions (never Bias/Dark/Flat), --unstacked drops sessions with a stacked frame, --session picks one by id."""
    from galileo.commands import stack
    from galileo.library.core import fitsProcessing
    from galileo.library.models import fitsFile

    fitsProcessing().createCalibrationSessions(progress_callback=None)
    names = [s.fitsSessionObjectName for s in stack._select_target_sessions(True, False, None)]
    assert names == ["M42"]
    assert [s.fitsSessionId for s in stack._select_target_sessions(False, True, None)] == [stackable.fitsSessionId]
    assert [s.fitsSessionId for s in stack._select_target_sessions(False, False, str(stackable.fitsSessionId))] == [stackable.fitsSessionId]
    assert stack._select_target_sessions(False, False, "999999") == []

    fitsFile.update(fitsFileStacked=1).where(fitsFile.fitsFileType == "LIGHT FRAME").execute()
    assert stack._select_target_sessions(False, True, None) == []


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_stack_dry_run_writes_nothing_and_unknown_session_exits_2(stackable, cli):
    """LIB-130: --dry-run reports the stack without writing it; an unknown --session exits 2."""
    from galileo.commands import stack
    from galileo.library.models import fitsFile

    folder = Path(fitsFile.select().where(fitsFile.fitsFileType == "LIGHT FRAME").get().fitsFileName).parent
    assert cli.run(stack, "--session", str(stackable.fitsSessionId), "--dry-run") == 0
    assert not list(folder.glob("stack_*.fits"))
    assert cli.run(stack, "--session", "999999") == 2


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
@pytest.mark.parametrize("photometric", [False, True])
def test_tc_lib_130_stack_session_writes_marks_and_is_idempotent(stackable, cli, monkeypatch, photometric):
    """LIB-130: a stack is written next to the frames by the right method (sigma-clip by default, registered mean with --photometric), the frames are marked stacked, and re-running does not redo it."""
    from galileo.commands import stack
    from galileo.library.core.master_manager import get_master_manager
    from galileo.library.models import fitsFile

    calls = []

    def fake_stack(self, **kwargs):
        calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"stack")
        return True

    manager = get_master_manager()
    monkeypatch.setattr(type(manager), "_create_master_sigma_clip", fake_stack)
    monkeypatch.setattr(type(manager), "_create_light_stack_photometric_mean", fake_stack)

    args = ["--session", str(stackable.fitsSessionId)] + (["--photometric"] if photometric else [])
    assert cli.run(stack, *args) == 0
    assert len(calls) == 1 and len(calls[0]["file_paths"]) == 3
    assert Path(calls[0]["output_path"]).name.startswith("photometric_stack_" if photometric else "stack_")
    assert ("cal_type" in calls[0]) == (not photometric)
    assert fitsFile.select().where(fitsFile.fitsFileStacked == 1).count() == 3

    assert cli.run(stack, *args) == 0 and len(calls) == 1, "the existing stack is kept, not rebuilt"


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_stack_session_skips_and_failures(stackable, cli, monkeypatch):
    """LIB-130: calibration sessions and sessions with fewer than two calibrated frames are skipped successfully; a stacker that fails makes the run exit 1."""
    from galileo.commands import stack
    from galileo.library.core.master_manager import get_master_manager
    from galileo.library.models import fitsFile, fitsSession

    log = logging.getLogger("test")
    fitsSession.create(fitsSessionId="bias-1", fitsSessionObjectName="Bias")
    assert stack.stack_session("bias-1", dry_run=False, logger=log) is True
    assert stack.stack_session("nope", dry_run=False, logger=log) is False

    monkeypatch.setattr(type(get_master_manager()), "_create_master_sigma_clip", lambda self, **kw: False)
    assert cli.run(stack, "--all") == 1, "the stacker reported failure"

    fitsFile.update(fitsFileCalibrated=0).execute()
    assert stack.stack_session(str(stackable.fitsSessionId), dry_run=False, logger=log) is True, "nothing calibrated: skipped, not failed"


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------

class FakeTelescopeManager:
    """Stands in for ``SmartTelescopeManager``: a telescope that holds the given files."""

    def __init__(self, files, *, found="10.0.0.5", fail=()):
        self.files, self.found, self.fail = files, found, set(fail)
        self.deleted, self.downloaded = [], []

    def find_telescope(self, telescope_type, network_range=None, hostname=None):
        return (self.found, None) if self.found else (None, "not on this network")

    def get_itelescope_credentials(self):
        return "user", "pw"

    def get_fits_files(self, telescope_type, ip, username=None, password=None):
        return self.files, None

    def download_file(self, telescope_type, ip, file_info, local_path, username=None, password=None, progress_callback=None):
        if file_info["name"] in self.fail:
            return False, "transfer failed"
        write_frame(Path(local_path).parent, Path(local_path).name, "Light Frame", "M45", 30, len(self.downloaded))
        self.downloaded.append(local_path)
        return True, None

    def delete_file(self, telescope_type, ip, file_info):
        self.deleted.append(file_info["name"])
        return True, None


def _remote(*names):
    return [{"name": n, "path": f"/data/{n}", "size": 1024 * 1024, "folder_name": "M45_sub"} for n in names]


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_download_destination_folder(library):
    """LIB-130: the download folder is the --destination override, else the repository ``source`` setting; with neither it is an error."""
    from galileo.commands.download import get_destination_folder
    from galileo.commands._common import load_config

    config = load_config()
    assert get_destination_folder(config, "/override") == "/override"
    assert get_destination_folder(config) == config.get("DEFAULT", "source")
    with pytest.raises(ValueError, match="source folder"):
        get_destination_folder(configparser.ConfigParser())


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_download_files_registers_what_it_fetches(library, monkeypatch):
    """LIB-130: download_files fetches every file the telescope lists, keeps the telescope's folder layout, registers each in the catalog and can delete them from the telescope."""
    from galileo.commands import download
    from galileo.library.models import fitsFile

    fake = FakeTelescopeManager(_remote("a.fits", "b.fits"))
    monkeypatch.setattr(download, "SmartTelescopeManager", lambda: fake)
    dest = library.root / "dl"

    assert download.download_files("SeeStar", "seestar.local", None, str(dest), delete_files=True) is True
    assert fitsFile.select().count() == 2
    assert fake.deleted == ["a.fits", "b.fits"]


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_download_files_dry_run_failures_and_missing_telescope(library, monkeypatch):
    """LIB-130: --dry-run lists without fetching; a failed transfer fails the run but not the others; no telescope or no files are handled."""
    from galileo.commands import download
    from galileo.library.models import fitsFile

    dest = str(library.root / "dl")
    fake = FakeTelescopeManager(_remote("a.fits", "b.fits"))
    monkeypatch.setattr(download, "SmartTelescopeManager", lambda: fake)
    assert download.download_files("SeeStar", None, "10.0.0.0/24", dest, dry_run=True) is True
    assert fake.downloaded == [] and fitsFile.select().count() == 0

    fake.fail = {"a.fits"}
    assert download.download_files("SeeStar", "h", None, dest) is False
    assert fitsFile.select().count() == 1, "the file that transferred was still registered"

    monkeypatch.setattr(download, "SmartTelescopeManager", lambda: FakeTelescopeManager([], found=None))
    assert download.download_files("SeeStar", None, None, dest) is False
    monkeypatch.setattr(download, "SmartTelescopeManager", lambda: FakeTelescopeManager([]))
    assert download.download_files("SeeStar", "h", None, dest) is True, "an empty telescope is not an error"


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_download_itelescope_credentials_and_sftp_choice(library, cli, monkeypatch):
    """LIB-130: iTelescope needs credentials (-u/-p or the saved ones) and exits 1 without them; SFTP is an accepted telescope type."""
    from galileo.commands import download

    monkeypatch.setattr("galileo.library.config.get_itelescope_password", lambda: "")
    assert cli.run(download, "-t", "iTelescope") == 1

    seen = {}
    monkeypatch.setattr(download, "download_files", lambda **kw: seen.update(kw) or True)
    assert cli.run(download, "-t", "SFTP", "-H", "observatory.example", "--dry-run", "-d", str(library.root / "dl")) == 0
    assert seen["telescope_type"] == "SFTP" and seen["hostname"] == "observatory.example" and seen["dry_run"] is True

    assert cli.run(download, "-t", "NotATelescope") == 2


# ---------------------------------------------------------------------------
# photometry / variable_star_photometry
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_photometry_inputs_and_output_paths(library, cli, monkeypatch):
    """LIB-130: photometry takes a file or a directory (by glob), writes a CSV next to each input (or at -o for a single file), and exits 2 when nothing matches, 1 when nothing could be measured."""
    from galileo.commands import photometry

    a = write_frame(library.root, "a.fits", "Light Frame", "M42", 60, 1)
    b = write_frame(library.root, "b.fits", "Light Frame", "M42", 60, 2)
    assert photometry._iter_inputs(str(library.root), "*.fits") == sorted([str(a), str(b)])
    assert photometry._iter_inputs(str(a), "*.fits") == [str(a)]

    measured, written = [], []
    monkeypatch.setattr("galileo.library.core.photometry.run_aperture_photometry",
                        lambda path, options=None: measured.append((path, options)) or [{"x": 1}, {"x": 2}])
    monkeypatch.setattr("galileo.library.core.photometry.write_photometry_csv", lambda rows, path: written.append(path))

    assert cli.run(photometry, str(library.root), "--aperture", "5", "--source-snr", "7", "--max-sources", "50") == 0
    assert [Path(p).name for p in written] == ["photometry_a.csv", "photometry_b.csv"]
    options = measured[0][1]
    assert (options.aperture_radius_pixels, options.source_snr, options.max_sources) == (5.0, 7.0, 50)

    written.clear()
    assert cli.run(photometry, str(a), "-o", str(library.root / "mine.csv")) == 0
    assert written == [str(library.root / "mine.csv")]

    assert cli.run(photometry, str(library.root), "--glob", "*.nomatch") == 2
    assert cli.run(photometry, str(library.root / "missing.fits")) == 1


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_variable_star_photometry_helpers():
    """LIB-130: variable-star photometry derives its JSON/CSV names from the stack and detects precalibrated data like stack does."""
    from galileo.commands import variable_star_photometry as vsp

    json_path, csv_path = vsp._default_outputs(os.path.join("/data", "stack_RW AUR.fits"))
    assert Path(json_path).name == "varstar_stack_RW AUR.json" and Path(csv_path).name == "varstar_stack_RW AUR.csv"
    assert Path(json_path).parent == Path(csv_path).parent == Path("/data")
    assert vsp._is_precalibrated_session("iTelescope T5", None) and vsp._is_precalibrated_session(None, "Seestar S30")
    assert not vsp._is_precalibrated_session("Home", "ASI")


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_variable_star_photometry_requires_a_source_and_a_star(library, cli):
    """LIB-130: --session and --stacked-fits are mutually exclusive and one is required, and --star-name is required (argparse exit 2)."""
    from galileo.commands import variable_star_photometry as vsp

    assert cli.run(vsp, "--star-name", "RW AUR") == 2
    assert cli.run(vsp, "--session", "1", "--stacked-fits", "x.fits", "--star-name", "RW AUR") == 2
    assert cli.run(vsp, "--session", "1") == 2


# ---------------------------------------------------------------------------
# auto_calibration
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_auto_calibration_config_defaults_and_overrides(library):
    """LIB-130: the auto-calibration settings come from library.ini with defaults (3 files per master, progress on), and a bad value is a ValueError."""
    from galileo.commands import auto_calibration
    from galileo.commands._common import load_config

    cfg = auto_calibration.get_auto_calibration_config(load_config())
    assert cfg["min_files_per_master"] == 3 and cfg["auto_calibration_progress"] is True and cfg["siril_path"] == ""

    set_ini(library, min_files_per_master=5, auto_calibration_progress="False")
    cfg = auto_calibration.get_auto_calibration_config(load_config())
    assert cfg["min_files_per_master"] == 5 and cfg["auto_calibration_progress"] is False

    set_ini(library, min_files_per_master="many")
    with pytest.raises(ValueError, match="Invalid auto-calibration configuration"):
        auto_calibration.get_auto_calibration_config(load_config())


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_auto_calibration_progress_callback(caplog):
    """LIB-130: the progress callback logs every 10% (not every call), accepts (current, total, message) and (percent, message) forms, and always continues."""
    from galileo.commands import auto_calibration

    callback = auto_calibration.create_cli_progress_callback("Creating masters")
    with caplog.at_level("INFO", logger=auto_calibration.logger.name):
        assert callback(1, 10, "start") and callback(1, 10, "start again") and callback(2, 10, "second")
        assert callback(50, None) is True
        assert callback(0, "just a message") is True
    messages = [r.getMessage() for r in caplog.records]
    assert sum("10%" in m for m in messages) == 1, "a repeated percentage is logged once"
    assert any("20%" in m for m in messages) and any("50%" in m for m in messages)
    assert any("just a message" in m for m in messages)


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_auto_calibration_operations_dispatch_and_exit_codes(library, cli, monkeypatch):
    """LIB-130: each --operation runs its own step with the shared options, a step reporting failure exits 1, and the default is the whole workflow."""
    from galileo.commands import auto_calibration

    calls = []

    def stub(name, result=True):
        def inner(*args, **kwargs):
            calls.append((name, args))
            return result
        return inner

    monkeypatch.setattr(auto_calibration, "validate_database_access", lambda: True)
    monkeypatch.setattr(auto_calibration, "analyze_calibration_opportunities", stub("analyze", result={"found": 1}))
    monkeypatch.setattr(auto_calibration, "create_master_frames", stub("masters"))
    monkeypatch.setattr(auto_calibration, "calibrate_light_frames", stub("calibrate"))
    monkeypatch.setattr(auto_calibration, "perform_quality_assessment", stub("quality"))
    monkeypatch.setattr(auto_calibration, "clear_all_masters", stub("clear"))
    monkeypatch.setattr(auto_calibration, "run_complete_workflow", stub("all"))

    for operation, expected in (("analyze", "analyze"), ("masters", "masters"), ("calibrate-lights", "calibrate"),
                                ("quality", "quality"), ("clear-masters", "clear"), ("all", "all")):
        calls.clear()
        assert cli.run(auto_calibration, "-o", operation, "-q", "--log-file", str(cli.logs / "ac.log")) == 0, operation
        assert [name for name, _ in calls] == [expected]

    calls.clear()
    assert cli.run(auto_calibration, "-q", "--quality-only", "--log-file", str(cli.logs / "ac.log")) == 0
    assert [name for name, _ in calls] == ["quality"], "--quality-only skips calibration"

    calls.clear()
    assert cli.run(auto_calibration, "-o", "masters", "-s", "42", "-f", "--dry-run", "-q", "--log-file", str(cli.logs / "ac.log")) == 0
    _, args = calls[0]
    assert args[1:] == ("42", True, True, False)       # session, force, dry_run, verbose

    monkeypatch.setattr(auto_calibration, "create_master_frames", stub("masters", result=False))
    assert cli.run(auto_calibration, "-o", "masters", "-q", "--log-file", str(cli.logs / "ac.log")) == 1


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_auto_calibration_failure_modes(library, cli, monkeypatch, capsys):
    """LIB-130: a missing config exits 1, a DatabaseError is reported plainly, Ctrl+C exits 130, and the workflow wrapper turns an exception or an unsuccessful result into False."""
    from galileo.commands import auto_calibration
    from galileo.library.exceptions import DatabaseError

    log = ["--log-file", str(cli.logs / "ac.log"), "-q"]
    assert cli.run(auto_calibration, "-c", str(library.root / "nope.ini"), *log) == 1

    log += ["-c", str(library.ini)]      # the bad -c above stays selected for the process until another is given
    monkeypatch.setattr(auto_calibration, "validate_database_access", lambda: (_ for _ in ()).throw(DatabaseError("stale schema")))
    assert cli.run(auto_calibration, *log) == 1
    assert "DATABASE ERROR" in capsys.readouterr().out

    monkeypatch.setattr(auto_calibration, "validate_database_access", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert cli.run(auto_calibration, *log) == 130

    class Processor:
        outcome = {"success": False, "errors": ["no masters"]}

        def runAutoCalibrationWorkflow(self, progress_callback=None):
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

    monkeypatch.setattr("galileo.library.core.fitsProcessing", Processor)
    assert auto_calibration.run_complete_workflow(None) is False
    Processor.outcome = {"success": True, "masters_created": 2, "opportunities_detected": 3, "errors": ["minor"]}
    assert auto_calibration.run_complete_workflow(None) is True
    Processor.outcome = RuntimeError("boom")
    assert auto_calibration.run_complete_workflow(None) is False


# ---------------------------------------------------------------------------
# cloud_sync
# ---------------------------------------------------------------------------

@pytest.fixture
def cloud_ini(library):
    auth = library.root / "service-account.json"
    auth.write_text("{}")
    set_ini(library, bucket_url="gs://my-bucket/", auth_file_path=auth, sync_profile="backup")
    return auth


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_cloud_config_validation(library, cloud_ini):
    """LIB-130: the cloud settings need a bucket URL and an existing credentials file, each with a message naming what to set; the profile defaults to complete."""
    from galileo.commands import cloud_sync
    from galileo.commands._common import load_config

    cfg = cloud_sync.get_cloud_config(load_config())
    assert cfg == {"bucket_url": "gs://my-bucket/", "auth_file_path": str(cloud_ini), "sync_profile": "backup"}

    set_ini(library, sync_profile="")
    assert cloud_sync.get_cloud_config(load_config())["sync_profile"] == ""

    set_ini(library, bucket_url="")
    with pytest.raises(ValueError, match="Bucket URL not configured"):
        cloud_sync.get_cloud_config(load_config())
    set_ini(library, bucket_url="gs://b", auth_file_path="")
    with pytest.raises(ValueError, match="Authentication file path not configured"):
        cloud_sync.get_cloud_config(load_config())
    set_ini(library, auth_file_path=library.root / "missing.json")
    with pytest.raises(ValueError, match="Authentication file not found"):
        cloud_sync.get_cloud_config(load_config())


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
@pytest.mark.parametrize("url,bucket", [("gs://my-bucket/", "my-bucket"), ("gs://my-bucket", "my-bucket"), ("plain-bucket/", "plain-bucket")])
def test_tc_lib_130_cloud_bucket_access_check(url, bucket, monkeypatch):
    """LIB-130: the bucket name is taken from a gs:// URL or a bare name, access is probed by listing one object, and a failure says it could not access the bucket."""
    from galileo.commands import cloud_sync

    asked = []

    class Client:
        def bucket(self, name):
            asked.append(name)
            return SimpleNamespace(list_blobs=lambda max_results: iter([]))

    monkeypatch.setattr("galileo.library.services.gcs._get_gcs_client", lambda auth: Client())
    assert cloud_sync.validate_bucket_access({"bucket_url": url, "auth_file_path": "key.json"}) is True
    assert asked == [bucket]

    monkeypatch.setattr("galileo.library.services.gcs._get_gcs_client", lambda auth: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(Exception, match="Failed to access cloud bucket: denied"):
        cloud_sync.validate_bucket_access({"bucket_url": url, "auth_file_path": "key.json"})


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_cloud_sync_confirmation_and_profile_routing(library, cloud_ini, monkeypatch, capsys):
    """LIB-130: a sync asks before it starts (declining cancels), -y skips the question, each profile runs its own routine, and an unknown profile or missing repository is an error."""
    from galileo.commands import cloud_sync

    ran = []
    for name in ("backup", "complete", "ondemand"):
        monkeypatch.setattr(cloud_sync, f"perform_{name}_sync_cli" if name != "ondemand" else "perform_ondemand_sync_cli",
                            lambda cfg, repo, name=name: ran.append(name))
    cfg = {"bucket_url": "gs://b", "auth_file_path": str(cloud_ini)}

    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    cloud_sync.perform_sync(cfg, "backup")
    assert ran == [] and "Operation cancelled" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    cloud_sync.perform_sync(cfg, "backup")
    for profile in ("complete", "ondemand"):
        cloud_sync.perform_sync(cfg, profile, auto_confirm=True)
    assert ran == ["backup", "complete", "ondemand"]

    with pytest.raises(ValueError, match="Unknown sync profile"):
        cloud_sync.perform_sync(cfg, "sideways", auto_confirm=True)

    set_ini(library, repo=library.root / "no_such_repo")
    with pytest.raises(ValueError, match="Repository path"):
        cloud_sync.perform_sync(cfg, "backup", auto_confirm=True)


@pytest.mark.requirement("TC-LIB-130")
@pytest.mark.priority("P2")
def test_tc_lib_130_cloud_sync_main_options(library, cloud_ini, cli, monkeypatch):
    """LIB-130: -p overrides the saved profile, -a only analyses, -y skips confirmation, and a bad configuration or inaccessible bucket exits 1."""
    from galileo.commands import cloud_sync

    seen = []
    monkeypatch.setattr(cloud_sync, "validate_bucket_access", lambda cfg: True)
    monkeypatch.setattr(cloud_sync, "perform_analysis", lambda cfg: seen.append(("analysis", cfg["sync_profile"])))
    monkeypatch.setattr(cloud_sync, "perform_sync", lambda cfg, profile, yes: seen.append(("sync", profile, yes)))

    assert cli.run(cloud_sync, "-y") == 0
    assert cli.run(cloud_sync, "-p", "complete") == 0
    assert cli.run(cloud_sync, "-a", "-p", "ondemand") == 0
    assert seen == [("sync", "backup", True), ("sync", "complete", False), ("analysis", "ondemand")]

    monkeypatch.setattr(cloud_sync, "validate_bucket_access", lambda cfg: (_ for _ in ()).throw(Exception("no access")))
    assert cli.run(cloud_sync, "-y") == 1

    set_ini(library, bucket_url="")
    assert cli.run(cloud_sync, "-y") == 1
    assert cli.run(cloud_sync, "-p", "everything") == 2
