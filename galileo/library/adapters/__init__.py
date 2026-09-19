# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""galileo.library.adapters package."""

from galileo.library.adapters.ftp import SmartTelescopeFtpAdapter
from galileo.library.adapters.sftp import SftpImageRetriever
from galileo.library.adapters.smb import SmartTelescopeSmbAdapter

__all__ = ["SmartTelescopeFtpAdapter", "SftpImageRetriever", "SmartTelescopeSmbAdapter"]
