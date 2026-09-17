"""Main application window (PySide6).

Thin shell that wires the domain services to the UI panels.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from PySide6.QtWidgets import QMainWindow, QTabWidget, QLabel, QStatusBar
    from PySide6.QtCore import Qt
    _HAS_QT = True
except ImportError:
    _HAS_QT = False


class AppWindow:
    """Main Galileo application window."""

    def __init__(self) -> None:
        if not _HAS_QT:
            return
        from PySide6.QtWidgets import QMainWindow, QTabWidget
        self._window = QMainWindow()
        self._window.setWindowTitle("Galileo")
        self._window.resize(1400, 900)
        self._tabs = QTabWidget()
        self._window.setCentralWidget(self._tabs)
        self._build_tabs()

    def show(self) -> None:
        if _HAS_QT and hasattr(self, "_window"):
            self._window.show()

    def _build_tabs(self) -> None:
        if not _HAS_QT:
            return
        from PySide6.QtWidgets import QLabel
        for label in ("Equipment", "Imaging", "Sequencer", "Sky Atlas", "Scheduler", "Library", "Variable Stars"):
            self._tabs.addTab(QLabel(label), label)
