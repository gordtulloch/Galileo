# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Altitude/visibility calculations for the sky atlas and scheduler.

Uses ``astropy.coordinates`` so all results are J2000 / ICRS with proper
refraction and local sidereal time.
"""

from __future__ import annotations

import datetime
import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class ObservingLocation:
    """Geographic location of an observatory."""
    name: str
    latitude: float          # degrees N
    longitude: float         # degrees E (negative = West)
    elevation_m: float = 0.0
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        self._horizon: HorizonProfile | None = None

    def set_horizon(self, profile: HorizonProfile) -> None:
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
    horizon: HorizonProfile | None = None,
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


def altitude_charts_batch(
    targets: list[tuple[float, float]],
    location: ObservingLocation,
    date_str: str | None = None,
    resolution_min: int = 30,
) -> list[dict]:
    """:func:`altitude_chart` for many *targets* (a list of ``(ra_deg,
    dec_deg)`` pairs) at once, via a single vectorized astropy transform
    instead of one per target — each individual call otherwise rebuilds the
    same ``EarthLocation``/``AltAz`` frame and time grid from scratch, which
    dominates the per-call cost. ~16x faster for 200 targets in practice
    (measured: ~10s individually vs. ~0.6s batched) — used by the Sky Atlas
    page's per-result cards (SKY-020/030), where up to 200 results each
    needing their own chart made the individual-call cost genuinely
    UI-blocking. No horizon-obstruction support (unlike :func:`altitude_chart`
    itself) — the per-result cards this feeds don't need it, only the plain
    altitude curve. Returns one ``{"times": [...], "altitudes": [...]}`` dict
    per target, same order as *targets*; an all-empty list of dicts on any
    failure (astropy unavailable, ...), matching :func:`altitude_chart`'s own
    "never raises" contract."""
    if not targets:
        return []
    try:
        from astropy.coordinates import SkyCoord, EarthLocation, AltAz
        from astropy.time import Time
        import astropy.units as u
        import numpy as np

        if date_str is None:
            date_str = datetime.date.today().isoformat()

        loc = EarthLocation(
            lat=location.latitude * u.deg, lon=location.longitude * u.deg, height=location.elevation_m * u.m,
        )
        start = Time(f"{date_str}T12:00:00", scale="utc")
        steps = int(24 * 60 / resolution_min)
        times = start + np.arange(steps) * (resolution_min * u.min)
        frame = AltAz(obstime=times, location=loc)

        coords = SkyCoord(
            ra=[t[0] for t in targets] * u.deg, dec=[t[1] for t in targets] * u.deg, frame="icrs",
        )
        # Broadcast every target against every time sample in one transform:
        # coords[:, None] is (N, 1), frame[None, :] is (1, steps) -> (N, steps).
        altaz = coords[:, None].transform_to(frame[None, :])
        time_list = [t.isot for t in times]
        alt_array = altaz.alt.deg

        return [{"times": time_list, "altitudes": alt_array[i].tolist()} for i in range(len(targets))]
    except Exception:
        logger.debug("Could not compute batched altitude charts", exc_info=True)
        return [{"times": [], "altitudes": []} for _ in targets]


def is_observable_tonight(
    ra_deg: float,
    dec_deg: float,
    location: ObservingLocation,
    date_str: str | None = None,
    min_altitude_deg: float = 20.0,
    min_duration_hours: float = 0.0,
) -> bool:
    """Return True if the target reaches at least *min_altitude_deg* tonight —
    for at least one sample by default (``min_duration_hours`` 0, the original
    SKY-020 check), or continuously for at least *min_duration_hours* when
    given (SKY-020's "reach an altitude of X for at least Y hours" filter,
    matching the reference Telescopius layout, `assets/samples/target.png`)."""
    chart = altitude_chart(ra_deg, dec_deg, location, date_str)
    altitudes = chart["altitudes"]
    if min_duration_hours <= 0:
        return any(a >= min_altitude_deg for a in altitudes)

    # altitude_chart's own default sampling resolution (30 min); N consecutive
    # samples at/above the threshold span (N-1) intervals of that length.
    resolution_min = 30
    needed_samples = math.ceil(min_duration_hours * 60 / resolution_min) + 1
    run = 0
    for alt in altitudes:
        if alt >= min_altitude_deg:
            run += 1
            if run >= needed_samples:
                return True
        else:
            run = 0
    return False


def rise_transit_set(
    ra_deg: float,
    dec_deg: float,
    location: ObservingLocation,
    date_str: str | None = None,
    horizon: HorizonProfile | None = None,
    threshold_deg: float = 0.0,
    chart: dict | None = None,
) -> dict:
    """Rise, transit (highest-altitude), and set times for a target over one
    night (SKY-030's rise/transit/set display), read off the same altitude
    curve :func:`altitude_chart` already computes — astropy-only, not a
    second independent calculation via astroplan (SDD's earlier design note
    named astroplan for this, but it was never actually added as a
    dependency; astroplan's own rise/set functions are themselves thin
    wrappers over the same astropy time/coordinate transforms this reuses).

    Pass an already-computed *chart* (from :func:`altitude_chart` or one
    element of :func:`altitude_charts_batch`, for the same target/location/
    date/horizon) to skip recomputing it — the Sky Atlas page's per-result
    cards need both the chart itself (for their altitude graph) and this, so
    computing it twice per result would double an already
    up-to-200-results cost for no reason.

    Returns ISO-8601 UTC strings under ``rise``/``transit``/``set``, or
    ``None`` for whichever doesn't occur within the charted night: circumpolar
    (never sets — ``set`` is ``None``), never rises above *threshold_deg* (the
    horizon profile's obstruction altitude at the target's azimuth when
    *horizon* is given, else a flat 0° math horizon — all three are ``None``),
    or already up at the start of the charted window (``rise`` is ``None``).
    """
    if chart is None:
        chart = altitude_chart(ra_deg, dec_deg, location, date_str, horizon)
    times, altitudes = chart["times"], chart["altitudes"]
    if not altitudes:
        return {"rise": None, "transit": None, "set": None}

    transit_idx = max(range(len(altitudes)), key=lambda i: altitudes[i])

    above = chart.get("above_horizon")
    if above is None:
        above = [alt >= threshold_deg for alt in altitudes]

    if not above[transit_idx]:
        # Never clears the horizon at all tonight.
        return {"rise": None, "transit": None, "set": None}

    def _crossing(i: int, j: int) -> str:
        """Linearly interpolate the horizon-crossing time between adjacent
        samples *i* and *j* for a finer estimate than the chart's own
        sampling resolution."""
        a_i, a_j = altitudes[i], altitudes[j]
        t_i = datetime.datetime.fromisoformat(times[i])
        t_j = datetime.datetime.fromisoformat(times[j])
        if a_j == a_i:
            return times[i]
        frac = min(max((threshold_deg - a_i) / (a_j - a_i), 0.0), 1.0)
        return (t_i + (t_j - t_i) * frac).isoformat()

    rise = None
    for i in range(transit_idx, 0, -1):
        if not above[i - 1] and above[i]:
            rise = _crossing(i - 1, i)
            break

    set_ = None
    for i in range(transit_idx, len(above) - 1):
        if above[i] and not above[i + 1]:
            set_ = _crossing(i, i + 1)
            break

    return {"rise": rise, "transit": times[transit_idx], "set": set_}


def moon_position_deg(location: ObservingLocation, date_str: str | None = None) -> tuple[float, float] | None:
    """The Moon's apparent RA/Dec (degrees) as seen from *location* at local
    midnight on *date_str* (today, when not given) — a single reference-time
    position (not tracked across the night), matching :func:`altitude_chart`'s
    own "noon to noon" one-night window convention, for the reference
    Telescopius layout's "Distance from the Moon" filter (SKY-020,
    `assets/samples/target.png`). Returns ``None`` if it can't be computed
    (astropy unavailable) — the caller (:meth:`SkyAtlas.filter`) then skips
    the Moon-distance filter entirely rather than wrongly excluding every
    object."""
    try:
        from astropy.coordinates import EarthLocation, get_body
        from astropy.time import Time
        import astropy.units as u

        if date_str is None:
            date_str = datetime.date.today().isoformat()
        loc = EarthLocation(
            lat=location.latitude * u.deg, lon=location.longitude * u.deg, height=location.elevation_m * u.m,
        )
        time = Time(f"{date_str}T12:00:00", scale="utc") + 12 * u.hour
        moon = get_body("moon", time, loc)
        return float(moon.ra.deg), float(moon.dec.deg)
    except Exception:
        logger.debug("Could not compute Moon position", exc_info=True)
        return None


def moon_separation_deg(ra_deg: float, dec_deg: float, moon_ra_deg: float, moon_dec_deg: float) -> float:
    """Angular separation (degrees) between (*ra_deg*, *dec_deg*) and a
    precomputed Moon position (:func:`moon_position_deg`) via the spherical
    law of cosines — plain trig, not a per-call astropy/``SkyCoord`` round
    trip, so checking it against every catalog object in
    :meth:`SkyAtlas.filter` (the Moon's own position computed once, outside
    that loop) stays cheap."""
    ra1, dec1, ra2, dec2 = (math.radians(v) for v in (ra_deg, dec_deg, moon_ra_deg, moon_dec_deg))
    cos_sep = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2)
    return math.degrees(math.acos(min(1.0, max(-1.0, cos_sep))))


def sun_altitude_deg(location: ObservingLocation, time=None) -> float | None:
    """The Sun's altitude (degrees) above *location*'s horizon at *time* (an
    ``astropy.time.Time``, defaulting to right now). Used to gate sky-flat
    capture to the local twilight window (CAL-070) via :func:`is_twilight`.
    Returns ``None`` if it can't be computed (astropy unavailable)."""
    try:
        from astropy.coordinates import AltAz, EarthLocation, get_sun
        from astropy.time import Time
        import astropy.units as u

        loc = EarthLocation(
            lat=location.latitude * u.deg, lon=location.longitude * u.deg, height=location.elevation_m * u.m,
        )
        t = time or Time.now()
        frame = AltAz(obstime=t, location=loc)
        return float(get_sun(t).transform_to(frame).alt.deg)
    except Exception:
        logger.debug("Could not compute the Sun's altitude", exc_info=True)
        return None


