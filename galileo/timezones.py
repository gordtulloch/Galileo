# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Country -> IANA timezone lookup, from the tz database's ``zone.tab`` and ``iso3166.tab``.

Used by the Observatory dialog so it lists a country's few zones instead of all ~600.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _read_tab(name: str) -> list[list[str]]:
    """Rows (tab-split, comments dropped) of a tz database table, or [] if not found."""
    candidates: list[Path] = []
    try:
        import tzdata  # type: ignore[import-not-found]
        candidates.append(Path(tzdata.__file__).parent / "zoneinfo" / name)
    except ImportError:
        pass
    try:
        import zoneinfo
        candidates.extend(Path(p) / name for p in zoneinfo.TZPATH)
    except Exception:
        pass
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        return [line.split("\t") for line in text.splitlines() if line and not line.startswith("#")]
    logger.warning("tz database table %s not found", name)
    return []


@functools.lru_cache(maxsize=1)
def _zones_by_country() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in _read_tab("zone.tab"):
        if len(row) >= 3:
            result.setdefault(row[0], []).append(row[2])
    return result


@functools.lru_cache(maxsize=1)
def countries() -> dict[str, str]:
    """ISO 3166 code -> country name, only for countries that have at least one zone."""
    zones = _zones_by_country()
    return {row[0]: row[1] for row in _read_tab("iso3166.tab") if len(row) >= 2 and row[0] in zones}


def zones_for_country(code: str) -> list[str]:
    return sorted(_zones_by_country().get(code, []))


def country_of_zone(zone: str) -> str | None:
    """ISO code of the country listing *zone*, or None (e.g. ``UTC``, unknown names)."""
    for code, names in _zones_by_country().items():
        if zone in names:
            return code
    return None
