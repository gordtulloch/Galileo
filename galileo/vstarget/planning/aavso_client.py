"""AAVSO Target Tool API client (adapted from VSTarget planning/aavso_client.py)."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

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
            import functools
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
