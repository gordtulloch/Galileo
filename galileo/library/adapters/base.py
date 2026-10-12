# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The ``RemoteSourceAdapter`` interface (SDD §4.23) and its one implementation.

``galileo.library.services.telescope.SmartTelescopeManager`` holds the only SMB, FTP/FTPS and SFTP
protocol code (the Download dialog and ``galileo-download`` use it directly, on worker threads). The
async adapters in this package are thin facades over it, so there is a single code path per protocol.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class RemoteSourceAdapter(Protocol):
    """A remote place FITS files can be listed on and fetched from."""

    async def browse(self, *args, **kwargs) -> list[str]:
        """Remote paths of the FITS files available."""

    async def download(self, remote_path: str, dest: Path | str) -> Path:
        """Fetch *remote_path* into the folder *dest*; returns the local file."""


class ManagerSourceAdapter:
    """Shared base: lists and fetches through ``smart_telescope_manager`` for one telescope type."""

    telescope_type = ""

    def __init__(self, host: str = "", user: str | None = None, password: str | None = None) -> None:
        self.host = host
        self.user = user
        self.password = password
        self._listing: dict[str, dict] = {}     # remote path -> the manager's file-info dict

    @staticmethod
    def _manager():
        from galileo.library.services.telescope import smart_telescope_manager
        return smart_telescope_manager

    def _browse_sync(self, telescope_type: str, host: str) -> list[str]:
        files, error = self._manager().get_fits_files(telescope_type, host, self.user, self.password)
        if error:
            logger.warning("%s listing on %s failed: %s", telescope_type, host, error)
        self._listing.update({f["path"]: f for f in files})
        return [f["path"] for f in files]

    def _download_sync(self, telescope_type: str, host: str, remote_path: str, dest_path: Path) -> bool:
        info = self._listing.get(remote_path) or {
            "name": Path(remote_path).name, "path": remote_path, "size": 0}
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        ok, error = self._manager().download_file(
            telescope_type, host, info, str(dest_path), self.user, self.password)
        if not ok:
            logger.warning("%s download of %s failed: %s", telescope_type, remote_path, error)
        return bool(ok)

    async def download(self, remote_path: str, dest: Path | str) -> Path:
        """Download *remote_path* to *dest*; a failure is logged and the (absent) path still returned."""
        dest_path = Path(dest) / Path(remote_path).name
        await asyncio.to_thread(self._download_sync, self.telescope_type, self.host, remote_path, dest_path)
        return dest_path
