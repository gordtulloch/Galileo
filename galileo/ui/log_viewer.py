"""The View Log window: Galileo's current log file, with a level filter, text search and live follow.

Opened from the small icon menu at the bottom of the sidebar. It reads the datestamped
``galileo_<date>.log`` the diagnostics service writes (every module's records, DEBUG and up), not the
INFO-only tail the per-screen log panes show.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Level name -> names that pass the filter (a "WARNING" view also shows ERROR and CRITICAL).
_LEVELS = {
    "Debug and above": ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    "Info and above": ("INFO", "WARNING", "ERROR", "CRITICAL"),
    "Warnings and above": ("WARNING", "ERROR", "CRITICAL"),
    "Errors only": ("ERROR", "CRITICAL"),
}
_MAX_BYTES = 5_000_000  # only the tail of a very large log is loaded


def filter_log_text(text: str, levels: tuple[str, ...], needle: str = "") -> str:
    """The lines of *text* that pass the level and search filters.

    A line that doesn't start a record (a traceback or other continuation) follows the record before it,
    so a hidden record hides its traceback too.
    """
    needle = needle.lower()
    out: list[str] = []
    keep = True
    for line in text.splitlines():
        parts = line.split(" ", 3)
        # "YYYY-MM-DD HH:MM:SS,mmm LEVEL logger: message" starts a record.
        if len(parts) >= 3 and len(parts[0]) == 10 and parts[0][4:5] == "-":
            keep = parts[2] in levels
        if keep and (not needle or needle in line.lower()):
            out.append(line)
    return "\n".join(out)


def read_log_tail(path: Path, max_bytes: int = _MAX_BYTES) -> str:
    """The text of the log file, or its last *max_bytes* if it is larger."""
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    if size > max_bytes:
        text = text.split("\n", 1)[-1]  # drop the partial first line
    return text


class LogViewerDialog(QDialog):
    """Non-modal log viewer; one instance is reused by the main window."""

    def __init__(self, parent: QWidget | None = None, log_path: Path | None = None) -> None:
        super().__init__(parent)
        from galileo.diagnostics import get_current_log_file

        self._path = log_path or get_current_log_file()
        self.setWindowTitle("Galileo Log")
        self.resize(1000, 640)

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.level_combo = QComboBox()
        self.level_combo.addItems(list(_LEVELS))
        self.level_combo.setCurrentText("Info and above")
        self.level_combo.currentIndexChanged.connect(self.reload)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.reload)
        self.follow_check = QCheckBox("Auto-refresh")
        self.follow_check.setChecked(True)
        self.follow_check.toggled.connect(self._on_follow_toggled)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.reload)
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self._copy)
        self.folder_button = QPushButton("Open Folder")
        self.folder_button.clicked.connect(self._open_folder)
        for widget in (self.level_combo, self.search_edit):
            controls.addWidget(widget, 1 if widget is self.search_edit else 0)
        for widget in (self.follow_check, self.refresh_button, self.copy_button, self.folder_button):
            controls.addWidget(widget)
        layout.addLayout(controls)

        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("LogPane")
        self.log_text.setReadOnly(True)
        self.log_text.setUndoRedoEnabled(False)
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.log_text, 1)

        self.path_label = QLabel(str(self._path) if self._path else "No log file is open.")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.path_label)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.reload)
        self.reload()
        self._timer.start()

    def _on_follow_toggled(self, on: bool) -> None:
        self._timer.start() if on else self._timer.stop()

    def reload(self, *_args) -> None:
        """Re-read the file and apply the filters, keeping the scroll position unless at the bottom."""
        if self._path is None or not Path(self._path).exists():
            self.log_text.setPlainText("Log file not found.")
            return
        try:
            raw = read_log_tail(Path(self._path))
        except OSError as exc:
            self.log_text.setPlainText(f"Could not read the log file: {exc}")
            return
        text = filter_log_text(raw, _LEVELS[self.level_combo.currentText()], self.search_edit.text())
        if text == self.log_text.toPlainText():
            return
        bar = self.log_text.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 2
        previous = bar.value()
        self.log_text.setPlainText(text)
        bar.setValue(bar.maximum() if at_bottom or previous == 0 else previous)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.log_text.toPlainText())

    def _open_folder(self) -> None:
        if self._path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._path).parent)))

    def done(self, result: int) -> None:
        self._timer.stop()
        super().done(result)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if self.follow_check.isChecked():
            self._timer.start()
            self.reload()
