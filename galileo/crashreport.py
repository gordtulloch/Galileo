# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Crash reporting: last-chance handlers for unhandled exceptions and fatal signals (LOG-030, LOG-070).

:func:`install_crash_handlers` hooks ``sys.excepthook``, ``threading.excepthook``, the asyncio loop
exception handler (qasync loops included) and :mod:`faulthandler`.  Each unhandled failure is logged
and written as a small text report (traceback, version, platform, recent log tail) to
``galileo.platform.get_crash_reports_dir()``.  Reports are scrubbed of anything that looks like a
credential before they are written.
"""

from __future__ import annotations

import asyncio
import datetime
import faulthandler
import logging
import platform as _platform
import re
import sys
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger(__name__)

_LOG_TAIL_LINES = 100
_MAX_REPORTS = 20

# key=value / key: value / "key": "value" where the key names a secret.
_SECRET_KV = re.compile(
    r"""(?ix)
    (?P<key>[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|auth|credential|private[_-]?key)[\w.-]*)
    (?P<sep>["']?\s*[:=]\s*["']?)
    (?P<val>[^\s,;"'&}]+)
    """
)
_URL_CREDS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")

_state: dict[str, Any] = {"installed": False, "fault_file": None, "notify": None, "dialog": None,
                          "previous": None}
_report_lock = threading.Lock()


def scrub_secrets(text: str) -> str:
    """Return *text* with credential-looking values replaced by ``***``."""
    text = _URL_CREDS.sub(lambda m: f"{m.group('scheme')}***:***@", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} ***", text)
    return _SECRET_KV.sub(lambda m: f"{m.group('key')}{m.group('sep')}***", text)


def _version() -> str:
    try:
        from galileo import __version__
        return __version__
    except Exception:
        return "unknown"


def _log_tail(n: int = _LOG_TAIL_LINES) -> list[str]:
    try:
        from galileo.diagnostics import get_recent_log_lines
        return get_recent_log_lines(n)
    except Exception:
        return []


def build_report(exc_type, exc, tb, *, origin: str = "main thread", log_tail: list[str] | None = None) -> str:
    """Format a crash report (already scrubbed of secrets)."""
    now = datetime.datetime.now().astimezone()
    lines = [
        "Galileo crash report",
        f"Time:     {now.isoformat(timespec='seconds')}",
        f"Version:  {_version()}",
        f"Platform: {_platform.platform()}",
        f"Python:   {sys.version.split()[0]} ({_platform.machine()})",
        f"Origin:   {origin}",
        "",
        "Traceback:",
        "".join(traceback.format_exception(exc_type, exc, tb)).rstrip(),
        "",
        "Recent log:",
    ]
    tail = _log_tail() if log_tail is None else log_tail
    lines.extend(tail or ["(none)"])
    return scrub_secrets("\n".join(lines)) + "\n"


def _prune(directory: Path) -> None:
    try:
        reports = sorted(directory.glob("crash_*.txt"))
        for old in reports[:-_MAX_REPORTS]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def write_report(exc_type, exc, tb, *, origin: str = "main thread", directory: Path | None = None) -> Path | None:
    """Write a crash report and return its path (``None`` if it could not be written)."""
    try:
        if directory is None:
            from galileo.platform import get_crash_reports_dir
            directory = get_crash_reports_dir()
        text = build_report(exc_type, exc, tb, origin=origin)
        with _report_lock:
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = Path(directory) / f"crash_{stamp}.txt"
            path.write_text(text, encoding="utf-8")
            _prune(Path(directory))
        return path
    except Exception:
        logger.debug("Could not write crash report", exc_info=True)
        return None


def _handle(exc_type, exc, tb, origin: str, *, fatal: bool) -> Path | None:
    try:
        logger.critical("Unhandled exception in %s", origin, exc_info=(exc_type, exc, tb))
    except Exception:
        pass
    path = write_report(exc_type, exc, tb, origin=origin)
    notify = _state.get("notify")
    if notify is not None:
        try:
            notify(f"Galileo error in {origin}: {exc_type.__name__}: {scrub_secrets(str(exc))}", path)
        except Exception:
            logger.debug("Crash notification failed", exc_info=True)
    dialog = _state.get("dialog")
    if fatal and dialog is not None:
        try:
            dialog(exc_type, exc, path)
        except Exception:
            logger.debug("Crash dialog failed", exc_info=True)
    return path


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    _handle(exc_type, exc, tb, "main thread", fatal=True)
    sys.__excepthook__(exc_type, exc, tb)


def _threading_excepthook(args) -> None:
    if issubclass(args.exc_type, SystemExit):
        return
    name = args.thread.name if args.thread else "unknown"
    # A worker thread dying does not end the app: report it, but do not interrupt with a dialog.
    _handle(args.exc_type, args.exc_value, args.exc_traceback, f"thread {name}", fatal=False)


def asyncio_exception_handler(loop, context: dict) -> None:
    """Loop exception handler: report the exception (or message) then defer to asyncio's default."""
    exc = context.get("exception")
    if exc is not None:
        _handle(type(exc), exc, exc.__traceback__, "asyncio task", fatal=False)
    else:
        try:
            logger.error("asyncio: %s", scrub_secrets(str(context.get("message", ""))))
        except Exception:
            pass
    loop.default_exception_handler(context)


def install_loop_handler(loop: asyncio.AbstractEventLoop) -> None:
    """Attach the crash-reporting exception handler to *loop* (call for each qasync/asyncio loop)."""
    loop.set_exception_handler(asyncio_exception_handler)


def enable_faulthandler(path: Path | None = None) -> Path | None:
    """Send native-crash tracebacks (segfaults etc.) to a file in the log directory."""
    try:
        if path is None:
            from galileo.platform import get_log_dir
            path = get_log_dir() / "faulthandler.log"
        fh: TextIO = open(path, "a", encoding="utf-8")  # noqa: SIM115 - must stay open for the process
        fh.write(f"\n--- Galileo {_version()} started {datetime.datetime.now().isoformat(timespec='seconds')} ---\n")
        fh.flush()
        faulthandler.enable(file=fh, all_threads=True)
        old = _state.get("fault_file")
        _state["fault_file"] = fh
        if old is not None:
            old.close()
        return path
    except Exception:
        logger.debug("Could not enable faulthandler", exc_info=True)
        return None


def show_fatal_dialog(exc_type, exc, report_path: Path | None) -> None:
    """Show a modal fatal-error dialog if a Qt application is running; otherwise do nothing."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    if QApplication.instance() is None:
        return
    box = QMessageBox(QMessageBox.Icon.Critical, "Galileo - unexpected error",
                      f"Galileo hit an unexpected error:\n\n{exc_type.__name__}: {scrub_secrets(str(exc))}")
    if report_path is not None:
        box.setInformativeText(f"A crash report was saved to:\n{report_path}\n\nPlease include it in a bug report.")
    box.exec()


def install_crash_handlers(*, notify: Callable[[str, Path | None], None] | None = None,
                           dialog: Callable[..., None] | None = None,
                           fault_log: Path | None = None) -> None:
    """Install all crash handlers (idempotent).  Call once, early in start-up."""
    _state["notify"] = notify
    _state["dialog"] = dialog
    if not _state["installed"]:
        _state["previous"] = (sys.excepthook, threading.excepthook)
        sys.excepthook = _excepthook
        threading.excepthook = _threading_excepthook
        _state["installed"] = True
    enable_faulthandler(fault_log)


def uninstall_crash_handlers() -> None:
    """Restore the previous hooks (used by tests)."""
    prev = _state.get("previous")
    if prev:
        sys.excepthook, threading.excepthook = prev
    if faulthandler.is_enabled():
        faulthandler.disable()
    fh = _state.get("fault_file")
    if fh is not None:
        fh.close()
    _state.update(installed=False, fault_file=None, notify=None, dialog=None, previous=None)
