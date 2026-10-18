# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Cloud Sync, Backup and On-Demand modes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging
import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QApplication
from galileo.library.services.gcs import check_file_exists_in_gcs, upload_file_to_backup
from galileo.library.config import load_config as load_library_config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as _MixinBase  # type checkers see a widget (it is mixed into one)
else:
    _MixinBase = object




class CloudBackupSyncMixin(_MixinBase):
    """Cloud Sync, Backup and On-Demand modes."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def perform_backup_sync(self):
        """Perform backup-only sync: upload local files that don't exist in cloud"""
        from galileo.library.models import fitsFile
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

            # Confirm operation
            reply = QMessageBox.question(
                self,
                "Backup Sync",
                f"This will:\n\n"
                f"1. Check all local FITS files in the database\n"
                f"2. Upload files that don't exist in cloud bucket: {self.cloud_config['bucket_url']}\n"
                f"3. Update cloud URLs for all processed files\n\n"
                f"Repository path: {repo_path}\n\n"
                f"This operation may take several minutes depending on the number of files.\n\n"
                f"Do you want to continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

            # Get all FITS files from database (including soft-deleted files for backup)
            fits_files = list(fitsFile.select().where(
                fitsFile.fitsFileName.is_null(False)
            ))

            if not fits_files:
                QMessageBox.information(
                    self,
                    "No Files Found",
                    "No FITS files found in the database.\n\n"
                    "Please scan your repository first using the Load Repository function."
                )
                return

            # Setup progress dialog
            progress = QProgressDialog("Starting backup sync...", "Cancel", 0, len(fits_files), self)
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

            # Process each file
            uploaded_count = 0
            updated_count = 0
            error_count = 0

            for i, fits_file in enumerate(fits_files):
                if progress.wasCanceled():
                    break

                try:
                    # Update progress
                    progress.setValue(i)
                    progress.setLabelText(f"Processing file {i+1} of {len(fits_files)}: {os.path.basename(fits_file.fitsFileName)}")
                    QApplication.processEvents()

                    # Get relative path from repository root
                    full_path = fits_file.fitsFileName
                    if full_path.startswith(repo_path):
                        relative_path = os.path.relpath(full_path, repo_path)
                    else:
                        # File is outside repo, use just the filename
                        relative_path = os.path.basename(full_path)

                    # Check if local file exists
                    if not os.path.exists(full_path):
                        logger.warning(f"Local file not found: {full_path}")
                        error_count += 1
                        continue

                    # Upload to backup if needed
                    success, cloud_url, message = upload_file_to_backup(
                        bucket_name, auth_info, full_path, relative_path
                    )

                    if success:
                        # Update the database with cloud URL
                        fits_file.fitsFileCloudURL = cloud_url
                        fits_file.save()
                        updated_count += 1

                        # Check if this is a soft-deleted file and verify cloud backup before deleting
                        if fits_file.fitsFileSoftDelete:
                            # Verify the file exists in cloud storage before deleting
                            try:
                                from galileo.library.services.cloud import _get_gcs_client
                                client = _get_gcs_client(auth_info)
                                gcs_object_name = relative_path.replace('\\', '/')

                                if check_file_exists_in_gcs(client, bucket_name, gcs_object_name):
                                    # File verified in cloud, safe to delete locally
                                    os.remove(full_path)
                                    logger.info(f"Deleted local soft-deleted file after verifying cloud backup: {relative_path}")
                                else:
                                    logger.error(f"SAFETY CHECK FAILED: File not found in cloud, keeping local copy: {relative_path}")
                            except OSError as e:
                                logger.warning(f"Failed to delete soft-deleted file {relative_path}: {e}")
                            except Exception:
                                logger.exception(f"Cloud verification failed for {relative_path}, keeping local copy")

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

            progress.setValue(len(fits_files))

            # Show results
            if not progress.wasCanceled():
                QMessageBox.information(
                    self,
                    "Backup Sync Complete",
                    f"Backup sync completed successfully!\n\n"
                    f"• Files processed: {len(fits_files)}\n"
                    f"• Files uploaded: {uploaded_count}\n"
                    f"• Database records updated: {updated_count}\n"
                    f"• Errors: {error_count}\n\n"
                    f"All processed files now have cloud URLs in the database."
                )
            else:
                QMessageBox.information(
                    self,
                    "Backup Sync Cancelled",
                    f"Backup sync was cancelled by user.\n\n"
                    f"Partial results:\n"
                    f"• Files processed: {i}\n"
                    f"• Files uploaded: {uploaded_count}\n"
                    f"• Database records updated: {updated_count}\n"
                    f"• Errors: {error_count}"
                )

        except Exception as e:
            logger.exception("Error during backup sync")
            QMessageBox.critical(
                self,
                "Backup Sync Error",
                f"An error occurred during backup sync:\n\n{e!s}\n\n"
                f"Please check the logs for more details."
            )

    def perform_on_demand_sync(self):
        """Perform on-demand sync: upload soft-deleted files and delete them locally"""
        from galileo.library.models import fitsFile
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

            # Get soft-deleted files that need to be uploaded
            soft_deleted_files = list(fitsFile.select().where(
                (fitsFile.fitsFileName.is_null(False)) &
                (fitsFile.fitsFileSoftDelete == True)
            ))

            if not soft_deleted_files:
                QMessageBox.information(
                    self,
                    "No Soft-Deleted Files",
                    "No soft-deleted files found in the database.\n\n"
                    "Soft-deleted files are created when master calibration frames are generated."
                )
                return

            # Confirm operation
            reply = QMessageBox.question(
                self,
                "On Demand Sync",
                f"This will:\n\n"
                f"1. Upload {len(soft_deleted_files)} soft-deleted files to cloud bucket: {self.cloud_config['bucket_url']}\n"
                f"2. Update cloud URLs for all uploaded files\n"
                f"3. Delete local copies of uploaded files to free up disk space\n\n"
                f"Repository path: {repo_path}\n\n"
                f"This operation cannot be undone locally (files will only exist in cloud).\n\n"
                f"Do you want to continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

            # Setup progress dialog
            progress = QProgressDialog("Starting on-demand sync...", "Cancel", 0, len(soft_deleted_files), self)
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

            # Process each soft-deleted file
            uploaded_count = 0
            deleted_count = 0
            updated_count = 0
            error_count = 0

            for i, fits_file in enumerate(soft_deleted_files):
                if progress.wasCanceled():
                    break

                try:
                    # Update progress
                    progress.setValue(i)
                    progress.setLabelText(f"Processing file {i+1} of {len(soft_deleted_files)}: {os.path.basename(fits_file.fitsFileName)}")
                    QApplication.processEvents()

                    # Get relative path from repository root
                    full_path = fits_file.fitsFileName
                    if full_path.startswith(repo_path):
                        relative_path = os.path.relpath(full_path, repo_path)
                    else:
                        # File is outside repo, use just the filename
                        relative_path = os.path.basename(full_path)

                    # Check if local file exists
                    if not os.path.exists(full_path):
                        logger.warning(f"Local soft-deleted file not found: {full_path}")
                        error_count += 1
                        continue

                    # Upload to cloud
                    success, cloud_url, message = upload_file_to_backup(
                        bucket_name, auth_info, full_path, relative_path
                    )

                    if success:
                        # Update the database with cloud URL
                        fits_file.fitsFileCloudURL = cloud_url
                        fits_file.save()
                        updated_count += 1

                        # Verify cloud backup before deleting local file
                        try:
                            from galileo.library.services.cloud import _get_gcs_client
                            client = _get_gcs_client(auth_info)
                            gcs_object_name = relative_path.replace('\\', '/')

                            if check_file_exists_in_gcs(client, bucket_name, gcs_object_name):
                                # File verified in cloud, safe to delete locally
                                os.remove(full_path)
                                deleted_count += 1
                                logger.info(f"Uploaded and deleted soft-deleted file after cloud verification: {relative_path}")
                            else:
                                logger.error(f"SAFETY CHECK FAILED: File not found in cloud, keeping local copy: {relative_path}")
                        except OSError as e:
                            logger.warning(f"Failed to delete local file {relative_path} after upload: {e}")
                        except Exception:
                            logger.exception(f"Cloud verification failed for {relative_path}, keeping local copy")

                        if "uploaded" in message.lower():
                            uploaded_count += 1
                            logger.info(f"Uploaded: {relative_path}")
                        else:
                            logger.info(f"Already exists: {relative_path}")
                    else:
                        logger.error(f"Failed to upload {relative_path}: {message}")
                        error_count += 1

                except Exception:
                    logger.exception(f"Error processing soft-deleted file {fits_file.fitsFileName}")
                    error_count += 1

            progress.setValue(len(soft_deleted_files))

            # Show results
            if not progress.wasCanceled():
                QMessageBox.information(
                    self,
                    "On Demand Sync Complete",
                    f"On-demand sync completed successfully!\n\n"
                    f"• Soft-deleted files processed: {len(soft_deleted_files)}\n"
                    f"• Files uploaded: {uploaded_count}\n"
                    f"• Local files deleted: {deleted_count}\n"
                    f"• Database records updated: {updated_count}\n"
                    f"• Errors: {error_count}\n\n"
                    f"All soft-deleted files have been moved to cloud storage."
                )
            else:
                QMessageBox.information(
                    self,
                    "On Demand Sync Cancelled",
                    f"On-demand sync was cancelled by user.\n\n"
                    f"Partial results:\n"
                    f"• Files processed: {i}\n"
                    f"• Files uploaded: {uploaded_count}\n"
                    f"• Local files deleted: {deleted_count}\n"
                    f"• Database records updated: {updated_count}\n"
                    f"• Errors: {error_count}"
                )

        except Exception as e:
            logger.exception("Error during on-demand sync")
            QMessageBox.critical(
                self,
                "On Demand Sync Error",
                f"An error occurred during on-demand sync:\n\n{e!s}\n\n"
                f"Please check the logs for more details."
            )
