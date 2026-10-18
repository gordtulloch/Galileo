# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Cloud Sync analysis: compare the bucket with the local library, find duplicates and matching local files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging
import os
from PySide6.QtWidgets import QDialog, QMessageBox, QApplication
from PySide6.QtGui import QFont
from galileo.library.services.gcs import _get_gcs_client, list_gcs_bucket_files, find_cloud_duplicates, format_file_size, _calculate_md5_hash
from galileo.library.exceptions import CloudSyncError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as _MixinBase  # type checkers see a widget (it is mixed into one)
else:
    _MixinBase = object




class CloudAnalysisMixin(_MixinBase):
    """Cloud Sync analysis: compare the bucket with the local library, find duplicates and matching local files."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def on_analyze_clicked(self):
        """Handle Analyze button click"""
        logger.info("Cloud Sync: Analyze operation requested")

        # Check if cloud is configured
        if self.cloud_config['vendor'] == 'Not configured' or self.cloud_config['bucket_url'] == 'Not configured':
            QMessageBox.warning(
                self,
                "Configuration Required",
                "Cloud sync is not configured.\n\n"
                "Please go to Options › Library and set up your cloud storage settings first."
            )
            return

        # Check if auth file exists
        auth_path = self.cloud_config['auth_file_path']
        if not auth_path or auth_path == 'Not configured' or not os.path.exists(auth_path):
            QMessageBox.warning(
                self,
                "Authentication Required",
                "Authentication file is not configured or not found.\n\n"
                "Please go to Options › Library and set up your authentication file."
            )
            return

        # Show confirmation dialog
        reply = QMessageBox.question(
            self,
            "Analyze Cloud Storage",
            f"This will:\n\n"
            f"1. Download a listing of all files in cloud bucket: {self.cloud_config['bucket_url']}\n"
            f"2. Compare with local files in the database\n"
            f"3. Update cloud URLs for files that exist in both locations\n\n"
            f"This process may take several minutes depending on the number of files.\n\n"
            f"Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                # First validate bucket access (can take time; show immediate feedback)
                from PySide6.QtWidgets import QProgressDialog
                from PySide6.QtCore import Qt

                validate_progress = QProgressDialog("Validating bucket access...", None, 0, 0, self)
                validate_progress.setWindowModality(Qt.WindowModality.WindowModal)
                validate_progress.setAutoClose(True)
                validate_progress.setAutoReset(True)
                validate_progress.setCancelButton(None)
                validate_progress.show()
                QApplication.processEvents()

                if not self.validate_bucket_access():
                    validate_progress.close()
                    return

                validate_progress.close()

                self.perform_cloud_analysis()
            except Exception as e:
                logger.exception("Error during cloud analysis")

                # Provide user-friendly error messages
                error_msg = str(e)
                if "does not exist" in error_msg.lower():
                    QMessageBox.critical(
                        self,
                        "Bucket Not Found",
                        f"The specified bucket could not be found.\n\n"
                        f"Error: {error_msg}\n\n"
                        f"Please check:\n"
                        f"• Bucket name is correct: '{self.cloud_config['bucket_url']}'\n"
                        f"• Bucket exists in your Google Cloud project\n"
                        f"• You have the correct project selected\n\n"
                        f"You can update the bucket name in Options › Library."
                    )
                elif "access denied" in error_msg.lower() or "403" in error_msg:
                    QMessageBox.critical(
                        self,
                        "Access Denied",
                        f"Access denied to the cloud storage bucket.\n\n"
                        f"Error: {error_msg}\n\n"
                        f"Please check:\n"
                        f"• Your service account has the correct permissions\n"
                        f"• The bucket exists in the correct project\n"
                        f"• Your authentication file is valid\n\n"
                        f"You may need to grant 'Storage Object Viewer' or 'Storage Object Admin' role to your service account."
                    )
                elif "authentication failed" in error_msg.lower() or "401" in error_msg:
                    QMessageBox.critical(
                        self,
                        "Authentication Failed",
                        f"Failed to authenticate with Google Cloud Storage.\n\n"
                        f"Error: {error_msg}\n\n"
                        f"Please check:\n"
                        f"• Your service account key file is valid\n"
                        f"• The file path is correct\n"
                        f"• The service account still exists\n\n"
                        f"You can update the authentication file in Options › Library."
                    )
                else:
                    QMessageBox.critical(
                        self,
                        "Analysis Error",
                        f"An error occurred during cloud analysis:\n\n{e!s}\n\n"
                        f"Please check your cloud configuration and try again."
                    )

    def validate_bucket_access(self):
        """Validate that the configured bucket exists and is accessible."""
        try:
            # Get bucket name from URL
            bucket_url = self.cloud_config['bucket_url']
            if bucket_url.startswith('gs://'):
                bucket_name = bucket_url.replace('gs://', '').rstrip('/')
            else:
                bucket_name = bucket_url.rstrip('/')

            # Try to list one file to test access

            auth_info = {'auth_string': self.cloud_config['auth_file_path']}
            client = _get_gcs_client(auth_info)
            bucket = client.bucket(bucket_name)

            # Test bucket access with minimal operation
            try:
                list(bucket.list_blobs(max_results=1))
                return True
            except Exception as e:
                if "404" in str(e) or "not found" in str(e).lower():
                    QMessageBox.critical(self, "Bucket Not Found",
                                       f"The bucket '{bucket_name}' does not exist.\n\n"
                                       f"Please check your bucket configuration or create the bucket in Google Cloud Console.")
                elif "403" in str(e) or "access denied" in str(e).lower():
                    QMessageBox.critical(self, "Access Denied",
                                       f"Access denied to bucket '{bucket_name}'.\n\n"
                                       f"Please check your service account permissions.")
                elif "401" in str(e) or "unauthorized" in str(e).lower():
                    QMessageBox.critical(self, "Authentication Failed",
                                       "Authentication failed.\n\n"
                                       "Please check your service account key file.")
                else:
                    QMessageBox.critical(self, "Cloud Error", f"Error accessing bucket: {e!s}")
                return False

        except Exception as e:
            QMessageBox.critical(self, "Configuration Error",
                               f"Error validating cloud configuration: {e!s}")
            return False

    def perform_cloud_analysis(self):
        """Perform the actual cloud analysis and update database"""
        from galileo.library.models import fitsFile

        try:
            # Show progress dialog
            from PySide6.QtWidgets import QProgressDialog
            from PySide6.QtCore import Qt

            progress = QProgressDialog("Analyzing cloud storage...", "Cancel", 0, 0, self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setAutoClose(True)
            progress.setAutoReset(True)
            progress.show()

            # Update progress
            progress.setLabelText("Connecting to cloud storage...")
            QApplication.processEvents()

            # Prepare auth info for cloud module
            auth_info = {
                'auth_string': self.cloud_config['auth_file_path']
            }

            # Get cloud file listing
            progress.setLabelText("Downloading file listing from cloud...")
            QApplication.processEvents()

            cloud_files = self.get_cloud_file_list(
                self.cloud_config['bucket_url'],
                auth_info
            )

            if progress.wasCanceled():
                return

            # Analyze for duplicates in cloud storage
            progress.setLabelText("Analyzing cloud storage for duplicates...")
            QApplication.processEvents()

            duplicate_analysis = find_cloud_duplicates(cloud_files)

            if progress.wasCanceled():
                return

            # Update progress
            progress.setLabelText("Analyzing matches with local files...")
            progress.setMaximum(len(cloud_files))
            QApplication.processEvents()

            # Track different types of matches
            matches_found = 0
            filename_matches = 0
            hash_matches = 0
            partial_matches = 0

            for i, cloud_file in enumerate(cloud_files):
                if progress.wasCanceled():
                    break

                progress.setValue(i)
                filename = cloud_file.get('name', '').split('/')[-1]
                progress.setLabelText(f"Analyzing: {filename}")
                QApplication.processEvents()

                # Try to find matching local file using enhanced matching
                local_file = self.find_matching_local_file(cloud_file)

                if local_file:
                    # Update the cloud URL in the database
                    cloud_url = self.build_cloud_url(cloud_file)
                    fitsFile.update(fitsFileCloudURL=cloud_url).where(
                        fitsFile.fitsFileId == local_file.fitsFileId
                    ).execute()
                    matches_found += 1

                    # Track match type for reporting
                    if local_file.fitsFileName == filename:
                        filename_matches += 1
                    elif cloud_file.get('md5_hash'):
                        try:
                            local_hash = _calculate_md5_hash(local_file.fitsFilePath)
                            if local_hash == cloud_file['md5_hash']:
                                hash_matches += 1
                            else:
                                partial_matches += 1
                        except Exception:
                            partial_matches += 1
                    else:
                        partial_matches += 1
                    logger.info(f"Updated cloud URL for file: {local_file.fitsFileName}")

            progress.close()

            # Build detailed results message
            results_message = (
                f"Cloud analysis completed successfully!\n\n"
                f"📊 Analysis Results:\n"
                f"• Cloud files found: {len(cloud_files)}\n"
                f"• Total local matches: {matches_found}\n"
                f"• Database records updated: {matches_found}\n\n"
            )

            # Add duplicate analysis results
            if duplicate_analysis.get('duplicate_groups', 0) > 0:
                wasted_space = duplicate_analysis.get('wasted_space_bytes', 0)
                results_message += (
                    f"🔍 Duplicate Detection:\n"
                    f"• Duplicate file groups: {duplicate_analysis['duplicate_groups']}\n"
                    f"• Total duplicate files: {duplicate_analysis['duplicate_files']}\n"
                    f"• Wasted storage space: {format_file_size(wasted_space)}\n\n"
                )
            else:
                results_message += (
                    "✅ No duplicates found in cloud storage!\n\n"
                )

            if matches_found > 0:
                results_message += (
                    f"🔍 Local Match Breakdown:\n"
                    f"• Exact filename matches: {filename_matches}\n"
                    f"• Hash-verified matches: {hash_matches}\n"
                    f"• Partial/fallback matches: {partial_matches}\n\n"
                )

            results_message += (
                "✅ Files with cloud URLs can now be synchronized.\n"
                "💡 Use the Sync button to upload/download files."
            )

            # Show results with option to view duplicate details
            result = QMessageBox.information(
                self,
                "Analysis Complete",
                results_message,
                QMessageBox.Ok | (QMessageBox.Help if duplicate_analysis.get('duplicate_groups', 0) > 0 else QMessageBox.Ok)
            )

            # If user clicked Help and there are duplicates, show detailed report
            if (result == QMessageBox.Help and
                duplicate_analysis.get('duplicate_groups', 0) > 0):
                self.show_duplicate_details(duplicate_analysis)

        except Exception:
            if 'progress' in locals():
                progress.close()
            raise

    def show_duplicate_details(self, duplicate_analysis):
        """Show detailed duplicate file report in a separate dialog"""
        try:
            details = duplicate_analysis.get('details', {})
            if not details:
                QMessageBox.information(self, "No Details", "No duplicate details available.")
                return

            # Create detailed report text
            report_lines = [
                "🔍 Detailed Duplicate Analysis Report",
                "=" * 50,
                "",
                "Summary:",
                f"• Total cloud files: {duplicate_analysis.get('total_files', 0)}",
                f"• Files with hash data: {duplicate_analysis.get('files_with_hashes', 0)}",
                f"• Duplicate groups found: {duplicate_analysis.get('duplicate_groups', 0)}",
                f"• Total duplicate files: {duplicate_analysis.get('duplicate_files', 0)}",
                f"• Wasted storage space: {format_file_size(duplicate_analysis.get('wasted_space_bytes', 0))}",
                "",
                "Duplicate Groups:",
                "-" * 30
            ]

            # Add details for each duplicate group
            for i, (hash_value, group_info) in enumerate(details.items(), 1):
                files = group_info.get('files', [])
                file_size = group_info.get('size', 0)
                wasted_space = group_info.get('wasted_space', 0)

                report_lines.extend([
                    "",
                    f"Group {i}: {len(files)} identical files",
                    f"  File size: {format_file_size(file_size)}",
                    f"  Wasted space: {format_file_size(wasted_space)}",
                    f"  MD5 hash: {hash_value[:16]}...",
                    "  Files:"
                ])

                for file_info in files:
                    file_name = file_info.get('name', 'Unknown')
                    file_path = file_name.split('/')[-1] if '/' in file_name else file_name
                    report_lines.append(f"    • {file_path}")
                    if len(file_name) > 50:  # Show full path for long names
                        report_lines.append(f"      Path: {file_name}")

            # Join all lines into report text
            report_text = "\n".join(report_lines)

            # Create and show dialog
            from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QPushButton

            dialog = QDialog(self)
            dialog.setWindowTitle("Cloud Storage Duplicate Analysis")
            dialog.setModal(True)
            dialog.resize(700, 500)

            layout = QVBoxLayout(dialog)

            # Add text area
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setPlainText(report_text)
            text_edit.setFont(QFont("Courier", 10))
            layout.addWidget(text_edit)

            # Add close button
            close_button = QPushButton("Close")
            close_button.clicked.connect(dialog.accept)
            layout.addWidget(close_button)

            dialog.exec()

        except Exception as e:
            logger.exception("Error showing duplicate details")
            QMessageBox.critical(self, "Error", f"Failed to show duplicate details: {e!s}")

    def get_cloud_file_list(self, bucket_name, auth_info):
        """Get list of files from cloud storage"""
        try:
            logger.info(f"Getting file list from bucket: {bucket_name}")

            # Use the list function
            cloud_files = list_gcs_bucket_files(bucket_name, auth_info)

            logger.info(f"Retrieved {len(cloud_files)} files from cloud storage")
            return cloud_files

        except Exception as e:
            logger.exception("Error getting cloud file list")
            raise CloudSyncError(f"Failed to get cloud file listing: {e!s}") from e

    def find_matching_local_file(self, cloud_file):
        """Find local file that matches the cloud file using filename and hash-based matching"""
        from galileo.library.models import fitsFile

        try:
            # Get the filename from the cloud file path
            filename = cloud_file.get('name', '').split('/')[-1]

            if not filename:
                return None

            # Try to match by filename first (fastest method)
            filename_match = None
            try:
                filename_match = fitsFile.get(fitsFile.fitsFileName == filename)
                logger.debug(f"Found exact filename match: {filename}")

                # If we have a filename match and hash functions are available,
                # verify content matches using hash comparison
                if cloud_file.get('md5_hash'):
                    try:
                        local_hash = _calculate_md5_hash(filename_match.fitsFilePath)
                        cloud_hash = cloud_file['md5_hash']

                        if local_hash == cloud_hash:
                            logger.debug(f"Hash verification successful for {filename}")
                            return filename_match
                        else:
                            logger.info(f"Filename match but content differs for {filename} (hash mismatch)")
                            # Continue to other matching methods
                    except Exception as e:
                        logger.warning(f"Could not verify hash for {filename}: {e}")
                        # Return filename match as fallback
                        return filename_match
                else:
                    # No hash available, trust filename match
                    return filename_match

            except fitsFile.DoesNotExist:
                pass

            # Try to match by partial filename (without extension)
            try:
                base_filename = filename.rsplit('.', 1)[0]  # Remove extension
                partial_match = fitsFile.get(fitsFile.fitsFileName.contains(base_filename))
                logger.debug(f"Found partial filename match: {base_filename}")

                # If we have a partial match and hash functions are available, verify with hash
                if cloud_file.get('md5_hash'):
                    try:
                        local_hash = _calculate_md5_hash(partial_match.fitsFilePath)
                        cloud_hash = cloud_file['md5_hash']

                        if local_hash == cloud_hash:
                            logger.debug(f"Hash verification successful for partial match {base_filename}")
                            return partial_match
                        else:
                            logger.debug(f"Partial filename match but content differs for {base_filename}")
                    except Exception as e:
                        logger.warning(f"Could not verify hash for partial match {base_filename}: {e}")
                        return partial_match
                else:
                    return partial_match

            except fitsFile.DoesNotExist:
                pass

            # Try hash-based matching across all local files (most thorough but slower)
            if cloud_file.get('md5_hash'):
                try:
                    cloud_hash = cloud_file['md5_hash']
                    logger.debug(f"Attempting hash-based matching for {filename}")

                    # Get all local files and check their hashes
                    # Note: This could be optimized by storing hashes in the database
                    local_files = fitsFile.select()
                    for local_file in local_files:
                        try:
                            if os.path.exists(local_file.fitsFilePath):
                                local_hash = _calculate_md5_hash(local_file.fitsFilePath)
                                if local_hash == cloud_hash:
                                    logger.info(f"Found hash-based match: {local_file.fitsFileName} matches cloud file {filename}")
                                    return local_file
                        except Exception as e:
                            logger.debug(f"Could not calculate hash for {local_file.fitsFilePath}: {e}")
                            continue

                except Exception as e:
                    logger.warning(f"Error during hash-based matching: {e}")

            logger.debug(f"No local match found for cloud file: {filename}")
            return None

        except Exception:
            logger.exception("Error finding matching local file")
            return None

    def build_cloud_url(self, cloud_file):
        """Build the cloud URL for a file"""
        try:
            # Use the URL already provided by the cloud listing
            if cloud_file.get('url'):
                return cloud_file['url']

            # Fallback: Build URL based on cloud vendor and file location
            if self.cloud_config['vendor'] == 'Google Cloud Storage':
                bucket = self.cloud_config['bucket_url']
                file_path = cloud_file.get('name', '')
                return f"gs://{bucket}/{file_path}"

            # Add other cloud vendors as needed
            return ''

        except Exception:
            logger.exception("Error building cloud URL")
            return ''
