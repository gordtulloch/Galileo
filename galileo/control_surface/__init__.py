# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Control Surface — the registry of operator-level operations and observable state, the per-Pier
control lease, operation-result events and held motion (SDD §4.29, CSURF-*, LEASE-*).

Remote-client plugins (MobileConnect, WebConnect) are written against this contract; domain services
register with it by declaration and the desktop is not required to use it.
"""

from galileo.control_surface.emergency import EMERGENCY_OPERATIONS, register_emergency
from galileo.control_surface.events import (
    LeaseChanged,
    OperationFinished,
    OperationProgress,
    OperationStarted,
    OperationTracker,
)
from galileo.control_surface.holds import HoldError, HoldManager, validate_timing
from galileo.control_surface.lease import DESKTOP, LeaseBroker, LeaseResult
from galileo.control_surface.registry import (
    Busy,
    OperationContext,
    OperationSpec,
    Outcome,
    Prepared,
    Refused,
    RegistrationError,
    Registry,
    Unreachable,
)
from galileo.control_surface.schema import Arg, InvalidArguments, validate_args
from galileo.control_surface.state import ObservableState

__all__ = [
    "DESKTOP", "EMERGENCY_OPERATIONS", "Arg", "Busy", "HoldError", "HoldManager", "InvalidArguments",
    "LeaseBroker", "LeaseChanged", "LeaseResult", "ObservableState", "OperationContext", "OperationFinished",
    "OperationProgress", "OperationSpec", "OperationStarted", "OperationTracker", "Outcome", "Prepared",
    "Refused", "RegistrationError", "Registry", "Unreachable", "register_emergency",
    "validate_args", "validate_timing",
]
