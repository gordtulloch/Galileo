# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""AAVSO Target Tool API client (adapted from VSTarget planning/aavso_client.py)."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_AAVSO_TARGET_TOOL_URL = "https://targettool.aavso.org/TargetTool/api/v1/targets/"


class AavsoTargetToolClient:
    """Downloads variable-star targets from the AAVSO Target Tool REST API (EXT-100)."""

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    async def fetch_targets(self, section: str = "") -> list[dict]:
        """Return target dicts for the given observing *section*."""
        params: dict[str, str] = {}
        if section:
            params["obscode"] = section
        if self.api_key:
            params["apikey"] = self.api_key

        url = _AAVSO_TARGET_TOOL_URL
        if params:
            url += "?" + urllib.parse.urlencode(params)

        try:
            import asyncio
            response = await asyncio.to_thread(self._get_sync, url)
            return response
        except Exception as exc:
            logger.warning("AAVSO Target Tool fetch failed: %s", exc)
            return []

    def _get_sync(self, url: str) -> list[dict]:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
        if isinstance(data, list):
            return data
        return data.get("targets", [])


_AAVSO_VSP_CHART_URL = "https://www.aavso.org/apps/vsp/api/chart/"


class AavsoVspClient:
    """Downloads comparison-star photometry for one target from the AAVSO
    Variable Star Plotter (VSP) REST API (VST-EXT-010)."""

    def __init__(self, fov_arcmin: float = 60.0, maglimit: float = 16.5) -> None:
        self.fov_arcmin = fov_arcmin
        self.maglimit = maglimit

    async def fetch_comparison_stars(self, target: str) -> list[dict]:
        """Return the VSP chart's comparison-star photometry dicts for *target*
        (AAVSO's own ``auid``/``ra``/``dec``/``bands`` fields, one per star)."""
        params = {
            "star": target, "fov": self.fov_arcmin, "maglimit": self.maglimit, "format": "json",
        }
        url = _AAVSO_VSP_CHART_URL + "?" + urllib.parse.urlencode(params)

        try:
            import asyncio
            return await asyncio.to_thread(self._get_sync, url)
        except Exception as exc:
            logger.warning("AAVSO VSP fetch failed for %r: %s", target, exc)
            return []

    def _get_sync(self, url: str) -> list[dict]:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get("photometry", [])
