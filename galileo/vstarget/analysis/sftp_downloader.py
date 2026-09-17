"""SFTP image downloader for variable-star analysis (adapted from VSTarget)."""

from __future__ import annotations

from galileo.library.adapters.sftp import SftpImageRetriever

# Re-exported so test code can import from galileo.vstarget.analysis
__all__ = ["SftpImageRetriever"]
