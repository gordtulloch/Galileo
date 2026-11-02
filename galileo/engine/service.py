# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Running the engine as a service (HEAD-030): signals, readiness and exit codes."""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_ALREADY_RUNNING = 3


def sd_notify(message: str) -> bool:
    """Tell systemd something (``READY=1``, ``STOPPING=1``, ``STATUS=...``). Does nothing, and returns False,
    when not run by systemd. Needs no library: it is one datagram to ``$NOTIFY_SOCKET``."""
    path = os.environ.get("NOTIFY_SOCKET")
    if not path or not hasattr(socket, "AF_UNIX"):
        return False
    if path.startswith("@"):
        path = "\0" + path[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(path)
            s.sendall(message.encode("utf-8"))
        return True
    except OSError:
        logger.debug("sd_notify(%r) failed", message, exc_info=True)
        return False


class StopSignal:
    """An event that ``SIGTERM`` and ``SIGINT`` set, so the engine can leave its wait and shut down in order."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.signal_name = ""

    def request(self, name: str = "stop") -> None:
        self.signal_name = name
        self.event.set()

    def install(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        for name in ("SIGTERM", "SIGINT", "SIGBREAK"):    # SIGBREAK is Ctrl+Break on Windows
            sig = getattr(signal, name, None)
            if sig is not None:
                signal.signal(sig, lambda _n, _f, n=name: self.request(n))

    def wait(self, timeout: float | None = None) -> bool:
        return self.event.wait(timeout)


def run_until_stopped(start: Callable[[], None], stop: Callable[[], None], stopper: StopSignal | None = None) -> int:
    """Start, report ready, wait for a stop request, stop in order. Returns the process exit code."""
    stopper = stopper or StopSignal()
    stopper.install()
    try:
        start()
    except Exception:
        logger.exception("The engine could not start")
        sd_notify("STATUS=Failed to start")
        try:
            stop()
        except Exception:
            logger.exception("Stopping after a failed start also failed")
        return EXIT_FAILURE
    sd_notify("READY=1\nSTATUS=Galileo engine running")
    logger.info("Galileo engine ready")
    while not stopper.wait(1.0):      # a timeout lets the main thread see signals promptly on every platform
        pass
    logger.info("Stopping on %s", stopper.signal_name)
    sd_notify("STOPPING=1")
    try:
        stop()
    except Exception:
        logger.exception("The engine did not stop cleanly")
        return EXIT_FAILURE
    return EXIT_OK


__all__ = ["EXIT_ALREADY_RUNNING", "EXIT_FAILURE", "EXIT_OK", "StopSignal", "run_until_stopped", "sd_notify"]
