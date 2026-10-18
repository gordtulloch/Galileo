"""
Utility functions for AstroFiler file processing.

This module contains common utility functions used throughout the application
for path normalization, string sanitization, and FITS header processing.
"""

import os
import logging
from galileo.library.config import load_config as load_library_config
from typing import Any

from ..types import FilePath

logger = logging.getLogger(__name__)


def normalize_file_path(file_path: FilePath | None) -> str | None:
    """
    Normalize file paths to use forward slashes consistently.

    Args:
        file_path: File path string that may contain backslashes

    Returns:
        Normalized path with forward slashes
    """
    if file_path:
        return str(file_path).replace('\\', '/')
    return None


def sanitize_filesystem_name(name: str | Any | None) -> str:
    """
    Sanitize a string for use in filesystem paths and filenames.

    Replaces invalid filesystem characters with underscores to match
    the existing folder creation logic in registerFitsImage.

    Args:
        name: String that may contain invalid filesystem characters

    Returns:
        Sanitized string safe for filesystem use
    """
    if not name:
        return "Unknown"

    # Convert to string and strip whitespace
    sanitized = str(name).strip()

    # Replace invalid filesystem characters with underscores
    # This matches the existing logic: .replace(" ", "_").replace("\\", "_")
    invalid_chars = [' ', '\\', '/', ':', '*', '?', '"', '<', '>', '|', '\t', '\n', '\r']

    for char in invalid_chars:
        sanitized = sanitized.replace(char, '_')

    # Remove multiple consecutive underscores
    while '__' in sanitized:
        sanitized = sanitized.replace('__', '_')

    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')

    # Ensure we don't return empty string
    if not sanitized:
        sanitized = "Unknown"

    return sanitized


def _utc_fits_timestamp() -> str:
    """Now, as a zone-less UTC ``DATE-OBS`` string."""
    from datetime import UTC, datetime
    return datetime.now(UTC).replace(tzinfo=None).strftime('%Y-%m-%dT%H:%M:%S')


def _find_dwarf_root(path_parts: list[str]) -> str | None:
    """The folder that holds a DWARF card's ``DWARF_RAW*``/``CALI_FRAME``/``DWARF_DARK`` tree, or ``None``."""
    for i, part in enumerate(path_parts):
        if part.startswith("DWARF_RAW"):
            # Check if parent directory contains required DWARF folders
            parent_path = os.sep.join(path_parts[:i])
            dwarf_raw_folders = [d for d in os.listdir(parent_path) if d.startswith("DWARF_RAW")]

            if (os.path.exists(os.path.join(parent_path, "CALI_FRAME")) and
                os.path.exists(os.path.join(parent_path, "DWARF_DARK")) and
                dwarf_raw_folders):
                return parent_path

    # Check if we're in CALI_FRAME or DWARF_DARK structure
    for i, part in enumerate(path_parts):
        if part in ["CALI_FRAME", "DWARF_DARK"]:
            parent_path = os.sep.join(path_parts[:i])
            if (os.path.exists(os.path.join(parent_path, "CALI_FRAME")) and
                os.path.exists(os.path.join(parent_path, "DWARF_DARK"))):
                return parent_path
    return None


def _fix_dwarf_raw_header(hdr: Any, folder_name: str, file: str) -> bool:
    """Fill a DWARF_RAW light frame's header from its folder name. False if the name cannot be parsed."""
    # Parse: DWARF_RAW_(INSTRUMEN)_(OBJECT)_EXP_(EXPTIME)_GAIN_(GAIN)_(DATE-OBS)
    parts = folder_name.split("_")
    if len(parts) < 8:  # Minimum expected parts
        return True
    try:
        instrument = parts[2]  # INSTRUMEN
        object_name = parts[3]  # OBJECT
        exptime = parts[5]  # EXPTIME (after EXP)
        gain = parts[7]  # GAIN (after GAIN)
        date_obs = "_".join(parts[8:])  # DATE-OBS (rest of string)

        # Update header
        hdr['INSTRUME'] = instrument
        hdr['OBJECT'] = object_name
        hdr['EXPTIME'] = float(exptime)
        hdr['GAIN'] = float(gain)

        # Add missing fields with defaults if not present
        if 'XBINNING' not in hdr:
            hdr['XBINNING'] = 1
        if 'YBINNING' not in hdr:
            hdr['YBINNING'] = 1
        if 'CCD-TEMP' not in hdr:
            hdr['CCD-TEMP'] = -10.0  # Default temperature

        # Parse and format date if needed
        if date_obs and 'DATE-OBS' not in hdr:
            # Assume date format needs to be converted to ISO format
            hdr['DATE-OBS'] = date_obs

        # Set image type to LIGHT
        hdr['IMAGETYP'] = 'LIGHT'

        logger.info(f"Fixed DWARF_RAW header for {file}: OBJECT={object_name}, INSTRUME={instrument}")
    except (ValueError, IndexError):
        logger.exception(f"Error parsing DWARF_RAW folder name {folder_name}")
        return False
    return True


