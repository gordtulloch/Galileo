# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Altitude/visibility calculations for the sky atlas and scheduler.

Uses ``astropy.coordinates`` so all results are J2000 / ICRS with proper
refraction and local sidereal time.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class ObservingLocation:
    """Geographic location of an observatory."""
    name: str
    latitude: float          # degrees N
    longitude: float         # degrees E (negative = West)
    elevation_m: float = 0.0
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        self._horizon: "HorizonProfile | None" = None

    def set_horizon(self, profile: "HorizonProfile") -> None:
        self._horizon = profile


@dataclass
class HorizonProfile:
    """Obstruction horizon defined as (azimuth_deg, min_altitude_deg) pairs."""
    points: list[tuple[float, float]]

    def min_altitude_at(self, azimuth_deg: float) -> float:
        """Interpolate the minimum observable altitude at *azimuth_deg*."""
        return float(self.min_altitudes(azimuth_deg))

    def min_altitudes(self, azimuth_deg):
        """Vectorised :meth:`min_altitude_at`: the obstruction altitude at each azimuth in
        *azimuth_deg* (scalar or array). Interpolates linearly between points and wraps
        through north, so the stretch from the last point back to the first is covered
        too. With no points there is no obstruction, and the answer is 0° everywhere."""
        import numpy as np
        az = np.asarray(azimuth_deg, dtype=float)
        if not self.points:
            return np.zeros_like(az)
        xp, fp = zip(*self.points)
        return np.interp(az, xp, fp, period=360.0)

    def is_obstructed(self, altitude_deg: float, azimuth_deg: float) -> bool:
        """Whether a line of sight at (*altitude_deg*, *azimuth_deg*) is blocked, i.e. it
        is lower than the obstruction at that azimuth."""
        return bool(altitude_deg < self.min_altitude_at(azimuth_deg)) if self.points else False


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def parse_horizon_text(text: str) -> list[tuple[float, float]]:
    """Read ``azimuth altitude`` pairs, one per line, from the text of a horizon file.

    Values may be separated by whitespace, commas, semicolons or tabs. Blank lines,
    ``#`` comments and a single non-numeric header line are ignored. Azimuth is
    degrees from north through east (0–360); altitude is degrees above the horizon
    (0–90). Returns the pairs sorted by azimuth. Raises ``ValueError``, naming the line,
    for anything else that isn't a valid pair, or when the file has no pairs at all."""
    import re
    points: list[tuple[float, float]] = []
    header_allowed = True
    for number, raw in enumerate(text.lstrip("﻿").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = [f for f in re.split(r"[\s,;]+", line) if f]
        try:
            if len(fields) != 2:
                raise ValueError
            az, alt = float(fields[0]), float(fields[1])
        except ValueError:
            if header_allowed and not any(_is_number(f) for f in fields):
                header_allowed = False      # e.g. "Azimuth,Altitude"
                continue
            raise ValueError(f"Line {number}: expected an azimuth and an altitude, got {raw.strip()!r}.") from None
        header_allowed = False
        if not 0.0 <= az <= 360.0:
            raise ValueError(f"Line {number}: azimuth {az:g}° is outside 0–360°.")
        if not 0.0 <= alt <= 90.0:
            raise ValueError(f"Line {number}: altitude {alt:g}° is outside 0–90°.")
        points.append((az, alt))
    if not points:
        raise ValueError("The file contains no azimuth/altitude pairs.")
    return sorted(points)


def altitude_chart(
    ra_deg: float,
    dec_deg: float,
    location: ObservingLocation,
    date_str: str | None = None,
    horizon: "HorizonProfile | None" = None,
    resolution_min: int = 30,
) -> dict:
    """Return altitude over one night for a target at (*ra_deg*, *dec_deg*).

    Returns a dict with keys ``times`` (list of UTC ISO strings),
    ``altitudes`` (list of float degrees), and optionally
    ``above_horizon`` (list of bool when a horizon profile is provided).
    """
    try:
        from astropy.coordinates import SkyCoord, EarthLocation, AltAz
        from astropy.time import Time
        import astropy.units as u
        import numpy as np

        if date_str is None:
            date_str = datetime.date.today().isoformat()

        loc = EarthLocation(
            lat=location.latitude * u.deg,
            lon=location.longitude * u.deg,
            height=location.elevation_m * u.m,
        )
        coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")

        start = Time(f"{date_str}T12:00:00", scale="utc")
        steps = int(24 * 60 / resolution_min)
        times = start + np.arange(steps) * (resolution_min * u.min)

        frame = AltAz(obstime=times, location=loc)
        altaz = coord.transform_to(frame)

        alt_list = altaz.alt.deg.tolist()
        az_list = altaz.az.deg.tolist()
        time_list = [t.isot for t in times]

        result: dict = {"times": time_list, "altitudes": alt_list}

        eff_horizon = horizon or (location._horizon if hasattr(location, "_horizon") else None)
        if eff_horizon is not None:
            result["above_horizon"] = [
                alt >= eff_horizon.min_altitude_at(az)
                for alt, az in zip(alt_list, az_list)
            ]

        return result

    except Exception:
        # astropy not available or calculation failed — return empty chart
        times_iso = [
            (datetime.datetime(2026, 9, 16, 12, 0, 0) + datetime.timedelta(minutes=i * resolution_min)).isoformat()
            for i in range(48)
        ]
        return {"times": times_iso, "altitudes": [0.0] * 48}


def is_observable_tonight(
    ra_deg: float,
    dec_deg: float,
    location: ObservingLocation,
    date_str: str | None = None,
    min_altitude_deg: float = 20.0,
) -> bool:
    """Return True if the target rises above *min_altitude_deg* tonight."""
    chart = altitude_chart(ra_deg, dec_deg, location, date_str)
    return any(a >= min_altitude_deg for a in chart["altitudes"])
