# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Mount meridian-flip and motion limits (EQP-MNT-060, EQP-MNT-070).

Pure functions and a settings dataclass — no device, Qt or database access — so the Mount page,
the slew guard and the tests all apply the same rules. The Mount page's background monitor feeds
:func:`evaluate` the live mount status and acts on the answer; the slew guard feeds
:func:`check_target` the destination of a slew before it is sent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class MountLimits:
    """The Mount page's "Meridian Flip" and "Limits" sections."""

    flip_enabled: bool = False
    flip_ha_deg: float = 5.0            # flip once the hour angle is past the meridian by this much
    alt_limits_enabled: bool = False
    min_alt: float = 0.0                # degrees
    max_alt: float = 90.0
    alt_tracking_only: bool = False     # alt limits don't interrupt a slew, only tracking
    ha_limits_enabled: bool = False
    max_ha_hours: float = 2.0           # |hour angle| beyond this is out of limits


@dataclass
class MountAction:
    """What the monitor should do about the mount's present state."""

    stop: bool = False                  # abort any slew and stop tracking
    flip: bool = False                  # perform a meridian flip
    reasons: tuple[str, ...] = ()


def hour_angle_hours(lst_hours: float, ra_hours: float) -> float:
    """Hour angle in hours, wrapped to [-12, 12): negative east of the meridian, positive west."""
    return (lst_hours - ra_hours + 12.0) % 24.0 - 12.0


def hour_angle_from_altaz(alt_deg: float, az_deg: float, latitude_deg: float) -> float:
    """Hour angle in hours of the direction (alt, az — az from north through east) seen from *latitude_deg*."""
    a, az, phi = math.radians(alt_deg), math.radians(az_deg), math.radians(latitude_deg)
    ha = math.atan2(-math.sin(az) * math.cos(a), math.sin(a) * math.cos(phi) - math.cos(a) * math.sin(phi) * math.cos(az))
    return math.degrees(ha) / 15.0


def violations(limits: MountLimits, alt_deg: float | None, ha_hours: float | None) -> list[str]:
    """Which enabled limits the given altitude / hour angle breaks (empty if none, or if unknown)."""
    found: list[str] = []
    if limits.alt_limits_enabled and alt_deg is not None:
        if alt_deg < limits.min_alt:
            found.append(f"altitude {alt_deg:.1f}° is below the minimum of {limits.min_alt:.1f}°")
        elif alt_deg > limits.max_alt:
            found.append(f"altitude {alt_deg:.1f}° is above the maximum of {limits.max_alt:.1f}°")
    if limits.ha_limits_enabled and ha_hours is not None and abs(ha_hours) > limits.max_ha_hours:
        found.append(f"hour angle {ha_hours:+.2f} h is beyond the limit of ±{limits.max_ha_hours:.2f} h")
    return found


def check_target(limits: MountLimits, alt_deg: float, ha_hours: float | None) -> list[str]:
    """Limits a slew destination would break. Slew targets are always checked, even with
    "Tracking only" set: the mount will be tracking there once the slew finishes."""
    return violations(limits, alt_deg, ha_hours)


def flip_due(limits: MountLimits, ha_hours: float | None, side_of_pier: str | None) -> bool:
    """True when a requested flip is needed: the target is more than ``flip_ha_deg`` past the
    meridian while the mount is still on the west side of the pier, looking east."""
    if not limits.flip_enabled or ha_hours is None or side_of_pier != "West":
        return False
    return ha_hours * 15.0 > limits.flip_ha_deg


def evaluate(
    limits: MountLimits,
    *,
    alt_deg: float | None,
    ha_hours: float | None,
    side_of_pier: str | None,
    tracking: bool,
    slewing: bool,
) -> MountAction:
    """Decide what to do about a mount's live state.

    Limits only matter while the mount is moving under its own power: tracking or slewing. With
    "Tracking only" set the altitude limits also leave a slew alone. A parked or idle mount is
    never acted on, so a stop doesn't re-trigger on every poll."""
    if not (tracking or slewing):
        return MountAction()
    found = violations(limits, alt_deg, ha_hours)
    if limits.alt_tracking_only and slewing and limits.alt_limits_enabled:
        found = [r for r in found if not r.startswith("altitude")]
    if found:
        return MountAction(stop=True, reasons=tuple(found))
    if tracking and not slewing and flip_due(limits, ha_hours, side_of_pier):
        return MountAction(flip=True, reasons=(f"hour angle {ha_hours:+.2f} h is past the flip limit of {limits.flip_ha_deg:.2f}°",))
    return MountAction()


def pier_side_text(side_of_pier: str | None) -> str:
    """The Mount page's "Pier Side" line, e.g. ``East (pointing West)``."""
    if side_of_pier == "East":
        return "East (pointing West)"
    if side_of_pier == "West":
        return "West (pointing East)"
    return "Unknown"
