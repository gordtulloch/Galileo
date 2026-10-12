# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""FTP/FTPS smart telescope adapter (iTelescope, DWARF) (LIB-100, LIB-110)."""

from __future__ import annotations

import asyncio

from galileo.library.adapters.base import ManagerSourceAdapter


class SmartTelescopeFtpAdapter(ManagerSourceAdapter):
    """Browse and download FITS files from iTelescope (FTPS) or a DWARF (plain FTP).

    *use_tls* selects the model — TLS is iTelescope, plain FTP the DWARF — because the manager knows
    each one's folder layout and login behaviour."""

    telescope_type = "iTelescope"

    def __init__(self, host: str = "", user: str = "", password: str = "") -> None:  # nosec B107 -- empty means 'ask/none', not a credential
        super().__init__(host, user or None, password or None)

    async def browse(self, host: str = "", use_tls: bool = True, path: str = "/") -> list[str]:
        """Return the remote FITS file paths (*path* is the manager's per-model start folder now)."""
        self.telescope_type = "iTelescope" if use_tls else "DWARF 3"
        return await asyncio.to_thread(self._browse_sync, self.telescope_type, host or self.host)
