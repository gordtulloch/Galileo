# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Node health on the engine (CSURF-310): samples the computer every few seconds and publishes the reading as the
observable state ``node.health`` of every Pier, so a phone sees it follow the node without polling. State is kept per
Pier, so the same reading is published under each; it describes the computer, not the Pier.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from galileo import node_health
from galileo.control_surface import ObservableState
from galileo.control_surface.node import STATE_KEY

logger = logging.getLogger(__name__)

SAMPLE_INTERVAL_S = 5.0


class EngineNode:
    def __init__(self, state: ObservableState, pier_ids: Callable[[], list[str]], runner: Any,
                 *, sampler: Callable[[], dict[str, Any]] = node_health.sample,
                 power: Callable[[str], None] = node_health.request_power) -> None:
        self._state, self._pier_ids, self._runner = state, pier_ids, runner
        self._sampler, self._power = sampler, power
        self._latest: dict[str, Any] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- sampling ---------------------------------------------------------------------------
    def start(self) -> None:
        self.sample_once()
        self._thread = threading.Thread(target=self._loop, name="node-health", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(SAMPLE_INTERVAL_S):
            self.sample_once()

    def sample_once(self) -> dict[str, Any]:
        try:
            self._latest = self._sampler()
            for pier in self._pier_ids():
                self._state.publish(pier, STATE_KEY, self._latest)
        except Exception:
            logger.exception("Node health could not be sampled")
        return self._latest

    # -- NodeAccess -------------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return dict(self._latest or self.sample_once())

    def busy_reason(self) -> str | None:
        runner = self._runner
        if runner is not None and any(runner.is_running(p) for p in self._pier_ids()):
            return "a session is running; stop it before restarting or powering off this computer"
        return None

    def power(self, action: str) -> None:
        try:
            self._power(action)
        except node_health.PowerError as exc:
            raise RuntimeError(str(exc)) from exc
