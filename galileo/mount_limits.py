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
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

#: The Mount page's jog speed levels 1 (slowest) to 9 (fastest), in deg/s. They follow LX200 OnStep's
#: numbered slew rates (1 = 0.5x … 9 = Max sidereal-based steps), so level n selects OnStep rate n;
#: other drivers get the nearest of their own rates, and Alpaca mounts get the deg/s figure directly.
JOG_RATE_LEVELS: dict[int, float] = {1: 0.002, 2: 0.004, 3: 0.008, 4: 0.017, 5: 0.033,
                                     6: 0.084, 7: 0.2, 8: 1.0, 9: 10.0}


def jog_level_text(rate: float) -> str:
    """How a jog speed reads in the log: ``"rate 9 (10°/s)"`` for a Mount-page level, else just ``"1°/s"``."""
    level = next((n for n, r in JOG_RATE_LEVELS.items() if math.isclose(r, abs(rate))), None)
    return f"rate {level} ({abs(rate):g}°/s)" if level else f"{abs(rate):g}°/s"


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


#: A sidereal hour is shorter than a clock hour, and the hour angle advances at the sidereal rate.
SIDEREAL_DAY_RATIO = 0.99726958


def minutes_to_flip(limits: MountLimits, ha_hours: float | None, side_of_pier: str | None) -> float | None:
    """Clock minutes until the hour angle reaches the flip limit (MFLIP-010), ``0.0`` once it has.

    ``None`` when no flip is ahead: the hour angle or pier side is unknown, or the mount is already on the east side
    of the pier (a flip has been done, and the target only moves further past the meridian)."""
    if ha_hours is None or side_of_pier != "West":
        return None
    return max(0.0, (limits.flip_ha_deg / 15.0 - ha_hours) * 60.0 * SIDEREAL_DAY_RATIO)


#: How long one deferral holds the flip back, by default and at most (CSURF-350).
DEFER_DEFAULT_MINUTES = 10
DEFER_MAX_MINUTES = 30
#: A flip is "imminent", and so may be deferred, from this many minutes before it is due.
DEFER_IMMINENT_MINUTES = 30.0
#: A deferral never outlives the safety margin: it ends (the flip goes ahead) once the hour angle is within this many
#: hours of the Mount page's hour-angle limit, and it is not offered once the mount is this many (sidereal) minutes
#: past the flip limit. A deferred flip must still happen before the mount's limits stop it.
DEFER_HA_MARGIN_HOURS = 0.25
DEFER_MAX_PAST_MINUTES = 60.0


def defer_refusal(limits: MountLimits, ha_hours: float | None, side_of_pier: str | None) -> str | None:
    """Why a flip cannot be deferred now, in words a person can act on, or ``None`` when it can (CSURF-350)."""
    if not limits.flip_enabled:
        return "automatic flips are off in this Pier's Mount settings, so there is no flip to defer"
    if ha_hours is None or side_of_pier != "West":
        return "no flip is pending: the mount is not on the west side of the pier"
    minutes = minutes_to_flip(limits, ha_hours, side_of_pier)
    if minutes is not None and minutes > DEFER_IMMINENT_MINUTES:
        return f"the flip is {minutes:.0f} minutes away; it can be deferred once it is within {DEFER_IMMINENT_MINUTES:.0f}"
    past = (ha_hours * 15.0 - limits.flip_ha_deg) * 4.0
    if past >= DEFER_MAX_PAST_MINUTES:
        return f"the mount is already {past:.0f} minutes past the flip limit; the flip cannot wait any longer"
    if limits.ha_limits_enabled and abs(ha_hours) >= limits.max_ha_hours - DEFER_HA_MARGIN_HOURS:
        return "the mount is too close to its hour-angle limit to defer the flip"
    return None


class FlipDeferrals:
    """Flips an operator has held back for a while (CSURF-350), by mount. Process-wide, so the desktop's Mount-page
    monitor, which performs the automatic flip, and the engine's ``flip.defer`` see the same answer. A deferral
    never silences a limit: :func:`evaluate` still stops the mount, and :meth:`active` ends it early near the hour-angle
    limit, so the flip still happens in time."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._until: dict[int, float] = {}

    def defer(self, mount: object, minutes: float = DEFER_DEFAULT_MINUTES) -> float:
        """Hold the flip back for *minutes* (at most :data:`DEFER_MAX_MINUTES`); returns the time it ends (epoch s)."""
        minutes = min(max(float(minutes), 1.0), float(DEFER_MAX_MINUTES))
        until = self._clock() + minutes * 60.0
        with self._lock:
            self._until[id(mount)] = until
        return until

    def clear(self, mount: object) -> None:
        with self._lock:
            self._until.pop(id(mount), None)

    def active(self, mount: object, limits: MountLimits, ha_hours: float | None) -> float | None:
        """When the deferral ends, if the flip is being held back right now; ``None`` if it was never deferred, has
        run out, or must not be held any longer (the mount is close to its hour-angle limit)."""
        with self._lock:
            until = self._until.get(id(mount))
        if until is None:
            return None
        if self._clock() >= until or (limits.ha_limits_enabled and ha_hours is not None
                                       and abs(ha_hours) >= limits.max_ha_hours - DEFER_HA_MARGIN_HOURS):
            self.clear(mount)
            return None
        return until


#: The one the desktop's monitor and the engine share.
deferrals = FlipDeferrals()


def flip_phase(limits: MountLimits, ha_hours: float | None, side_of_pier: str | None, *,
               tracking: bool, slewing: bool, flipping: bool) -> str:
    """Where the Mount page's "Meridian Flip" section would say the flip stands (EQP-MNT-060, CSURF-170):
    ``flipping`` while one runs, ``inactive`` when not requested, ``waiting`` until the mount tracks, ``due`` once
    the limit is passed on the west side, else ``armed``."""
    if flipping:
        return "flipping"
    if not limits.flip_enabled:
        return "inactive"
    if not tracking or slewing:
        return "waiting"
    return "due" if flip_due(limits, ha_hours, side_of_pier) else "armed"


def evaluate(
    limits: MountLimits,
    *,
    alt_deg: float | None,
    ha_hours: float | None,
    side_of_pier: str | None,
    tracking: bool,
    slewing: bool,
    flip_deferred: bool = False,
) -> MountAction:
    """Decide what to do about a mount's live state.

    Limits only matter while the mount is moving under its own power: tracking or slewing. With
    "Tracking only" set the altitude limits also leave a slew alone. A parked or idle mount is
    never acted on, so a stop doesn't re-trigger on every poll.

    ``flip_deferred`` holds back only the *flip* (CSURF-350, ``FlipDeferrals.active``): a limit is still a stop."""
    if not (tracking or slewing):
        return MountAction()
    found = violations(limits, alt_deg, ha_hours)
    if limits.alt_tracking_only and slewing and limits.alt_limits_enabled:
        found = [r for r in found if not r.startswith("altitude")]
    if found:
        return MountAction(stop=True, reasons=tuple(found))
    if tracking and not slewing and not flip_deferred and flip_due(limits, ha_hours, side_of_pier):
        return MountAction(flip=True, reasons=(f"hour angle {ha_hours:+.2f} h is past the flip limit of {limits.flip_ha_deg:.2f}°",))
    return MountAction()


def pier_side_text(side_of_pier: str | None) -> str:
    """The Mount page's "Pier Side" line, e.g. ``East (pointing West)``."""
    if side_of_pier == "East":
        return "East (pointing West)"
    if side_of_pier == "West":
        return "West (pointing East)"
    return "Unknown"
