"""
Core modules for AstroFiler application.

This package contains modular components extracted from the original monolithic
astrofiler_file.py for better maintainability and organization:

- utils: Common utility functions
- file_processing: FITS file handling and database operations
- auto_calibration / light_calibration / master_manager: Master frame creation and calibration processing
- enhanced_quality: Advanced image quality assessment with SEP star detection
- repository: File organization and repository management
"""

import os
import sys
from typing import Optional, Union, Any

from ..config import load_config as load_library_config
from ..types import FilePath

__version__ = "1.2.0"

# Import key classes and functions for convenient access
from .file_processing import FileProcessor
from .enhanced_quality import EnhancedQualityAnalyzer
from .repository import RepositoryManager
from .master_manager import MasterFrameManager, get_master_manager
from .compress_files import get_fits_compressor, compress_fits_file, is_compression_enabled
from .session_processing import SessionProcessor
from .utils import (
    normalize_file_path,
    sanitize_filesystem_name,
    dwarfFixHeader,
    mapFitsHeader,
    clearMappingCache,
    get_master_calibration_path
)

# Create a unified processing class that combines all functionality
class fitsProcessing:
    """
    Unified FITS processing class that combines all core functionality.
    
    This class provides backwards compatibility with the original fitsProcessing
    class while using the new modular architecture internally.
    """

    def __init__(self) -> None:
        """Initialize all processor components."""
        self.file_processor = FileProcessor()
        self.quality_analyzer = EnhancedQualityAnalyzer()
        self.repository_manager = RepositoryManager()
        self.master_manager = get_master_manager()  # Advanced master frame management
        self.session_processor = SessionProcessor()  # Session creation and linking

        # Load configuration for backwards compatibility
        self.config = load_library_config()
        self.sourceFolder = self.config.get('DEFAULT', 'source', fallback='.')
        self.repoFolder = self.config.get('DEFAULT', 'repo', fallback='.')

    # The folders live on the components that do the work. The commands' --source/--repo overrides set them on this
    # facade, so they must reach those components - otherwise files are still filed into the configured repository.
    @property
    def sourceFolder(self) -> str:
        return self.file_processor.sourceFolder

    @sourceFolder.setter
    def sourceFolder(self, folder: str) -> None:
        self.file_processor.sourceFolder = folder
        self.repository_manager.sourceFolder = folder

    @property
    def repoFolder(self) -> str:
        return self.file_processor.repoFolder

    @repoFolder.setter
    def repoFolder(self, folder: str) -> None:
        self.file_processor.repoFolder = folder
        self.repository_manager.repoFolder = folder

    # Delegate methods to appropriate processors with original signatures
    def calculateFileHash(self, filePath: FilePath) -> str | None:
        """Calculate hash for file - delegates to FileProcessor."""
        return self.file_processor.calculateFileHash(filePath)

    def registerFitsImage(self, root: str, file: str, moveFiles: bool) -> str | bool:
        """Register FITS image - original signature from astrofiler_file."""
        return self.file_processor.registerFitsImage(root, file, moveFiles)

    def registerMasters(
        self,
        progress_callback=None,
        source_folder: str | None = None,
        moveFiles: bool = False,
        destination_folder: str | None = None,
        precount: bool = False,
        recursive: bool = True,
    ):
        """Scan for existing master FITS files and register them in the Masters table."""
        return self.file_processor.registerMasters(
            progress_callback=progress_callback,
            source_folder=source_folder,
            moveFiles=moveFiles,
            destination_folder=destination_folder,
            precount=precount,
            recursive=recursive,
        )

    def registerExistingFiles(self, progress_callback=None, scan_subdirectories=True, verify_headers=True) -> dict:
        """Catalog what is already in the repository folder, where it is: master calibration frames first, then every
        other FITS file. Nothing is moved, renamed or cleared.

        This is the registration the Images screen's Regenerate button performs after it has emptied the catalog
        (and what ``galileo-register-existing`` runs), minus the emptying — so it can also be pointed at a catalog that
        is merely out of date. Files already catalogued are recognised by content hash and not added twice.

        Args:
            progress_callback: ``callback(current, total, filename) -> bool``; returning False stops the scan.
            scan_subdirectories: Walk the repository's sub-folders too (default).
            verify_headers: Accepted for command-line compatibility. Registration always reads each file's headers
                (that is how it is catalogued), so there is no cheaper mode to switch to.

        Returns:
            ``{"summary": {"total_files_processed", "master_frames": {"found"}, "calibrated_lights": {"found"},
            "database_changes"}, "errors": [...]}``. ``database_changes`` is the net number of catalog rows added.
        """
        from galileo.library.models import Masters, fitsFile

        def row_count() -> int:
            return fitsFile.select().count() + Masters.select().count()

        errors: list[str] = []
        before = row_count()
        folder = self.repoFolder

        master_ids: list[str] = []
        try:
            master_ids = self.registerMasters(
                progress_callback=progress_callback, source_folder=folder, precount=False,
                recursive=scan_subdirectories,
            ) or []
        except Exception as exc:
            errors.append(f"Registering master frames failed: {exc}")

        registered: list[str] = []
        try:
            registered = self.registerFitsImages(
                moveFiles=False, progress_callback=progress_callback, source_folder=folder,
                recursive=scan_subdirectories,
            ) or []
        except Exception as exc:
            errors.append(f"Registering images failed: {exc}")

        calibrated = [p for p in registered if os.path.basename(str(p)).lower().startswith("cal_")]
        return {
            "summary": {
                "total_files_processed": len(master_ids) + len(registered),
                "master_frames": {"found": len(master_ids)},
                "calibrated_lights": {"found": len(calibrated)},
                "database_changes": row_count() - before,
            },
            "errors": errors,
        }

    def registerFitsImages(self, moveFiles=True, progress_callback=None, source_folder=None, recursive=True):
        """Register multiple FITS images from source folder (sub-folders too unless *recursive* is False)."""
        import os
        processed_files = []

        # Use specified folder or default to sourceFolder
        scan_folder = source_folder or self.sourceFolder

        # First, count total files to process
        total_files = 0
        from .compress_files import get_fits_compressor
        compressor = get_fits_compressor()

        def _is_master_fits_by_imagetyp(file_path: str) -> bool:
            """Return True if FITS header IMAGETYP indicates a master calibration frame."""
            try:
                from astropy.io import fits
                hdr = fits.getheader(file_path, 0)
                imagetyp = str(hdr.get('IMAGETYP', '')).upper()
                if 'MASTER' not in imagetyp:
                    return False
                return any(token in imagetyp for token in ('DARK', 'FLAT', 'BIAS'))
            except Exception:
                return False

        for root, dirs, files in os.walk(scan_folder):
            if not recursive:
                dirs[:] = []
            for file in files:
                # Use the comprehensive FITS file detection that includes compressed files
                file_path = os.path.join(root, file)
                if compressor.is_fits_file(file_path):
                    if _is_master_fits_by_imagetyp(file_path):
                        continue
                    total_files += 1

        current_file = 0
        for root, dirs, files in os.walk(scan_folder):
            if not recursive:
                dirs[:] = []
            for file in files:
                # Use the comprehensive FITS file detection that includes compressed files
                file_path = os.path.join(root, file)
                if compressor.is_fits_file(file_path) or file.lower().endswith('.xisf'):
                    if compressor.is_fits_file(file_path) and _is_master_fits_by_imagetyp(file_path):
                        continue
                    current_file += 1
                    try:
                        result = self.registerFitsImage(root, file, moveFiles)
                        if result:  # If registration was successful
                            processed_files.append(file_path)
                        if progress_callback:
                            # Call with expected signature: current, total, filename
                            if not progress_callback(current_file, total_files, file_path):
                                break  # Stop if callback returns False (user cancelled)
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.error(f"Error processing {file}: {e}")

        return processed_files

    def submitFileToDB(self, fileName, hdr, fileHash=None):
        """Submit file to database - original signature."""
        # Extract required parameters from header
        newName = os.path.basename(fileName)
        newPath = os.path.dirname(fileName)
        exptime = hdr.get('EXPTIME', 0)
        source = 'galileo'

        # Get HDU data - for backwards compatibility, set to None if not available
        hduData = None

        return self.file_processor.submitFileToDB(fileName, hdr, hduData,
                                                newName, newPath, exptime, source)

    def extractZipFile(self, zip_path):
        """Extract ZIP file - original signature."""
        return self.file_processor.extractZipFile(zip_path, progressbar=None)

    def convertXisfToFits(self, xisf_file_path):
        """Convert XISF to FITS - original signature."""
        return self.file_processor.convertXisfToFits(xisf_file_path, outputFile=None)

    # Advanced master management methods
    def createAdvancedMaster(self, session_id, cal_type, min_files=2, progress_callback=None):
        """Create master frame using advanced Siril integration."""
        return self.master_manager.create_master_from_session(
            session_id, cal_type, min_files, progress_callback)

    def findMatchingMaster(self, session_data, cal_type):
        """Find a matching master frame for the given session."""
        return self.master_manager.find_matching_master(session_data, cal_type)

    def runAutoCalibrationWorkflow(self, progress_callback=None, operations=None):
        """
        Run the auto-calibration workflow with optional operation selection.
        
        Args:
            progress_callback: Callback function for progress updates (percentage, message)
            operations: List of operations to run ['analyze', 'masters', 'calibrate', 'quality']
                       If None, runs all operations
        
        Returns:
            dict: Results with keys: status, sessions_analyzed, masters_created,
                  calibration_opportunities, light_frames_calibrated, errors
        """
        import logging
        from .auto_calibration import (
            load_config, validate_database_access,
            analyze_calibration_opportunities, create_master_frames,
            calibrate_light_frames, perform_quality_assessment
        )

        logger = logging.getLogger(__name__)

        # Default operations if none specified
        if operations is None:
            operations = ['analyze', 'masters', 'calibrate', 'quality']

        results = {
            'status': 'success',
            'sessions_analyzed': 0,
            'masters_created': 0,
            'calibration_opportunities': 0,
            'light_frames_calibrated': 0,
            'errors': []
        }

        try:
            # Load configuration
            config = load_config()

            # Validate database access
            if not validate_database_access():
                raise Exception("Database validation failed")

            # Progress tracking
            total_operations = len(operations)
            completed_operations = 0

            for operation in operations:
                if progress_callback:
                    progress = int((completed_operations / total_operations) * 100)
                    progress_callback(progress, f"Running {operation} operation...")

                logger.info(f"Running auto-calibration operation: {operation}")

                try:
                    # Define progress callback for this operation
                    def operation_progress(percentage, message, *, completed=completed_operations):
                        if progress_callback:
                            # Map operation progress to overall progress
                            base_progress = int((completed / total_operations) * 100)
                            operation_progress_range = int(100 / total_operations)
                            overall_progress = base_progress + int((percentage * operation_progress_range) / 100)
                            progress_callback(overall_progress, message)

                    if operation == 'analyze':
                        analysis_result = analyze_calibration_opportunities(config, progress_callback=operation_progress)
                        if analysis_result:
                            results['calibration_opportunities'] = analysis_result.get('total_opportunities', 0)
                        else:
                            raise Exception("Analysis failed")

                    elif operation == 'masters':
                        success = create_master_frames(config, progress_callback=operation_progress)
                        if success:
                            # Count created masters (rough estimate based on opportunities)
                            results['masters_created'] = results.get('calibration_opportunities', 1)
                        else:
                            raise Exception("Master creation failed")

                    elif operation == 'calibrate':
                        from .light_calibration import get_calibration_statistics
                        frames_before = get_calibration_statistics()['calibrated_frames']
                        success = calibrate_light_frames(config, progress_callback=operation_progress)
                        if success:
                            frames_after = get_calibration_statistics()['calibrated_frames']
                            results['light_frames_calibrated'] = frames_after - frames_before
                        else:
                            raise Exception("Light frame calibration failed")

                    elif operation == 'quality':
                        success = perform_quality_assessment(config, progress_callback=operation_progress)
                        if not success:
                            raise Exception("Quality assessment failed")

                except Exception as e:
                    error_msg = f"{operation} operation failed: {e!s}"
                    logger.error(error_msg)
                    results['errors'].append(error_msg)

                    # Critical operations cause complete failure
                    if operation in ['analyze', 'masters']:
                        results['status'] = 'error'
                        results['message'] = error_msg
                        return results

                completed_operations += 1

                if progress_callback:
                    progress = int((completed_operations / total_operations) * 100)
                    progress_callback(progress, f"Completed {operation} operation")

            # Final progress update
            if progress_callback:
                progress_callback(100, "Auto-calibration workflow completed")

            # Set sessions analyzed (rough estimate)
            results['sessions_analyzed'] = results.get('calibration_opportunities', 0) + results.get('light_frames_calibrated', 0)

            logger.info(f"Auto-calibration workflow completed: {results}")

        except Exception as e:
            error_msg = f"Auto-calibration workflow failed: {e!s}"
            logger.error(error_msg, exc_info=True)
            results['status'] = 'error'
            results['message'] = error_msg
            results['errors'].append(error_msg)

        return results

    def validateMasters(self, progress_callback=None):
        """Validate all master frames in the database and filesystem."""
        return self.master_manager.validate_masters(progress_callback)

    def cleanupMasters(self, retention_days=None, progress_callback=None):
        """Clean up old and unused master frames."""
        return self.master_manager.cleanup_masters(retention_days, progress_callback)

    def getMasterStatistics(self):
        """Get comprehensive statistics about master frames."""
        return self.master_manager.get_master_statistics()

    # Session processing methods - delegate to SessionProcessor
    def createLightSessions(self, progress_callback=None):
        """Create sessions for all Light files not currently assigned to one."""
        return self.session_processor.createLightSessions(progress_callback)

    def createCalibrationSessions(self, progress_callback=None):
        """Create sessions for all calibration files not currently assigned to one."""
        return self.session_processor.createCalibrationSessions(progress_callback)

    def linkSessions(self, progress_callback=None):
        """Link calibration sessions to light sessions based on matching criteria."""
        return self.session_processor.linkSessions(progress_callback)

# Export the main class for backwards compatibility
__all__ = [
    'EnhancedQualityAnalyzer',
    'FileProcessor',
    'MasterFrameManager',
    'RepositoryManager',
    'SessionProcessor',
    'clearMappingCache',
    'compress_fits_file',
    'dwarfFixHeader',
    'fitsProcessing',
    'get_fits_compressor',
    'get_master_calibration_path',
    'get_master_manager',
    'is_compression_enabled',
    'mapFitsHeader',
    'normalize_file_path',
    'sanitize_filesystem_name'
]