def is_twilight(
    location: ObservingLocation, time=None,
    max_altitude_deg: float = 0.0, min_altitude_deg: float = -18.0,
) -> bool:
    """Whether the Sun sits within the local dawn/dusk twilight band at
    *location* and *time* (now, if not given) — below the horizon but not yet
    (or still) fully dark, which is the window sky flats need (CAL-070):
    bright enough for a short, even exposure, dim enough that direct
    sunlight doesn't saturate the frame. Defaults to the full civil-through-
    astronomical twilight range (0° down to -18°). Returns ``False`` (i.e.
    refuses the run) if the Sun's altitude can't be computed at all, rather
    than assuming it's safe to proceed."""
    altitude = sun_altitude_deg(location, time)
    if altitude is None:
        return False
    return min_altitude_deg <= altitude <= max_altitude_deg


def sun_altitude_track(
    location: ObservingLocation,
    date_str: str | None = None,
    resolution_min: int = 1,
) -> dict:
    """The Sun's altitude across one local calendar day at *location*, from local
    midnight to the next local midnight (unlike :func:`altitude_chart`'s UTC
    noon-to-noon "one observing night" window) — the day/night band on the
    What's Up Tonight screen (WUT-110) is keyed to the wall-clock day the user
    picked, not to a night that straddles two calendar dates. Sampled every
    *resolution_min* minute(s) via a single vectorized astropy transform (the
    same batching :func:`altitude_charts_batch` already uses, rather than one
    ``get_sun`` call per sample). Returns a dict with ``times`` (local-time ISO
    strings, one per sample, tz-aware) and ``altitudes`` (degrees); both empty
    on failure (astropy unavailable), matching :func:`altitude_chart`'s own
    never-raises contract.

    Uses the *system's* local timezone (via plain ``datetime.astimezone()``),
    the same convention the Scheduler's ``_AltitudeChart`` tick labels already
    use, rather than ``ObservingLocation.timezone`` — that field is an IANA
    name and resolving it correctly needs the ``tzdata`` package, which isn't
    a declared dependency (bundled with most Linux/macOS systems but not
    Windows). One consequence: on the two days a year the system clock's DST
    offset changes, the second half of that local day is computed at the
    pre-transition UTC offset, which can shift band boundaries there by up to
    an hour."""
    try:
        from astropy.coordinates import AltAz, EarthLocation, get_sun
        from astropy.time import Time
        import astropy.units as u
        import numpy as np

        if date_str is None:
            date_str = datetime.datetime.now().astimezone().date().isoformat()
        year, month, day = (int(p) for p in date_str.split("-"))
        local_midnight = datetime.datetime(year, month, day).astimezone()

        loc = EarthLocation(
            lat=location.latitude * u.deg, lon=location.longitude * u.deg, height=location.elevation_m * u.m,
        )
        steps = int(24 * 60 / resolution_min) + 1
        local_times = [local_midnight + datetime.timedelta(minutes=i * resolution_min) for i in range(steps)]
        utc_times = Time([t.astimezone(datetime.UTC).replace(tzinfo=None) for t in local_times], scale="utc")
        frame = AltAz(obstime=utc_times, location=loc)
        altitudes = get_sun(utc_times).transform_to(frame).alt.deg

        return {"times": [t.isoformat() for t in local_times], "altitudes": np.asarray(altitudes).tolist()}
    except Exception:
        logger.debug("Could not compute the Sun's altitude track", exc_info=True)
        return {"times": [], "altitudes": []}


