# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Sessions tree's double-click, right-click menu and the actions behind it (view, thumbnail, checkout)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging
import os
import glob
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QTreeWidgetItem
from galileo.library.models import fitsFile as FitsFileModel, fitsSession as FitsSessionModel, Masters
from galileo.library.config import load_config as load_library_config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as _MixinBase  # type checkers see a widget (it is mixed into one)
else:
    _MixinBase = object




class SessionsMenuMixin(_MixinBase):
    """The Sessions tree's double-click, right-click menu and the actions behind it (view, thumbnail, checkout)."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Handle double-clicks in the sessions tree.

        Requirement: double-clicking the Thumbnail column opens the stacked image
        for that light session (if available) in the external viewer.
        """
        try:
            THUMBNAIL_COLUMN = 1
            if column != THUMBNAIL_COLUMN:
                return

            parent = item.parent()
            if not parent:
                return  # ignore parent object rows

            session_id = item.data(0, Qt.ItemDataRole.UserRole)
            if not session_id:
                return

            # Only respond if a thumbnail exists for this session
            thumb_path = self._get_thumbnail_path(str(session_id))
            if not (thumb_path and os.path.exists(thumb_path)):
                return

            # Resolve session + find best matching stack output
            try:
                session = FitsSessionModel.get_by_id(str(session_id))
            except Exception:
                session = None
            if not session:
                QMessageBox.warning(self, "Error", "Session not found in database")
                return

            object_name = parent.text(0) or (session.fitsSessionObjectName or "Unknown")
            if object_name in ['Bias', 'Dark', 'Flat', 'FlatDark']:
                return

            out_dir = self._get_session_stack_output_dir(session)
            if not out_dir:
                QMessageBox.information(self, "No Stack", "No stack location found for this session.")
                return

            stack_path = self._find_best_stack_for_session(session=session, object_name=object_name, out_dir=out_dir)
            if not stack_path:
                QMessageBox.information(self, "No Stack", "No stacked FITS file found for this session.")
                return

            self._open_path_in_external_viewer(stack_path)

        except Exception:
            logger.exception("Error handling thumbnail double-click")

    def _get_session_stack_output_dir(self, session: FitsSessionModel) -> str:
        """Best-effort directory where stack outputs are expected to be written."""
        try:
            telescope = getattr(session, 'fitsSessionTelescope', None) or ''
            instrument = getattr(session, 'fitsSessionImager', None) or ''
            is_precalibrated_session = (
                ('itelescope' in telescope.lower()) or
                ('seestar' in instrument.lower())
            )

            base = (
                (FitsFileModel.fitsFileSession == session.fitsSessionId)
                & (FitsFileModel.fitsFileSoftDelete == False)
                & (FitsFileModel.fitsFileType.in_(['LIGHT', 'LIGHT FRAME', 'Light Frame']))
            )

            if is_precalibrated_session:
                candidates = list(FitsFileModel.select().where(base))
            else:
                candidates = list(FitsFileModel.select().where(base & (FitsFileModel.fitsFileCalibrated == 1)))

            for f in candidates:
                p = getattr(f, 'fitsFileName', None)
                if p and os.path.exists(p):
                    return os.path.dirname(p)

        except Exception:
            logger.debug("Could not determine a light-frame directory for the session", exc_info=True)

        return ''

    def _find_best_stack_for_session(self, session: FitsSessionModel, object_name: str, out_dir: str) -> str:
        """Find the most likely stack FITS file for a session.

        Preference order:
          1) photometric stacks
          2) deep stacks (stack_*)
          3) sample stacks
        If multiple matches exist, choose the newest by mtime.
        """
        try:
            from galileo.library.core.utils import sanitize_filesystem_name

            safe_object = sanitize_filesystem_name(object_name or 'Unknown')
            date_str = str(session.fitsSessionDate) if session.fitsSessionDate else 'unknown_date'
            session_id = str(session.fitsSessionId)

            patterns = [
                os.path.join(out_dir, f"photometric_stack_{safe_object}_{date_str}*.fits"),
                os.path.join(out_dir, f"stack_{safe_object}_{date_str}_{session_id}*.fits"),
                os.path.join(out_dir, f"stack_{safe_object}_{date_str}*.fits"),
                os.path.join(out_dir, f"sample_stack_{safe_object}_{date_str}*.fits"),
                os.path.join(out_dir, f"*stack*{session_id}*.fits"),
            ]

            matches = []
            for pat in patterns:
                matches.extend([p for p in glob.glob(pat) if os.path.isfile(p)])

            # De-dupe while preserving order
            seen = set()
            unique = []
            for p in matches:
                if p not in seen:
                    seen.add(p)
                    unique.append(p)

            if not unique:
                return ''

            # Pick newest mtime
            best = max(unique, key=lambda p: os.path.getmtime(p))
            return best if os.path.exists(best) else ''

        except Exception:
            return ''

    @staticmethod
    def _classify_selection(selected_items):
        """Split the selected tree items into ``(light_sessions, calibration_sessions, parent_objects)``."""
        light_sessions = []
        calibration_sessions = []
        parent_objects = []

        for selected_item in selected_items:
            parent = selected_item.parent()
            if not parent:
                # This is a parent item (object name)
                parent_objects.append(selected_item)
                continue

            # This is a session item
            if parent.text(0) in ['Bias', 'Dark', 'Flat', 'FlatDark']:
                calibration_sessions.append(selected_item)
            else:
                light_sessions.append(selected_item)
        return light_sessions, calibration_sessions, parent_objects

    def _add_light_session_actions(self, context_menu, light_sessions) -> dict:
        """Check-out, calibrate, stack and thumbnail entries for the selected light session(s)."""
        actions: dict = {}
        if light_sessions:
            if len(light_sessions) == 1:
                actions["checkout"] = context_menu.addAction("📂 Check out")
                actions["checkout"].setToolTip("Create symbolic links for this session's files")
            else:
                actions["checkout"] = context_menu.addAction(f"📂 Check out ({len(light_sessions)} sessions)")
                actions["checkout"].setToolTip("Create symbolic links for selected light sessions")

        if len(light_sessions) == 1:
            actions["calibrate"] = context_menu.addAction("⚙️ Calibrate")
            actions["calibrate"].setToolTip("Calibrate light frames in this session using available master frames")

            actions["stack"] = context_menu.addAction("📚 Stack")
            actions["stack"].setToolTip(
                "Stack light frames and open the result in the external FITS viewer. If the session is not precalibrated, calibration runs automatically if needed."
            )

            actions["photometric_stack"] = context_menu.addAction("📚 Stack (photometric)")
            actions["photometric_stack"].setToolTip(
                "Create a photometry-safe stack (registered mean, no sigma clipping) and open the result in the external FITS viewer. If the session is not precalibrated, calibration runs automatically if needed."
            )

            actions["regenerate_thumbnail"] = context_menu.addAction("🖼️ Regenerate Thumbnail")
            actions["regenerate_thumbnail"].setToolTip(
                "Recreate the session thumbnail from the most recent stack file (photometric/deep/sample) if available."
            )
        return actions

    @staticmethod
    def _add_view_master_action(context_menu, selected_items, parent_objects):
        """"View Master" entry when exactly one session is selected and it has a master frame."""
        if len(selected_items) != 1 or parent_objects:
            return None
        session_id = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        if not session_id:
            return None
        try:
            master = Masters.select().where(
                Masters.source_session_id == session_id,
                Masters.soft_delete == False
            ).first()
            if not master:
                logger.debug(f"No master found for session {session_id}")
                return None
            action = context_menu.addAction("🔍 View Master")
            action.setToolTip(f"Open master {master.master_type} frame in external FITS viewer")
            logger.debug(f"Found master for session {session_id}: {master.master_path}")
            return action
        except Exception:
            logger.exception("Error checking for master")
            return None

    def show_context_menu(self, position):
        """Show context menu for session items with master frame management"""
        item = self.sessions_tree.itemAt(position)
        if not item:
            return

        # Get all selected items
        selected_items = self.sessions_tree.selectedItems()
        if not selected_items:
            return

        # Analyze selected items to determine menu options
        light_sessions, _calibration_sessions, parent_objects = self._classify_selection(selected_items)

        # Create context menu based on selection
        context_menu = QMenu(self)

        # Session ID clipboard helper
        session_items_for_clipboard = [si for si in selected_items if si.parent() is not None]
        session_ids_for_clipboard = [str(si.data(0, Qt.ItemDataRole.UserRole)) for si in session_items_for_clipboard if si.data(0, Qt.ItemDataRole.UserRole)]
        copy_session_id_action = None
        if session_ids_for_clipboard:
            label = "📋 Copy Session ID" if len(session_ids_for_clipboard) == 1 else f"📋 Copy Session IDs ({len(session_ids_for_clipboard)})"
            copy_session_id_action = context_menu.addAction(label)
            copy_session_id_action.setToolTip("Copy the selected session ID(s) to the clipboard")

        actions = self._add_light_session_actions(context_menu, light_sessions)
        view_master_action = self._add_view_master_action(context_menu, selected_items, parent_objects)

        # Show the menu and handle selected action
        if context_menu.isEmpty():
            return

        action = context_menu.exec(self.sessions_tree.viewport().mapToGlobal(position))
        if not action:
            return

        # === HANDLE ACTIONS ===
        if action == actions.get("checkout"):
            if len(light_sessions) == 1:
                logger.info(f"Checking out session: {light_sessions[0].parent().text(0)} on {light_sessions[0].text(2)}")
                self.checkout_session(light_sessions[0])
            else:
                logger.info(f"Checking out {len(light_sessions)} sessions")
                self.checkout_multiple_sessions(light_sessions)
        elif action == actions.get("calibrate"):
            logger.info(f"Calibrating session: {light_sessions[0].parent().text(0)} on {light_sessions[0].text(2)}")
            self.calibrate_session(light_sessions[0])
        elif action == actions.get("stack"):
            logger.info(f"Stacking session: {light_sessions[0].parent().text(0)} on {light_sessions[0].text(2)}")
            self.sample_stack_session(light_sessions[0])
        elif action == actions.get("photometric_stack"):
            logger.info(f"Photometric stacking session: {light_sessions[0].parent().text(0)} on {light_sessions[0].text(2)}")
            self.photometric_stack_session(light_sessions[0])
        elif action == actions.get("regenerate_thumbnail"):
            self._regenerate_session_thumbnail(light_sessions[0])
        elif action == view_master_action:
            session_id = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            self.view_master_frame(session_id)
        elif action == copy_session_id_action:
            try:
                if not session_ids_for_clipboard:
                    return
                QApplication.clipboard().setText("\n".join(session_ids_for_clipboard))
                logger.info(f"Copied {len(session_ids_for_clipboard)} session id(s) to clipboard")
            except Exception:
                logger.exception("Failed to copy session id(s) to clipboard")

    def _regenerate_session_thumbnail(self, item) -> None:
        """Recreate a light session's thumbnail from its most recent stack, reporting problems to the user."""
        try:
            session_id = item.data(0, Qt.ItemDataRole.UserRole)
            if not session_id:
                QMessageBox.warning(self, "Error", "Session ID not found")
                return

            parent_item = item.parent()
            object_name = parent_item.text(0) if parent_item else "Unknown"
            if object_name in ['Bias', 'Dark', 'Flat', 'FlatDark']:
                QMessageBox.information(self, "Not Applicable", "Thumbnails are only generated for light sessions.")
                return

            try:
                session = FitsSessionModel.get_by_id(str(session_id))
            except Exception:
                session = None
            if not session:
                QMessageBox.warning(self, "Error", "Session not found in database")
                return

            out_dir = self._get_session_stack_output_dir(session)
            if not out_dir:
                QMessageBox.information(self, "No Stack", "No stack location found for this session.")
                return

            stack_path = self._find_best_stack_for_session(session=session, object_name=object_name, out_dir=out_dir)
            if not stack_path:
                QMessageBox.information(self, "No Stack", "No stacked FITS file found for this session.")
                return

            from galileo.library.core.master_manager import get_master_manager
            master_manager = get_master_manager()
            out_thumb = master_manager._write_light_session_thumbnail(
                stacked_fits_path=stack_path,
                session_id=str(session_id),
                width_px=150,
            )

            if not out_thumb or not os.path.exists(out_thumb):
                QMessageBox.warning(self, "Thumbnail Failed", "Failed to regenerate thumbnail.")
                return

            logger.info(f"Thumbnail regenerated for session {session_id}: {out_thumb}")
            self.load_sessions_data()

        except Exception as e:
            logger.exception("Error regenerating thumbnail")
            QMessageBox.critical(self, "Error", f"Failed to regenerate thumbnail:\n{e!s}")

    def view_master_frame(self, session_id):
        """Open master frame in external FITS viewer"""
        try:
            # Get the master frame for this session
            master = Masters.select().where(
                Masters.source_session_id == session_id,
                Masters.soft_delete == False
            ).first()

            if not master:
                QMessageBox.warning(self, "No Master", "No master frame found for this session.")
                return

            master_path = master.master_path

            # Check if file exists
            if not os.path.exists(master_path):
                QMessageBox.warning(self, "File Not Found", f"Master file not found:\n{master_path}")
                return

            self._open_path_in_external_viewer(master_path)

        except Exception as e:
            logger.exception("Error viewing master frame")
            QMessageBox.critical(self, "Error", f"Failed to open master frame:\n{e!s}")

    def _open_path_in_external_viewer(self, file_path: str) -> None:
        """Open a file path in the configured external FITS viewer (or OS default)."""
        if not file_path:
            return
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "File Not Found", f"File not found:\n{file_path}")
            return

        # Read configuration to get FITS viewer path
        config = load_library_config()
        fits_viewer_path = config.get('DEFAULT', 'fits_viewer_path', fallback=None)

        # Try to open with configured FITS viewer first
        if fits_viewer_path and os.path.exists(fits_viewer_path):
            try:
                import subprocess
                subprocess.Popen([fits_viewer_path, file_path])
                logger.info(f"Opened file with configured viewer: {fits_viewer_path}")
                return
            except Exception as e:
                logger.warning(f"Failed to open with configured viewer {fits_viewer_path}: {e}")

        # Fall back to OS default viewer
        try:
            if os.name == 'nt':
                os.startfile(file_path)
            elif os.name == 'posix':
                import subprocess
                if hasattr(os, 'uname') and os.uname().sysname == 'Darwin':
                    subprocess.run(["open", file_path], check=False)
                else:
                    subprocess.run(["xdg-open", file_path], check=False)
            else:
                QMessageBox.information(self, "Unsupported", "File viewing not supported on this platform")
        except Exception as e:
            logger.exception("Failed to open file in external viewer")
            QMessageBox.critical(self, "Error", f"Failed to open file:\n{e!s}")

    def checkout_session(self, item):
        """Create symbolic links for session files in a Siril-friendly format"""
        from .sessions.checkout_workflow import checkout_single_session

        return checkout_single_session(self, item)

    def checkout_multiple_sessions(self, session_items):
        """Create symbolic links for multiple sessions in a common directory structure"""
        from .sessions.checkout_workflow import checkout_multiple_sessions

        return checkout_multiple_sessions(self, session_items)
