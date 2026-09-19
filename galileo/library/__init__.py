# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""galileo.library package — image library and repository management.

Incorporates and extends code from the AstroFiler project (GPL-3.0). The
catalog schema is ``galileo.library.migrations``; ingest, sessions and master
calibration frames are ``galileo.library.core``; the screens are
``galileo.ui.library``; the batch utilities are ``galileo.commands``.
"""

from galileo.library.adapters.ftp import SmartTelescopeFtpAdapter
from galileo.library.adapters.sftp import SftpImageRetriever
from galileo.library.adapters.smb import SmartTelescopeSmbAdapter
from galileo.library.registrar import LibraryRegistrar, SessionContainer

__all__ = [
    "LibraryRegistrar",
    "SessionContainer",
    "SftpImageRetriever",
    "SmartTelescopeFtpAdapter",
    "SmartTelescopeSmbAdapter",
]
