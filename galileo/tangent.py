# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Gnomonic (tangent-plane) projection about a reference point, in degrees.

Standard coordinates ``(xi, eta)`` are the offsets a flat photographic plate tangent to the sky at
the reference point would show: ``xi`` towards increasing RA (east), ``eta`` towards the north pole.
They are what a plate-solve's CD matrix maps pixels to, and what a mosaic's panes have to be laid
out in — a step of ``d`` degrees east on the plate is ``d / cos(dec)`` degrees of RA, not ``d``.
"""

from __future__ import annotations

import math


def sky_to_tangent(ra_deg: float, dec_deg: float, ra0_deg: float, dec0_deg: float) -> tuple[float, float]:
    """``(xi, eta)`` in degrees of (*ra_deg*, *dec_deg*) on the plane tangent at (*ra0_deg*, *dec0_deg*)."""
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    ra0, dec0 = math.radians(ra0_deg), math.radians(dec0_deg)
    d_ra = ra - ra0
    denom = math.sin(dec) * math.sin(dec0) + math.cos(dec) * math.cos(dec0) * math.cos(d_ra)
    if denom <= 1e-9:
        raise ValueError("the position is on the far side of the sky from the projection centre")
    xi = math.cos(dec) * math.sin(d_ra) / denom
    eta = (math.sin(dec) * math.cos(dec0) - math.cos(dec) * math.sin(dec0) * math.cos(d_ra)) / denom
    return math.degrees(xi), math.degrees(eta)


def tangent_to_sky(xi_deg: float, eta_deg: float, ra0_deg: float, dec0_deg: float) -> tuple[float, float]:
    """``(ra_deg, dec_deg)`` of the point at standard coordinates (*xi_deg*, *eta_deg*) on the plane
    tangent at (*ra0_deg*, *dec0_deg*); RA is returned in [0, 360)."""
    xi, eta = math.radians(xi_deg), math.radians(eta_deg)
    ra0, dec0 = math.radians(ra0_deg), math.radians(dec0_deg)
    rho = math.hypot(xi, eta)
    if rho == 0.0:
        return ra0_deg % 360.0, dec0_deg
    c = math.atan(rho)
    dec = math.asin(math.cos(c) * math.sin(dec0) + eta * math.sin(c) * math.cos(dec0) / rho)
    ra = ra0 + math.atan2(xi * math.sin(c), rho * math.cos(dec0) * math.cos(c) - eta * math.sin(dec0) * math.sin(c))
    return math.degrees(ra) % 360.0, math.degrees(dec)
