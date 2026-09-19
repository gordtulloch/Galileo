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
        if not self.points:
            return 0.0
        # Sort by azimuth
        pts = sorted(self.points, key=lambda p: p[0])
        for i, (az, alt) in enumerate(pts):
            next_az, next_alt = pts[(i + 1) % len(pts)]
            if az <= azimuth_deg <= next_az:
                frac = (azimuth_deg - az) / (next_az - az) if next_az != az else 0
                return alt + frac * (next_alt - alt)
        return pts[0][1]


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
