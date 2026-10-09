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

    from galileo.diagnostics import DiagnosticsService
    diag = DiagnosticsService()
    logger.info("Galileo %s starting", _version())

    from galileo.library.database import init_db
    init_db()

    from galileo.ui.app_window import AppWindow
    window = AppWindow()
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
    from PySide6.QtWidgets import QSplashScreen
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

    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
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
            import galileo.library.core  # noqa: F401
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
