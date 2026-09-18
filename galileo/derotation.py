"""Field derotation for alt-az mounts (galileo.derotation).

An alt-az mount rotates the sky's field of view relative to the camera as it
tracks; a rotator counters that by turning at the *field rotation rate*. This
module holds the domain logic behind the Rotator screen's derotation section:
turning a target's RA/Dec into Alt/Az for a site and time, the resulting
rotation rate, a source for the target (a FITS header), and the
accumulator that converts a rate into rotator move commands. It has no Qt,
INDI or Alpaca dependency; the Rotator page drives a device adapter with it.
"""

from __future__ import annotations

import datetime
import math
import re
from pathlib import Path

# Earth's rotation relative to the stars: 360.98564736629 deg per mean solar day.
SIDEREAL_DEG_PER_MIN = 360.98564736629 / (24.0 * 60.0)

_MAX_ALT_DEG = 89.9  # field rotation diverges at the zenith; clamp rather than blow up

FITS_SUFFIXES = (".fits", ".fit", ".fts")


def julian_date(when: datetime.datetime) -> float:
    if when.tzinfo is not None:
        when = when.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    y, m = when.year, when.month
    if m <= 2:
        y, m = y - 1, m + 12
    a = y // 100
    b = 2 - a + a // 4
    day = when.day + (when.hour + (when.minute + (when.second + when.microsecond / 1e6) / 60.0) / 60.0) / 24.0
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + day + b - 1524.5


def local_sidereal_deg(when: datetime.datetime, longitude_deg: float) -> float:
    """Local mean sidereal time in degrees (longitude east-positive)."""
    jd = julian_date(when)
    t = (jd - 2451545.0) / 36525.0
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0)
            + 0.000387933 * t * t - t ** 3 / 38710000.0)
    return (gmst + longitude_deg) % 360.0


def radec_to_altaz(ra_deg: float, dec_deg: float, lat_deg: float, lon_deg: float,
                   when: "datetime.datetime | None" = None) -> tuple[float, float]:
    """Altitude and azimuth (degrees, azimuth from north through east) of an
    RA/Dec (degrees) for a site (longitude east-positive) at *when* (UTC)."""
    when = when or datetime.datetime.now(datetime.timezone.utc)
    hour_angle = math.radians(local_sidereal_deg(when, lon_deg) - ra_deg)
    dec, lat = math.radians(dec_deg), math.radians(lat_deg)
    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(hour_angle)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    az = math.atan2(
        -math.cos(dec) * math.sin(hour_angle),
        math.sin(dec) * math.cos(lat) - math.cos(dec) * math.cos(hour_angle) * math.sin(lat),
    )
    return math.degrees(alt), math.degrees(az) % 360.0


def field_rotation_rate_deg_per_min(lat_deg: float, alt_deg: float, az_deg: float) -> float:
    """Signed field rotation rate, in degrees per minute, of an alt-az mount
    tracking a target at (*alt_deg*, *az_deg*) from latitude *lat_deg*:
    ``Ω · cos(lat) · cos(az) / cos(alt)``. It is zero when the target is due
    east/west and largest near the meridian at high altitude."""
    alt = math.radians(min(alt_deg, _MAX_ALT_DEG))
    return SIDEREAL_DEG_PER_MIN * math.cos(math.radians(lat_deg)) * math.cos(math.radians(az_deg)) / math.cos(alt)


