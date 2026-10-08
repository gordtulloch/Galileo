# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Startup registration ping (ported from AstroFiler's ``services/registration.py``).

On startup, Galileo opens a short-lived TCP connection to the author's
registration server and sends a one-line handshake identifying the app and
version, then closes the connection — the server counts the connection as a
"use". Galileo never reads a response and never blocks or fails startup on
this; any error is logged at INFO and swallowed. Users can opt out by adding
``Registration = False`` to ``library.ini`` (Options > Library, or by hand).
"""

from __future__ import annotations

import contextlib
import logging
import socket
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Hardcoded registration settings (per project decision, mirroring AstroFiler).
REGISTRATION_ENABLED = True
REGISTRATION_HOST = "www.gordtulloch.com"
REGISTRATION_PORT = 5050
REGISTRATION_TIMEOUT_SECONDS = 2.0
REGISTRATION_HANDSHAKE = "GA02.0"


def _ini_allows_registration() -> bool:
    """Return True unless ``library.ini`` explicitly disables registration."""
    try:
        from galileo.library.config import load_config
        return load_config().getboolean("DEFAULT", "Registration", fallback=True)
    except Exception:
        # Fail open: registration must never break startup.
        return True


def ping_once(
    host: str = REGISTRATION_HOST,
    port: int = REGISTRATION_PORT,
    timeout_seconds: float = REGISTRATION_TIMEOUT_SECONDS,
) -> None:
    """Open and close a TCP connection, sending the handshake. Raises on failure."""
    with socket.create_connection((host, port), timeout=timeout_seconds) as conn:
        conn.sendall(REGISTRATION_HANDSHAKE.encode("utf-8"))


def start_startup_ping(status_callback: Callable[[str], None] | None = None) -> None:
    """Kick off a background registration ping. Never raises; safe to call during GUI startup."""

    def status(msg: str) -> None:
        if callable(status_callback):
            with contextlib.suppress(Exception):
                status_callback(msg)

    def worker() -> None:
        try:
            if not REGISTRATION_ENABLED:
                logger.debug("Registration ping disabled (hardcoded)")
                return

            if not _ini_allows_registration():
                logger.debug("Registration ping disabled (library.ini Registration=False)")
                return

            status("Pinging registration server...")
            ping_once()
            logger.info("Registration ping succeeded (%s:%d)", REGISTRATION_HOST, REGISTRATION_PORT)
        except Exception as exc:
            # Intentionally quiet: registration must not impact startup.
            logger.info("Registration ping failed: %s", exc)

    threading.Thread(target=worker, name="registration-ping", daemon=True).start()
