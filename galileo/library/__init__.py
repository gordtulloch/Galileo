# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""galileo.library package — image library and repository management.

Incorporates and extends code from the AstroFiler project (GPL-3.0).
"""

from galileo.library.adapters.ftp import SmartTelescopeFtpAdapter
from galileo.library.adapters.sftp import SftpImageRetriever
from galileo.library.adapters.smb import SmartTelescopeSmbAdapter
from galileo.library.calibration import CalibrationApplyResult, LibraryCalibrationService
from galileo.library.cloud import CloudSyncService
from galileo.library.repository import Repository, RepositoryEntry, SessionContainer

# Convenience alias matching test expectations
LibraryService = LibraryCalibrationService

__all__ = [
    "CloudSyncService",
    "LibraryCalibrationService",
    "LibraryService",
    "Repository",
    "RepositoryEntry",
    "SessionContainer",
    "SmartTelescopeFtpAdapter",
    "SmartTelescopeSmbAdapter",
    "SftpImageRetriever",
]
