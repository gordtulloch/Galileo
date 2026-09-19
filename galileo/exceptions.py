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


# --- Safety errors --------------------------------------------------------

class SafetyError(GalileoError):
    """A safety-related error."""


# --- Library / repository errors ------------------------------------------

class LibraryError(GalileoError):
    """An image-library operation failed."""

class DatabaseError(LibraryError):
    """A database operation failed."""


# --- Plugin errors --------------------------------------------------------

class PluginError(GalileoError):
    """A plugin operation failed."""

class ServiceAccessDenied(PluginError):
    """A plugin attempted to access a core service it was not granted."""
