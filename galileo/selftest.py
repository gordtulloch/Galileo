# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""``Galileo --selftest [REPORT_FILE]``: a headless check that an installed/frozen build is whole.

Runs without hardware, network or a display (it forces Qt's ``offscreen`` platform) and touches no
user data (the database is a temp file).  It exists because the usual way a PyInstaller build breaks is
silently: a module only imported dynamically is left out, a data file is not copied, or the CPU worker
pool cannot relaunch the frozen executable.  Exit status is 0 only if every check passed.

The result is also written to *REPORT_FILE* when given, because a windowed Windows executable has no
console to print to.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import traceback
from pathlib import Path

# Imports that must work in any working install (the dynamic ones are the ones a freeze can drop).
_REQUIRED_MODULES = (
    "numpy", "scipy", "astropy", "sep", "astroalign", "photutils", "peewee", "peewee_migrate",
    "keyring", "requests", "paramiko", "zeroconf", "PIL", "matplotlib", "reproject",
    "PySide6.QtWidgets", "PySide6.QtSvg",
    "galileo.adapters.indi", "galileo.adapters.indi_client", "galileo.adapters.alpaca",
    "galileo.sequencer.advanced", "galileo.scheduler", "galileo.planning.sky_atlas",
    "galileo.library.database", "galileo.plugins", "galileo.ui.app_window",
)


def _cpu_probe(size: int) -> int:
    """Runs in a pool worker: a real SEP detection, so the worker must import numpy and sep."""
    import numpy as np
    import sep
    data = np.zeros((size, size), dtype=np.float32)
    data[size // 2 - 2:size // 2 + 3, size // 2 - 2:size // 2 + 3] = 1000.0
    bkg = sep.Background(data)
    return len(sep.extract(data - bkg, 5.0, err=bkg.globalrms))


def _check_imports() -> None:
    failed = []
    for name in _REQUIRED_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - report every failure, not just the first
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    if failed:
        raise RuntimeError("could not import:\n    " + "\n    ".join(failed))


def _check_data_files() -> None:
    import galileo.app as app
    from galileo.library.database import MIGRATIONS_DIR
    if not app._LOGO_PATH.exists():
        raise FileNotFoundError(f"logo missing: {app._LOGO_PATH}")
    if not app._ICON_PATH.exists():
        raise FileNotFoundError(f"icon missing: {app._ICON_PATH}")
    if not list(Path(MIGRATIONS_DIR).glob("[0-9][0-9][0-9]_*.py")):
        raise FileNotFoundError(f"no migrations in {MIGRATIONS_DIR}")
    from galileo import help as help_content
    if not help_content.screen_ids():
        raise FileNotFoundError("no in-app help content found (galileo/help/content/*.md)")


def _check_qt() -> None:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([sys.argv[0]])
    if app is None:
        raise RuntimeError("QApplication could not be created")


def _check_database() -> None:
    from galileo.library.database import init_db
    from galileo.library.models.base import db
    with tempfile.TemporaryDirectory() as tmp:
        try:
            init_db(Path(tmp) / "selftest.db")
            tables = db.get_tables()
            if "fitsfile" not in {t.lower() for t in tables}:
                raise RuntimeError(f"migrations ran but the catalog tables are missing: {sorted(tables)}")
        finally:
            if not db.is_closed():
                db.close()


def _check_cpu_pool() -> None:
    from galileo.core import compute
    if compute.WORKERS_ENV in os.environ and compute.worker_count() == 0:
        raise RuntimeError(f"{compute.WORKERS_ENV}=0 would skip the pool check")
    os.environ.setdefault(compute.WORKERS_ENV, "1")
    try:
        found = compute.run_cpu_sync(_cpu_probe, 64)
    finally:
        compute.shutdown_cpu_executor(wait=True)
    if found != 1:
        raise RuntimeError(f"pool worker detected {found} sources in a one-star image, expected 1")


_CHECKS = (
    ("imports", _check_imports),
    ("data files", _check_data_files),
    ("Qt", _check_qt),
    ("database + migrations", _check_database),
    ("CPU worker pool", _check_cpu_pool),
)


def run(report_file: str | None = None) -> int:
    """Run every check, print/write a report, and return the process exit code."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines = [f"Galileo self-test ({'frozen' if getattr(sys, 'frozen', False) else 'source'}, "
             f"Python {sys.version.split()[0]}, {sys.platform})"]
    failures = 0
    for name, check in _CHECKS:
        try:
            check()
            lines.append(f"PASS  {name}")
        except Exception:  # noqa: BLE001
            failures += 1
            lines.append(f"FAIL  {name}\n" + "".join(traceback.format_exc()).rstrip())
    lines.append("SELFTEST OK" if not failures else f"SELFTEST FAILED ({failures} check(s))")
    text = "\n".join(lines) + "\n"
    if sys.stdout is not None:
        print(text, end="")
    if report_file:
        try:
            Path(report_file).write_text(text, encoding="utf-8")
        except OSError as exc:
            # A bad report path must not turn into a crash dialog in a windowed build.
            if sys.stderr is not None:
                print(f"Could not write report to {report_file}: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0