# CALI_FRAME file names: bias_gain_(GAIN)_bin_(BINNING)_*.fits, flat_gain_..., and for darks
# dark_exp_(EXPTIME)_gain_(GAIN)_bin_(BINNING)_(CCD-TEMP)_*.fits.
# Per frame type: (file-name prefix, minimum "_" parts, defaults added when the header lacks them).
_DWARF_GAIN_BIN_FRAMES = {
    "bias": ("bias_gain_", 5, (('EXPTIME', 0.0), ('CCD-TEMP', -10.0))),
    "flat": ("flat_gain_", 5, (('EXPTIME', 1.0), ('CCD-TEMP', -10.0), ('FILTER', 'UNKNOWN'))),
}


def _fix_dwarf_cali_frame_header(hdr: Any, path_components: list[str], file: str) -> None:
    """Fill a CALI_FRAME master calibration header from its folder and file names."""
    cali_index = path_components.index("CALI_FRAME")
    if len(path_components) <= cali_index + 2:
        return
    frame_type = path_components[cali_index + 1]  # bias, dark, or flat
    cam_folder = path_components[cali_index + 2]   # cam_0 or cam_1

    # Set IMAGETYP and OBJECT
    hdr['IMAGETYP'] = frame_type.upper()
    hdr['OBJECT'] = f"MASTER{frame_type.upper()}"

    # Add DATE-OBS if missing (use current date as fallback)
    if 'DATE-OBS' not in hdr:
        hdr['DATE-OBS'] = _utc_fits_timestamp()

    # Set INSTRUME based on camera folder
    if cam_folder == "cam_0":
        hdr['INSTRUME'] = 'TELE'
    elif cam_folder == "cam_1":
        hdr['INSTRUME'] = 'WIDE'
    else:
        logger.warning(f"Unknown camera folder: {cam_folder}")

    # Parse filename for specific calibration parameters
    filename_base = os.path.splitext(file)[0]
    kind = frame_type.lower()

    if kind in _DWARF_GAIN_BIN_FRAMES:
        prefix, min_parts, defaults = _DWARF_GAIN_BIN_FRAMES[kind]
        parts = filename_base.split("_")
        if filename_base.startswith(prefix) and len(parts) >= min_parts:
            binning = parts[4]
            hdr['GAIN'] = float(parts[2])
            hdr['XBINNING'] = int(binning)
            hdr['YBINNING'] = int(binning)
            for key, value in defaults:
                if key not in hdr:
                    hdr[key] = value
    elif kind == "dark" and filename_base.startswith("dark_exp_"):
        parts = filename_base.split("_")
        if len(parts) >= 8:
            binning = parts[6]
            hdr['EXPTIME'] = float(parts[2])
            hdr['GAIN'] = float(parts[4])
            hdr['XBINNING'] = int(binning)
            hdr['YBINNING'] = int(binning)
            hdr['CCD-TEMP'] = float(parts[7])

    logger.debug(f"Fixed CALI_FRAME header for {file}: IMAGETYP={frame_type.upper()}, INSTRUME={hdr.get('INSTRUME')}")


def _fix_dwarf_dark_library_header(hdr: Any, file: str) -> None:
    """Fill a DWARF_DARK library file's header: tele_exp_(EXPTIME)_gain_(GAIN)_bin_(BINNING)_(OBS-DATE).fits."""
    filename_base = os.path.splitext(file)[0]
    if not filename_base.startswith("tele_exp_"):
        return
    parts = filename_base.split("_")
    if len(parts) < 7:
        return
    exptime = parts[2]
    gain = parts[4]
    binning = parts[6]
    obs_date = "_".join(parts[7:]) if len(parts) > 7 else ""

    hdr['INSTRUME'] = 'TELE'
    hdr['IMAGETYP'] = 'DARKMASTER'
    hdr['OBJECT'] = 'DARKMASTER'
    hdr['EXPTIME'] = float(exptime)
    hdr['GAIN'] = float(gain)
    hdr['XBINNING'] = int(binning)
    hdr['YBINNING'] = int(binning)

    # Add DATE-OBS if missing
    if 'DATE-OBS' not in hdr:
        hdr['DATE-OBS'] = obs_date or _utc_fits_timestamp()

    logger.info(f"Fixed DWARF_DARK header for {file}: EXPTIME={exptime}, GAIN={gain}")