class Derotator:
    """Turns a changing field-rotation rate into rotator angle commands.

    Keeps a *virtual* angle that integrates the rate exactly, and only asks
    for a move once it has drifted at least ``min_step_deg`` from what the
    rotator was last commanded to — rotators have finite resolution and
    issuing a move every tick for a hundredth of a degree just wears them.
    """

    def __init__(self, start_angle_deg: float, min_step_deg: float = 0.05) -> None:
        self.min_step_deg = min_step_deg
        self._virtual = float(start_angle_deg)
        self._commanded = float(start_angle_deg)
        self._last_t: "float | None" = None

    def update(self, rate_deg_per_min: float, now_s: float) -> "float | None":
        """Advance the virtual angle to time *now_s* (any monotonic clock, in
        seconds) at *rate_deg_per_min*. Returns the new angle (0–360) the
        rotator should be moved to, or ``None`` if no move is due yet."""
        if self._last_t is not None:
            self._virtual += rate_deg_per_min * (now_s - self._last_t) / 60.0
        self._last_t = now_s
        # Signed shortest difference, so wrapping past 360 isn't a huge "move".
        drift = (self._virtual - self._commanded + 180.0) % 360.0 - 180.0
        if abs(drift) < self.min_step_deg:
            return None
        self._commanded = self._virtual % 360.0
        return self._commanded


# ---------------------------------------------------------------------------
# Target sources
# ---------------------------------------------------------------------------

def parse_sexagesimal(text: str) -> float:
    """Parse ``"12 34 56.7"`` / ``"-05:30:00"`` / plain ``"12.5"`` to a float
    (hours or degrees — the caller knows which)."""
    parts = [p for p in re.split(r"[\s:]+", str(text).strip()) if p]
    if not parts:
        raise ValueError(f"not a coordinate: {text!r}")
    negative = parts[0].startswith("-")
    return (-1 if negative else 1) * sum(abs(float(p)) / 60.0 ** i for i, p in enumerate(parts))


def to_sexagesimal(value: float, decimals: int = 1) -> tuple[int, int, int, float]:
    """Split hours/degrees into ``(sign, whole, minutes, seconds)`` for
    display in separate boxes, rounding *seconds* to *decimals* places
    without ever producing ``60.0`` (a naive split turns 12.9999999 into
    ``12 59 60.0``)."""
    scale = 10 ** decimals
    total = round(abs(value) * 3600 * scale)
    whole, rest = divmod(total, 3600 * scale)
    minutes, seconds = divmod(rest, 60 * scale)
    return (-1 if value < 0 else 1), int(whole), int(minutes), seconds / scale


def pointing_from_fits_header(header) -> tuple[float, float]:
    """RA/Dec (degrees) a FITS frame was pointed at. A plate-solved WCS
    (``CRVAL1/2`` with RA/DEC axes) wins, then the capture software's
    ``OBJCTRA``/``OBJCTDEC`` (sexagesimal, hours/degrees), then plain
    ``RA``/``DEC``. Raises ``ValueError`` if the header has none of them."""
    if str(header.get("CTYPE1", "")).upper().startswith("RA") and "CRVAL1" in header and "CRVAL2" in header:
        return float(header["CRVAL1"]), float(header["CRVAL2"])
    if "OBJCTRA" in header and "OBJCTDEC" in header:
        return parse_sexagesimal(header["OBJCTRA"]) * 15.0, parse_sexagesimal(header["OBJCTDEC"])
    if "RA" in header and "DEC" in header:
        ra, dec = header["RA"], header["DEC"]
        ra_deg = float(ra) if isinstance(ra, (int, float)) else parse_sexagesimal(ra) * 15.0
        dec_deg = float(dec) if isinstance(dec, (int, float)) else parse_sexagesimal(dec)
        return ra_deg, dec_deg
    raise ValueError("FITS header has no pointing (CRVAL1/2, OBJCTRA/OBJCTDEC, or RA/DEC)")


def newest_fits_file(folder: "str | Path") -> Path:
    files = [p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in FITS_SUFFIXES]
    if not files:
        raise FileNotFoundError(f"No FITS files in {folder}")
    return max(files, key=lambda p: p.stat().st_mtime)


def pointing_from_fits_folder(folder: "str | Path") -> tuple[float, float, Path]:
    """Pointing of the most recently written FITS file in *folder*."""
    from astropy.io import fits
    path = newest_fits_file(folder)
    return (*pointing_from_fits_header(fits.getheader(path)), path)

