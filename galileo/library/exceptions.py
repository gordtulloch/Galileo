# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Library exception hierarchy, rooted at :class:`galileo.exceptions.LibraryError`.

Vendored from AstroFiler's ``exceptions`` module. ``DatabaseError`` is shared
with the rest of Galileo rather than redefined here.
"""


from galileo.exceptions import DatabaseError, LibraryError

__all__ = [
    "AstroFilerError", "CalibrationError", "CloudSyncError", "ConfigurationError",
    "DatabaseError", "DatabaseTransaction", "FileOperation", "FileProcessingError",
    "FitsHeaderError", "QualityAnalysisError", "RepositoryError",
    "TelescopeConnectionError", "ValidationError",
]


class AstroFilerError(LibraryError):
    """Base class for library errors that carry an optional error code and details."""

    def __init__(self, message: str, error_code: str | None = None, **kwargs):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = kwargs

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class FileProcessingError(AstroFilerError):
    """Raised when file processing operations fail."""

    def __init__(self, message: str, file_path: str | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.file_path = file_path


class FitsHeaderError(FileProcessingError):
    """Raised when FITS header processing fails."""


class CalibrationError(AstroFilerError):
    """Raised when calibration operations fail."""


class RepositoryError(AstroFilerError):
    """Raised when repository operations fail."""


class TelescopeConnectionError(AstroFilerError):
    """Raised when telescope connection operations fail."""

    def __init__(self, message: str, telescope_name: str | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.telescope_name = telescope_name


class CloudSyncError(AstroFilerError):
    """Raised when cloud synchronization operations fail."""


class ConfigurationError(AstroFilerError):
    """Raised when configuration is invalid or missing."""


class ValidationError(AstroFilerError):
    """Raised when data validation fails."""

    def __init__(self, message: str, field: str | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.field = field


class QualityAnalysisError(AstroFilerError):
    """Raised when quality analysis operations fail."""


# Context managers for better resource handling
class DatabaseTransaction:
    """Context manager for database transactions."""

    def __init__(self, db_connection):
        self.db = db_connection

    def __enter__(self):
        self.db.begin()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.db.rollback()
            return False
        else:
            self.db.commit()
            return True


class FileOperation:
    """Context manager for file operations with cleanup."""

    def __init__(self, temp_files: list = None):
        self.temp_files = temp_files or []

    def add_temp_file(self, file_path: str):
        """Add a temporary file to be cleaned up."""
        self.temp_files.append(file_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Cleanup temporary files
        import os
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except OSError:
                pass  # Best effort cleanup
