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


def fits_image_data(hdul):
    """Return ``(data, header)`` for the first HDU with 2-D+ image data.

    Handles plain, multi-extension and tile-compressed FITS. Galileo's own compressed files have an
    empty primary HDU with the image in a ``CompImageHDU``, so reading ``hdul[0].data`` would find
    nothing; astropy decompresses a tile-compressed HDU transparently when ``.data`` is read.

    Returns ``(None, hdul[0].header)`` if there is no image HDU.
    """
    for hdu in hdul:
        try:
            data = hdu.data
        except Exception:  # an HDU whose data cannot be read is not a candidate
            logger.debug("HDU has unreadable data", exc_info=True)
            continue
        if data is not None and getattr(data, "ndim", 0) >= 2:
            return data, hdu.header
    return None, hdul[0].header


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


def normalize_image_type(image_type: str | Any | None) -> str:
    """Upper-case alphanumerics only, so ``"Flat Dark"``, ``"FLAT-DARK"`` and ``"flatdark"`` compare equal."""
    if image_type is None:
        return ""
    return "".join(ch for ch in str(image_type).upper() if ch.isalnum())


def is_flat_dark_image_type(image_type: str | Any | None) -> bool:
    """True when the image type is a flat-dark (dark-flat) frame."""
    normalized = normalize_image_type(image_type)
    return "FLATDARK" in normalized or "DARKFLAT" in normalized


def is_dark_image_type(image_type: str | Any | None) -> bool:
    """True for regular dark frames, excluding flat-darks."""
    normalized = normalize_image_type(image_type)
    return "DARK" in normalized and not is_flat_dark_image_type(normalized)


def is_flat_image_type(image_type: str | Any | None) -> bool:
    """True for regular flat frames, excluding flat-darks."""
    normalized = normalize_image_type(image_type)
    return "FLAT" in normalized and not is_flat_dark_image_type(normalized)


def exposures_match(
    exposure_a: str | float | int | None,
    exposure_b: str | float | int | None,
    tolerance: float = 1e-3,
) -> bool:
    """Compare exposure values numerically with a small tolerance."""
    try:
        if exposure_a is None or exposure_b is None:
            return exposure_a == exposure_b
        return abs(float(exposure_a) - float(exposure_b)) <= tolerance
    except (TypeError, ValueError):
        return str(exposure_a) == str(exposure_b)


def session_to_calibration_criteria(session: Any) -> dict[str, Any]:
    """Master-matching criteria from a session-like object."""
    return {
        "telescope": getattr(session, "fitsSessionTelescope", None),
        "instrument": getattr(session, "fitsSessionImager", None),
        "exposure_time": getattr(session, "fitsSessionExposure", None),
        "filter_name": getattr(session, "fitsSessionFilter", None),
        "binning_x": getattr(session, "fitsSessionBinningX", None),
        "binning_y": getattr(session, "fitsSessionBinningY", None),
        "ccd_temp": getattr(session, "fitsSessionCCDTemp", None),
        "gain": getattr(session, "fitsSessionGain", None),
        "offset": getattr(session, "fitsSessionOffset", None),
    }


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
    except (ValueError, IndexError) as e:
        logger.exception(f"Error parsing DWARF_RAW folder name {folder_name}: {e}")
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
        # Any DWARF variant (DWARF, DWARF3, DWARF MINI, ...). An empty TELESCOP is allowed: the
        # caller may have recognised the card from its folder structure.
        telescop_value = hdr.get("TELESCOP", "")
        if telescop_value and not telescop_value.upper().startswith("DWARF"):
            logger.warning(f"dwarfFixHeader called for non-DWARF file (TELESCOP={telescop_value!r}): {file}")
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

    except Exception as e:
        logger.exception(f"Error in dwarfFixHeader for {file}: {e}")
        return False


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

        # Static cache for mappings to avoid repeated database queries
        if not hasattr(mapFitsHeader, '_cached_mappings'):
            mapFitsHeader._cached_mappings = None
            mapFitsHeader._cache_loaded = False

        # Load mappings from database if not cached
        if not mapFitsHeader._cache_loaded:
            try:
                mappings = list(Mapping.select())
                mapFitsHeader._cached_mappings = {}
                for mapping in mappings:
                    key = (mapping.old_value.upper(), mapping.header_field.upper())
                    mapFitsHeader._cached_mappings[key] = mapping.new_value

                mapFitsHeader._cache_loaded = True
                logger.debug(f"Loaded {len(mappings)} header mappings from database")

            except Exception as e:
                logger.exception(f"Failed to load header mappings: {e}")
                mapFitsHeader._cached_mappings = {}
                mapFitsHeader._cache_loaded = True  # Set to avoid repeated failures
                return False

        if not mapFitsHeader._cached_mappings:
            return False

        changes_made = False

        # Apply mappings to header fields
        for header_field, value in list(hdr.items()):
            if isinstance(value, str):
                key = (value.upper(), header_field.upper())
                if key in mapFitsHeader._cached_mappings:
                    new_value = mapFitsHeader._cached_mappings[key]
                    hdr[header_field] = new_value
                    logger.debug(f"Mapped {header_field} from '{value}' to '{new_value}' for {file_path}")
                    changes_made = True

        return changes_made

    except Exception as e:
        logger.exception(f"Error in mapFitsHeader for {file_path}: {e}")
        return False


def clearMappingCache() -> None:
    """Clear the mapping cache to force reload from database."""
    if hasattr(mapFitsHeader, '_cache_loaded'):
        mapFitsHeader._cache_loaded = False
        mapFitsHeader._cached_mappings = None
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
    except Exception as e:
        logger.exception(f"Error getting master calibration path: {e}")
        return os.path.join('.', 'Masters')
