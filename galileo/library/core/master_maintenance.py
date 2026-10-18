# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Master-frame housekeeping: validate, clean up, link to sessions and report statistics."""

from __future__ import annotations

import logging
import os
import hashlib
import datetime
from typing import TYPE_CHECKING, Any
from collections.abc import Callable
from ..models import Masters, fitsSession

logger = logging.getLogger(__name__)


class MasterMaintenanceMixin:
    """Master-frame housekeeping: validate, clean up, link to sessions and report statistics."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def validate_masters(self, progress_callback: Callable | None = None) -> dict[str, Any]:
        """
        Validate all master frames in the database and filesystem.

        Args:
            progress_callback: Progress reporting function

        Returns:
            Dictionary with validation results
        """
        try:
            results: dict[str, Any] = {
                'total_masters': 0,
                'valid_masters': 0,
                'invalid_masters': 0,
                'missing_files': 0,
                'corrupted_files': 0,
                'validated_masters': []
            }

            masters = list(Masters.select())
            results['total_masters'] = len(masters)

            if progress_callback:
                progress_callback(0, len(masters), "Starting master validation...")

            for i, master in enumerate(masters):
                try:
                    # Check file existence
                    if not os.path.exists(master.master_path):
                        results['missing_files'] += 1
                        results['invalid_masters'] += 1
                        logger.warning(f"Master file not found: {master.master_path}")
                        continue

                    # Verify file hash
                    current_hash = self._calculate_file_hash(master.master_path)
                    if master.hash_value and current_hash != master.hash_value:
                        results['corrupted_files'] += 1
                        results['invalid_masters'] += 1
                        logger.warning(f"Master file hash mismatch: {master.master_path}")
                        continue

                    # Try to open FITS file
                    try:
                        from astropy.io import fits
                        with fits.open(master.master_path) as hdul:
                            # Basic validation - check if we can read the data
                            _ = hdul[0].data.shape
                    except Exception as e:
                        results['corrupted_files'] += 1
                        results['invalid_masters'] += 1
                        logger.warning(f"Cannot read master FITS file {master.master_path}: {e}")
                        continue

                    # Mark as validated
                    master.is_validated = True
                    master.validation_date = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                    master.save()

                    results['valid_masters'] += 1
                    results['validated_masters'].append(master.id)

                    if progress_callback:
                        progress_callback(i + 1, len(masters), f"Validated: {os.path.basename(master.master_path)}")

                except Exception:
                    logger.exception(f"Error validating master {master.id}")
                    results['invalid_masters'] += 1

            if progress_callback:
                progress_callback(len(masters), len(masters), "Validation completed")

            logger.info(f"Master validation completed: {results['valid_masters']}/{results['total_masters']} valid")
            return results

        except Exception as e:
            logger.exception("Error during master validation")
            return {'error': str(e)}

    def cleanup_masters(self, retention_days: int | None = None,
                       progress_callback: Callable | None = None) -> dict[str, Any]:
        """
        Clean up old and unused master frames.

        Args:
            retention_days: Number of days to retain masters (None = keep all)
            progress_callback: Progress reporting function

        Returns:
            Dictionary with cleanup results
        """
        try:
            results: dict[str, Any] = {
                'total_masters': 0,
                'deleted_masters': 0,
                'space_freed': 0,
                'errors': []
            }

            # Get retention period from config if not specified
            if retention_days is None:
                retention_days = self.config.getint('maintenance', 'master_retention_days', fallback=365)

            cutoff_date = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=retention_days)

            # Find masters older than retention period
            old_masters = list(Masters.select().where(
                Masters.creation_date < cutoff_date,
                Masters.is_validated == True  # Only delete validated masters
            ))

            results['total_masters'] = len(old_masters)

            if progress_callback:
                progress_callback(0, len(old_masters), f"Starting cleanup of {len(old_masters)} old masters...")

            for i, master in enumerate(old_masters):
                try:
                    # Check if master is still in use by any sessions
                    # A session refers to its master by master_id (or, historically, by path)
                    refs = [master.master_id, master.master_path]
                    sessions_using = fitsSession.select().where(
                        fitsSession.fitsBiasMaster.in_(refs) |
                        fitsSession.fitsDarkMaster.in_(refs) |
                        fitsSession.fitsFlatMaster.in_(refs)
                    ).count()

                    if sessions_using > 0:
                        logger.info(f"Keeping master {master.id} - still in use by {sessions_using} sessions")
                        continue

                    # Get file size before deletion
                    file_size = 0
                    if os.path.exists(master.master_path):
                        file_size = os.path.getsize(master.master_path)
                        os.remove(master.master_path)
                        results['space_freed'] += file_size

                    # Delete database record
                    master.delete_instance()
                    results['deleted_masters'] += 1

                    if progress_callback:
                        progress_callback(i + 1, len(old_masters),
                                        f"Deleted: {os.path.basename(master.master_path)}")

                except Exception as e:
                    error_msg = f"Error deleting master {master.id}: {e}"
                    logger.exception(error_msg)
                    results['errors'].append(error_msg)

            if progress_callback:
                progress_callback(len(old_masters), len(old_masters), "Cleanup completed")

            logger.info(f"Master cleanup completed: {results['deleted_masters']} deleted, "
                       f"{results['space_freed'] / (1024*1024):.2f} MB freed")
            return results

        except Exception as e:
            logger.exception("Error during master cleanup")
            return {'error': str(e)}

    def update_session_with_master(self, session_id: str, master_id: int, cal_type: str) -> bool:
        """
        Update a session to use a specific master frame.

        Args:
            session_id: Session ID to update
            master_id: Master frame ID
            cal_type: Type of calibration ('bias', 'dark', 'flat')

        Returns:
            True if successful, False otherwise
        """
        try:
            session = fitsSession.get_by_id(session_id)
            master = Masters.get_by_id(master_id)

            # Update appropriate field based on calibration type
            if cal_type == 'bias':
                session.fitsBiasMaster = master.master_id
            elif cal_type == 'dark':
                session.fitsDarkMaster = master.master_id
            elif cal_type == 'flat':
                session.fitsFlatMaster = master.master_id
            else:
                logger.error(f"Invalid calibration type: {cal_type}")
                return False

            session.save()
            logger.info(f"Updated session {session_id} with master {cal_type} {master_id}")
            return True

        except Exception:
            logger.exception("Error updating session with master")
            return False

    def get_master_statistics(self) -> dict[str, Any]:
        """
        Get comprehensive statistics about master frames.

        Returns:
            Dictionary with master frame statistics
        """
        try:
            stats: dict[str, Any] = {
                'total_masters': 0,
                'by_type': {},
                'by_telescope': {},
                'by_instrument': {},
                'total_size': 0,
                'avg_file_size': 0,
                'avg_frame_count': 0,
                'validation_status': {},
                'creation_dates': [],
                'avg_quality': 0
            }

            masters = list(Masters.select())
            stats['total_masters'] = len(masters)

            if len(masters) == 0:
                return stats

            total_size = 0
            total_frame_count = 0
            total_quality = 0.0
            quality_count = 0

            for master in masters:
                # By type
                master_type = master.master_type or 'unknown'
                stats['by_type'][master_type] = stats['by_type'].get(master_type, 0) + 1

                # By telescope
                telescope = master.telescope or 'unknown'
                stats['by_telescope'][telescope] = stats['by_telescope'].get(telescope, 0) + 1

                # By instrument
                instrument = master.instrument or 'unknown'
                stats['by_instrument'][instrument] = stats['by_instrument'].get(instrument, 0) + 1

                # File size
                if master.file_size:
                    total_size += master.file_size

                # Frame count
                if master.file_count:
                    total_frame_count += master.file_count

                # Creation dates
                if master.creation_date:
                    stats['creation_dates'].append(master.creation_date.isoformat())

                # Quality scores
                if hasattr(master, 'quality_score') and master.quality_score:
                    total_quality += master.quality_score
                    quality_count += 1

                # Validation status
                validated = 'validated' if master.is_validated else 'not_validated'
                stats['validation_status'][validated] = stats['validation_status'].get(validated, 0) + 1

            # Calculate averages
            stats['total_size'] = total_size
            if len(masters) > 0:
                stats['avg_file_size'] = total_size / len(masters)
                stats['avg_frame_count'] = total_frame_count / len(masters)

            if quality_count > 0:
                stats['avg_quality'] = total_quality / quality_count

            return stats

        except Exception:
            logger.exception("Error getting master statistics")
            return {}

    def _calculate_file_hash(self, file_path: str) -> str:
        """MD5 of a file, the same integrity digest ``Masters.create_master_record`` stores in ``hash_value``."""
        try:
            hash_md5 = hashlib.md5(usedforsecurity=False)
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            logger.exception(f"Error calculating hash for {file_path}")
            return ""
