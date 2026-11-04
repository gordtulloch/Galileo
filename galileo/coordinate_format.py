# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Sexagesimal text for coordinates, with no dependency on a screen (used by the Mount page's status display and
anything else that shows a position the way astronomy software conventionally does)."""

from __future__ import annotations


def format_hms(hours: float | None) -> str:
    """Format an hour-angle-like value (Right Ascension, Sidereal Time, time-to-meridian) as ``HH:MM:SS``."""
    if hours is None:
        return "—"
    total_seconds = round((hours % 24.0) * 3600.0)
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_dms(degrees: float | None) -> str:
    """Format a degree value (Declination, Altitude, Azimuth, Site Latitude/Longitude) as ``±DD° MM' SS"``."""
    if degrees is None:
        return "—"
    sign = "-" if degrees < 0 else ""
    total_seconds = round(abs(degrees) * 3600.0)
    d, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{sign}{d:02d}° {m:02d}' {s:02d}\""


__all__ = ["format_dms", "format_hms"]
