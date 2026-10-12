# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Application-level exception hierarchy for Galileo."""

from __future__ import annotations


class GalileoError(Exception):
    """Base class for all Galileo errors."""


# --- Device / connection errors -------------------------------------------

class DeviceError(GalileoError):
    """A device operation failed."""

class DeviceConnectionError(DeviceError):
    """Could not connect to a device."""

class DeviceTimeoutError(DeviceError):
    """A device operation timed out."""

class DeviceCapabilityError(DeviceError):
    """The device does not support the requested operation."""

class DevicePropertyError(DeviceError):
    """A device property read or write failed."""

class MountParkedError(DeviceError):
    """A movement command was not sent because the mount is parked."""

class SlewObstructedError(DeviceError):
    """A slew was refused because the target is behind a horizon obstruction."""

    def __init__(self, message: str = "Unable to slew to that area, it is obstructed") -> None:
        super().__init__(message)

class MountLimitError(DeviceError):
    """A slew was refused because the target is outside the mount's configured altitude/hour-angle limits."""


# --- Profile errors --------------------------------------------------------

class ProfileError(GalileoError):
    """An equipment-profile operation failed."""

class ProfileNotFoundError(ProfileError):
    """The requested profile does not exist."""


# --- Sequence errors -------------------------------------------------------

class SequenceError(GalileoError):
    """A sequence operation failed."""

class SequenceAbortedError(SequenceError):
    """The sequence was aborted by the user or a safety event."""


# --- Plate-solve errors ----------------------------------------------------

class PlateSolveError(GalileoError):
    """Plate-solve operation failed."""


# --- Autofocus errors ------------------------------------------------------

class AutofocusError(GalileoError):
    """Autofocus routine failed (e.g. no valid curve fit)."""


# --- Calibration errors (flat wizard) -------------------------------------

class CalibrationError(GalileoError):
    """A calibration operation failed."""

class FlatCalibrationError(CalibrationError):
    """The flat-capture routine could not reach the target ADU level."""

class OutsideTwilightError(CalibrationError):
    """A Sky Flats run was refused because the Sun is outside the local dawn/dusk twilight window."""


# --- Safety errors --------------------------------------------------------

class SafetyError(GalileoError):
    """A safety-related error."""


# --- Library / repository errors ------------------------------------------

class LibraryError(GalileoError):
    """An image-library operation failed.

    Carries an optional machine-readable ``error_code`` and free-form ``details``
    (extra keyword arguments), inherited from AstroFiler's error model. ``str()``
    prefixes the code as ``[CODE] message`` when one is set.
    """

    def __init__(self, message: str = "", error_code: str | None = None, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message

class DatabaseError(LibraryError):
    """A database operation failed.

    ``file_path`` names the file being processed when the failure occurred, if any.
    """

    def __init__(self, message: str = "", error_code: str | None = None,
                 file_path: str | None = None, **details: object) -> None:
        super().__init__(message, error_code, **details)
        self.file_path = file_path


# --- Plugin errors --------------------------------------------------------

class PluginError(GalileoError):
    """A plugin operation failed."""

class ServiceAccessDenied(PluginError):
    """A plugin attempted to access a core service it was not granted."""
