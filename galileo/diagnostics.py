"""Diagnostics and structured logging service (LOG-010 … LOG-040)."""

from __future__ import annotations

import logging
import traceback
from enum import IntEnum
from pathlib import Path
from typing import Any


class Severity(IntEnum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class LogEntry:
    """One log entry with severity, message, and optional stack trace."""

    def __init__(
        self,
        severity: Severity,
        message: str,
        timestamp: str = "",
        stack_trace: str | None = None,
        context: dict | None = None,
    ) -> None:
        self.severity = severity
        self.message = message
        self.timestamp = timestamp
        self.stack_trace = stack_trace
        self.context = context or {}


class DiagnosticsService:
    """Records structured log entries and writes them to a log file (LOG-010 … LOG-040)."""

    def __init__(self, log_dir: "Path | str | None" = None) -> None:
        if log_dir is None:
            from galileo.platform import get_log_dir
            log_dir = get_log_dir()
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._entries: list[LogEntry] = []

        import datetime
        log_file = self._log_dir / f"galileo_{datetime.date.today().isoformat()}.log"
        self._log_file = log_file

        # Configure a file handler
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)

    def log_info(self, message: str) -> None:
        self._record(Severity.INFO, message)

    def log_warning(self, message: str) -> None:
        self._record(Severity.WARNING, message)

    def log_error(self, message: str) -> None:
        self._record(Severity.ERROR, message)

    def log_exception(self, exc: BaseException, context: dict | None = None) -> None:
        """Log an exception with its full stack trace (LOG-030)."""
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        self._record(
            Severity.ERROR,
            str(exc),
            stack_trace="".join(tb),
            context=context,
        )

    def get_entries(self) -> list[LogEntry]:
        return list(self._entries)

    def export_support_bundle(self, dest: "Path | str") -> None:
        """Export a zip bundle of recent logs plus non-sensitive config (LOG-040)."""
        import zipfile
        import glob

        dest_path = Path(dest)
        with zipfile.ZipFile(dest_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for log_path in self._log_dir.glob("*.log"):
                zf.write(log_path, log_path.name)

    def _record(
        self,
        severity: Severity,
        message: str,
        stack_trace: str | None = None,
        context: dict | None = None,
    ) -> None:
        import datetime

        ts = datetime.datetime.utcnow().isoformat()
        entry = LogEntry(
            severity=severity,
            message=message,
            timestamp=ts,
            stack_trace=stack_trace,
            context=context,
        )
        self._entries.append(entry)

        # Also log to stdlib logging
        py_level = int(severity)
        logger = logging.getLogger("galileo.diagnostics")
        logger.log(py_level, message)
        if stack_trace:
            logger.debug("Stack trace:\n%s", stack_trace)

        # Write to log file directly
        try:
            with open(self._log_file, "a", encoding="utf-8") as fh:
                fh.write(f"{ts} {severity.name} {message}\n")
                if stack_trace:
                    fh.write(stack_trace)
        except Exception:
            pass


class LogViewer:
    """In-app log viewer with severity filtering (LOG-020)."""

    def __init__(self, service: DiagnosticsService) -> None:
        self._service = service

    def get_entries(self, min_severity: Severity = Severity.INFO) -> list[LogEntry]:
        return [e for e in self._service.get_entries() if e.severity >= min_severity]
