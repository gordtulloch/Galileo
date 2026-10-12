# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Smart telescope SMB/CIFS adapter (SEESTAR, StellarMate) (LIB-090)."""

from __future__ import annotations

import asyncio

from galileo.library.adapters.base import ManagerSourceAdapter


class SmartTelescopeSmbAdapter(ManagerSourceAdapter):
    """Browse and download FITS files from a SEESTAR or StellarMate via SMB/CIFS.

    *share* picks the model: a share containing ``stellarmate`` or ``pictures`` selects StellarMate,
    anything else SeeStar (the manager owns each model's share name, folder and credentials)."""

    telescope_type = "SeeStar"

    def __init__(self, host: str = "", share: str = "") -> None:
        super().__init__(host)
        self.share = share
        self.telescope_type = self._model_for(share)

    @staticmethod
    def _model_for(share: str) -> str:
        return "StellarMate" if share.lower() in ("pictures", "stellarmate") else "SeeStar"

    async def browse(self, host: str = "", share: str = "") -> list[str]:
        """Return the remote FITS file paths on the telescope's SMB share."""
        if share:
            self.telescope_type = self._model_for(share)
        return await asyncio.to_thread(self._browse_sync, self.telescope_type, host or self.host)
