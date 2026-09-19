# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Smart telescope SMB/CIFS adapter (SEESTAR, StellarMate) (LIB-090)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SmartTelescopeSmbAdapter:
    """Browse and download FITS files from a SEESTAR or StellarMate via SMB/CIFS."""

    def __init__(self, host: str = "", share: str = "") -> None:
        self.host = host
        self.share = share

    async def browse(self, host: str = "", share: str = "") -> list[str]:
        """Return a list of remote FITS file paths on the SMB share."""
        host = host or self.host
        share = share or self.share
        try:
            from smb.SMBConnection import SMBConnection  # type: ignore[import]
            import socket
            conn = SMBConnection("", "", "galileo", host)
            conn.connect(socket.gethostbyname(host), 139)
            files = []
            for item in conn.listPath(share, "/"):
                if item.filename.endswith((".fits", ".fit")):
                    files.append(f"/{item.filename}")
            conn.close()
            return files
        except Exception as exc:
            logger.debug("SMB browse error: %s", exc)
            return []

    async def download(self, remote_path: str, dest: "Path | str") -> Path:
        """Download *remote_path* from the SMB share to *dest*."""
        dest_path = Path(dest) / Path(remote_path).name
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from smb.SMBConnection import SMBConnection  # type: ignore[import]
            import socket
            conn = SMBConnection("", "", "galileo", self.host)
            conn.connect(socket.gethostbyname(self.host), 139)
            with open(dest_path, "wb") as fh:
                conn.retrieveFile(self.share, remote_path, fh)
            conn.close()
        except Exception as exc:
            logger.warning("SMB download error: %s", exc)
        return dest_path
