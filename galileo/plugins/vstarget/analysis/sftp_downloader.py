# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SFTP image downloader for variable-star analysis (adapted from VSTarget)."""

from __future__ import annotations

from galileo.library.adapters.sftp import SftpImageRetriever

# Re-exported so test code can import from galileo.plugins.vstarget.analysis
__all__ = ["SftpImageRetriever"]
