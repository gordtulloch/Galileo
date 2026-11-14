# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Astrospheric forecast client (What's Up Tonight hourly strip under the day/night bar).

Uses the Astrospheric Data API v2 (``GetForecastData``; needs a Professional membership key, set under
Options > Planning). Standard library only. Failures never raise: ``fetch_forecast`` returns an error string
the screen shows. The API does not document units for Cloud/Seeing/Transparency, so the raw numbers are shown
alongside the colour Astrospheric supplies for each hour.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

API_URL = "https://v2-api-public.astrospheric.com/api/GetForecastData"
VARIABLES = ["Cloud", "Seeing", "Transparency", "Temperature", "DewPoint", "Wind"]
ROW_LABELS = {"Cloud": "Cloud", "Seeing": "Seeing", "Transparency": "Transparency",
              "Temperature": "Temp °C", "DewPoint": "Dew point °C", "Wind": "Wind",
              "Smoke": "Smoke AQI", "Aurora": "Aurora Kp"}


def display_value(variable: str, value: float) -> float:
    """Astrospheric reports Temperature/DewPoint in kelvin; shown in °C. Everything else is shown raw."""
    return value - 273.15 if variable in ("Temperature", "DewPoint") else value
_CACHE_SECONDS = 900.0
_cache: dict[tuple[str, float, float], tuple[float, dict[str, Any]]] = {}


def fetch_forecast(api_key: str, latitude: float, longitude: float,
                   timeout: float = 20.0) -> tuple[dict[str, Any] | None, str]:
    """``(response, "")`` on success, else ``(None, reason)``. Cached for 15 minutes per key/location."""
    key = api_key.strip()
    if not key:
        return None, "no API key set (Options > Planning)"
    cache_key = (key, round(latitude, 3), round(longitude, 3))
    hit = _cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1], ""
    body = json.dumps({"APIKey": key, "Latitude": latitude, "Longitude": longitude,
                       "Variables": VARIABLES}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 -- fixed https URL
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = ""
        with contextlib.suppress(Exception):
            detail = str(json.loads(exc.read()).get("ErrorInfo") or "")
        reason = {403: "key rejected or monthly credits used up", 429: "rate limited, try again shortly"}.get(
            exc.code, f"HTTP {exc.code}")
        logger.warning("Astrospheric HTTP %s: %s", exc.code, detail)
        return None, reason + (f" ({detail})" if detail else "")
    except Exception as exc:
        logger.warning("Astrospheric request failed: %s", exc)
        return None, f"request failed ({exc})"
    where = f"{latitude:.3f}, {longitude:.3f}"
    if not isinstance(data, dict):
        logger.warning("Astrospheric unexpected response for %s: %r", where, str(data)[:300])
        return None, f"unexpected response for {where}: {str(data)[:120]!r}"
    if data.get("ErrorInfo"):
        return None, str(data["ErrorInfo"])
    if not hourly(data):
        logger.warning("Astrospheric returned no forecast variables for %s: %s", where, str(data)[:500])
        shown = ", ".join(f"{k}={'list' if isinstance(v, list) else repr(v)[:30]}" for k, v in list(data.items())[:12])
        return None, f"no Cloud/Seeing/Transparency in the response for {where} ({shown})"
    _cache[cache_key] = (time.monotonic(), data)
    return data, ""


def _entries(forecast: dict[str, Any], var: str) -> list[tuple[Any, Any]]:
    """``[(UTCForecastHour, value dict), ...]`` for *var*. The live API returns one ``HourlyForecast`` list
    whose hours each carry every variable; its published example instead shows one list per variable."""
    rows = [(h.get("UTCForecastHour"), h.get(var)) for h in forecast.get("HourlyForecast") or []
            if isinstance(h, dict)]
    if not rows:
        rows = [(e.get("UTCForecastHour"), e.get("Value")) for e in forecast.get(var) or []
                if isinstance(e, dict)]
    return rows


def hourly(forecast: dict[str, Any] | None) -> dict[str, list[tuple[_dt.datetime, float, str]]]:
    """``{variable: [(hour start, UTC-aware; value; hex colour), ...]}`` for each of ``VARIABLES``."""
    out: dict[str, list[tuple[_dt.datetime, float, str]]] = {}
    for var in VARIABLES:
        rows = []
        for hour, value in _entries(forecast or {}, var):
            try:
                when = _dt.datetime.fromisoformat(hour)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=_dt.UTC)
                rows.append((when, float(value["ActualValue"]), str(value.get("ValueColor") or "")))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        if rows:
            out[var] = rows
    return out
