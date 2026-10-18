# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Cloud Sync, Complete mode: download what is missing locally, then upload what is not yet backed up."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging
import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QApplication
from galileo.library.services.gcs import upload_file_to_backup, list_gcs_bucket_files, download_file_from_gcs
from galileo.library.config import load_config as load_library_config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as _MixinBase  # type checkers see a widget (it is mixed into one)
else:
    _MixinBase = object




class CloudCompleteSyncMixin(_MixinBase):
    """Cloud Sync, Complete mode: download what is missing locally, then upload what is not yet backed up."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def perform_complete_sync(self):
        """Perform complete bidirectional sync: download missing files from cloud and upload files without cloud URLs"""
        from PySide6.QtWidgets import QProgressDialog

        try:
            # Get repository path from configuration
            config = load_library_config()
            repo_path = config.get('DEFAULT', 'repo', fallback='')

            if not repo_path or not os.path.exists(repo_path):
                QMessageBox.critical(
                    self,
                    "Configuration Error",
                    "Repository path is not configured or does not exist.\n\n"
                    "Please configure your repository path in Options › Library."
                )
                return

            if not self._confirm_complete_sync(repo_path):
                return

            # Setup progress dialog
            progress = QProgressDialog("Starting complete sync...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setAutoClose(True)
            progress.setAutoReset(True)
            progress.show()

            # Prepare bucket info
            bucket_url = self.cloud_config['bucket_url']
            if bucket_url.startswith('gs://'):
                bucket_name = bucket_url.replace('gs://', '').rstrip('/')
            else:
                bucket_name = bucket_url.rstrip('/')

            auth_info = {'auth_string': self.cloud_config['auth_file_path']}

            # Phase 1: Download missing files from cloud
            progress.setLabelText("Phase 1: Getting cloud file list...")
            progress.setValue(10)
            QApplication.processEvents()

            if progress.wasCanceled():
                return

            cloud_files = list_gcs_bucket_files(bucket_name, auth_info)
            logger.info(f"Found {len(cloud_files)} files in cloud storage")

            progress.setLabelText("Phase 1: Checking for missing local files...")
            progress.setValue(20)
            QApplication.processEvents()

            downloaded_count, registered_count = self._download_missing_cloud_files(
                progress, cloud_files, bucket_name, auth_info, config)

            if progress.wasCanceled():
                return

            # Phase 2: Upload local files without cloud URLs (same as backup sync)
            progress.setLabelText("Phase 2: Getting local files without cloud URLs...")
            progress.setValue(50)
            QApplication.processEvents()

            fits_files, uploaded_count, updated_count, error_count = self._upload_unbacked_files(
                progress, bucket_name, auth_info, repo_path)

            progress.setValue(100)

            self._show_complete_sync_results(
                cancelled=progress.wasCanceled(), cloud_checked=len(cloud_files), local_processed=len(fits_files),
                downloaded=downloaded_count, registered=registered_count, uploaded=uploaded_count,
                updated=updated_count, errors=error_count)

        except Exception as e:
            logger.exception("Error during complete sync")
            QMessageBox.critical(
                self,
                "Complete Sync Error",
                f"An error occurred during complete sync:\n\n{e!s}\n\n"
                f"Please check the logs for more details."
            )

    def _confirm_complete_sync(self, repo_path: str) -> bool:
        """Ask the user to confirm the bidirectional sync."""
        reply = QMessageBox.question(
            self,
            "Complete Sync",
            f"This will perform bidirectional synchronization:\n\n"
            f"DOWNLOAD:\n"
            f"1. Check all files in cloud bucket: {self.cloud_config['bucket_url']}\n"
            f"2. Download files that exist in cloud but missing locally\n"
            f"3. Register downloaded files in the database\n\n"
            f"UPLOAD:\n"
            f"4. Check all local FITS files in the database\n"
            f"5. Upload files that don't have cloud URLs (not yet backed up)\n"
            f"6. Update cloud URLs for all processed files\n\n"
            f"Repository path: {repo_path}\n\n"
            f"This operation may take considerable time depending on file count and sizes.\n\n"
            f"Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        return reply == QMessageBox.StandardButton.Yes

    @staticmethod
    def _is_already_local(cloud_file_name: str, bucket_name: str) -> bool:
        """True if a cloud file is already catalogued: by file name, by cloud URL, or by its filename timestamp."""
        import re
        from galileo.library.models import fitsFile

        filename_only = os.path.basename(cloud_file_name)
        cloud_url = f"gs://{bucket_name}/{cloud_file_name}"

        # Method 1: exact filename
        try:
            fitsFile.get(fitsFile.fitsFileName == filename_only)
            logger.info(f"File already exists in repository (by filename): {filename_only}")
            return True
        except fitsFile.DoesNotExist:
            pass

        # Method 2: cloud URL (for files downloaded previously)
        try:
            fitsFile.get(fitsFile.fitsFileCloudURL == cloud_url)
            logger.info(f"File already exists in repository (by cloud URL): {filename_only}")
            return True
        except fitsFile.DoesNotExist:
            pass

        # Method 3: timestamp pattern in the filename, like "20240116031554"
        timestamp_match = re.search(r'-(\d{14})[s-]', filename_only)
        if timestamp_match:
            timestamp = timestamp_match.group(1)
            try:
                fitsFile.get(fitsFile.fitsFileName.contains(timestamp))
                logger.info(f"File already exists in repository (by timestamp {timestamp}): {filename_only}")
                return True
            except fitsFile.DoesNotExist:
                pass
        return False

    def _download_missing_cloud_files(self, progress, cloud_files, bucket_name, auth_info, config) -> tuple[int, int]:
        """Phase 1 (20% to 50%): download the cloud files that are not local yet; (downloaded, registered) counts."""
        downloaded_count = 0
        registered_count = 0

        for i, cloud_file in enumerate(cloud_files):
            if progress.wasCanceled():
                break

            progress.setLabelText(f"Phase 1: Checking {cloud_file['name']}")
            progress.setValue(20 + int((i / len(cloud_files)) * 30))
            QApplication.processEvents()

            if self._is_already_local(cloud_file['name'], bucket_name):
                continue

            try:
                logger.info(f"Downloading missing file: {cloud_file['name']}")

                source_path = config.get('DEFAULT', 'source', fallback='')
                if not source_path:
                    logger.error("Source folder not configured. Cannot download files.")
                    continue

                os.makedirs(source_path, exist_ok=True)

                # Download to the source (incoming) folder first
                incoming_file_path = os.path.join(source_path, os.path.basename(cloud_file['name']))
                success, _message = download_file_from_gcs(bucket_name, auth_info, cloud_file['name'], incoming_file_path)

                if success:
                    downloaded_count += 1
                    if incoming_file_path.lower().endswith(('.fits', '.fit', '.fts')):
                        if self._register_downloaded_fits(incoming_file_path, cloud_file['name']):
                            registered_count += 1
                    else:
                        logger.info(f"Downloaded non-FITS file: {cloud_file['name']}")

            except Exception:
                logger.exception(f"Failed to download {cloud_file['name']}")

        return downloaded_count, registered_count

    @staticmethod
    def _register_downloaded_fits(incoming_file_path: str, cloud_name: str) -> bool:
        """Register a downloaded FITS (moving it from incoming into the repository); True if it counted as registered."""
        from galileo.library.core import fitsProcessing

        processor = fitsProcessing()
        # Split path into directory and filename for registerFitsImage
        result = processor.registerFitsImage(
            os.path.dirname(incoming_file_path), os.path.basename(incoming_file_path), moveFiles=True)
        if not result:
            logger.warning(f"Downloaded but failed to register file: {cloud_name}")
            return False

        # Success includes both new registrations and duplicates
        if result == "DUPLICATE":
            # File already exists in repository, delete the downloaded copy
            try:
                os.remove(incoming_file_path)
                logger.info(f"Downloaded file already exists in repository, deleted incoming copy: {cloud_name}")
            except OSError as e:
                logger.warning(f"Failed to delete duplicate file from incoming: {e}")
        else:
            logger.info(f"Downloaded and registered file: {cloud_name}")
        return True

    def _upload_unbacked_files(self, progress, bucket_name, auth_info, repo_path) -> tuple[list, int, int, int]:
        """Phase 2 (50% to 100%): upload local files that have no cloud URL; (files, uploaded, updated, errors)."""
        from galileo.library.models import fitsFile

        # All FITS files in the database that don't have cloud URLs (including soft-deleted)
        fits_files = list(fitsFile.select().where(
            (fitsFile.fitsFileName.is_null(False)) &
            ((fitsFile.fitsFileCloudURL.is_null(True)) | (fitsFile.fitsFileCloudURL == ""))
        ))
        logger.info(f"Found {len(fits_files)} local files without cloud URLs")

        uploaded_count = 0
        updated_count = 0
        error_count = 0

        for i, fits_file in enumerate(fits_files):
            if progress.wasCanceled():
                break

            try:
                full_path = str(fits_file.fitsFileName)  # never None: the query above excludes null names
                progress.setLabelText(f"Phase 2: Processing {os.path.basename(full_path)}")
                progress.setValue(50 + int((i / len(fits_files)) * 50))
                QApplication.processEvents()

                if full_path.startswith(repo_path):
                    relative_path = os.path.relpath(full_path, repo_path)
                else:
                    # File is outside repo, use just the filename
                    relative_path = os.path.basename(full_path)

                if not os.path.exists(full_path):
                    logger.warning(f"Local file not found: {full_path}")
                    error_count += 1
                    continue

                success, cloud_url, message = upload_file_to_backup(bucket_name, auth_info, full_path, relative_path)

                if success:
                    # Update the database with cloud URL. Complete Sync keeps files in both local and cloud
                    # storage: soft-deleted files are not removed here.
                    fits_file.fitsFileCloudURL = cloud_url
                    fits_file.save()
                    updated_count += 1

                    if "uploaded" in message.lower():
                        uploaded_count += 1
                        logger.info(f"Uploaded: {relative_path}")
                    else:
                        logger.info(f"Already exists: {relative_path}")
                else:
                    logger.error(f"Failed to process {relative_path}: {message}")
                    error_count += 1

            except Exception:
                logger.exception(f"Error processing file {fits_file.fitsFileName}")
                error_count += 1

        return fits_files, uploaded_count, updated_count, error_count

    def _show_complete_sync_results(self, *, cancelled: bool, cloud_checked: int, local_processed: int,
                                    downloaded: int, registered: int, uploaded: int, updated: int,
                                    errors: int) -> None:
        if not cancelled:
            QMessageBox.information(
                self,
                "Complete Sync Finished",
                f"Complete bidirectional sync completed!\n\n"
                f"DOWNLOAD PHASE:\n"
                f"• Cloud files checked: {cloud_checked}\n"
                f"• Files downloaded: {downloaded}\n"
                f"• Files registered: {registered}\n\n"
                f"UPLOAD PHASE:\n"
                f"• Local files processed: {local_processed}\n"
                f"• Files uploaded: {uploaded}\n"
                f"• Database records updated: {updated}\n"
                f"• Errors: {errors}\n\n"
                f"Your local and cloud storage are now synchronized!"
            )
        else:
            QMessageBox.information(
                self,
                "Complete Sync Cancelled",
                f"Complete sync was cancelled by user.\n\n"
                f"Partial results:\n"
                f"• Files downloaded: {downloaded}\n"
                f"• Files registered: {registered}\n"
                f"• Files uploaded: {uploaded}\n"
                f"• Database records updated: {updated}\n"
                f"• Errors: {errors}"
            )