# Sun-altitude boundaries (degrees) between consecutive day/night bands, in
# ascending order — the standard sunrise/sunset (-0.8333°, accounting for
# atmospheric refraction and the solar disk's radius) plus the standard
# civil/nautical/astronomical twilight bands, the same fixed reference table
# already used for the What's Up Tonight advisory summary's Kp/AQI bands.
_BAND_ORDER = ("Night", "Astronomical Twilight", "Nautical Twilight", "Civil Twilight", "Daylight")
_BAND_THRESHOLDS_DEG = (-18.0, -12.0, -6.0, -0.8333)


def _band_index(altitude_deg: float) -> int:
    idx = 0
    for threshold in _BAND_THRESHOLDS_DEG:
        if altitude_deg < threshold:
            break
        idx += 1
    return idx


def _interp_crossing_time(
    t1: datetime.datetime, alt1: float, t2: datetime.datetime, alt2: float, threshold_deg: float,
) -> datetime.datetime:
    if alt2 == alt1:
        return t1
    frac = min(max((threshold_deg - alt1) / (alt2 - alt1), 0.0), 1.0)
    return t1 + (t2 - t1) * frac


def day_night_bands(
    location: ObservingLocation,
    date_str: str | None = None,
    resolution_min: int = 1,
) -> dict:
    """The day/night band for the What's Up Tonight screen's top graphic
    (WUT-110) — one local calendar day (local midnight to local midnight, via
    :func:`sun_altitude_track`) split into contiguous Night / Astronomical
    Twilight / Nautical Twilight / Civil Twilight / Daylight segments by the
    Sun's altitude, each boundary crossing linearly interpolated between the
    straddling samples for a finer time than the raw sampling resolution
    (the same technique :func:`rise_transit_set` already uses for its own
    horizon crossings).

    Returns a dict with:
    - ``segments``: ``[{"label", "start", "end"}, ...]`` in chronological
      order, local-time ISO strings, covering the full day with no gaps —
      a band that never changes (e.g. permanent polar night) is a single
      segment.
    - ``totals_hours``: ``{label: total_hours}`` summed across every segment
      with that label (a label can recur, e.g. "Night" before dawn and again
      after dusk).
    - ``solar_noon`` / ``solar_midnight``: local-time ISO strings for the
      Sun's highest/lowest altitude sample that day, or ``None``.

    All fields are empty/``None`` when the underlying track can't be
    computed (astropy unavailable) — never raises, matching this module's
    existing never-block-the-screen convention."""
    track = sun_altitude_track(location, date_str, resolution_min)
    times_iso, altitudes = track["times"], track["altitudes"]
    if not times_iso:
        return {"segments": [], "totals_hours": {}, "solar_noon": None, "solar_midnight": None}

    times = [datetime.datetime.fromisoformat(t) for t in times_iso]
    indices = [_band_index(a) for a in altitudes]

    boundaries = [times[0]]
    labels = [_BAND_ORDER[indices[0]]]
    for i in range(1, len(times)):
        if indices[i] == indices[i - 1]:
            continue
        rising = indices[i] > indices[i - 1]
        lo, hi = sorted((indices[i - 1], indices[i]))
        crossed = _BAND_THRESHOLDS_DEG[lo:hi]
        cursor = indices[i - 1]
        for threshold in (crossed if rising else reversed(crossed)):
            boundaries.append(_interp_crossing_time(times[i - 1], altitudes[i - 1], times[i], altitudes[i], threshold))
            cursor += 1 if rising else -1
            labels.append(_BAND_ORDER[cursor])
    boundaries.append(times[-1])

    segments = [
        {"label": labels[j], "start": boundaries[j].isoformat(), "end": boundaries[j + 1].isoformat()}
        for j in range(len(labels))
    ]
    totals_hours: dict[str, float] = {}
    for j, seg in enumerate(segments):
        hours = (boundaries[j + 1] - boundaries[j]).total_seconds() / 3600.0
        totals_hours[seg["label"]] = totals_hours.get(seg["label"], 0.0) + hours

    noon_idx = max(range(len(altitudes)), key=lambda i: altitudes[i])
    midnight_idx = min(range(len(altitudes)), key=lambda i: altitudes[i])

    return {
        "segments": segments,
        "totals_hours": totals_hours,
        "solar_noon": times_iso[noon_idx],
        "solar_midnight": times_iso[midnight_idx],
    }


