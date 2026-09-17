"""Galileo application entry point (EXT-010).

Starts the PySide6 QApplication and the main window.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


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

    from galileo.diagnostics import DiagnosticsService
    diag = DiagnosticsService()
    logger.info("Galileo %s starting", _version())

    from galileo.ui.app_window import AppWindow
    window = AppWindow()
    window.show()

    sys.exit(app.exec())


def _version() -> str:
    from galileo import __version__
    return __version__


if __name__ == "__main__":
    main()