def dwarfFixHeader(hdr: Any, root: str, file: str) -> Any | bool:
    """
    Fix FITS headers for DWARF telescope files based on folder structure and filenames.

    Args:
        hdr: FITS header object
        root: Root directory path containing the file
        file: Filename

    Returns:
        Modified header object or False if error
    """
    try:
        # Check if this is a DWARF telescope file
        telescop_value = hdr.get("TELESCOP", "")
        if not telescop_value or telescop_value.upper() != "DWARF":
            logger.warning(f"dwarfFixHeader called for non-DWARF file: {file}")
            return False

        # Skip failed images
        if file.startswith("failed_"):
            logger.info(f"Ignoring failed DWARF image: {file}")
            return False

        dwarf_root = _find_dwarf_root(os.path.normpath(root).split(os.sep))
        if not dwarf_root:
            logger.error(f"Dwarf folder structure not recognized for file: {file}")
            return False

        # Determine file type based on path
        path_components = os.path.relpath(root, dwarf_root).split(os.sep)

        if path_components[0].startswith("DWARF_RAW"):
            if not _fix_dwarf_raw_header(hdr, path_components[0], file):
                return False
        elif "CALI_FRAME" in path_components:
            _fix_dwarf_cali_frame_header(hdr, path_components, file)
        elif "DWARF_DARK" in path_components:
            _fix_dwarf_dark_library_header(hdr, file)
        else:
            logger.info(f"Ignoring DWARF file in unrecognized folder structure: {file}")
            return hdr  # Return unchanged header

        return hdr

    except Exception:
        logger.exception(f"Error in dwarfFixHeader for {file}")
        return False


# (old value, header field) -> new value, loaded lazily from the Mapping table; None = not loaded yet.
_mapping_cache: dict[tuple[str, str], str] | None = None


def mapFitsHeader(hdr: Any, file_path: str) -> bool:
    """
    Apply mappings from the Mapping table to FITS header fields.
    Uses static caching to avoid repeated database queries.

    Args:
        hdr: FITS header object to modify
        file_path: Full path to the FITS file (for logging)

    Returns:
        bool: True if any header changes were made, False otherwise
    """
    try:
        from ..models import Mapping

        global _mapping_cache

        # Load mappings from database if not cached (avoids a query per file)
        if _mapping_cache is None:
            try:
                mappings = list(Mapping.select())
                _mapping_cache = {}
                for mapping in mappings:
                    if mapping.current and mapping.replace:  # a blank side is "no mapping" (see Mapping.get_mapped_value)
                        _mapping_cache[(mapping.current.upper(), mapping.card.upper())] = mapping.replace

                logger.debug(f"Loaded {len(mappings)} header mappings from database")

            except Exception:
                logger.exception("Failed to load header mappings")
                _mapping_cache = {}  # cached as empty to avoid repeated failures
                return False

        if not _mapping_cache:
            return False

        changes_made = False

        # Apply mappings to header fields
        for header_field, value in list(hdr.items()):
            if isinstance(value, str):
                key = (value.upper(), header_field.upper())
                if key in _mapping_cache:
                    new_value = _mapping_cache[key]
                    hdr[header_field] = new_value
                    logger.debug(f"Mapped {header_field} from '{value}' to '{new_value}' for {file_path}")
                    changes_made = True

        return changes_made

    except Exception:
        logger.exception(f"Error in mapFitsHeader for {file_path}")
        return False


def session_light_frames(session, *, calibrated_only: bool) -> list:
    """The session's live light frames (only the calibrated ones when *calibrated_only*)."""
    from galileo.library.models import fitsFile as FitsFileModel

    condition = (
        (FitsFileModel.fitsFileSession == session.fitsSessionId)
        & (FitsFileModel.fitsFileSoftDelete == False)
        & (FitsFileModel.fitsFileType.in_(["LIGHT", "LIGHT FRAME"]))
    )
    if calibrated_only:
        condition = condition & (FitsFileModel.fitsFileCalibrated == 1)
    return list(FitsFileModel.select().where(condition))


def best_hfr_reference_path(frames) -> str | None:
    """Path of the frame with the smallest average HFR (``fitsFileAvgHFRArcsec``) - the registration reference.

    Frames whose file is missing or that have no usable HFR are ignored; None when none qualifies.
    """
    best_path = None
    best_hfr = None
    for f in frames:
        p = getattr(f, 'fitsFileName', None)
        if not p or not os.path.exists(p):
            continue
        hfr = getattr(f, 'fitsFileAvgHFRArcsec', None)
        if hfr is None:
            continue
        try:
            hfr_val = float(hfr)
        except Exception:
            logger.debug("Skipping unusable HFR value %r for %s", hfr, p)
            continue
        if best_hfr is None or hfr_val < best_hfr:
            best_hfr = hfr_val
            best_path = p
    return best_path


def clearMappingCache() -> None:
    """Clear the mapping cache to force reload from database."""
    global _mapping_cache
    if _mapping_cache is not None:
        _mapping_cache = None
        logger.info("Header mapping cache cleared")


def get_master_calibration_path() -> str | None:
    """
    Get the master calibration frames path from configuration.

    Returns:
        str: Path to master calibration frames directory
    """
    try:
        config = load_library_config()
        repo_folder = config.get('DEFAULT', 'repo', fallback='.')
        return os.path.join(repo_folder, 'Masters')
    except Exception:
        logger.exception("Error getting master calibration path")
        return os.path.join('.', 'Masters')
