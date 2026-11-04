# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""What the Rotator page does to a rotator and how it describes one, with no screen (EQP-ROT).

* :class:`RotatorOps` runs a rotator command against the adapter it is given and returns an
  :class:`~galileo.device_ops.Outcome`.
* :func:`describe_status` turns an adapter's status dictionary into what the panel shows.
* :func:`derotation_rate` is the field-rotation rate (deg/min) for a target now, with the person's correction and
  the reverse option applied.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from galileo import derotation
from galileo.device_ops import FAILED, NOT_CONNECTED, OK, UNSUPPORTED, DeviceOps, Outcome
from galileo.exceptions import DevicePropertyError

logger = logging.getLogger(__name__)


class RotatorOps(DeviceOps):
    def run(self, method: str, *args: Any, action: str) -> Outcome:
        """Run ``adapter.<method>(*args)``. ``unsupported`` carries the driver's own explanation, ``failed`` the
        text for the status bar."""
        adapter = self._get()
        if adapter is None:
            return Outcome(False, NOT_CONNECTED)
        try:
            asyncio.run(getattr(adapter, method)(*args))
        except DevicePropertyError as exc:
            logger.warning("Rotator %s not available: %s", action, exc)
            return Outcome(False, UNSUPPORTED, str(exc))
        except Exception:
            logger.exception("Rotator %s failed", action)
            return Outcome(False, FAILED, f"Rotator {action} failed — see log.")
        return OK


@dataclass(frozen=True)
class RotatorView:
    connected: bool = False                 # an empty status means not connected
    position: float | None = None
    position_text: str = "—"
    detail: str = ""
    reverse: bool | None = None
    backlash_supported: bool = False
    backlash: float | None = None           # only when the driver supports a backlash setting and reports one
    backlash_tip: str = ""
    can_sync: bool = True
    goto_hint: str = ""                     # empty when the rotator reports no travel limit


def describe_status(status: dict) -> RotatorView:
    connected = bool(status)
    position, mechanical = status.get("position"), status.get("mechanical_position")
    bits = []
    if mechanical is not None:
        bits.append(f"Mechanical {mechanical:.2f}°")
    if position is not None:
        bits.append(f"Sky {position:.2f}°")
    if status.get("is_moving"):
        bits.append("moving")
    supported = bool(status.get("backlash_supported"))
    max_angle = status.get("max_angle")
    return RotatorView(
        connected=connected, position=position, position_text="—" if position is None else f"{position:.2f}",
        detail=" · ".join(bits), reverse=None if status.get("reverse") is None else bool(status["reverse"]),
        backlash_supported=supported,
        backlash=status["backlash"] if supported and status.get("backlash") is not None else None,
        backlash_tip="" if supported or not connected else "This rotator's driver has no backlash setting.",
        can_sync=bool(status.get("can_sync", True)),
        goto_hint=f"(0 – {min(max_angle, 359.99):g})" if max_angle else "")


def derotation_rate(target: tuple[float, float] | None, lat_deg: float, lon_deg: float, correction_pct: float,
                    reverse: bool) -> tuple[float, float, float | None] | None:
    """``(alt, az, effective deg/min)`` for *target* (RA, Dec degrees) now, or ``None`` with no target. The rate is
    ``None`` while the target is below the horizon."""
    if target is None:
        return None
    alt, az = derotation.radec_to_altaz(target[0], target[1], lat_deg, lon_deg)
    if alt <= 0.0:
        return alt, az, None
    rate = derotation.field_rotation_rate_deg_per_min(lat_deg, alt, az) * (1.0 + correction_pct / 100.0)
    return alt, az, -rate if reverse else rate


__all__ = ["RotatorOps", "RotatorView", "derotation_rate", "describe_status"]
