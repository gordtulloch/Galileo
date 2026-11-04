# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""What the Switches page does to a power/switch device, with no screen (EQP-SW).

* :class:`SwitchOps` sets a channel or a raw property, reads the panel, and reports how it went.
* :func:`panel_signature` decides whether a panel's widgets must be rebuilt rather than refreshed in place.
* :func:`format_reading` is how a sensor reading is shown.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Any

from galileo.device_ops import FAILED, NOT_CONNECTED, OK, UNSUPPORTED, DeviceOps, Outcome

logger = logging.getLogger(__name__)


def panel_signature(panel: Any) -> tuple:
    """What decides whether the widgets must be rebuilt rather than refreshed in place."""
    return (
        panel.recognised, panel.message, panel.profile,
        tuple((g.name, tuple((c.id, c.kind, c.switchable, c.available, c.writable) for c in g.channels))
              for g in panel.groups),
        tuple(s.id for s in panel.sensors),
        tuple((g.name, tuple((p.name, p.kind) for p in g.properties)) for g in panel.other),
    )


def format_reading(value: float | None, unit: str) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:.2f} {unit}".strip()


@dataclass(frozen=True)
class PanelResult:
    """The panel read from the device, or why it could not be: a lost server or a device that stopped answering
    degrades the panel, nothing more (EQP-SW-120)."""

    panel: Any = None
    error: str = ""


class SwitchOps(DeviceOps):
    def set_channel(self, channel: Any, **kwargs: Any) -> Outcome:
        """Set one channel; ``failed`` carries the text for the status bar."""
        adapter = self._get()
        if adapter is None:
            return Outcome(False, NOT_CONNECTED)
        from galileo.core.devices import SwitchController
        try:
            asyncio.run(SwitchController(adapter).set_channel(channel.id, **kwargs))
        except Exception as exc:
            logger.exception("Switches: setting %s failed", channel.id)
            return Outcome(False, FAILED, f"Could not set {channel.label}: {exc}")
        logger.info("Switches: set %s %s", channel.label, kwargs)
        return OK

    def write_property(self, name: str, values: dict) -> Outcome:
        adapter = self._get()
        writer = getattr(adapter, "write_property", None)
        if adapter is None:
            return Outcome(False, NOT_CONNECTED)
        if writer is None:
            return Outcome(False, UNSUPPORTED)
        try:
            asyncio.run(writer(name, values))
        except Exception as exc:
            logger.exception("Switches: writing %s failed", name)
            return Outcome(False, FAILED, f"Could not set {name}: {exc}")
        return OK

    def read_panel(self) -> PanelResult | None:
        """``None`` when no device is connected."""
        adapter = self._get()
        if adapter is None:
            return None
        from galileo.core.devices import SwitchController
        try:
            return PanelResult(panel=asyncio.run(SwitchController(adapter).get_panel()))
        except Exception as exc:
            logger.warning("Switches: could not refresh the panel: %s", exc)
            return PanelResult(error=f"Cannot read the device right now: {exc}")


__all__ = ["PanelResult", "SwitchOps", "format_reading", "panel_signature"]
