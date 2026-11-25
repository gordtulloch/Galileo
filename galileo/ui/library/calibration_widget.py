# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Library > Calibration: run the auto-calibration command from the UI (LIB-230).

The command (``galileo.commands.auto_calibration``) runs as a separate process, so a long run
never blocks the UI, can be stopped, and behaves exactly as it does from a terminal. Its console
output is shown in a frame on the same screen.
"""

from __future__ import annotations

import codecs
import logging
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

logger = logging.getLogger(__name__)

#: The switch `galileo.app.main` recognises in a frozen build, where there is no `python -m`.
FROZEN_SWITCH = "--auto-calibration"

OPERATIONS = [
    ("all", "All (complete workflow)"),
    ("analyze", "Analyze opportunities"),
    ("masters", "Create masters"),
    ("calibrate-lights", "Calibrate light frames"),
    ("quality", "Assess quality"),
    ("clear-masters", "Clear all masters"),
]

# Which switches the command actually honours for each operation. A switch it would silently ignore
# is greyed out and left off the command line -- above all --dry-run, which `all` ignores.
_APPLIES = {
    "session": {"masters", "calibrate-lights", "quality"},
    "min_files": {"analyze"},
    "force": {"masters", "calibrate-lights"},
    "dry_run": {"masters", "calibrate-lights", "clear-masters"},
    "quality_only": {"all"},
    "report": set(),
    "no_cleanup": set(),
}


class CalibrationWidget(QWidget):
    """Choose the command's switches, run it, and watch its output."""

    def __init__(self) -> None:
        super().__init__()
        self._process: QProcess | None = None
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._build_ui()
        self._update_controls()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._kill)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("Auto-Calibration")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        layout.addWidget(title)

        self.parameters_box = QGroupBox("Parameters")
        columns = QHBoxLayout(self.parameters_box)

        form = QFormLayout()
        self.operation_combo = QComboBox()
        for value, label in OPERATIONS:
            self.operation_combo.addItem(label, value)
        self.operation_combo.currentIndexChanged.connect(self._update_controls)
        form.addRow("Operation", self.operation_combo)

        self.session_edit = QLineEdit()
        self.session_edit.setPlaceholderText("All sessions")
        self.session_edit.textChanged.connect(self._update_preview)
        form.addRow("Session ID", self.session_edit)

        self.min_files_spin = QSpinBox()
        self.min_files_spin.setRange(0, 1000)
        self.min_files_spin.setSpecialValueText("From settings")
        self.min_files_spin.valueChanged.connect(self._update_preview)
        form.addRow("Minimum files", self.min_files_spin)

        self.config_edit, config_row = self._file_row("Default settings", self._browse_config)
        form.addRow("Configuration file", config_row)
        self.log_edit, log_row = self._file_row("library.log", self._browse_log)
        form.addRow("Log file", log_row)
        columns.addLayout(form, 1)

        checks = QVBoxLayout()
        self.dry_run_check = QCheckBox("Dry run")
        self.force_check = QCheckBox("Force")
        self.quality_only_check = QCheckBox("Quality only")
        self.report_check = QCheckBox("Quality report")
        self.no_cleanup_check = QCheckBox("No cleanup")
        self.verbose_check = QCheckBox("Verbose")
        self.quiet_check = QCheckBox("Quiet")
        for box in (self.dry_run_check, self.force_check, self.quality_only_check, self.report_check,
                    self.no_cleanup_check, self.verbose_check, self.quiet_check):
            box.toggled.connect(self._update_controls)
            checks.addWidget(box)
        checks.addStretch(1)
        columns.addLayout(checks)
        layout.addWidget(self.parameters_box)

        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.preview_label)

        buttons = QHBoxLayout()
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.run)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        self.clear_button = QPushButton("Clear output")
        self.status_label = QLabel("Ready")
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.clear_button)
        buttons.addWidget(self.status_label, 1)
        layout.addLayout(buttons)

        output_box = QGroupBox("Output")
        output_layout = QVBoxLayout(output_box)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.output.setMaximumBlockCount(20000)
        self.clear_button.clicked.connect(self.output.clear)
        output_layout.addWidget(self.output)
        layout.addWidget(output_box, 1)

    def _file_row(self, placeholder: str, browse) -> tuple[QLineEdit, QHBoxLayout]:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(self._update_preview)
        button = QPushButton("Browse...")
        button.clicked.connect(browse)
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(button)
        return edit, row

    def _browse_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Configuration file", "", "INI files (*.ini);;All files (*)")
        if path:
            self.config_edit.setText(path)

    def _browse_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Log file", "", "Log files (*.log);;All files (*)",
                                              options=QFileDialog.Option.DontConfirmOverwrite)  # it appends
        if path:
            self.log_edit.setText(path)

    def operation(self) -> str:
        return self.operation_combo.currentData()

    def _applies(self, name: str) -> bool:
        operation = self.operation()
        # `all` with Quality only runs the quality assessment, which does take a session.
        if operation == "all" and self.quality_only_check.isChecked() and name == "session":
            return True
        return operation in _APPLIES[name]

    def arguments(self) -> list[str]:
        """The command-line switches for what is currently chosen."""
        args = ["--operation", self.operation()]
        session = self.session_edit.text().strip()
        if session and self._applies("session"):
            args.append(f"--session={session}")
        if self.min_files_spin.value() and self._applies("min_files"):
            args += ["--min-files", str(self.min_files_spin.value())]
        for name, box in (("dry_run", self.dry_run_check), ("force", self.force_check),
                          ("quality_only", self.quality_only_check), ("report", self.report_check),
                          ("no_cleanup", self.no_cleanup_check)):
            if box.isChecked() and self._applies(name):
                args.append("--" + name.replace("_", "-"))
        if self.verbose_check.isChecked():
            args.append("--verbose")
        if self.quiet_check.isChecked():
            args.append("--quiet")
        for switch, edit in (("--config", self.config_edit), ("--log-file", self.log_edit)):
            if edit.text().strip():
                args.append(f"{switch}={edit.text().strip()}")
        return args

    def _update_controls(self, *_) -> None:
        for name, control in (("session", self.session_edit), ("min_files", self.min_files_spin),
                              ("dry_run", self.dry_run_check), ("force", self.force_check),
                              ("quality_only", self.quality_only_check), ("report", self.report_check),
                              ("no_cleanup", self.no_cleanup_check)):
            control.setEnabled(self._applies(name))
        self._update_preview()

    def _update_preview(self, *_) -> None:
        self.preview_label.setText("Command: galileo-auto-calibration " + subprocess.list2cmdline(self.arguments()))

    def command(self) -> tuple[str, list[str]]:
        """The program and arguments to start."""
        if getattr(sys, "frozen", False):
            return sys.executable, [FROZEN_SWITCH, *self.arguments()]
        return sys.executable, ["-u", "-m", "galileo.commands.auto_calibration", *self.arguments()]

    def is_running(self) -> bool:
        return self._process is not None

    def _confirm_clear(self) -> bool:
        return QMessageBox.question(
            self, "Clear all masters",
            "This permanently deletes ALL master frames: their catalog records and every file in the "
            "repository's Masters folder.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def run(self) -> None:
        if self.is_running():
            return
        if self.operation() == "clear-masters" and not self.dry_run_check.isChecked() and not self._confirm_clear():
            return
        program, args = self.command()
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUNBUFFERED", "1")
        process.setProcessEnvironment(environment)
        if not getattr(sys, "frozen", False):
            process.setWorkingDirectory(str(Path(__file__).resolve().parents[3]))  # where `galileo` imports from
        process.readyReadStandardOutput.connect(self._read_output)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._failed)
        self._process = process
        self._decoder.reset()
        self._append(self.preview_label.text() + "\n")
        self._set_running(True)
        self.status_label.setText("Running...")
        process.start(program, args)
        if self._process is process:       # it may already have failed to start
            process.closeWriteChannel()

    def stop(self) -> None:
        if self._process is not None:
            self.status_label.setText("Stopping...")
            self._process.kill()

    def _kill(self) -> None:
        if self._process is not None:
            self._process.kill()
            self._process.waitForFinished(2000)

    def _set_running(self, running: bool) -> None:
        self.parameters_box.setEnabled(not running)
        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def _append(self, text: str) -> None:
        bar = self.output.verticalScrollBar()
        follow = bar.value() >= bar.maximum()
        cursor = QTextCursor(self.output.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        if follow:
            bar.setValue(bar.maximum())

    def _read_output(self) -> None:
        if self._process is not None:
            data = bytes(self._process.readAllStandardOutput().data())
            self._append(self._decoder.decode(data).replace("\r\n", "\n"))

    def _finished(self, exit_code: int, exit_status) -> None:
        if self._process is None:
            return
        stopped = self.status_label.text() == "Stopping..."
        self._read_output()
        if stopped:
            status = "Stopped"
        elif exit_status == QProcess.ExitStatus.CrashExit:
            status = "The command crashed"
        elif exit_code == 0:
            status = "Finished successfully"
        else:
            status = f"Failed (exit code {exit_code})"
        self._end(status)

    def _failed(self, error) -> None:
        # Every other error is followed by `finished`; a process that never started is not.
        if error == QProcess.ProcessError.FailedToStart and self._process is not None:
            logger.error("Could not start auto-calibration: %s", self._process.errorString())
            self._end(f"Could not start: {self._process.errorString()}")

    def _end(self, status: str) -> None:
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
        self.status_label.setText(status)
        self._append(f"\n[{status}]\n\n")
        self._set_running(False)
