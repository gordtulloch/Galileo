# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Plugin Marketplace client (PLUG-100 / PLUG-110).

Fetches the list of available plugins from the Galileo-Plugins GitHub
repository via raw.githubusercontent.com.  The repository maintains a
``plugins.json`` index at its root; each entry carries the plugin metadata and
a direct download URL for its ZIP file.  The CI pipeline rebuilds this index
automatically on every push, so no separate website upload is needed.

The client is intentionally synchronous — callers run it in a QThread so it
doesn't block the Qt event loop.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)

# URL of the plugins.json index in the Galileo-Plugins GitHub repository.
# Override in tests by passing a different index_url to MarketplaceClient().
MARKETPLACE_INDEX_URL = (
    "https://raw.githubusercontent.com/gordtulloch/Galileo-Plugins/main/plugins.json"
)


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
    """Fetch and cache the list of plugins available in the Galileo-Plugins repo.

    Usage::

        client = MarketplaceClient()
        entries, error = client.fetch()   # blocks; run in a QThread
        for e in entries:
            print(e.name, e.version, e.download_url)

    The last successful fetch is cached for the lifetime of the object;
    call :meth:`refresh` to force a new HTTP request.
    """

    def __init__(self, index_url: str = MARKETPLACE_INDEX_URL) -> None:
        self._index_url = index_url
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
            resp = requests.get(self._index_url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            msg = f"Could not fetch plugin index from {self._index_url}: {exc}"
            logger.warning(msg)
            return [], msg

        if not isinstance(data, list):
            msg = "Plugin index is not a JSON array — the repository format may have changed."
            logger.warning(msg)
            return [], msg

        entries = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                entries.append(MarketplaceEntry(
                    name=item["name"],
                    description=item.get("description", ""),
                    version=item.get("version", ""),
                    tier=item.get("tier", "third_party"),
                    author=item.get("author", ""),
                    download_url=item["download_url"],
                    description_long=item.get("description_long", ""),
                    icon_url=item.get("icon_url", ""),
                ))
            except KeyError:
                logger.debug("Skipping malformed plugin index entry: %r", item)

        for entry in entries:
            if entry.icon_url:
                entry.icon_data = self._fetch_icon(entry.icon_url)

        with self._lock:
            self._cache = list(entries)

        return list(entries), ""

    def _fetch_icon(self, url: str) -> bytes | None:
        import requests
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            return resp.content
        except Exception:
            logger.debug("Could not fetch icon %r", url)
            return None