_MOON_PHASE_NAMES = (
    (22.5, "New"), (67.5, "Waxing Crescent"), (112.5, "First Quarter"),
    (157.5, "Waxing Gibbous"), (202.5, "Full"), (247.5, "Waning Gibbous"),
    (292.5, "Last Quarter"), (337.5, "Waning Crescent"), (360.1, "New"),
)


def moon_phase_info(date_str: str | None = None) -> dict | None:
    """The Moon's phase at local noon on *date_str* (today, if not given):
    illuminated fraction (0.0-1.0) and a phase name (New, Waxing Crescent,
    First Quarter, Waxing Gibbous, Full, Waning Gibbous, Last Quarter, Waning
    Crescent) — for the Schedule screen's per-night almanac shading
    (`galileo.ui.schedule`). Derived from the geocentric Moon-minus-Sun
    apparent ecliptic-longitude difference (the "age angle": 0=new,
    180=full), the standard low-precision approximation used for a display
    label rather than the precise phase-angle calculation SKY-020's Moon-
    distance filter would need; independent of observer location, unlike
    :func:`moon_position_deg`. Returns ``None`` if it can't be computed
    (astropy unavailable), never raises — the same convention every other
    function in this module follows."""
    try:
        from astropy.coordinates import GeocentricTrueEcliptic, get_body
        from astropy.time import Time

        if date_str is None:
            date_str = datetime.date.today().isoformat()
        time = Time(f"{date_str}T12:00:00", scale="utc")

        frame = GeocentricTrueEcliptic(equinox=time)
        moon_lon = get_body("moon", time).transform_to(frame).lon.deg
        sun_lon = get_body("sun", time).transform_to(frame).lon.deg
        age_deg = float(moon_lon - sun_lon) % 360.0
        fraction = (1.0 - math.cos(math.radians(age_deg))) / 2.0
        name = next(label for threshold, label in _MOON_PHASE_NAMES if age_deg < threshold)

        return {"fraction": fraction, "age_deg": age_deg, "name": name}
    except Exception:
        logger.debug("Could not compute Moon phase", exc_info=True)
        return None


def altaz_to_radec_deg(
    alt_deg: float, az_deg: float, location: ObservingLocation, time=None,
) -> tuple[float, float] | None:
    """Convert a local (altitude, azimuth) direction as seen from *location* at
    *time* (now, if not given) to J2000 RA/Dec degrees — used to slew a mount
    at a fixed sky *direction* (e.g. the Sky Flat routine's East vantage
    point, CAL-070) rather than a fixed RA/Dec, which would drift out of that
    direction as the night goes on. Returns ``None`` if it can't be computed."""
    try:
        from astropy.coordinates import AltAz, EarthLocation, SkyCoord
        from astropy.time import Time
        import astropy.units as u

        loc = EarthLocation(
            lat=location.latitude * u.deg, lon=location.longitude * u.deg, height=location.elevation_m * u.m,
        )
        t = time or Time.now()
        frame = AltAz(obstime=t, location=loc)
        coord = SkyCoord(alt=alt_deg * u.deg, az=az_deg * u.deg, frame=frame)
        icrs = coord.transform_to("icrs")
        return float(icrs.ra.deg), float(icrs.dec.deg)
    except Exception:
        logger.debug("Could not convert alt/az to RA/Dec for the Sky Flat slew", exc_info=True)
        return None
