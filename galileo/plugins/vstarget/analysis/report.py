# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""AAVSO WebObs Extended-format report generation (VST-AN-050)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from galileo.plugins.vstarget.analysis.photometry import PhotometryResult

_REPORT_HEADER = "#TYPE=EXTENDED\n#OBSCODE=\n#SOFTWARE=Galileo\n#DELIM=,\n#DATE=JD\n#OBSTYPE=CCD\n"


def generate_aavso_report(measurements: list[PhotometryResult]) -> str:
    """Return a WebObs Extended-format report string (VST-AN-050)."""
    lines = [_REPORT_HEADER]
    for m in measurements:
        trans = "YES" if m.is_transformed else "NO"
        line = (
            f"{m.target},{m.jd:.5f},{m.magnitude:.4f},"
            f"{m.uncertainty:.4f},{m.filter_band},,"
            f"{m.comp_star},{m.check_star},,ENSEMBLE,,"
            f"na,,,,TRANS={trans}"
        )
        lines.append(line)
    return "\n".join(lines)


def save_aavso_report(measurements: list[PhotometryResult], output_path: Path | str) -> None:
    Path(output_path).write_text(generate_aavso_report(measurements), encoding="utf-8")
