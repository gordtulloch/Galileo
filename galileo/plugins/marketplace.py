# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Plugin Marketplace client (PLUG-100 / PLUG-110).

Fetches the list of available plugins from the galileo-imaging.com plugins page.
Primary strategy: parse a ``<script type="application/json" id="galileo-plugins">``
JSON block embedded in the page.  Fallback: scrape ``<a href="*.zip">`` links
inside a ``<section id="plugins">`` element.

The client is intentionally synchronous — callers run it in a QThread so it
doesn't block the Qt event loop.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)

# Default index URL — can be overridden in tests or config.
MARKETPLACE_URL = "https://www.galileo-imaging.com/assets/plug-ins/"


@dataclass
class MarketplaceEntry:
    """A single plugin entry returned by the marketplace."""
    name: str
    description: str
    version: str
    tier: str           # "first_party" | "third_party"
    author: str
    download_url: str
    description_long: str = ""
    icon_url: str = ""
    icon_data: bytes | None = field(default=None, compare=False, repr=False)


class MarketplaceClient:
    """Fetch and cache the list of plugins available on galileo-imaging.com.

    Usage::

        client = MarketplaceClient()
        entries, error = client.fetch()   # blocks; run in a QThread
        for e in entries:
            print(e.name, e.version, e.download_url)

    The last successful fetch is cached for the lifetime of the object;
    call :meth:`refresh` to force a new HTTP request.
    """

    def __init__(self, base_url: str = MARKETPLACE_URL) -> None:
        self._base_url = base_url
        self._cache: list[MarketplaceEntry] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self) -> tuple[list[MarketplaceEntry], str]:
        """Return ``(entries, error_message)``.

        Uses the cached result if one exists.  ``error_message`` is an empty
        string on success, a human-readable explanation on failure.
        """
        with self._lock:
            if self._cache is not None:
                return list(self._cache), ""
        return self._do_fetch()

    def refresh(self) -> tuple[list[MarketplaceEntry], str]:
        """Clear the cache and fetch fresh results."""
        with self._lock:
            self._cache = None
        return self._do_fetch()

    def download(
        self,
        entry: MarketplaceEntry,
        dest_path: str,
        progress_callback: Callable[[int, int], None] | None = None,
        cancel_flag: threading.Event | None = None,
    ) -> bool:
        """Download *entry*'s ZIP to *dest_path*.

        *progress_callback(bytes_received, total_bytes)* is called periodically;
        *total_bytes* is -1 when the server doesn't send Content-Length.
        *cancel_flag* is checked between chunks; if set, the partial file is
        deleted and this method returns ``False``.

        Returns ``True`` on success, ``False`` on cancellation or error.
        """
        import requests
        from pathlib import Path

        dest = Path(dest_path)
        try:
            with requests.get(entry.download_url, stream=True, timeout=30) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", -1))
                received = 0
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if cancel_flag and cancel_flag.is_set():
                            fh.close()
                            dest.unlink(missing_ok=True)
                            return False
                        if chunk:
                            fh.write(chunk)
                            received += len(chunk)
                            if progress_callback:
                                progress_callback(received, total)
            return True
        except Exception:
            logger.exception("Download failed for %r", entry.name)
            dest.unlink(missing_ok=True)
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _do_fetch(self) -> tuple[list[MarketplaceEntry], str]:
        import requests

        try:
            resp = requests.get(self._base_url, timeout=15)
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            msg = f"Could not reach {self._base_url}: {exc}"
            logger.warning(msg)
            return [], msg

        entries = self._parse_json_embed(html, self._base_url)
        if entries is None:
            entries = self._parse_html_fallback(html, self._base_url)

        if entries is None:
            msg = "Plugin list not found on the page — the website format may have changed."
            logger.warning(msg)
            return [], msg

        for entry in entries:
            if entry.icon_url:
                entry.icon_data = self._fetch_icon(entry.icon_url)

        with self._lock:
            self._cache = list(entries)

        return list(entries), ""

    @staticmethod
    def _parse_json_embed(html: str, base_url: str = "") -> list[MarketplaceEntry] | None:
        """Primary strategy: extract the JSON block embedded in the page."""
        from urllib.parse import urljoin

        pattern = r'<script[^>]+type=["\']application/json["\'][^>]+id=["\']galileo-plugins["\'][^>]*>(.*?)</script>'
        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, list):
            return None
        entries = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                raw_url = item["download_url"]
                download_url = urljoin(base_url, raw_url) if base_url else raw_url
                raw_icon = item.get("icon_url", "")
                icon_url = urljoin(base_url, raw_icon) if base_url and raw_icon else raw_icon
                entries.append(MarketplaceEntry(
                    name=item["name"],
                    description=item.get("description", ""),
                    version=item.get("version", ""),
                    tier=item.get("tier", "third_party"),
                    author=item.get("author", ""),
                    download_url=download_url,
                    description_long=item.get("description_long", ""),
                    icon_url=icon_url,
                ))
            except KeyError:
                continue
        return entries if entries else None

    def _fetch_icon(self, url: str) -> bytes | None:
        import requests
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            return resp.content
        except Exception:
            logger.debug("Could not fetch icon %r", url)
            return None

    @staticmethod
    def _parse_html_fallback(html: str, base_url: str) -> list[MarketplaceEntry] | None:
        """Fallback: scrape <a href="*.zip"> links inside <section id="plugins">."""
        # Narrow to the plugins section if possible.
        section_match = re.search(
            r'<section[^>]+id=["\']plugins["\'][^>]*>(.*?)</section>',
            html, re.DOTALL | re.IGNORECASE,
        )
        search_html = section_match.group(1) if section_match else html

        # Find all .zip anchor links.
        link_pattern = re.compile(
            r'<a\s[^>]*href=["\']([^"\']*\.zip)["\'][^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE,
        )
        entries = []
        from urllib.parse import urljoin
        for m in link_pattern.finditer(search_html):
            href = m.group(1).strip()
            label = re.sub(r"<[^>]+>", "", m.group(2)).strip()  # strip inner tags
            url = urljoin(base_url, href)
            # Derive a minimal name from the filename (e.g. "vstarget-planning-1.0.0.zip").
            filename = href.rsplit("/", 1)[-1]
            name = re.sub(r"-\d+\.\d+.*\.zip$", "", filename, flags=re.IGNORECASE) or filename
            entries.append(MarketplaceEntry(
                name=name,
                description=label or name,
                version="",
                tier="third_party",
                author="",
                download_url=url,
            ))
        return entries if entries else None
