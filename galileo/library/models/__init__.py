# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""galileo.library.models — the library's ORM models.

The image-catalog models (``fitsFile``, ``fitsSession``, ``Mapping``, ``Masters``,
``VariableStars``) are AstroFiler's, kept under AstroFiler's names and camelCase
column names so existing AstroFiler databases open unchanged. The observatory,
pier, device-config and optical-tube records are Galileo's own and live in the
same database.
"""

from galileo.library.models.autofocus_settings import AutofocusSettingsRecord
from galileo.library.models.base import BaseModel, db
from galileo.library.models.device_config import DeviceConfigRecord
from galileo.library.models.fits_file import fitsFile
from galileo.library.models.fits_session import fitsSession
from galileo.library.models.mapping import Mapping
from galileo.library.models.horizon import HorizonPointRecord
from galileo.library.models.masters import Masters
from galileo.library.models.observatory import ObservatoryRecord, PierRecord
from galileo.library.models.optical_tube import OpticalTubeRecord
from galileo.library.models.solver_settings import SolverSettingsRecord
from galileo.library.models.variable_stars import VariableStars

__all__ = [
    "BaseModel", "db",
    "fitsFile", "fitsSession", "Mapping", "Masters", "VariableStars",
    "ObservatoryRecord", "PierRecord", "DeviceConfigRecord", "OpticalTubeRecord",
    "HorizonPointRecord", "AutofocusSettingsRecord", "SolverSettingsRecord",
]
