"""Galileo application entry point (EXT-010).

Starts the PySide6 QApplication and the main window.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "images" / "logo.png"
_SPLASH_DURATION_S = 5.0


def main() -> None:
    """Launch Galileo."""
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
    if splash is not None:
        _hold_splash(app, splash, _SPLASH_DURATION_S)

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

    sys.exit(app.exec())


def _show_splash(app):
    """Show the Galileo logo immediately as a translucent splash screen."""
    from PySide6.QtWidgets import QSplashScreen
    from PySide6.QtGui import QPixmap
    from PySide6.QtCore import Qt

    if not _LOGO_PATH.exists():
        logger.warning("Splash logo not found at %s", _LOGO_PATH)
        return None

    pixmap = QPixmap(str(_LOGO_PATH))
    if pixmap.isNull():
        logger.warning("Failed to load splash logo at %s", _LOGO_PATH)
        return None

    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
    splash.setAttribute(Qt.WA_TranslucentBackground)
    splash.show()
    app.processEvents()
    return splash


def _hold_splash(app, splash, seconds: float) -> None:
    """Keep *splash* on screen and responsive for *seconds* before continuing startup."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.03)


def _version() -> str:
    from galileo import __version__
    return __version__


if __name__ == "__main__":
    main()
