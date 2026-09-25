"""
Type definitions for AstroFiler application.

This module provides type aliases and protocols for better type safety.
"""

from typing import Protocol, Any, Union
from pathlib import Path
from datetime import datetime

# Type aliases for common data structures
FitsHeaderDict = dict[str, Any]
FilePath = Union[str, Path]
SessionId = str
FileId = str
QualityMetrics = dict[str, float]
ProcessingOptions = dict[str, Any]

# Configuration types
class DatabaseConfig(Protocol):
    """Protocol for database configuration."""
    host: str
    database: str
    user: str | None
    password: str | None

class RepositoryConfig(Protocol):
    """Protocol for repository configuration."""
    repository_path: str
    incoming_path: str
    backup_enabled: bool

class TelescopeConfig(Protocol):
    """Protocol for telescope configuration."""
    name: str
    host: str
    protocol: str  # 'ftp', 'smb', etc.
    credentials: dict[str, str]

# File processing types
class FitsFileInfo(Protocol):
    """Protocol for FITS file information."""
    file_path: FilePath
    file_hash: str
    header: FitsHeaderDict
    image_type: str
    telescope: str
    instrument: str
    object_name: str | None
    exposure_time: float
    date_obs: datetime

# Quality analysis types
class QualityResult(Protocol):
    """Protocol for quality analysis results."""
    overall_score: float
    metrics: QualityMetrics
    recommendations: list[str]
    timestamp: datetime

# Session types
class SessionInfo(Protocol):
    """Protocol for session information."""
    session_id: SessionId
    object_name: str
    telescope: str
    instrument: str
    date: datetime
    file_count: int

# Processing callbacks

class ProgressCallback(Protocol):
    """Protocol for progress reporting callbacks."""
    def __call__(self, current: int, total: int, message: str = "") -> None:
        """Report progress of an operation."""
        ...

# Result types
ProcessingResult = tuple[bool, str, dict[str, Any] | None]
CalibrationResult = tuple[bool, list[FilePath], str | None]

# Cloud storage types
class CloudProvider(Protocol):
    """Protocol for cloud storage providers."""
    def upload_file(self, local_path: FilePath, remote_path: str) -> bool: ...
    def download_file(self, remote_path: str, local_path: FilePath) -> bool: ...
    def list_files(self, remote_path: str) -> list[str]: ...
    def file_exists(self, remote_path: str) -> bool: ...

# Telescope connection types
class TelescopeConnection(Protocol):
    """Protocol for telescope connections."""
    def connect(self) -> bool: ...
    def disconnect(self) -> None: ...
    def list_files(self, path: str) -> list[str]: ...
    def download_file(self, remote_path: str, local_path: FilePath) -> bool: ...
