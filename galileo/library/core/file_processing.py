# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""
Core file processing module for AstroFiler.

This module handles FITS file registration, header processing, hash calculation,
compression, and database operations for importing astronomical images.
"""

import os
from pathlib import Path
import logging
import uuid
from galileo.library.config import load_config as load_library_config
import shutil
from datetime import datetime
from math import cos, sin
from typing import Any, Literal
from astropy.io import fits
from peewee import IntegrityError

from .utils import (
    normalize_file_path,
    sanitize_filesystem_name,
    dwarfFixHeader,
    mapFitsHeader,
    get_master_calibration_path,
    is_dark_image_type,
    is_flat_dark_image_type,
    is_flat_image_type,
    normalize_image_type,
)
from ..types import FilePath
from ..exceptions import (
    FileProcessingError, FitsHeaderError, DatabaseError,
    ValidationError
)
from .file_formats import get_file_format_processor
from .services.file_hash_calculator import get_file_hash_calculator
from .compress_files import get_fits_compressor

logger = logging.getLogger(__name__)


class FileProcessor:
    """
    Handles FITS file processing operations including registration and database operations.
    """

    def __init__(self) -> None:
        """Initialize FileProcessor with configuration and services."""
        config = load_library_config()
        self.sourceFolder: str = config.get('DEFAULT', 'source', fallback='.')
        self.repoFolder: str = config.get('DEFAULT', 'repo', fallback='.')

        # Initialize services following Dependency Inversion Principle
        self.format_processor = get_file_format_processor()
        self.hash_calculator = get_file_hash_calculator()
        self.compressor = get_fits_compressor()

    def calculateFileHash(self, filePath: FilePath) -> str | None:
        """
        Calculate SHA-256 hash of a file for duplicate detection.

        Uses the dedicated FileHashCalculator service following Single Responsibility Principle.

        Args:
            filePath: Path to the file

        Returns:
            SHA-256 hash hex string, or None if error

        Raises:
            FileProcessingError: If file cannot be read or hash calculation fails
        """
        return self.hash_calculator.calculate_sha256(filePath)

    def registerMasters(
        self,
        progress_callback=None,
        source_folder: str | None = None,
        moveFiles: bool = False,
        destination_folder: str | None = None,
        precount: bool = False,
        recursive: bool = True,
    ) -> list[str]:
        """Scan a folder for existing master calibration FITS files and register them.

        Detection is based on FITS header `IMAGETYP` containing 'MASTER' and one of
        'DARK'/'FLAT'/'BIAS' (case-insensitive).

        Args:
            progress_callback: Optional callback(current, total, filename) -> bool.
                If it returns False, scanning stops.
            source_folder: Folder to scan; defaults to configured sourceFolder.
            recursive: Also scan sub-folders (default); False looks only at *source_folder* itself.

        Returns:
            List of registered master IDs.
        """
        scan_folder = source_folder or self.sourceFolder
        master_ids: list[str] = []

        logger.info(f"registerMasters: scanning folder: {scan_folder}")

        dest_root = self._master_destination_root(moveFiles, destination_folder)
        total_files = self._count_fits_files(scan_folder) if precount else 0

        current_file = 0
        for root, _dirs, files in os.walk(scan_folder):
            if not recursive:
                _dirs[:] = []
            for file in files:
                file_path = os.path.join(root, file)
                # Allow externally compressed FITS (e.g. .fits.gz / .fits.zip) by
                # passing through the format processor first.
                if not (self.compressor.is_fits_file(file_path) or self.format_processor.can_process(file_path)):
                    continue

                current_file += 1
                if not self._master_scan_should_continue(progress_callback, current_file, total_files, file_path):
                    return master_ids

                try:
                    master_id = self._register_master_candidate(file_path, moveFiles, dest_root)
                except Exception as e:
                    logger.debug(f"Skipping master registration for {file_path}: {e}")
                    continue
                if master_id:
                    master_ids.append(master_id)

        logger.info(f"registerMasters: completed. Registered/updated {len(master_ids)} masters")
        return master_ids

    @staticmethod
    def _master_destination_root(moveFiles: bool, destination_folder: str | None) -> str | None:
        """The folder masters are moved into (created if needed), or None when they stay where they are."""
        dest_root = destination_folder
        if moveFiles and not dest_root:
            dest_root = get_master_calibration_path()
        if moveFiles and dest_root:
            try:
                os.makedirs(dest_root, exist_ok=True)
            except Exception as e:
                logger.warning(f"registerMasters: could not create destination folder {dest_root}: {e}")
                return None
        return dest_root

    def _count_fits_files(self, scan_folder: str) -> int:
        """Optional pre-count for determinate progress; can be slow on large folders."""
        return sum(
            1
            for root, _dirs, files in os.walk(scan_folder)
            for file in files
            if self.compressor.is_fits_file(os.path.join(root, file))
        )

    @staticmethod
    def _master_scan_should_continue(progress_callback, current_file: int, total_files: int, file_path: str) -> bool:
        """Report progress; False when the callback asked to stop (callback errors never stop the scan)."""
        if not progress_callback:
            return True
        try:
            return bool(progress_callback(current_file, total_files, file_path))
        except Exception:
            logger.debug("progress_callback raised for %s", file_path, exc_info=True)
            return True

    def _register_master_candidate(self, file_path: str, moveFiles: bool, dest_root: str | None) -> str | None:
        """Register *file_path* if its header says it is a master dark/flat/bias; return its master id, else None."""
        # Cheap pre-check: astropy reads .fits/.gz/.fz headers directly, so non-masters
        # are rejected without decompressing or extracting anything.
        try:
            pre_imagetyp = str(fits.getheader(file_path, 0).get('IMAGETYP', '')).upper()
            if 'MASTER' not in pre_imagetyp or not any(
                token in pre_imagetyp for token in ('DARK', 'FLAT', 'BIAS')
            ):
                return None
        except Exception:
            pass  # not directly readable (e.g. zip/xisf): fall through to full processing

        candidate_path = file_path
        cleanup_source_path = None
        if self.format_processor.can_process(candidate_path):
            candidate_path = self.format_processor.process_file(candidate_path)
            # For externally compressed FITS (e.g. .fits.gz), remove the source
            # archive only after successful registration.
            if str(file_path).lower().endswith('.gz') and candidate_path != file_path:
                cleanup_source_path = file_path

        # Read only the primary header; master detection should not require data.
        imagetyp = str(fits.getheader(candidate_path, 0).get('IMAGETYP', '')).upper()
        if 'MASTER' not in imagetyp or not any(token in imagetyp for token in ('DARK', 'FLAT', 'BIAS')):
            return None

        final_path = candidate_path
        if moveFiles and dest_root:
            final_path = self._move_master_into(final_path, file_path, dest_root)

        # Compress master frames if enabled (same policy as normal imports)
        try:
            compressed_path = self.compressor.process_file_for_compression(final_path)
            if compressed_path:
                final_path = compressed_path
        except Exception as e:
            logger.warning(f"registerMasters: compression processing failed for {final_path}: {e}")

        master_id = self._register_master_file(final_path)
        if master_id and cleanup_source_path and os.path.exists(cleanup_source_path):
            try:
                os.remove(cleanup_source_path)
                logger.info(f"registerMasters: removed source gzip file after successful import: {cleanup_source_path}")
            except Exception as e:
                logger.warning(f"registerMasters: failed to remove source gzip file {cleanup_source_path}: {e}")
        return master_id

    @staticmethod
    def _move_master_into(final_path: str, file_path: str, dest_root: str) -> str:
        """Move *final_path* into *dest_root* (``_1``, ``_2``... on a name clash); returns where it ended up."""
        try:
            base_name = os.path.basename(file_path)
            # Preserve multi-suffix names like .fits.fz
            suffix = ''.join(Path(base_name).suffixes)
            stem = base_name[:-len(suffix)] if suffix else base_name

            candidate = os.path.join(dest_root, base_name)
            if os.path.normcase(os.path.normpath(candidate)) != os.path.normcase(os.path.normpath(file_path)):
                i = 1
                while os.path.exists(candidate):
                    candidate = os.path.join(dest_root, f"{stem}_{i}{suffix}")
                    i += 1
                shutil.move(final_path, candidate)
                return candidate
        except Exception as e:
            logger.warning(f"registerMasters: failed to move {final_path} into {dest_root}: {e}")
        return final_path

    def _is_master_file(self, file_path: str) -> bool:
        """
        Check if a file is a master calibration frame that should be handled specially.

        Args:
            file_path: Full path to the file

        Returns:
            True if this is a master file
        """
        # Normalize path separators
        normalized_path = os.path.normpath(file_path)
        path_parts = normalized_path.split(os.sep)

        # Check if file is in a Masters directory
        if 'Masters' in path_parts:
            return True

        # Check for master-related naming patterns
        filename = os.path.basename(file_path).lower()
        master_patterns = [
            'master',
            'masterbias',
            'masterdark',
            'masterflat',
            'master_bias',
            'master_dark',
            'master_flat',
            'bias_master',
            'dark_master',
            'flat_master'
        ]

        return any(pattern in filename for pattern in master_patterns)

    def _register_master_file(self, file_path):
        """
        Register a master calibration frame in the Masters table.

        Args:
            file_path (str): Full path to the master file

        Returns:
            str: Master ID if successful

        Raises:
            FileProcessingError: If file cannot be processed
            ValidationError: If master type cannot be determined
            DatabaseError: If database operations fail
        """
        try:
            # Import here to avoid circular imports
            try:
                from ..models import Masters
            except ImportError as exc:
                raise DatabaseError(
                    "Masters table not available yet. Run migrations to create Masters table.",
                    error_code="MASTERS_TABLE_MISSING"
                ) from exc

            # Open the FITS file to read header
            try:
                with fits.open(file_path, mode='readonly') as hdul:
                    hdr = hdul[0].header
            except OSError as e:
                raise FileProcessingError(
                    f"Cannot read FITS file: {e}",
                    file_path=file_path,
                    error_code="FITS_READ_ERROR"
                ) from e
            except Exception as e:
                raise FitsHeaderError(
                    f"Error reading FITS header: {e}",
                    file_path=file_path,
                    error_code="FITS_HEADER_ERROR"
                ) from e

            # Determine master type from filename or header
            master_type = self._determine_master_type(file_path, hdr)
            if not master_type:
                raise ValidationError(
                    f"Could not determine master type for file {file_path}",
                    field="master_type",
                    file_path=file_path
                )

            # Extract session data from header
            session_data = {
                'telescope': hdr.get('TELESCOP', 'Unknown'),
                'instrument': hdr.get('INSTRUME', 'Unknown'),
                'binning_x': str(hdr.get('XBINNING', '1')),
                'binning_y': str(hdr.get('YBINNING', '1')),
                'ccd_temp': str(hdr.get('CCD-TEMP', '')),
                'gain': str(hdr.get('GAIN', '')),
                'offset': str(hdr.get('OFFSET', '')),
                'session_id': None  # No source session for existing masters
            }

            # Add type-specific data
            if master_type in ('dark', 'flatdark'):
                session_data['exposure_time'] = str(hdr.get('EXPTIME', hdr.get('EXPOSURE', '')))
            elif master_type == 'flat':
                session_data['filter_name'] = hdr.get('FILTER', '')

            # Get file count from header if available
            file_count = hdr.get('NCOMBINE', hdr.get('NIMAGES', 0))
            if isinstance(file_count, str):
                try:
                    file_count = int(file_count)
                except ValueError:
                    file_count = 0

            # Check if this master already exists
            existing_master = Masters.find_matching_master(
                session_data['telescope'],
                session_data['instrument'],
                master_type,
                **{k: v for k, v in session_data.items()
                   if k not in ['telescope', 'instrument', 'session_id'] and v}
            )

            if existing_master:
                logger.info(f"Master {master_type} already exists in database: {existing_master.master_id}")
                # Update path if different
                if existing_master.master_path != file_path:
                    existing_master.master_path = file_path
                    existing_master.save()
                    logger.info(f"Updated master path: {file_path}")
                return existing_master.master_id

            # Create new master record
            try:
                master = Masters.create_master_record(
                    master_path=file_path,
                    session_data=session_data,
                    cal_type=master_type,
                    file_count=file_count
                )
            except Exception as e:
                raise DatabaseError(
                    f"Failed to create master record: {e}",
                    file_path=file_path,
                    error_code="MASTER_CREATE_ERROR"
                ) from e

            # Validate the file
            try:
                if master.validate_and_mark():
                    logger.info(f"Successfully registered master {master_type}: {master.master_id}")
                    return master.master_id
                else:
                    logger.warning(f"Master file validation failed: {file_path}")
                    return master.master_id  # Still return ID even if validation failed
            except Exception:
                logger.exception("Master validation error")
                return master.master_id  # Return ID anyway for partial success

        except (FileProcessingError, ValidationError, DatabaseError, FitsHeaderError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            raise FileProcessingError(
                f"Unexpected error registering master file: {e}",
                file_path=file_path,
                error_code="MASTER_REGISTER_ERROR"
            ) from e

    def _determine_master_type(self, file_path, hdr):
        """
        Determine the type of master calibration frame.

        Args:
            file_path (str): Path to the file
            hdr: FITS header

        Returns:
            str or None: 'bias', 'dark', 'flat', 'flatdark', or None if undetermined
        """
        # Check filename for master type indicators (punctuation-insensitive, so
        # "Master_Flat-Dark" and "masterflatdark" match alike)
        filename = normalize_image_type(os.path.basename(file_path))

        if any(pattern in filename for pattern in ['BIAS', 'MASTERBIAS']):
            return 'bias'
        elif 'FLATDARK' in filename or 'DARKFLAT' in filename:
            return 'flatdark'
        elif any(pattern in filename for pattern in ['DARK', 'MASTERDARK']):
            return 'dark'
        elif any(pattern in filename for pattern in ['FLAT', 'MASTERFLAT']):
            return 'flat'

        # Check FITS header
        imagetyp = hdr.get('IMAGETYP', '').upper()
        if 'BIAS' in imagetyp:
            return 'bias'
        elif is_flat_dark_image_type(imagetyp):
            return 'flatdark'
        elif is_dark_image_type(imagetyp):
            return 'dark'
        elif is_flat_image_type(imagetyp):
            return 'flat'

        # Check OBJECT field for master indicators
        object_name = normalize_image_type(hdr.get('OBJECT', ''))
        if 'BIAS' in object_name:
            return 'bias'
        elif 'FLATDARK' in object_name or 'DARKFLAT' in object_name:
            return 'flatdark'
        elif 'DARK' in object_name:
            return 'dark'
        elif 'FLAT' in object_name:
            return 'flat'

        return None

    def submitFileToDB(self, fileName: str, hdr: Any, fileHash: str | None = None) -> str | None:
        """
        Submit FITS file to database after processing.

        Args:
            fileName: Full path to the FITS file
            hdr: FITS header object
            fileHash: Pre-calculated file hash

        Returns:
            File ID if successful, None if failed

        Raises:
            DatabaseError: If database operations fail
            ValidationError: If required header fields are missing
            FileProcessingError: If file processing fails
        """
        try:
            from ..models import fitsFile as FitsFileModel
        except ImportError as e:
            raise DatabaseError(
                f"Cannot import database models: {e}",
                error_code="MODEL_IMPORT_ERROR"
            ) from e

        try:
            # Calculate hash if not provided
            if fileHash is None:
                fileHash = self.calculateFileHash(fileName)
                if fileHash is None:
                    raise FileProcessingError(
                        "Could not calculate file hash",
                        file_path=fileName,
                        error_code="HASH_CALCULATION_FAILED"
                    )

            # Check for duplicate files by hash
            try:
                existing_file = FitsFileModel.get(FitsFileModel.fitsFileHash == fileHash)
                logger.warning(f"Duplicate file detected: {fileName} matches {existing_file.fitsFileName}")
                return existing_file.fitsFileId
            except FitsFileModel.DoesNotExist:
                pass  # File is unique, proceed with registration

            # Validate required header values
            date_obs = hdr.get("DATE-OBS")
            if not date_obs:
                raise ValidationError(
                    "Missing required DATE-OBS field in FITS header",
                    field="DATE-OBS",
                    file_path=fileName
                )

            image_type = hdr.get("IMAGETYP")
            if not image_type:
                raise ValidationError(
                    "Missing required IMAGETYP field in FITS header",
                    field="IMAGETYP",
                    file_path=fileName
                )

            # Get exposure time
            exposure = hdr.get("EXPTIME", hdr.get("EXPOSURE"))
            if exposure is None:
                raise ValidationError(
                    "Missing required EXPTIME/EXPOSURE field in FITS header",
                    field="EXPTIME",
                    file_path=fileName
                )

            # Get telescope and instrument
            telescope = hdr.get("TELESCOP", "Unknown")
            instrument = hdr.get("INSTRUME", "Unknown")

            # Check if telescope is iTelescope or instrument is SeeStar - mark as calibrated
            is_precalibrated = False
            if (telescope and "itelescope" in telescope.lower()) or \
               (instrument and "seestar" in instrument.lower()):
                is_precalibrated = True
                if telescope and "itelescope" in telescope.lower():
                    logger.debug(f"Marking file as pre-calibrated from iTelescope: {telescope}")
                else:
                    logger.debug(f"Marking file as pre-calibrated from SeeStar instrument: {instrument}")

            # Create new file record
            if hdr.get("OBJECT"):
                newfile = FitsFileModel.create(
                    fitsFileId=str(uuid.uuid4()),
                    fitsFileName=normalize_file_path(fileName),
                    fitsFileDate=date_obs,
                    fitsFileType=image_type.upper(),
                    fitsFileObject=hdr["OBJECT"],
                    fitsFileExpTime=exposure,
                    fitsFileXBinning=hdr.get("XBINNING", 1),
                    fitsFileYBinning=hdr.get("YBINNING", 1),
                    fitsFileCCDTemp=hdr.get("CCD-TEMP", 0),
                    fitsFileTelescop=telescope,
                    fitsFileInstrument=instrument,
                    fitsFileFilter=hdr.get("FILTER", None),
                    fitsFileHash=fileHash,
                    fitsFileSession=None,
                    fitsFileCalibrated=1 if is_precalibrated else 0
                )
            else:
                newfile = FitsFileModel.create(
                    fitsFileId=str(uuid.uuid4()),
                    fitsFileName=normalize_file_path(fileName),
                    fitsFileDate=date_obs,
                    fitsFileType=image_type.upper(),
                    fitsFileObject=image_type,  # Use image type as object for calibration frames
                    fitsFileExpTime=exposure,
                    fitsFileXBinning=hdr.get("XBINNING", 1),
                    fitsFileYBinning=hdr.get("YBINNING", 1),
                    fitsFileCCDTemp=hdr.get("CCD-TEMP", 0),
                    fitsFileTelescop=telescope,
                    fitsFileInstrument=instrument,
                    fitsFileFilter=hdr.get("FILTER", None),
                    fitsFileHash=fileHash,
                    fitsFileSession=None,
                    fitsFileCalibrated=1 if is_precalibrated else 0
                )

            logger.info(f"Successfully registered FITS file: {newfile.fitsFileId}")
            return newfile.fitsFileId

        except IntegrityError as e:
            raise DatabaseError(
                f"Database integrity constraint violated: {e}",
                file_path=fileName,
                error_code="DB_INTEGRITY_ERROR"
            ) from e
        except (ValidationError, FileProcessingError, DatabaseError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            raise DatabaseError(
                f"Unexpected database error: {e}",
                file_path=fileName,
                error_code="DB_UNEXPECTED_ERROR"
            ) from e

    def registerFitsImage(self, root: str, file: str, moveFiles: bool) -> str | Literal[False]:
        """
        Register a FITS image file, process headers, and move to repository structure.

        Args:
            root: Directory containing the file
            file: Filename
            moveFiles: Whether to move files to repository structure

        Returns:
            File ID if successful, False if failed

        Raises:
            FileProcessingError: If file processing fails
            ValidationError: If file validation fails
            FitsHeaderError: If FITS header processing fails
            DatabaseError: If database operations fail
        """
        try:
            return self._register_fits_image_internal(root, file, moveFiles)
        except (FileProcessingError, ValidationError, FitsHeaderError, DatabaseError):
            logger.exception(f"Error processing {os.path.join(root, file)}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error processing {os.path.join(root, file)}")
            raise FileProcessingError(
                f"Unexpected error during FITS registration: {e}",
                file_path=os.path.join(root, file),
                error_code="UNEXPECTED_REGISTRATION_ERROR"
            ) from e

    def _register_fits_image_internal(self, root: str, file: str, moveFiles: bool) -> str | Literal[False]:
        """Internal implementation of FITS image registration with proper error handling."""
        # Read configuration
        config = load_library_config()
        save_modified = config.getboolean('DEFAULT', 'save_modified_headers', fallback=False)

        prepared = self._prepare_input_file(root, file)
        if prepared is None:
            return False
        root, file, cleanup_source_path = prepared

        # Check if this is a master calibration frame
        full_file_path = os.path.join(root, file)
        if self._is_master_file(full_file_path):
            logger.info(f"Detected master calibration frame: {file}")
            # Register in Masters table instead of regular file table
            return self._register_master_file(full_file_path)

        hdr = self._read_fits_header(root, file)
        hdr, header_modified, exposure, fitsDate = self._validate_and_normalise_header(hdr, root, file)
        newName, wcs_added = self._frame_filename(hdr, exposure, fitsDate, root, file)
        header_modified = header_modified or wcs_added

        # Save modified header if required
        if header_modified and save_modified:
            self._save_modified_header(hdr, root, file)

        # Process file for compression if enabled and appropriate
        current_file_path = os.path.join(root, file)
        current_file_path = self._compress_if_enabled(current_file_path)

        # If requested, move/rename the file into the repository structure.
        # This is required for the Images view "Load New" workflow.
        if moveFiles:
            current_file_path = self._move_into_repository(current_file_path, hdr, newName)

        # Submit file to database (use the potentially compressed file path)
        fileHash = self.calculateFileHash(current_file_path)
        newFitsFileId = self.submitFileToDB(current_file_path, hdr, fileHash)

        # Cleanup source gzip only after successful DB registration
        if newFitsFileId and cleanup_source_path and os.path.exists(cleanup_source_path):
            try:
                os.remove(cleanup_source_path)
                logger.info(f"Removed source gzip file after successful import: {cleanup_source_path}")
            except Exception as e:
                logger.warning(f"Failed to remove source gzip file {cleanup_source_path}: {e}")

        return newFitsFileId or False

    def _prepare_input_file(self, root: str, file: str) -> tuple[str, str, str | None] | None:
        """Run the file through the format processor; ``None`` if it is not a file we import.

        Returns ``(root, file, cleanup_source_path)`` for the (possibly converted) FITS file. When an external
        gzip archive was expanded, ``cleanup_source_path`` is the archive to delete once the import succeeds.
        """
        _, file_extension = os.path.splitext(os.path.join(root, file))
        original_input_path = os.path.join(root, file)
        cleanup_source_path = None

        # Process files through the FileFormatProcessor following Open/Closed Principle
        if self.format_processor.can_process(original_input_path):
            processed_file_path = self.format_processor.process_file(original_input_path)

            # If we expanded an external gzip archive, delete it only after the import succeeds (DB record created).
            if str(original_input_path).lower().endswith('.gz') and processed_file_path != original_input_path:
                cleanup_source_path = original_input_path

            # Update root and file to point to processed file
            root = os.path.dirname(processed_file_path)
            file = os.path.basename(processed_file_path)
            logger.info(f"Successfully processed file: {processed_file_path}")
        elif "fit" not in file_extension.lower():
            # No handler available and not a FITS file directly
            logger.debug(f"Ignoring unsupported file {os.path.join(root, file)}")
            return None
        return root, file, cleanup_source_path

    @staticmethod
    def _read_fits_header(root: str, file: str):
        """Read the primary header, closing the file straight away."""
        try:
            hdul = fits.open(os.path.join(root, file), mode='readonly')
            hdr = hdul[0].header
            hdul.close()
        except OSError as e:
            raise FileProcessingError(
                f"Cannot read FITS file: {e}",
                file_path=os.path.join(root, file),
                error_code="FITS_FILE_READ_ERROR"
            ) from e
        except Exception as e:
            raise FitsHeaderError(
                f"Error reading FITS header: {e}",
                file_path=os.path.join(root, file),
                error_code="FITS_HEADER_READ_ERROR"
            ) from e
        return hdr

    @staticmethod
    def _validate_and_normalise_header(hdr, root: str, file: str):
        """Apply vendor fixes and header mappings, validate the required fields and tidy calibration-frame headers.

        Returns ``(hdr, header_modified, exposure, fitsDate)`` where ``fitsDate`` is ``DATE-OBS`` as ``YYYYMMDDhhmmss``.
        """
        path = os.path.join(root, file)

        # Special handling for vendors with incomplete headers
        header_modified = False
        telescop_value = hdr.get("TELESCOP", "")
        # Any DWARF variant (Dwarf Mini, DWARF 3, DWARF II, ...), by TELESCOP prefix or, when the
        # header names no frame type, by the DWARF_RAW folder structure
        is_dwarf = (telescop_value and telescop_value.upper().startswith("DWARF")) or (
            not (hdr.get("IMAGETYP") or hdr.get("FRAME")) and "DWARF_RAW" in root
        )
        if is_dwarf:
            modified_hdr = dwarfFixHeader(hdr, root, file)
            if not modified_hdr:
                raise FitsHeaderError(
                    "Error fixing DWARF header",
                    file_path=path,
                    error_code="DWARF_HEADER_FIX_FAILED"
                )
            hdr = modified_hdr
            header_modified = True

        # Apply FITS header mappings from the Mapping table
        if mapFitsHeader(hdr, path):
            header_modified = True

        # Validate required header fields
        if not (hdr.get("IMAGETYP") or hdr.get("FRAME")):
            raise ValidationError(
                "Missing required IMAGETYP or FRAME field in FITS header",
                field="IMAGETYP",
                file_path=path
            )

        # Fix header field variations
        if hdr.get("FRAME") and not hdr.get("IMAGETYP"):
            hdr["IMAGETYP"] = hdr["FRAME"]
            header_modified = True

        # Get exposure time
        exposure = hdr.get("EXPTIME", hdr.get("EXPOSURE"))
        if exposure is None:
            raise ValidationError(
                "Missing required EXPTIME/EXPOSURE field in FITS header",
                field="EXPTIME",
                file_path=path
            )

        # Fix calibration frames where OBJECT is set to an object rather than the frame type
        image_type = hdr["IMAGETYP"]
        if is_flat_dark_image_type(image_type):
            hdr["OBJECT"] = "FlatDark"
            header_modified = True
        elif is_dark_image_type(image_type):
            hdr["OBJECT"] = "Dark"
            header_modified = True
        elif is_flat_image_type(image_type):
            hdr["OBJECT"] = "Flat"
            header_modified = True
        elif "BIAS" in image_type.upper():
            hdr["OBJECT"] = "Bias"
            header_modified = True

        # Validate date field
        date_obs = hdr.get("DATE-OBS")
        if not date_obs:
            raise ValidationError(
                "Missing required DATE-OBS field in FITS header",
                field="DATE-OBS",
                file_path=path
            )

        try:
            datestr = date_obs.replace("T", " ")
            datestr = datestr[0:datestr.find('.')] if '.' in datestr else datestr
            dateobj = datetime.strptime(datestr, '%Y-%m-%d %H:%M:%S')  # noqa: DTZ007 -- calendar date, no zone
            fitsDate = dateobj.strftime("%Y%m%d%H%M%S")
        except ValueError as exc:
            raise ValidationError(
                f"Invalid date format in DATE-OBS field: {date_obs}",
                field="DATE-OBS",
                file_path=path
            ) from exc

        return hdr, header_modified, exposure, fitsDate

    @staticmethod
    def _add_cd_matrix_from_cdelt(hdr) -> bool:
        """Derive the CD rotation matrix from CDELT1/2 + CROTA2 when a light frame has no CD1_1. True if added."""
        if "CD1_1" in hdr or not all(field in hdr for field in ["CDELT1", "CDELT2", "CROTA2"]):
            return False
        fitsCDELT1 = float(hdr["CDELT1"])
        fitsCDELT2 = float(hdr["CDELT2"])
        fitsCROTA2 = float(hdr["CROTA2"])
        hdr.append(('CD1_1', str(fitsCDELT1 * cos(fitsCROTA2)), 'Rotation Matrix'), end=True)
        hdr.append(('CD1_2', str(-fitsCDELT2 * sin(fitsCROTA2)), 'Rotation Matrix'), end=True)
        hdr.append(('CD2_1', str(fitsCDELT1 * sin(fitsCROTA2)), 'Rotation Matrix'), end=True)
        hdr.append(('CD2_2', str(fitsCDELT2 * cos(fitsCROTA2)), 'Rotation Matrix'), end=True)
        return True

    def _frame_filename(self, hdr, exposure, fitsDate: str, root: str, file: str) -> tuple[str, bool]:
        """The repository file name for this frame, plus whether the WCS matrix was added to *hdr*."""
        path = os.path.join(root, file)
        telescope = hdr.get("TELESCOP", "Unknown")
        instrument = sanitize_filesystem_name(hdr.get("INSTRUME", "Unknown"))
        scope = sanitize_filesystem_name(telescope)
        xbin, ybin, temp = hdr.get("XBINNING", 1), hdr.get("YBINNING", 1), hdr.get("CCD-TEMP", 0)
        imagetyp = hdr["IMAGETYP"].upper()
        wcs_added = False
        newName = None

        if "LIGHT" in imagetyp:
            # Handle WCS transformation for light frames
            wcs_added = self._add_cd_matrix_from_cdelt(hdr)
            if not hdr.get("OBJECT"):
                raise ValidationError(
                    "Missing or invalid object name in header for light frame",
                    field="OBJECT",
                    file_path=path
                )
            filter_name = hdr.get("FILTER", "OSC")
            newName = "{}-{}-{}-{}-{}-{}s-{}x{}-t{}.fits".format(
                sanitize_filesystem_name(hdr["OBJECT"]), scope, instrument, sanitize_filesystem_name(filter_name),
                fitsDate, exposure, xbin, ybin, temp)
        elif is_flat_dark_image_type(imagetyp):
            newName = "{}-{}-{}-{}-{}s-{}x{}-t{}.fits".format(
                "FlatDark", scope, instrument, fitsDate, exposure, xbin, ybin, temp)
        elif is_flat_image_type(imagetyp):
            filter_name = hdr.get("FILTER", "OSC")
            newName = "{}-{}-{}-{}-{}-{}s-{}x{}-t{}.fits".format(
                "Flat", scope, instrument, sanitize_filesystem_name(filter_name), fitsDate, exposure, xbin, ybin, temp)
        elif is_dark_image_type(imagetyp):
            newName = "{}-{}-{}-{}-{}s-{}x{}-t{}.fits".format(
                "Dark", scope, instrument, fitsDate, exposure, xbin, ybin, temp)
        elif "BIAS" in imagetyp:
            newName = "{}-{}-{}-{}-{}x{}-t{}.fits".format(
                "Bias", scope, instrument, fitsDate, xbin, ybin, temp)

        if not newName:
            raise ValidationError(
                f"Could not determine appropriate filename for file type {hdr.get('IMAGETYP', 'Unknown')}",
                field="IMAGETYP",
                file_path=path
            )
        return newName, wcs_added

    @staticmethod
    def _save_modified_header(hdr, root: str, file: str) -> None:
        """Write the corrected header back to the file, keeping a ``.backup`` copy. Failures are logged, not raised."""
        try:
            # Create backup of original file
            backup_path = os.path.join(root, file + ".backup")
            import shutil
            shutil.copy2(os.path.join(root, file), backup_path)

            # Save modified header
            with fits.open(os.path.join(root, file), mode='update') as hdul:
                hdul[0].header = hdr
                hdul.flush()

            logger.info(f"Saved modified header for {file}")
        except OSError:
            logger.exception(f"File I/O error saving modified header for {file}")
            # Continue processing despite header save failure
        except Exception:
            logger.exception(f"Unexpected error saving modified header for {file}")
            # Continue processing despite header save failure

    def _compress_if_enabled(self, current_file_path: str) -> str:
        """Compress the file when the settings ask for it; on failure keep using the original."""
        try:
            compressed_file_path = self.compressor.process_file_for_compression(current_file_path)
            if compressed_file_path != current_file_path:
                # File was compressed, update path references
                logger.info(f"File compressed: {current_file_path} -> {compressed_file_path}")
                return compressed_file_path
        except Exception as e:
            logger.warning(f"Compression processing failed for {current_file_path}: {e}")
            # Continue with original file if compression fails
        return current_file_path

    def _move_into_repository(self, current_file_path: str, hdr, new_filename: str) -> str:
        """Move/rename the file into the repository structure; returns its new path."""
        try:
            from .repository import RepositoryManager

            repo_manager = RepositoryManager()
            # A fresh manager reads library.ini; honour this processor's folder instead, so the commands'
            # --repo override (and any caller that sets repoFolder) decides where the file is filed.
            repo_manager.repoFolder = self.repoFolder
            # Ensure the repository root folders exist (Light/Calibrate/Masters/Incoming/etc.)
            repo_manager.createRepositoryStructure()

            moved_path = repo_manager.organizeFileByType(
                current_file_path,
                hdr,
                new_filename=new_filename,
            )
            if not moved_path:
                raise FileProcessingError(
                    "Failed to move file into repository structure",
                    file_path=current_file_path,
                    error_code="REPO_MOVE_FAILED",
                )
            return moved_path
        except Exception as e:
            raise FileProcessingError(
                f"Failed moving file into repository: {e}",
                file_path=current_file_path,
                error_code="REPO_MOVE_FAILED",
            ) from e

    # Legacy methods for backward compatibility - delegate to new services
    def extractZipFile(self, zip_path):
        """
        DEPRECATED: Extract FITS file from ZIP archive.

        This method is deprecated. Use FileFormatProcessor directly instead.
        Delegates to the ZIP handler in the format processor.

        Args:
            zip_path (str): Path to ZIP file

        Returns:
            str: Path to extracted FITS file

        Raises:
            FileProcessingError: If extraction fails
        """
        import warnings
        warnings.warn(
            "extractZipFile is deprecated. Use FileFormatProcessor instead.",
            DeprecationWarning,
            stacklevel=2
        )

        try:
            from .file_formats.handlers.zip_handler import ZipFileHandler
            handler = ZipFileHandler()
            return handler.process_file(zip_path)
        except Exception:
            # Convert any exception to the expected format for backward compatibility
            logger.exception(f"Error extracting zip file {zip_path}")
            return None

    def convertXisfToFits(self, xisf_file_path):
        """
        DEPRECATED: Convert XISF file to FITS format.

        This method is deprecated. Use FileFormatProcessor directly instead.
        Delegates to the XISF handler in the format processor.

        Args:
            xisf_file_path (str): Path to XISF file

        Returns:
            str: Path to converted FITS file

        Raises:
            FileProcessingError: If conversion fails
        """
        import warnings
        warnings.warn(
            "convertXisfToFits is deprecated. Use FileFormatProcessor instead.",
            DeprecationWarning,
            stacklevel=2
        )

        try:
            from .file_formats.handlers.xisf_handler import XisfFileHandler
            handler = XisfFileHandler()
            return handler.process_file(xisf_file_path)
        except Exception:
            # Convert any exception to the expected format for backward compatibility
            logger.exception(f"Error converting XISF file {xisf_file_path}")
            return None
