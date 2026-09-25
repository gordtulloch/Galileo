# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Diagnostics and structured logging service (LOG-010 … LOG-040)."""

from __future__ import annotations

import collections
import logging
import socket
import threading
import traceback
from enum import IntEnum
from pathlib import Path

from galileo.exceptions import DeviceError

_APP_ROOT = Path(__file__).resolve().parent.parent


def default_log_dir() -> Path:
    """``.\\logs\\`` under the application root (not the per-user platform
    log directory) — the location Galileo's own log file lives in."""
    return _APP_ROOT / "logs"


# Failures that mean "the device/network isn't reachable", not "Galileo has a
# bug": worth one readable line, not a traceback.
_EXPECTED_CONNECTIVITY_ERRORS = (DeviceError, ConnectionError, TimeoutError, socket.gaierror)

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _ConciseFormatter(logging.Formatter):
    """Formats records like the stdlib default, except that a record carrying
    an expected connectivity failure (device off, unreachable host, mDNS
    lookup timeout, ...) is written as its message plus the exception's own
    text, without a traceback. Any other exception keeps its full traceback."""

    def format(self, record: logging.LogRecord) -> str:
        exc = record.exc_info[1] if record.exc_info else None
        if not isinstance(exc, _EXPECTED_CONNECTIVITY_ERRORS):
            return super().format(record)
        saved = record.exc_info, record.exc_text
        record.exc_info = record.exc_text = None
        try:
            return f"{super().format(record)} — {exc}"
        finally:
            record.exc_info, record.exc_text = saved


# ---------------------------------------------------------------------------
# Process-wide tail buffer, so any UI pane can show "the last N log lines"
# without needing a reference to whichever DiagnosticsService instance set
# logging up — every record any module logs (via plain
# ``logging.getLogger(__name__)`` or through DiagnosticsService itself)
# passes through here once installed, since it hooks the root logger.
# ---------------------------------------------------------------------------

_TAIL_BUFFER: collections.deque[str] = collections.deque(maxlen=1000)
_TAIL_LOCK = threading.Lock()
_tail_handler_installed = False


class _TailBufferHandler(logging.Handler):
    """Appends every formatted log record to the shared in-memory tail buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            return
        with _TAIL_LOCK:
            _TAIL_BUFFER.append(line)


def _ensure_tail_handler() -> None:
    global _tail_handler_installed
    if _tail_handler_installed:
        return
    handler = _TailBufferHandler()
    handler.setFormatter(_ConciseFormatter(_LOG_FORMAT))
    # The on-screen log panes (fed by get_recent_log_lines) are meant for a
    # user glancing at what the app is doing, not for debugging internals —
    # DEBUG-level records still reach the on-disk file via the root logger's
    # own DEBUG level and the separate FileHandler, just not this buffer.
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    _tail_handler_installed = True


def get_recent_log_lines(n: int = 10) -> list[str]:
    """Return the last *n* formatted log lines written by any module (LOG-020)."""
    with _TAIL_LOCK:
        return list(_TAIL_BUFFER)[-n:]


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

    def __init__(self, log_dir: Path | str | None = None) -> None:
        if log_dir is None:
            log_dir = default_log_dir()
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._entries: list[LogEntry] = []

        import datetime
        log_file = self._log_dir / f"galileo_{datetime.date.today().isoformat()}.log"
        self._log_file = log_file

        root_logger = logging.getLogger()
        # Every module logs via its own logger.info()/.exception()/etc.
        # (not just through this service's own log_*() methods below); the
        # root logger's level gates all of that, so it must be permissive
        # for "all runtime information" to actually reach the file/tail
        # buffer rather than being silently dropped before any handler sees it.
        root_logger.setLevel(logging.DEBUG)

        # mode="w" (not the logging default "a") so the datestamped file
        # resets on every run rather than accumulating across same-day runs.
        existing = [h for h in root_logger.handlers if isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_file]
        if not existing:
            file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
            file_handler.setFormatter(_ConciseFormatter(_LOG_FORMAT))
            root_logger.addHandler(file_handler)

        _ensure_tail_handler()

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

    def export_support_bundle(self, dest: Path | str) -> None:
        """Export a zip bundle of recent logs plus non-sensitive config (LOG-040)."""
        import zipfile

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

        # Route through stdlib logging — the root-logger file handler and
        # tail buffer installed in __init__ pick this up from there; no
        # separate write to self._log_file needed (that would just double
        # every line, once here and once via the handler).
        py_level = int(severity)
        logger = logging.getLogger("galileo.diagnostics")
        logger.log(py_level, message)
        if stack_trace:
            logger.log(py_level, "Stack trace:\n%s", stack_trace)


class LogViewer:
    """In-app log viewer with severity filtering (LOG-020)."""

    def __init__(self, service: DiagnosticsService) -> None:
        self._service = service

    def get_entries(self, min_severity: Severity = Severity.INFO) -> list[LogEntry]:
        return [e for e in self._service.get_entries() if e.severity >= min_severity]
