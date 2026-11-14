# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Aurora (Kp) and smoke rows for What's Up Tonight's hourly strip, in the strip's cell format
``(start UTC-aware, value, hex colour, hours)``. Free NOAA sources, no key. Every failure returns ``[]``."""

from __future__ import annotations

import datetime as _dt
import json
import logging

logger = logging.getLogger(__name__)

KP_FORECAST_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
Cell = tuple[_dt.datetime, float, str, float]


def kp_color(kp: float) -> str:
    """Quiet below 3, unsettled/active 3-5, storm from 5 (the same bands as the advisory text)."""
    if kp < 3.0:
        return "#2f6f4f"
    if kp < 4.0:
        return "#c9b03a"
    if kp < 5.0:
        return "#e08a2e"
    return "#d0443c"


def aqi_color(aqi: float) -> str:
    """EPA AQI category colours."""
    for limit, color in ((50, "#2e9e4f"), (100, "#e5d12e"), (150, "#f08a24"), (200, "#d6342c"), (300, "#8f3f97")):
        if aqi <= limit:
            return color
    return "#7e0023"


def parse_kp_forecast(rows: object) -> list[Cell]:
    """3-hour Kp cells from NOAA's ``noaa-planetary-k-index-forecast.json`` (observed + predicted)."""
    cells: list[Cell] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            when = _dt.datetime.fromisoformat(row["time_tag"]).replace(tzinfo=_dt.UTC)
            kp = float(row["kp"])
        except (KeyError, TypeError, ValueError):
            continue
        cells.append((when, kp, kp_color(kp), 3.0))
    return cells


def fetch_kp_cells() -> list[Cell]:
    try:
        from galileo.safety import _http_get
        return parse_kp_forecast(json.loads(_http_get(KP_FORECAST_URL)))
    except Exception:
        logger.debug("NOAA Kp forecast unavailable", exc_info=True)
        return []


def fetch_smoke_cell(latitude: float, longitude: float, start: _dt.datetime, end: _dt.datetime) -> list[Cell]:
    """One cell across the whole window: today's NOAA HMS smoke rating (no hourly smoke forecast exists
    there), as an approximate AQI. Empty when unavailable (HMS covers North America only)."""
    try:
        import asyncio
        from galileo.safety import NoaaSmokeClient
        aqi = asyncio.run(NoaaSmokeClient(latitude, longitude).get_smoke_aqi())
    except Exception:
        logger.debug("NOAA smoke unavailable", exc_info=True)
        return []
    if aqi is None:
        return []
    return [(start.astimezone(_dt.UTC), float(aqi), aqi_color(aqi), (end - start).total_seconds() / 3600.0)]
