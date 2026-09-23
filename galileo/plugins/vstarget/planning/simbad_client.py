# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Simbad coordinate/magnitude lookup client (EXT-110)."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class SimbadClient:
    """Queries the CDS Simbad database for target coordinates and magnitude (EXT-110)."""

    async def lookup(self, target_name: str) -> dict:
        """Return ``{"ra_deg": …, "dec_deg": …, "magnitude_v": …}`` for *target_name*."""
        try:
            from astroquery.simbad import Simbad  # type: ignore[import]
            import astropy.units as u

            custom_simbad = Simbad()
            custom_simbad.add_votable_fields("flux(V)")

            result_table = await asyncio.to_thread(custom_simbad.query_object, target_name)
            if result_table is None or len(result_table) == 0:
                return {}

            row = result_table[0]
            from astropy.coordinates import SkyCoord
            coord = SkyCoord(
                ra=row["RA"],
                dec=row["DEC"],
                unit=("hourangle", "deg"),
                frame="icrs",
            )
            return {
                "ra_deg": float(coord.ra.deg),
                "dec_deg": float(coord.dec.deg),
                "magnitude_v": float(row["FLUX_V"]) if row["FLUX_V"] else None,
            }
        except Exception as exc:
            logger.debug("Simbad lookup failed for %r: %s", target_name, exc)
            return {}
