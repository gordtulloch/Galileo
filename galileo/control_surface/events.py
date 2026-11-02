# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Operation-result and lease events on the bus (CSURF-070, LEASE-050).

A long-running operation publishes ``OperationStarted``, any number of ``OperationProgress`` and
exactly one ``OperationFinished``, all carrying one correlation id; :class:`OperationTracker`
guarantees the single ``finished`` even if the handler dies.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from galileo.bus import Event, EventBus, get_bus

logger = logging.getLogger(__name__)


class OperationStarted(Event):
    """Payload: ``correlation_id``, ``operation``, ``pier``, ``principal``."""


class OperationProgress(Event):
    """Payload: ``correlation_id``, ``operation``, ``pier``, ``fraction`` (0-1 or None), ``message``."""


class OperationFinished(Event):
    """Payload: ``correlation_id``, ``operation``, ``pier``, ``outcome`` (an outcome status), ``reason``."""


class LeaseChanged(Event):
    """Payload: ``pier``, ``holder`` ('' when free), ``previous``, ``reason``."""


class OperationTracker:
    """Publishes the lifecycle of one operation; ``finish`` is idempotent."""

    def __init__(self, operation: str, pier: str, principal: str, bus: EventBus | None = None,
                 correlation_id: str = "") -> None:
        self.operation, self.pier, self.principal = operation, pier, principal
        self.correlation_id = correlation_id or uuid.uuid4().hex
        self._bus = bus or get_bus()
        self._finished = False

    @property
    def finished(self) -> bool:
        return self._finished

    def _publish(self, event: Event) -> None:
        try:
            self._bus.publish(event)
        except Exception:                                 # a subscriber never reaches the service
            logger.exception("operation event subscriber failed")

    def start(self) -> None:
        self._publish(OperationStarted("control_surface", correlation_id=self.correlation_id,
                                       operation=self.operation, pier=self.pier, principal=self.principal))

    def progress(self, fraction: float | None = None, message: str = "") -> None:
        if not self._finished:
            self._publish(OperationProgress(
                "control_surface", correlation_id=self.correlation_id, operation=self.operation,
                pier=self.pier, fraction=fraction, message=message))

    def finish(self, outcome: str, reason: str = "", **extra: Any) -> bool:
        if self._finished:
            return False
        self._finished = True
        self._publish(OperationFinished(
            "control_surface", correlation_id=self.correlation_id, operation=self.operation,
            pier=self.pier, outcome=outcome, reason=reason, **extra))
        return True


__all__ = ["LeaseChanged", "OperationFinished", "OperationProgress", "OperationStarted", "OperationTracker"]
