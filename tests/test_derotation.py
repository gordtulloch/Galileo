# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Field-derotation logic behind the Rotator screen (``galileo.derotation``).

Derotation has no numbered SRS requirement yet (it comes from the reference
screen assets/samples/rot.png), so these tests carry a priority but no TC ID.
"""

from __future__ import annotations

import datetime
import math
import os

import pytest

from galileo import derotation as d

UTC = datetime.UTC


# --- time and coordinates ----------------------------------------------------

@pytest.mark.priority("P3")
def test_julian_date_and_sidereal_time_match_j2000_reference():
    """J2000.0 (2000-01-01 12:00 UTC) is JD 2451545.0, where Greenwich mean sidereal time is 280.46°."""
    j2000 = datetime.datetime(2000, 1, 1, 12, 0, tzinfo=UTC)
    assert d.julian_date(j2000) == pytest.approx(2451545.0)
    assert d.local_sidereal_deg(j2000, 0.0) == pytest.approx(280.46, abs=0.01)
    assert d.local_sidereal_deg(j2000, 10.0) == pytest.approx(290.46, abs=0.01)  # east adds


@pytest.mark.priority("P3")
def test_altaz_on_the_meridian_and_at_the_eastern_horizon():
    """A target on the meridian is due south at 90°−|lat−dec|; one at hour angle −6h on the equator rises due east."""
    when = datetime.datetime(2026, 9, 18, 3, 0, tzinfo=UTC)
    lat, lon = 50.0, -110.0
    lst = d.local_sidereal_deg(when, lon)

    alt, az = d.radec_to_altaz(lst, 20.0, lat, lon, when)   # hour angle 0, dec 30° south of the zenith
    assert alt == pytest.approx(60.0, abs=1e-6) and az == pytest.approx(180.0, abs=1e-6)

    alt, az = d.radec_to_altaz(lst + 90.0, 0.0, lat, lon, when)  # hour angle -6h
    assert alt == pytest.approx(0.0, abs=1e-6) and az == pytest.approx(90.0, abs=1e-6)


# --- rate ----------------------------------------------------------------------

@pytest.mark.priority("P3")
def test_field_rotation_rate_sign_magnitude_and_zenith_clamp():
    """Rate is Ω·cos(lat)·cos(az)/cos(alt): zero due east, opposite signs north vs south, finite at the zenith."""
    omega = d.SIDEREAL_DEG_PER_MIN
    assert omega == pytest.approx(0.25068, abs=1e-4)
    assert d.field_rotation_rate_deg_per_min(45.0, 45.0, 0.0) == pytest.approx(omega)
    assert d.field_rotation_rate_deg_per_min(45.0, 45.0, 180.0) == pytest.approx(-omega)
    assert d.field_rotation_rate_deg_per_min(45.0, 45.0, 90.0) == pytest.approx(0.0, abs=1e-12)
    assert math.isfinite(d.field_rotation_rate_deg_per_min(45.0, 90.0, 0.0))


# --- Derotator -------------------------------------------------------------------

@pytest.mark.priority("P3")
def test_derotator_accumulates_small_moves_until_a_step_is_due():
    """0.02° per tick is below the 0.05° step, so it is held back and issued once enough has built up."""
    derotator = d.Derotator(100.0, min_step_deg=0.05)
    rate = 0.6  # deg/min -> 0.02° per 2 s tick
    results = [derotator.update(rate, t) for t in (0.0, 2.0, 4.0, 6.0)]
    assert results[:3] == [None, None, None]     # 0.00°, 0.02°, 0.04° — all under the step
    assert results[3] == pytest.approx(100.06)   # 0.06° is over it


@pytest.mark.priority("P3")
def test_derotator_fires_once_the_accumulated_step_is_reached():
    """At 0.03° per tick the second tick (0.06° built up) crosses the 0.05° step and the third is held again."""
    derotator = d.Derotator(100.0, min_step_deg=0.05)
    rate = 0.9  # deg/min -> 0.03° per 2 s tick
    assert derotator.update(rate, 0.0) is None
    assert derotator.update(rate, 2.0) is None                       # 0.03°
    assert derotator.update(rate, 4.0) == pytest.approx(100.06)      # 0.06° >= 0.05°
    assert derotator.update(rate, 6.0) is None                       # only 0.03° since the last command


@pytest.mark.priority("P3")
def test_derotator_wraps_through_360_without_a_huge_jump():
    """Crossing 360° commands a small angle just past 0, not a move the long way round."""
    derotator = d.Derotator(359.9)
    derotator.update(6.0, 0.0)
    command = derotator.update(6.0, 2.0)   # +0.2°
    assert command == pytest.approx(0.1, abs=1e-6)


@pytest.mark.priority("P3")
def test_derotator_negative_rate_moves_backwards():
    derotator = d.Derotator(10.0)
    derotator.update(-6.0, 0.0)
    assert derotator.update(-6.0, 2.0) == pytest.approx(9.8)


# --- coordinate text ---------------------------------------------------------------

@pytest.mark.priority("P3")
def test_sexagesimal_parsing_and_splitting():
    assert d.parse_sexagesimal("-05:30:00") == -5.5
    assert d.parse_sexagesimal("12 34 56.7") == pytest.approx(12 + 34 / 60 + 56.7 / 3600)
    assert d.parse_sexagesimal("12.5") == 12.5
    with pytest.raises(ValueError):
        d.parse_sexagesimal("  ")

    assert d.to_sexagesimal(-10.5) == (-1, 10, 30, 0.0)
    assert d.to_sexagesimal(12.9999999) == (1, 13, 0, 0.0)          # never "12 59 60.0"
    assert d.to_sexagesimal(-0.25) == (-1, 0, 15, 0.0)              # sign survives a zero whole part


# --- FITS ----------------------------------------------------------------------------

def _header(**cards):
    from astropy.io import fits
    header = fits.Header()
    for key, value in cards.items():
        header[key] = value
    return header


@pytest.mark.priority("P3")
def test_fits_pointing_prefers_solved_wcs_then_objctra_then_ra_dec():
    solved = _header(CTYPE1="RA---TAN", CRVAL1=150.0, CRVAL2=-20.0, OBJCTRA="01 00 00", OBJCTDEC="+10 00 00", RA=1.0, DEC=1.0)
    assert d.pointing_from_fits_header(solved) == (150.0, -20.0)
    capture = _header(OBJCTRA="10 30 00", OBJCTDEC="-05 30 00", RA=1.0, DEC=1.0)
    assert d.pointing_from_fits_header(capture) == (157.5, -5.5)     # hours -> degrees
    plain = _header(RA=83.8, DEC=-5.4)
    assert d.pointing_from_fits_header(plain) == (83.8, -5.4)
    with pytest.raises(ValueError, match="no pointing"):
        d.pointing_from_fits_header(_header(EXPTIME=30))


@pytest.mark.priority("P3")
def test_fits_folder_sync_uses_the_newest_file(tmp_path):
    import numpy as np
    from astropy.io import fits

    for name, ra, age in (("old.fits", 10.0, 100), ("new.FIT", 200.0, 0)):
        path = tmp_path / name
        fits.PrimaryHDU(np.zeros((2, 2), dtype=np.uint16), header=_header(RA=ra, DEC=5.0)).writeto(path)
        mtime = path.stat().st_mtime - age
        os.utime(path, (mtime, mtime))
    (tmp_path / "notes.txt").write_text("ignored")

    ra, dec, path = d.pointing_from_fits_folder(tmp_path)
    assert (ra, dec, path.name) == (200.0, 5.0, "new.FIT")


@pytest.mark.priority("P3")
def test_fits_folder_sync_reports_a_folder_with_no_fits(tmp_path):
    (tmp_path / "notes.txt").write_text("not a frame")
    with pytest.raises(FileNotFoundError, match="No FITS files"):
        d.pointing_from_fits_folder(tmp_path)

