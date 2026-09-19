# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""ASTAP plate-solver integration for variable-star analysis (adapted from VSTarget)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from galileo.platesolve import SolveResult


async def solve_fits(
    fits_path: "Path | str",
    astap_executable: str = "",
) -> "SolveResult":
    """Plate-solve *fits_path* with ASTAP and write the WCS back to the file."""
    from galileo.platesolve import PlateSolver, SolverParams
    solver = PlateSolver(backend="astap", executable=astap_executable)
    return await solver.solve(fits_path)
