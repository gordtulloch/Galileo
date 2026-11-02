# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Galileo engine: Galileo's domain core with no display (HEAD-010).

``Galileo --engine`` runs this. It imports nothing from ``galileo.ui`` and nothing from ``PySide6``
(``tests/test_head.py`` checks that in a subprocess), so it runs on a controller with no screen.

This is the first step of the engine (SDD §4.33): the composition root, the single-engine lock and the
service run. Device connections, the session runner, the Pier helpers, safety and the watchdog join it in the
later steps; until then they are still held by the desktop.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from typing import Any

from galileo.engine.lock import EngineAlreadyRunning, EngineLock
from galileo.engine.service import EXIT_ALREADY_RUNNING, StopSignal, run_until_stopped

logger = logging.getLogger(__name__)


class Engine:
    """Owns what the engine starts and stops, in order. Safe to ``stop()`` after a partial ``start()``."""

    def __init__(self, lock: EngineLock | None = None) -> None:
        self.lock = lock or EngineLock()
        self.plugin_manager: Any = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.lock.acquire(role="engine")          # HEAD-020: before touching the database or any device

        from galileo.crashreport import install_crash_handlers
        install_crash_handlers()                  # no dialog: there is no screen

        from galileo.library.database import init_db
        init_db()

        from galileo.plugins import PluginManager
        self.plugin_manager = PluginManager()
        self.plugin_manager.initialize_from_disk()
        self._started = True

    def stop(self) -> None:
        """Stop in the reverse order of ``start``. Each step is isolated so a failure in one never skips the rest."""
        steps = (
            ("Connect Link", self._stop_link),
            ("CPU workers", self._stop_workers),
        )
        for name, step in steps:
            try:
                step()
            except Exception:
                logger.exception("Stopping %s failed", name)
        self._started = False
        self.lock.release()

    @staticmethod
    def _stop_link() -> None:
        from galileo.connect_link.host import shutdown_host
        shutdown_host()

    @staticmethod
    def _stop_workers() -> None:
        from galileo.core.compute import shutdown_cpu_executor
        shutdown_cpu_executor(wait=False)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``Galileo --engine``. Returns the process exit code."""
    import multiprocessing
    multiprocessing.freeze_support()

    from galileo.diagnostics import DiagnosticsService
    DiagnosticsService()
    logging.getLogger().setLevel(logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")

    from galileo import __version__
    logger.info("Galileo engine %s starting", __version__)
    engine = Engine()
    try:
        engine.lock.acquire(role="engine")
        engine.lock.release()                     # a quick check so a refusal says so before any start-up work
    except EngineAlreadyRunning as exc:
        logger.error("%s", exc)  # noqa: TRY400 -- a refusal, not a fault: no traceback wanted
        print(exc, file=sys.stderr)
        return EXIT_ALREADY_RUNNING
    return run_until_stopped(engine.start, engine.stop, StopSignal())


__all__ = ["Engine", "main"]
