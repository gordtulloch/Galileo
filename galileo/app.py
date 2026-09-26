# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Galileo application entry point (EXT-010).

Starts the PySide6 QApplication and the main window.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "images" / "logo.png"


def main() -> None:
    """Launch Galileo."""
    # A frozen (Nuitka/MSI) build re-launches this executable for each CPU worker process
    # (galileo.core.compute); this makes those launches run the worker, not a second app.
    # It does nothing when running from source.
    import multiprocessing
    multiprocessing.freeze_support()

    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
    except ImportError:
        print("PySide6 is required to run Galileo.  Install it with: pip install PySide6")
        sys.exit(1)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Galileo")
    app.setOrganizationName("GordTulloch")

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
        splash.finish(getattr(window, "_window", None))

    exit_code = app.exec()
    # Stop the CPU worker pool (SDD §2.3) now rather than leaving atexit to do it after Qt is gone.
    from galileo.core.compute import shutdown_cpu_executor
    shutdown_cpu_executor(wait=False)
    sys.exit(exit_code)


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
        FULL_NOTICE,
        Qt.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("white"),
    )
    splash.show()
    app.processEvents()
    return splash


def _version() -> str:
    from galileo import __version__
    return __version__


if __name__ == "__main__":
    main()
