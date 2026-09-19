# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""CLI: apply calibration frames to light frames (LIB-060, LIB-130, EXT-140)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Galileo: Apply master calibration frames to a set of light frames."
    )
    parser.add_argument("light_dir", help="Directory containing light frames")
    parser.add_argument("--dark", required=True, help="Master dark frame path")
    parser.add_argument("--flat", required=True, help="Master flat frame path")
    parser.add_argument("--output", "-o", default=None, help="Output directory (default: <light_dir>/calibrated)")
    parser.add_argument("--yes", "-y", action="store_true", help="Non-interactive mode")
    args = parser.parse_args(argv)

    light_dir = Path(args.light_dir)
    output_dir = Path(args.output) if args.output else light_dir / "calibrated"

    from galileo.library.calibration import LibraryCalibrationService

    svc = LibraryCalibrationService(repo_dir=light_dir.parent)
    result = svc.calibrate(
        light_dir=light_dir,
        master_dark=Path(args.dark),
        master_flat=Path(args.flat),
        output_dir=output_dir,
    )
    print(f"Calibrated {result.calibrated_count} frame(s) → {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
