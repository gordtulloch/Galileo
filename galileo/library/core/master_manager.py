# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""
Advanced Master Calibration Frame Management Module

This module provides advanced master calibration frame operations including:
- Astropy-based sigma-clipped and simple-average master frame creation
- Intelligent matching of master frames to sessions
- Validation and quality assessment of master frames
- Cleanup and maintenance operations
- Statistics and analytics for master frame management
"""

import os
import logging
import datetime
from galileo.library.config import load_config as load_library_config

try:
    import winreg  # For checking Windows Developer Mode
except ImportError:
    winreg = None  # type: ignore[assignment]  # Not on Windows
from typing import Any
from collections.abc import Callable


from ..models import Masters, fitsSession, fitsFile
from galileo.library.core.master_stacking import (
    MasterStackingMixin,
)
from galileo.library.core.master_maintenance import (
    MasterMaintenanceMixin,
)

logger = logging.getLogger(__name__)


def _get_config():
    """Get configuration from the library settings file."""
    config = load_library_config()
    return config


# ---------------------------------------------------------------------------
# Light-frame registration, run in the CPU worker pool (galileo.core.compute)
# ---------------------------------------------------------------------------
# astroalign holds the GIL for 4-8 s per full frame, so from the stacking QThread it froze the
# UI for the whole stack (NFR-PERF-020). The worker reads each frame, and the reference, from disk
# itself, so only paths go in. The reference is deliberately re-read per frame rather than cached:
# a cache would leave every idle worker holding a full-size frame after the stack finished, and the
# re-read (from the OS file cache) costs about 2% of a registration.


class MasterFrameManager(MasterMaintenanceMixin, MasterStackingMixin):
    """Advanced manager class for master calibration frame operations."""

    def __init__(self):
        """Initialize the master frame manager."""
        self.config = _get_config()
        self.masters_dir = self._get_master_calibration_path()

    def _get_master_calibration_path(self) -> str:
        """
        Get the path to the master calibration frames directory.

        Returns:
            str: Path to the Masters directory within the repository folder
        """
        try:
            config = _get_config()
            repo_folder = config.get('DEFAULT', 'repo', fallback='.')
        except Exception as e:
            logger.warning(f"Could not get repository folder from config: {e}")
            repo_folder = os.getcwd()

        masters_dir = os.path.join(repo_folder, 'Masters')
        # Don't create the directory here - let it be created when actually needed
        return masters_dir

    def _ensure_masters_directory_exists(self) -> str:
        """
        Ensure the Masters directory exists and return its path.

        Returns:
            str: Path to the Masters directory
        """
        masters_dir = self.masters_dir
        os.makedirs(masters_dir, exist_ok=True)
        return masters_dir

    def _get_thumbnails_directory(self) -> str:
        """Return the Thumbnails directory path under the configured repository, creating it if needed."""
        try:
            config = _get_config()
            repo_folder = config.get('DEFAULT', 'repo', fallback='.')
        except Exception as e:
            logger.warning(f"Could not get repository folder from config: {e}")
            repo_folder = os.getcwd()

        thumbs_dir = os.path.join(repo_folder, 'Thumbnails')
        os.makedirs(thumbs_dir, exist_ok=True)
        return thumbs_dir


    def find_matching_master(self, session_data: dict[str, Any], cal_type: str) -> Masters | None:
        """
        Find a matching master frame for the given session and calibration type.

        Args:
            session_data: Session data with equipment and settings
            cal_type: Type of calibration ('bias', 'dark', 'flat')

        Returns:
            Matching master frame or None
        """
        try:
            criteria = {
                'exposure_time': session_data.get('exposure_time') if cal_type in ('dark', 'flatdark') else None,
                'filter_name': session_data.get('filter_name') if cal_type == 'flat' else None,
                'binning_x': session_data.get('binning_x'),
                'binning_y': session_data.get('binning_y'),
                'ccd_temp': session_data.get('ccd_temp'),
                'gain': session_data.get('gain'),
                'offset': session_data.get('offset')
            }

            # Remove None values
            criteria = {k: v for k, v in criteria.items() if v is not None}

            return Masters.find_matching_master(
                telescope=session_data.get('telescope'),
                instrument=session_data.get('instrument'),
                master_type=cal_type,
                **criteria
            )

        except Exception:
            logger.exception("Error finding matching master")
            return None

    def create_master_from_session(self, session_id: str, cal_type: str,
                                 min_files: int = 2,
                                 progress_callback: Callable | None = None,
                                 verbose: bool = False) -> Masters | None:
        """
        Create a master calibration frame from a session's files using sigma-clipped stacking.

        Args:
            session_id: Session ID to create master from
            cal_type: Type of calibration ('bias', 'dark', 'flat')
            min_files: Minimum number of files required
            progress_callback: Progress reporting function
            verbose: Enable verbose output showing which files are used

        Returns:
            Created master frame record or None if creation failed
        """
        try:
            if progress_callback:
                progress_callback(0, 100, f"Starting {cal_type} master creation...")

            # Get session and files
            session = fitsSession.get_by_id(session_id)
            files = list(fitsFile.select().where(
                fitsFile.fitsFileSession == session.fitsSessionId,
                fitsFile.fitsFileObject.contains(cal_type.upper())
            ))

            if len(files) < min_files:
                logger.warning(f"Not enough files for {cal_type} master: {len(files)} < {min_files}")
                return None

            if progress_callback:
                progress_callback(10, 100, f"Found {len(files)} {cal_type} frames...")

            # Verbose output: List all files being used to create the master
            if verbose:
                logger.info(f"\n{'='*80}")
                logger.info(f"Creating {cal_type.upper()} master from {len(files)} files:")
                logger.info(f"Session ID: {session_id}")
                logger.info(f"Telescope: {session.fitsSessionTelescope}")
                logger.info(f"Camera: {session.fitsSessionImager}")
                logger.info(f"Exposure: {session.fitsSessionExposure}s")
                logger.info(f"Binning: {session.fitsSessionBinningX}x{session.fitsSessionBinningY}")
                logger.info(f"Temperature: {session.fitsSessionCCDTemp}°C")
                logger.info("\nFiles being stacked:")
                for i, f in enumerate(files, 1):
                    logger.info(f"  {i:3d}. {os.path.basename(f.fitsFileName or '')}")
                    if verbose and cal_type.lower() in ('dark', 'flatdark'):
                        # For dark frames, also show exposure time from file
                        logger.info(f"       Exposure: {f.fitsFileExpTime}s, Temp: {f.fitsFileCCDTemp}°C")
                logger.info(f"{'='*80}\n")

            # Generate output filename with Master prefix using session date not current date
            if session.fitsSessionDate:
                # Use the session date (observation date) instead of current date
                timestamp = session.fitsSessionDate.strftime("%Y%m%d")
            else:
                # Fallback to current date if session date is not available
                timestamp = datetime.datetime.now().astimezone().strftime("%Y%m%d")
                logger.warning(f"Session {session_id} has no date, using current date for master filename")

            # Clean telescope and imager names for filename compatibility
            telescope_clean = (session.fitsSessionTelescope or "").replace(" ", "_").replace("\\", "_").replace("@", "_").replace("/", "_")
            imager_clean = (session.fitsSessionImager or "").replace(" ", "_").replace("\\", "_").replace("@", "_").replace("/", "_")

            # Build filename following the same pattern as calibration frames in fitsFile registration
            if cal_type.lower() == 'flat':
                # For flats: Master-Flat-[Telescope]-[Instrument]-[Filter]-[Date]-[Exposure]s-[XBinning]x[YBinning]-t[CCDTemp].fits
                filter_name = session.fitsSessionFilter or "OSC"
                output_filename = f"Master-Flat-{telescope_clean}-{imager_clean}-{filter_name}-{timestamp}-{session.fitsSessionExposure}s-{session.fitsSessionBinningX}x{session.fitsSessionBinningY}-t{session.fitsSessionCCDTemp}.fits"
            else:
                # For bias/dark: Master-[Type]-[Telescope]-[Instrument]-[Date]-[Exposure]s-[XBinning]x[YBinning]-t[CCDTemp].fits
                output_filename = f"Master-{cal_type.title()}-{telescope_clean}-{imager_clean}-{timestamp}-{session.fitsSessionExposure}s-{session.fitsSessionBinningX}x{session.fitsSessionBinningY}-t{session.fitsSessionCCDTemp}.fits"

            # Ensure Masters directory exists before creating the file
            masters_dir = self._ensure_masters_directory_exists()
            output_path = os.path.join(masters_dir, output_filename)

            # Extract file paths
            file_paths = [f.fitsFileName for f in files if f.fitsFileName]

            if progress_callback:
                progress_callback(20, 100, "Creating master frame with internal stacking...")

            # Create master frame using internal sigma-clipped stacking
            success = self._create_master_sigma_clip(file_paths, output_path, cal_type, progress_callback)

            if not success or not os.path.exists(output_path):
                logger.error(f"Failed to create master {cal_type} frame")
                return None

            if progress_callback:
                progress_callback(80, 100, "Updating FITS header...")

            # Update FITS header with metadata
            self._update_master_header(output_path, session, files, cal_type)

            if progress_callback:
                progress_callback(90, 100, "Saving master frame record...")

            # Create database record
            session_data = {
                'session_id': str(session.fitsSessionId),
                'telescope': session.fitsSessionTelescope,
                'instrument': session.fitsSessionImager,
                'exposure_time': session.fitsSessionExposure,
                'filter_name': session.fitsSessionFilter,
                'binning_x': session.fitsSessionBinningX,
                'binning_y': session.fitsSessionBinningY,
                'ccd_temp': session.fitsSessionCCDTemp,
                'gain': session.fitsSessionGain,
                'offset': session.fitsSessionOffset
            }

            master_record = Masters.create_master_record(
                master_path=output_path,
                session_data=session_data,
                cal_type=cal_type,
                file_count=len(files)
            )

            # Soft-delete source calibration frames now that master is created
            if progress_callback:
                progress_callback(95, 100, f"Marking {len(files)} source frames as soft-deleted...")

            soft_deleted_count = 0
            for source_file in files:
                try:
                    source_file.fitsFileSoftDelete = True
                    source_file.save()
                    soft_deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to soft-delete source file {source_file.fitsFileName}: {e}")

            logger.info(f"Soft-deleted {soft_deleted_count} of {len(files)} source calibration frames for master {output_filename}")

            if progress_callback:
                progress_callback(100, 100, f"Master {cal_type} frame created successfully")

            logger.info(f"Created master {cal_type} frame: {output_filename}")
            return master_record

        except Exception:
            logger.exception(f"Error creating master {cal_type} frame")
            if progress_callback:
                progress_callback(100, 100, f"Error creating master {cal_type} frame")
            return None


# Singleton instance
_master_manager_instance = None

def get_master_manager() -> MasterFrameManager:
    """Get a singleton instance of the master frame manager."""
    global _master_manager_instance
    if _master_manager_instance is None:
        _master_manager_instance = MasterFrameManager()
    return _master_manager_instance
