# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Galileo application entry point (EXT-010).

Starts the PySide6 QApplication and the main window.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import cast

logger = logging.getLogger(__name__)

_SPLASH_MINIMUM_MS = 1000
_SPLASH_PAINT_GRACE_MS = 100
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "images" / "logo.png"
_ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "images" / "galileo.ico"


def main() -> None:
    """Launch Galileo."""
    # A frozen (Nuitka/MSI) build re-launches this executable for each CPU worker process
    # (galileo.core.compute); this makes those launches run the worker, not a second app.
    # It does nothing when running from source.
    import multiprocessing
    multiprocessing.freeze_support()

    # `Galileo --selftest [REPORT_FILE]`: headless check of an installed/frozen build (CI runs it).
    if "--selftest" in sys.argv:
        from galileo.selftest import run
        idx = sys.argv.index("--selftest")
        report = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        sys.exit(run(report))

    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QIcon
    except ImportError:
        print("PySide6 is required to run Galileo.  Install it with: pip install PySide6")
        sys.exit(1)

    # instance() is typed as QCoreApplication; a running one here is always the QApplication we create.
    app = cast(QApplication, QApplication.instance() or QApplication(sys.argv))
    app.setApplicationName("Galileo")
    app.setOrganizationName("GordTulloch")
    if _ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(_ICON_PATH)))
    else:
        logger.warning("Application icon not found at %s", _ICON_PATH)

    splash_started_at = time.monotonic()
    splash = _show_splash(app)

    # Operations still to come once the main window module is imported are added then (add_steps);
    # the fixed ones here are: diagnostics, crash handlers, database, window code, window chrome,
    # plugins, top bar, theme, watchdog.
    from galileo.ui import startup_progress
    progress = None
    if splash is not None:
        progress = startup_progress.StartupProgress(splash, app, total=9)
        startup_progress.set_reporter(progress)

    startup_progress.report("Starting diagnostics")
    from galileo.diagnostics import DiagnosticsService
    DiagnosticsService()
    logger.info("Galileo %s starting", _version())

    # Last-chance crash reporting (LOG-070): excepthooks, faulthandler, fatal-error dialog.
    startup_progress.report("Installing crash reporting")
    from galileo.crashreport import install_crash_handlers, show_fatal_dialog
    install_crash_handlers(dialog=show_fatal_dialog)

    startup_progress.report("Opening database and applying migrations")
    from galileo.library.database import init_db
    init_db()

    startup_progress.report("Loading user interface code")
    from galileo.ui.app_window import AppWindow, PRIMARY_SECTIONS
    startup_progress.add_steps(len(PRIMARY_SECTIONS) + 1)   # one per screen, plus Options
    window = AppWindow()

    startup_progress.report("Starting watchdog")
    # Crash/hang watchdog (SAFE-060): beaten from the event loop, stopped on aboutToQuit.
    try:
        from galileo.ui.app_window._watchdog import start_watchdog
        start_watchdog(window)
    except Exception:
        logger.exception("Could not start the watchdog")

    startup_progress.set_reporter(None)
    if progress is not None:
        progress.finish()
    window.show()

    if splash is not None:
        _schedule_splash_finish(splash, getattr(window, "_window", None), splash_started_at)

    _schedule_registration_ping()
    _schedule_library_preload()

    exit_code = app.exec()
    # Stop the CPU worker pool (SDD §2.3) now rather than leaving atexit to do it after Qt is gone.
    from galileo.core.compute import shutdown_cpu_executor
    shutdown_cpu_executor(wait=False)
    sys.exit(exit_code)


def _schedule_splash_finish(splash, main_window, started_at: float) -> None:
    """Keep the splash visible until Qt has had time to paint the main window."""
    from PySide6.QtCore import QTimer

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    delay_ms = max(_SPLASH_PAINT_GRACE_MS, _SPLASH_MINIMUM_MS - elapsed_ms)
    QTimer.singleShot(delay_ms, lambda: splash.finish(main_window))


def _show_splash(app):
    """Show the Galileo logo immediately as a translucent splash screen.

    It stays up only while startup work (database, main window) runs; ``main``
    closes it as soon as the window is shown, with no fixed minimum display time.
    """
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtCore import Qt

    from galileo.copyright import FULL_NOTICE

    if not _LOGO_PATH.exists():
        logger.warning("Splash logo not found at %s", _LOGO_PATH)
        return None

    pixmap = QPixmap(str(_LOGO_PATH))
    if pixmap.isNull():
        logger.warning("Failed to load splash logo at %s", _LOGO_PATH)
        return None

    from PySide6.QtGui import QPainter

    from galileo.ui.startup_progress import PROGRESS_AREA_HEIGHT, make_splash_class

    # Extend the logo downwards with a transparent strip so the progress bar sits beneath the licence notice
    # instead of over the artwork.
    logo_height = pixmap.height()
    padded = QPixmap(pixmap.width(), logo_height + PROGRESS_AREA_HEIGHT)
    padded.fill(Qt.transparent)
    painter = QPainter(padded)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()

    splash = make_splash_class()(padded, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
    splash.set_logo_height(logo_height)
    splash.setAttribute(Qt.WA_TranslucentBackground)
    font = splash.font()
    font.setPointSize(16)
    splash.setFont(font)
    splash.showMessage(
        f"v{_version()}\n{FULL_NOTICE}",
        Qt.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("white"),
    )
    splash.show()
    app.processEvents()
    return splash


def _version() -> str:
    from galileo import __version__
    return __version__


def _schedule_registration_ping() -> None:
    """Fire the usage-tracking registration ping once the event loop is spinning (never blocks startup)."""
    try:
        from PySide6.QtCore import QTimer
        from galileo.registration import start_startup_ping
        QTimer.singleShot(0, start_startup_ping)
    except Exception:
        logger.debug("Could not schedule the registration ping", exc_info=True)


def _schedule_library_preload() -> None:
    """Import the Library's heavy modules (scipy, astropy) on a background thread once the window is up.

    The Library screens are built the first time the section is opened, on the UI thread; most of that
    time is these imports, not the catalog, so doing them early removes the pause on first open.
    """
    def _preload() -> None:
        try:
            import galileo.library.core
            import galileo.ui.library.pages  # noqa: F401
        except Exception:
            logger.debug("Library preload failed", exc_info=True)

    try:
        import threading
        from PySide6.QtCore import QTimer
        QTimer.singleShot(
            500, lambda: threading.Thread(target=_preload, name="library-preload", daemon=True).start())
    except Exception:
        logger.debug("Could not schedule the Library preload", exc_info=True)


if __name__ == "__main__":
    main()
