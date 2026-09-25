# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SFTP image retrieval adapter (EXT-120)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SftpImageRetriever:
    """Downloads calibrated FITS images from a remote server via SFTP (EXT-120)."""

    def __init__(self, host: str = "", user: str = "", key_path: str = "") -> None:
        self.host = host
        self.user = user
        self.key_path = key_path

    async def download(
        self,
        host: str = "",
        path: str = "/",
        dest: Path | str = ".",
    ) -> list[str]:
        """Download all FITS files in *path* on the SFTP server to *dest*."""
        host = host or self.host
        dest_path = Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)
        return await asyncio.to_thread(self._download_sync, host, path, dest_path)

    def _download_sync(self, host: str, remote_path: str, dest: Path) -> list[str]:
        downloaded = []
        try:
            import paramiko  # type: ignore[import]
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            # WarningPolicy, not AutoAddPolicy: an unknown host key is still accepted (this is a
            # LAN-only smart-telescope/server use case with no interactive prompt available here),
            # but it's logged rather than trusted silently, so key rotation or a MITM on an
            # unfamiliar host is at least visible instead of being cached with zero trace.
            client.set_missing_host_key_policy(paramiko.WarningPolicy())
            connect_kwargs = {"hostname": host, "username": self.user, "timeout": 10}
            if self.key_path:
                connect_kwargs["key_filename"] = self.key_path
            client.connect(**connect_kwargs)
            sftp = client.open_sftp()
            for entry in sftp.listdir_attr(remote_path):
                if entry.filename.endswith((".fits", ".fit")):
                    local = dest / entry.filename
                    sftp.get(f"{remote_path}/{entry.filename}", str(local))
                    downloaded.append(str(local))
            sftp.close()
            client.close()
        except Exception as exc:
            logger.debug("SFTP download error: %s", exc)
        return downloaded
