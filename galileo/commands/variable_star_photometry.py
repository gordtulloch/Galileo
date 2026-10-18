# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

r"""galileo.commands.variable_star_photometry - Process variable star photometry from a session.

Pipeline:
  1) Ensure session light frames are calibrated (if not precalibrated)
  2) Create a photometric stack (registered mean)
  3) Run variable-star ensemble photometry using AAVSO VSP comparison stars

Examples:
  .venv\Scripts\python commands\galileo.commands.variable_star_photometry --session 12496 --star-name "RW AUR"
  .venv\Scripts\python commands\galileo.commands.variable_star_photometry --stacked-fits path\to\photometric_stack_*.fits --star-name "RW AUR"
"""

import argparse
import json
import logging
import os
import sys




from galileo.commands._common import get_log_path, load_config

def setup_logging(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(get_log_path(), mode='a', encoding='utf-8')],
        force=True,
    )
    logging.getLogger("peewee").setLevel(logging.WARNING)
    return logging.getLogger(__name__)


def _is_precalibrated_session(telescope: str | None, instrument: str | None) -> bool:
    telescope = telescope or ""
    instrument = instrument or ""
    return ("itelescope" in telescope.lower()) or ("seestar" in instrument.lower())


def _default_outputs(stacked_fits_path: str) -> tuple[str, str]:
    base = os.path.splitext(os.path.basename(stacked_fits_path))[0]
    out_dir = os.path.dirname(stacked_fits_path)
    return (
        os.path.join(out_dir, f"varstar_{base}.json"),
        os.path.join(out_dir, f"varstar_{base}.csv"),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Variable star photometry from a calibrated photometric stack")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--session", help="Session ID to process", default=None)
    g.add_argument("--stacked-fits", help="Path to an existing photometric stack FITS", default=None)

    parser.add_argument("--star-name", required=True, help="Target star name for resolution (e.g., 'RW AUR')")
    parser.add_argument("--band", default="V", help="Photometric band for AAVSO VSP")
    parser.add_argument("--bright", type=float, default=11.0, help="Brightest comp star magnitude")
    parser.add_argument("--dim", type=float, default=13.0, help="Dimmest comp star magnitude")
    parser.add_argument("--snr", type=float, default=20.0, help="SEP detection SNR multiplier")
    parser.add_argument("--match-arcsec", type=float, default=4.0, help="Catalog match radius in arcsec")
    parser.add_argument("--aperture", type=float, default=6.0, help="Aperture radius in pixels")
    parser.add_argument("--check-auid", default=None, help="Optional AUID to compute as check star")
    parser.add_argument("--out-json", default=None, help="Write summary JSON to this path")
    parser.add_argument("--out-csv", default=None, help="Write per-star CSV to this path")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _build_session_stack(session_id: str, logger) -> tuple[str | None, int]:
    """Calibrate (if needed) and stack a session's lights; returns (stack path, 0) or (None, exit code)."""
    from galileo.library.models import fitsSession as FitsSessionModel
    from galileo.library.core.master_manager import get_master_manager
    from galileo.library.core.utils import best_hfr_reference_path, sanitize_filesystem_name, session_light_frames
    from galileo.library.core.auto_calibration import calibrate_light_frames

    session = FitsSessionModel.get_by_id(session_id)
    if not session:
        logger.error(f"Session not found: {session_id}")
        return None, 2

    precalibrated = _is_precalibrated_session(session.fitsSessionTelescope, session.fitsSessionImager)
    # If there are no calibrated frames, calibrate first.
    if not precalibrated and not session_light_frames(session, calibrated_only=True):
        logger.info(f"Calibrating session {session_id} before photometric stack...")
        config = load_config()
        if not calibrate_light_frames(config, session_id=session_id):
            logger.error("Calibration failed")
            return None, 3

    candidates = session_light_frames(session, calibrated_only=not precalibrated)
    file_paths = [f.fitsFileName for f in candidates if f.fitsFileName and os.path.exists(f.fitsFileName)]
    if len(file_paths) < 2:
        logger.error("Not enough light frames to stack (need >= 2)")
        return None, 4

    out_dir = os.path.dirname(file_paths[0])
    date_str = str(session.fitsSessionDate) if session.fitsSessionDate else "unknown_date"
    obj = sanitize_filesystem_name(session.fitsSessionObjectName or "Unknown")
    stacked_path = os.path.join(out_dir, f"photometric_stack_{obj}_{date_str}_{session_id}.fits")

    if os.path.exists(stacked_path):
        logger.info(f"Using existing photometric stack: {stacked_path}")
        return stacked_path, 0

    logger.info(f"Creating photometric stack: {stacked_path}")

    def _progress(current, total, message):
        if message:
            logger.info(str(message))

    ok = get_master_manager()._create_light_stack_photometric_mean(
        file_paths=file_paths,
        output_path=stacked_path,
        reference_path=best_hfr_reference_path(candidates),  # prefer the best-HFR frame as the reference
        progress_callback=_progress,
        thumbnail_session_id=str(session.fitsSessionId),
    )
    if not ok or not os.path.exists(stacked_path):
        logger.error("Photometric stacking failed")
        return None, 5
    return stacked_path, 0


_CSV_FIELDS = ["auid", "ra", "dec", "vmag", "error", "x", "y", "peak", "aperture_sum", "instrumental_mag"]


def _write_results(result: dict, out_json: str, out_csv: str) -> None:
    """Write the summary JSON and the flat per-star CSV (creating their folders)."""
    import csv

    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        w.writeheader()
        for r in result.get("rows") or []:
            w.writerow({k: r.get(k) for k in _CSV_FIELDS})


def main() -> int:
    args = _build_parser().parse_args()

    logger = setup_logging(args.verbose)

    from galileo.library.core.variable_star_photometry import (
        VariableStarPhotometryOptions,
        run_variable_star_photometry,
    )

    stacked_path = args.stacked_fits
    if args.session:
        stacked_path, error_code = _build_session_stack(str(args.session), logger)
        if error_code:
            return error_code

    if not stacked_path or not os.path.exists(stacked_path):
        logger.error("Stacked FITS not found")
        return 6

    options = VariableStarPhotometryOptions(
        band=str(args.band),
        brightest_comp_mag=float(args.bright),
        dimmest_comp_mag=float(args.dim),
        source_snr=float(args.snr),
        match_radius_arcsec=float(args.match_arcsec),
        aperture_radius_pixels=float(args.aperture),
    )

    result = run_variable_star_photometry(
        stacked_path,
        star_name=str(args.star_name),
        options=options,
        check_auid=args.check_auid,
    )

    out_json = args.out_json
    out_csv = args.out_csv
    if not out_json or not out_csv:
        djson, dcsv = _default_outputs(stacked_path)
        out_json = out_json or djson
        out_csv = out_csv or dcsv

    _write_results(result, out_json, out_csv)

    logger.info(f"Target magnitude: {result.get('target_magnitude')} (band {result.get('band')})")
    logger.info(f"Chart ID: {result.get('chart_id')}")
    logger.info(f"Wrote: {out_json}")
    logger.info(f"Wrote: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
