# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Sessions screen's bulk actions: clear, link, auto-calibrate and regenerate sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging
import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QProgressDialog, QApplication, QMessageBox
from galileo.library.core import fitsProcessing
from galileo.library.models import fitsFile as FitsFileModel, fitsSession as FitsSessionModel

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as _MixinBase  # type checkers see a widget (it is mixed into one)
else:
    _MixinBase = object




class SessionsRegenerateMixin(_MixinBase):
    """The Sessions screen's bulk actions: clear, link, auto-calibrate and regenerate sessions."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def clear_sessions(self):
        """Clear all Session records from the database and refresh the display."""
        try:
            logger.info("Clearing all sessions from database")

            # Clear session references in files first to avoid foreign key constraints
            FitsFileModel.update(fitsFileSession=None).execute()

            # Delete all sessions
            deleted_count = FitsSessionModel.delete().execute()

            logger.info(f"Cleared {deleted_count} sessions from database")

            # Refresh the display
            self.load_sessions_data()

            QMessageBox.information(self, "Sessions Cleared",
                                  f"Successfully cleared {deleted_count} sessions from the database.")

        except Exception as e:
            logger.exception("Error clearing sessions")
            QMessageBox.critical(self, "Error", f"Failed to clear sessions: {e}")

    def link_sessions(self):
        """Link calibration sessions to light sessions with progress dialog."""
        try:
            logger.info("Starting session linking")

            # Create progress dialog
            progress_dialog = QProgressDialog("Initializing...", "Cancel", 0, 100, self)
            progress_dialog.setWindowTitle("Linking Sessions")
            progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            progress_dialog.setMinimumDuration(0)  # Show immediately
            progress_dialog.setValue(0)
            progress_dialog.show()
            QApplication.processEvents()

            # Create the processor
            processor = fitsProcessing()

            # Define progress callback
            def progress_callback(current, total, description):
                if progress_dialog.wasCanceled():
                    return False

                if total > 0:
                    progress = int((current / total) * 100)
                    progress_dialog.setValue(progress)
                    progress_dialog.setLabelText(f"Linking sessions {current}/{total}: {description}")
                else:
                    progress_dialog.setLabelText(f"Processing: {description}")

                QApplication.processEvents()
                return not progress_dialog.wasCanceled()

            # Run the session linking
            updated_sessions = processor.linkSessions(progress_callback)

            progress_dialog.close()

            if progress_dialog.wasCanceled():
                logger.info("Session linking cancelled by user")
                QMessageBox.information(self, "Cancelled", "Session linking was cancelled.")
                return

            # Refresh the display
            self.load_sessions_data()

            logger.info(f"Linked {len(updated_sessions)} sessions")
            QMessageBox.information(self, "Sessions Linked",
                                  f"Successfully linked {len(updated_sessions)} light sessions with calibration sessions.")

        except Exception as e:
            if 'progress_dialog' in locals():
                progress_dialog.close()
            logger.exception("Error linking sessions")
            QMessageBox.critical(self, "Error", f"Failed to link sessions: {e}")

    def run_auto_calibration(self):
        """Run the auto-calibration workflow with customizable operation selection"""
        try:
            from .auto_calibration_dialog import AutoCalibrationDialog
            from PySide6.QtWidgets import QDialog

            # Create and show the workflow selection dialog
            dialog = AutoCalibrationDialog(self)
            result = dialog.exec()

            # Refresh the sessions display if workflow completed
            if result == QDialog.DialogCode.Accepted:
                self.load_sessions_data()

        except Exception as e:
            logger.exception("Error running auto-calibration workflow")
            QMessageBox.critical(self, "Error", f"Failed to run auto-calibration workflow:\n\n{e}")

    def regenerate_sessions(self):
        """Regenerate all sessions: Clear → Update Lights → Update Calibrations → Link Sessions"""
        try:
            # Ask user to choose regeneration mode
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Regenerate Sessions")
            msg_box.setText("Choose session regeneration mode:")
            msg_box.setDetailedText(
                "All Sessions: Clear all existing sessions and recreate them from all FITS files.\n\n"
                "New Only: Only create sessions for FITS files that don't currently have a session assigned."
            )

            all_button = msg_box.addButton("All Sessions", QMessageBox.AcceptRole)
            new_only_button = msg_box.addButton("New Only", QMessageBox.AcceptRole)
            cancel_button = msg_box.addButton("Cancel", QMessageBox.RejectRole)

            msg_box.setDefaultButton(new_only_button)
            msg_box.exec()

            clicked_button = msg_box.clickedButton()

            if clicked_button == cancel_button:
                return
            elif clicked_button == all_button:
                # Confirm the destructive operation
                reply = QMessageBox.question(self, "Confirm Regenerate All",
                                           "This will clear ALL existing sessions and recreate them from FITS files.\n\n"
                                           "Are you sure you want to continue?",
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                           QMessageBox.StandardButton.No)

                if reply != QMessageBox.StandardButton.Yes:
                    return

                # Call the full regeneration method (existing behavior)
                self._do_regenerate_sessions()
            elif clicked_button == new_only_button:
                # Call the new-only regeneration method
                self._do_regenerate_sessions_new_only(show_user_messages=True)

        except Exception as e:
            logger.exception("Error in regenerate_sessions")
            QMessageBox.critical(self, "Error", f"Session regeneration failed: {e}")

    def _do_regenerate_sessions(self):
        """Internal method that performs the actual session regeneration without confirmation dialog"""
        try:
            logger.info("Starting complete session regeneration")

            # Step 1: Clear all existing sessions
            logger.info("Step 1: Clearing existing sessions")
            try:
                # Clear session references in files first to avoid foreign key constraints
                FitsFileModel.update(fitsFileSession=None).execute()

                # Delete all sessions
                deleted_count = FitsSessionModel.delete().execute()
                logger.info(f"Cleared {deleted_count} existing sessions")

                # Refresh display immediately to show empty sessions
                self.load_sessions_data()
                QApplication.processEvents()

            except Exception as e:
                logger.exception("Error clearing sessions")
                QMessageBox.critical(self, "Error", f"Failed to clear existing sessions: {e}")
                return

            # Step 2: Create light sessions
            logger.info("Step 2: Creating light sessions")
            light_sessions = []
            try:
                progress_dialog = QProgressDialog("Creating light sessions...", "Cancel", 0, 100, self)
                progress_dialog.setWindowTitle("Regenerating Sessions - Step 2/4")
                progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
                progress_dialog.setMinimumDuration(0)
                progress_dialog.setValue(0)
                progress_dialog.show()
                QApplication.processEvents()

                processor = fitsProcessing()

                # Track if operation was cancelled
                was_cancelled = False

                def light_progress_callback(current, total, description):
                    nonlocal was_cancelled
                    if was_cancelled:
                        return False
                    if progress_dialog.wasCanceled():
                        was_cancelled = True
                        return False
                    if total > 0:
                        progress = int((current / total) * 100)
                        progress_dialog.setValue(progress)
                        # Extract filename from full path in description
                        filename = os.path.basename(description) if description else ""
                        progress_dialog.setLabelText(f"Light sessions {current}/{total}: {filename}")
                    QApplication.processEvents()
                    return True

                light_sessions = processor.createLightSessions(light_progress_callback)
                progress_dialog.close()

                if was_cancelled:
                    logger.info("Session regeneration cancelled during light sessions creation")
                    QMessageBox.information(self, "Cancelled", "Session regeneration was cancelled.")
                    return

                logger.info(f"Created {len(light_sessions)} light sessions")

            except Exception as e:
                if 'progress_dialog' in locals():
                    progress_dialog.close()
                logger.exception("Error creating light sessions")
                QMessageBox.critical(self, "Error", f"Failed to create light sessions: {e}")
                return

            # Step 3: Create calibration sessions
            logger.info("Step 3: Creating calibration sessions")
            cal_sessions = []
            try:
                progress_dialog = QProgressDialog("Creating calibration sessions...", "Cancel", 0, 100, self)
                progress_dialog.setWindowTitle("Regenerating Sessions - Step 3/4")
                progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
                progress_dialog.setMinimumDuration(0)
                progress_dialog.setValue(0)
                progress_dialog.show()
                QApplication.processEvents()

                # Track if operation was cancelled
                was_cancelled = False

                def cal_progress_callback(current, total, description):
                    nonlocal was_cancelled
                    if was_cancelled:
                        return False
                    if progress_dialog.wasCanceled():
                        was_cancelled = True
                        return False
                    if total > 0:
                        progress = int((current / total) * 100)
                        progress_dialog.setValue(progress)
                        # Extract filename from description (format: "Type: /path/to/file")
                        if ": " in description:
                            file_type, file_path = description.split(": ", 1)
                            filename = os.path.basename(file_path)
                            display_text = f"{file_type}: {filename}"
                        else:
                            display_text = os.path.basename(description) if description else ""
                        progress_dialog.setLabelText(f"Calibration sessions {current}/{total}: {display_text}")
                    QApplication.processEvents()
                    return True

                cal_sessions = processor.createCalibrationSessions(cal_progress_callback)
                progress_dialog.close()

                if was_cancelled:
                    logger.info("Session regeneration cancelled during calibration sessions creation")
                    QMessageBox.information(self, "Cancelled", "Session regeneration was cancelled.")
                    return

                logger.info(f"Created {len(cal_sessions)} calibration sessions")

            except Exception as e:
                if 'progress_dialog' in locals():
                    progress_dialog.close()
                logger.exception("Error creating calibration sessions")
                QMessageBox.critical(self, "Error", f"Failed to create calibration sessions: {e}")
                return

            # Step 4: Link sessions
            logger.info("Step 4: Linking Master sessions")
            linked_sessions = []
            try:
                progress_dialog = QProgressDialog("Linking Master sessions...", "Cancel", 0, 100, self)
                progress_dialog.setWindowTitle("Regenerating Sessions - Step 4/4")
                progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
                progress_dialog.setMinimumDuration(0)
                progress_dialog.setValue(0)
                progress_dialog.show()
                QApplication.processEvents()

                # Track if operation was cancelled
                was_cancelled = False

                def link_progress_callback(current, total, description):
                    nonlocal was_cancelled
                    if was_cancelled:
                        return False
                    if progress_dialog.wasCanceled():
                        was_cancelled = True
                        return False
                    if total > 0:
                        progress = int((current / total) * 100)
                        progress_dialog.setValue(progress)
                        # For linking, description should be object names, but handle file paths just in case
                        display_text = os.path.basename(description) if description and os.path.sep in description else description
                        progress_dialog.setLabelText(f"Linking {current}/{total}: {display_text}")
                    QApplication.processEvents()
                    return True

                linked_sessions = processor.linkSessions(link_progress_callback)
                progress_dialog.close()

                if was_cancelled:
                    logger.info("Session regeneration cancelled during linking")
                    QMessageBox.information(self, "Cancelled", "Session regeneration was cancelled.")
                    return

                logger.info(f"Linked {len(linked_sessions)} sessions")

            except Exception as e:
                if 'progress_dialog' in locals():
                    progress_dialog.close()
                logger.exception("Error linking sessions")
                QMessageBox.critical(self, "Error", f"Failed to link sessions: {e}")
                return

            # Final step: Refresh the display
            self.load_sessions_data()

            # Show completion message
            total_light = len(light_sessions) if 'light_sessions' in locals() else 0
            total_cal = len(cal_sessions) if 'cal_sessions' in locals() else 0
            total_linked = len(linked_sessions) if 'linked_sessions' in locals() else 0

            logger.info(f"Session regeneration complete: {total_light} light, {total_cal} calibration, {total_linked} linked")

        except Exception as e:
            logger.exception("Unexpected error during session regeneration")
            QMessageBox.critical(self, "Error", f"Unexpected error during session regeneration: {e}")

    def _do_regenerate_sessions_new_only(self, show_user_messages: bool = True):
        """Regenerate sessions only for files without sessions assigned."""
        try:
            logger.info("Starting new-only session regeneration (files without sessions)")

            # Count unassigned files first
            unassigned_light_count = FitsFileModel.select().where(
                FitsFileModel.fitsFileSession.is_null(),
                FitsFileModel.fitsFileType == 'LIGHT FRAME',
                FitsFileModel.fitsFileSoftDelete == False
            ).count()

            unassigned_cal_count = FitsFileModel.select().where(
                FitsFileModel.fitsFileSession.is_null(),
                FitsFileModel.fitsFileType.in_(['BIAS FRAME', 'DARK FRAME', 'FLAT FIELD']),
                FitsFileModel.fitsFileSoftDelete == False
            ).count()

            total_unassigned = unassigned_light_count + unassigned_cal_count

            if total_unassigned == 0:
                if show_user_messages:
                    QMessageBox.information(
                        self,
                        "No Unassigned Files",
                        "All FITS files already have sessions assigned.\n\n"
                        "No new sessions need to be created.",
                    )
                return

            logger.info(f"Found {unassigned_light_count} unassigned light files and {unassigned_cal_count} unassigned calibration files")

            # Step 1: Create light sessions for unassigned files
            logger.info("Step 1: Creating light sessions for unassigned files")
            light_sessions = []
            try:
                progress_dialog = QProgressDialog("Creating light sessions for unassigned files...", "Cancel", 0, 100, self)
                progress_dialog.setWindowTitle("Creating Sessions - Step 1/3")
                progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
                progress_dialog.setMinimumDuration(0)
                progress_dialog.setValue(0)
                progress_dialog.show()
                QApplication.processEvents()

                processor = fitsProcessing()

                # Track if operation was cancelled
                was_cancelled = False

                def light_progress_callback(current, total, description):
                    nonlocal was_cancelled
                    if was_cancelled:
                        return False
                    if progress_dialog.wasCanceled():
                        was_cancelled = True
                        return False
                    if total > 0:
                        progress = int((current / total) * 100)
                        progress_dialog.setValue(progress)
                        filename = os.path.basename(description) if description else ""
                        progress_dialog.setLabelText(f"Light sessions {current}/{total}: {filename}")
                    QApplication.processEvents()
                    return True

                light_sessions = processor.createLightSessions(light_progress_callback)
                progress_dialog.close()

                if was_cancelled:
                    logger.info("New-only session regeneration cancelled during light sessions creation")
                    if show_user_messages:
                        QMessageBox.information(self, "Cancelled", "Session creation was cancelled.")
                    return

                logger.info(f"Created {len(light_sessions)} light sessions for unassigned files")

            except Exception as e:
                if 'progress_dialog' in locals():
                    progress_dialog.close()
                logger.exception("Error creating light sessions")
                if show_user_messages:
                    QMessageBox.critical(self, "Error", f"Failed to create light sessions: {e}")
                return

            # Step 2: Create calibration sessions for unassigned files
            logger.info("Step 2: Creating calibration sessions for unassigned files")
            cal_sessions = []
            try:
                progress_dialog = QProgressDialog("Creating calibration sessions for unassigned files...", "Cancel", 0, 100, self)
                progress_dialog.setWindowTitle("Creating Sessions - Step 2/3")
                progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
                progress_dialog.setMinimumDuration(0)
                progress_dialog.setValue(0)
                progress_dialog.show()
                QApplication.processEvents()

                was_cancelled = False

                def cal_progress_callback(current, total, description):
                    nonlocal was_cancelled
                    if was_cancelled:
                        return False
                    if progress_dialog.wasCanceled():
                        was_cancelled = True
                        return False
                    if total > 0:
                        progress = int((current / total) * 100)
                        progress_dialog.setValue(progress)
                        if ": " in description:
                            file_type, file_path = description.split(": ", 1)
                            filename = os.path.basename(file_path)
                            display_text = f"{file_type}: {filename}"
                        else:
                            display_text = os.path.basename(description) if description else ""
                        progress_dialog.setLabelText(f"Calibration sessions {current}/{total}: {display_text}")
                    QApplication.processEvents()
                    return True

                cal_sessions = processor.createCalibrationSessions(cal_progress_callback)
                progress_dialog.close()

                if was_cancelled:
                    logger.info("New-only session regeneration cancelled during calibration sessions creation")
                    if show_user_messages:
                        QMessageBox.information(self, "Cancelled", "Session creation was cancelled.")
                    return

                logger.info(f"Created {len(cal_sessions)} calibration sessions for unassigned files")

            except Exception as e:
                if 'progress_dialog' in locals():
                    progress_dialog.close()
                logger.exception("Error creating calibration sessions")
                if show_user_messages:
                    QMessageBox.critical(self, "Error", f"Failed to create calibration sessions: {e}")
                return

            # Step 3: Link sessions
            logger.info("Step 3: Linking calibration sessions to light sessions")
            linked_sessions = []
            try:
                progress_dialog = QProgressDialog("Linking calibration sessions...", "Cancel", 0, 100, self)
                progress_dialog.setWindowTitle("Creating Sessions - Step 3/3")
                progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
                progress_dialog.setMinimumDuration(0)
                progress_dialog.setValue(0)
                progress_dialog.show()
                QApplication.processEvents()

                was_cancelled = False

                def link_progress_callback(current, total, description):
                    nonlocal was_cancelled
                    if was_cancelled:
                        return False
                    if progress_dialog.wasCanceled():
                        was_cancelled = True
                        return False
                    if total > 0:
                        progress = int((current / total) * 100)
                        progress_dialog.setValue(progress)
                        progress_dialog.setLabelText(f"Linking sessions {current}/{total}")
                    QApplication.processEvents()
                    return True

                linked_sessions = processor.linkSessions(link_progress_callback)
                progress_dialog.close()

                if was_cancelled:
                    logger.info("New-only session regeneration cancelled during linking")
                    if show_user_messages:
                        QMessageBox.information(self, "Cancelled", "Session creation was cancelled.")
                    return

                logger.info(f"Linked {len(linked_sessions)} sessions")

            except Exception as e:
                if 'progress_dialog' in locals():
                    progress_dialog.close()
                logger.exception("Error linking sessions")
                if show_user_messages:
                    QMessageBox.critical(self, "Error", f"Failed to link sessions: {e}")
                return

            # Final step: Refresh the display
            self.load_sessions_data()

            # Show completion message
            total_light = len(light_sessions) if 'light_sessions' in locals() else 0
            total_cal = len(cal_sessions) if 'cal_sessions' in locals() else 0
            total_linked = len(linked_sessions) if 'linked_sessions' in locals() else 0

            completion_message = (f"Session creation completed successfully!\n\n"
                                f"Created {total_light} new light sessions\n"
                                f"Created {total_cal} new calibration sessions\n"
                                f"Linked {total_linked} light sessions with calibrations\n\n"
                                f"Only files without existing sessions were processed.")

            if show_user_messages:
                QMessageBox.information(self, "Session Creation Complete", completion_message)
            logger.info(f"New-only session creation complete: {total_light} light, {total_cal} calibration, {total_linked} linked")

        except Exception as e:
            logger.exception("Unexpected error during new-only session regeneration")
            if show_user_messages:
                QMessageBox.critical(self, "Error", f"Unexpected error during session creation: {e}")

    def auto_regenerate_sessions(self):
        """Auto-regenerate sessions without user confirmation (for use after file imports)"""
        try:
            logger.info("Auto-regenerating sessions after file import")

            # Create a progress dialog for auto-regeneration
            progress_dialog = QProgressDialog("Auto-regenerating sessions...", None, 0, 100, self)
            progress_dialog.setWindowTitle("Updating Sessions")
            progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setValue(0)
            progress_dialog.show()
            QApplication.processEvents()

            # Only build sessions for newly imported (unassigned) files.
            self._do_regenerate_sessions_new_only(show_user_messages=False)

            # Close the progress dialog
            progress_dialog.close()

            logger.info("Auto-regeneration completed")

        except Exception:
            logger.exception("Error in auto_regenerate_sessions")
            if 'progress_dialog' in locals():
                progress_dialog.close()
