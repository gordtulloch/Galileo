# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Refuse slews into the observatory's horizon obstructions.

The mount adapters call :func:`get_slew_guard` before they move, so every route to a
slew — the Mount page, the Star Atlas Goto, the sequencer, plate-solve centring, the
meridian flip — is covered by the one check. The guard is off until the application
switches it on (Options > Planning, "Do not slew where obstructed") and hands it the
current Observatory's horizon and site; while it is off, or has no horizon, it never
blocks anything.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

from galileo.exceptions import SlewObstructedError

logger = logging.getLogger(__name__)


class SlewGuard:
    """Holds the obstruction horizon and the site it belongs to.

    ``horizon`` is any object with ``is_obstructed(altitude_deg, azimuth_deg)`` (in
    practice ``galileo.planning.visibility.HorizonProfile``). ``latitude`` and
    ``longitude`` (degrees, east positive) are needed only to turn the RA/Dec of a
    coordinate slew into the altitude/azimuth the horizon is described in."""

    def __init__(self) -> None:
        self.enabled = False
        self.horizon: Any = None
        self.latitude: float | None = None
        self.longitude: float | None = None

    def check_altaz(self, altitude_deg: float, azimuth_deg: float) -> None:
        """Raise :class:`SlewObstructedError` if that direction is obstructed and the guard is on."""
        if not self.enabled or self.horizon is None:
            return
        if self.horizon.is_obstructed(altitude_deg, azimuth_deg % 360.0):
            logger.warning("Slew refused: Alt %.2f° Az %.2f° is obstructed", altitude_deg, azimuth_deg)
            raise SlewObstructedError()

    def check_radec(self, ra_deg: float, dec_deg: float, when: _dt.datetime | None = None) -> None:
        """As :meth:`check_altaz`, for coordinates of date (what the mount adapters are
        handed) as seen from the site now, or at *when* (UTC)."""
        if not self.enabled or self.horizon is None:
            return
        if self.latitude is None or self.longitude is None:
            logger.warning("Horizon check skipped: the Observatory has no latitude/longitude set")
            return
        from galileo.planning import star_atlas as sa
        when = when or _dt.datetime.now(_dt.timezone.utc)
        lst = sa.local_sidereal_deg(sa.julian_date(when), self.longitude)
        alt, az = sa.equatorial_to_horizontal(ra_deg, dec_deg, lst, self.latitude)
        self.check_altaz(float(alt), float(az))


_guard = SlewGuard()


def get_slew_guard() -> SlewGuard:
    """The process-wide guard the mount adapters consult."""
    return _guard
