# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Simbad coordinate/magnitude lookup client (EXT-110).

Re-exports the core implementation (``galileo.planning.sky_atlas.SimbadClient``)
rather than keeping a second copy of the same Simbad query — EXT-110 is core,
shared infrastructure (it also backs ``SkyAtlas.search_online``'s SKY-100
fallback), not a VSTarget-specific client.
"""

from __future__ import annotations

from galileo.planning.sky_atlas import SimbadClient

__all__ = ["SimbadClient"]
