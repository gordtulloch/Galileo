# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Loads the Sessions tree: fetches sessions, builds rows, icons, tooltips and the calibration-resources cell."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging
import os
import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem, QProgressDialog, QApplication, QMessageBox, QLabel
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush
from ._worker import run_in_worker
from galileo.library.core import fitsProcessing
from galileo.library.models import fitsFile as FitsFileModel, fitsSession as FitsSessionModel, Masters
from galileo.library.config import load_config as load_library_config

logger = logging.getLogger(__name__)


def _master_label(master_type: str) -> str:
    """Display name of a master of *master_type* ('bias' -> 'MasterBias')."""
    mt = str(master_type or '').strip().lower()
    if mt in ('bias', 'dark', 'flat'):
        return f"Master{mt.title()}"
    return f"Master{mt.title()}" if mt else 'Master'


def _masters_for_source_session(types_by_source_session: dict, source_session_id) -> set:
    """Master types built from the calibration session *source_session_id* (empty if none/unknown)."""
    if not source_session_id:
        return set()
    return set(types_by_source_session.get(str(source_session_id), set()))


def _matching_masters_for_session(cache: dict, s) -> set:
    """Matching master types for a session by querying the Masters table (cached in *cache*).

    Imported masters often have no source_session_id, so we must match by session metadata.
    """
    sid = getattr(s, 'fitsSessionId', None)
    if not sid:
        return set()
    sid = str(sid)
    cached = cache.get(sid)
    if cached is not None:
        return set(cached)

    try:
        from galileo.library.core.master_manager import get_master_manager
        master_manager = get_master_manager()
        session_data = {
            'telescope': getattr(s, 'fitsSessionTelescope', None),
            'instrument': getattr(s, 'fitsSessionImager', None),
            'exposure_time': getattr(s, 'fitsSessionExposure', None),
            'filter_name': getattr(s, 'fitsSessionFilter', None),
            'binning_x': getattr(s, 'fitsSessionBinningX', None),
            'binning_y': getattr(s, 'fitsSessionBinningY', None),
            'ccd_temp': getattr(s, 'fitsSessionCCDTemp', None),
            'gain': getattr(s, 'fitsSessionGain', None),
            'offset': getattr(s, 'fitsSessionOffset', None),
        }

        found = set()
        for cal_type in ('bias', 'dark', 'flat'):
            m = master_manager.find_matching_master(session_data, cal_type)
            if m and getattr(m, 'master_path', None) and os.path.exists(m.master_path):
                found.add(cal_type)

        cache[sid] = set(found)
        return set(found)
    except Exception:
        cache[sid] = set()
        return set()


def _calibration_session_status(session, masters_for, matched_masters) -> dict:
    """Resources cell of a calibration (Bias/Dark/Flat) session row: which masters exist for it."""
    mtypes = masters_for(getattr(session, 'fitsSessionId', None))
    if not mtypes:
        # Fallback for imported masters (no source_session_id): match by session metadata.
        # For calibration sessions, only show the master type relevant to that session.
        cal_obj = (session.fitsSessionObjectName or '').strip().lower()
        if cal_obj in ('bias', 'dark', 'flat') and cal_obj in matched_masters(session):
            mtypes = {cal_obj}
    if not mtypes:
        return {"text": "", "tooltip": "", "percentage": 0}

    labels = [_master_label(mt) for mt in sorted(mtypes)]
    return {
        "text": ", ".join(labels),
        "tooltip": "Masters available: " + ", ".join(labels),
        "percentage": 100,
        "has_bias": 'bias' in mtypes,
        "has_dark": 'dark' in mtypes,
        "has_flat": 'flat' in mtypes,
        "has_masters": True,
    }


def _precalibrated_status(session) -> dict | None:
    """Resources cell for iTelescope / Seestar sessions (delivered already calibrated), else None."""
    telescope = session.fitsSessionTelescope or ""
    instrument = session.fitsSessionImager or ""
    if 'itelescope' in telescope.lower():
        source_name = session.fitsSessionTelescope
    elif 'seestar' in instrument.lower():
        source_name = session.fitsSessionImager
    else:
        return None
    return {
        "text": "Precalibrated",
        "tooltip": f"Pre-calibrated images from {source_name}",
        "percentage": 100,
        "has_bias": True,
        "has_dark": True,
        "has_flat": True,
        "has_masters": True
    }


def _resource_part(kind: str, has_master: bool, has_session: bool, frame_count) -> tuple[str, str]:
    """(table text, tooltip line) for one calibration kind ('dark'/'flat'/'bias')."""
    title = kind.title()
    if has_master:
        return _master_label(kind), f"✓ {title} master frame available"
    if has_session:
        if frame_count is not None:
            return f"{title}: {frame_count}", f"✓ {frame_count} {kind} frames available"
        return f"{title}: Available", f"✓ {title} frames available"
    return f"{title}: None", f"✗ No {kind} frames available"

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as _MixinBase  # type checkers see a widget (it is mixed into one)
else:
    _MixinBase = object




class SessionsTreeMixin(_MixinBase):
    """Loads the Sessions tree: fetches sessions, builds rows, icons, tooltips and the calibration-resources cell."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def update_sessions(self):
        """Update light sessions by running createLightSessions method with progress dialog."""
        try:
            logger.info("Starting light sessions creation")

            # Create progress dialog
            progress_dialog = QProgressDialog("Initializing...", "Cancel", 0, 100, self)
            progress_dialog.setWindowTitle("Creating Light Sessions")
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
                    progress_dialog.setLabelText(f"Creating sessions {current}/{total}: {description}")
                else:
                    progress_dialog.setLabelText(f"Processing: {description}")

                QApplication.processEvents()
                return not progress_dialog.wasCanceled()

            # Run the light sessions creation
            created_sessions = processor.createLightSessions(progress_callback)

            progress_dialog.close()

            if progress_dialog.wasCanceled():
                logger.info("Light sessions creation cancelled by user")
                QMessageBox.information(self, "Cancelled", "Light sessions creation was cancelled.")
                return

            # Refresh the display
            self.load_sessions_data()

            logger.info(f"Created {len(created_sessions)} light sessions")
            QMessageBox.information(self, "Sessions Created",
                                  f"Successfully created {len(created_sessions)} light sessions.")

        except Exception as e:
            if 'progress_dialog' in locals():
                progress_dialog.close()
            logger.exception("Error creating light sessions")
            QMessageBox.critical(self, "Error", f"Failed to create light sessions: {e}")

    def update_calibration_sessions(self):
        """Update calibration Sessions by running createCalibrationSessions method with progress dialog."""
        try:
            logger.info("Starting calibration sessions creation")

            # Create progress dialog
            progress_dialog = QProgressDialog("Initializing...", "Cancel", 0, 100, self)
            progress_dialog.setWindowTitle("Creating Calibration Sessions")
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
                    progress_dialog.setLabelText(f"Creating calibration sessions {current}/{total}: {description}")
                else:
                    progress_dialog.setLabelText(f"Processing: {description}")

                QApplication.processEvents()
                return not progress_dialog.wasCanceled()

            # Run the calibration sessions creation
            created_sessions = processor.createCalibrationSessions(progress_callback)

            progress_dialog.close()

            if progress_dialog.wasCanceled():
                logger.info("Calibration sessions creation cancelled by user")
                QMessageBox.information(self, "Cancelled", "Calibration sessions creation was cancelled.")
                return

            # Refresh the display
            self.load_sessions_data()

            logger.info(f"Created {len(created_sessions)} calibration sessions")
            QMessageBox.information(self, "Sessions Created",
                                  f"Successfully created {len(created_sessions)} calibration sessions.")

        except Exception as e:
            if 'progress_dialog' in locals():
                progress_dialog.close()
            logger.exception("Error creating calibration sessions")
            QMessageBox.critical(self, "Error", f"Failed to create calibration sessions: {e}")

    def load_sessions_data(self):
        """Reload the sessions tree. Queries and per-session status run on a worker thread; the tree
        (and its pixmaps, which Qt only allows on the UI thread) is built when they finish."""
        self._load_generation += 1
        generation = self._load_generation
        self.sessions_tree.clear()
        self.sessions_tree.setEnabled(False)

        def done(result):
            if generation != self._load_generation:
                return      # superseded by a newer load
            self.sessions_tree.setEnabled(True)
            try:
                self._populate_sessions_tree(*result)
            except Exception as e:
                self._report_load_error(e)

        def failed(exc):
            if generation != self._load_generation:
                return
            self.sessions_tree.setEnabled(True)
            self._report_load_error(exc)

        run_in_worker(self, self._fetch_sessions_data, done, failed)

    def _report_load_error(self, exc):
        logger.error(f"Error loading Sessions data: {exc}")
        # Don't show error dialog on startup if database is just empty
        if "no such table" not in str(exc).lower():
            QMessageBox.warning(self, "Error", f"Failed to load Sessions data: {exc}")

    def _fetch_sessions_data(self):
        """Everything the tree needs, as plain data. Runs on a worker thread: no Qt objects here."""
        # Reset caches for this rebuild
        self._matched_master_types_by_session_id = {}

        # Precompute counts/master flags up-front to avoid N+1 queries
        from peewee import fn

        sessions = list(FitsSessionModel.select())

        # File counts per session (matches previous behavior: includes soft-deleted rows)
        self._session_file_counts = {
            row["sid"]: int(row["cnt"])
            for row in (
                FitsFileModel
                .select(
                    FitsFileModel.fitsFileSession.alias("sid"),
                    fn.COUNT(FitsFileModel.fitsFileId).alias("cnt"),
                )
                .where(FitsFileModel.fitsFileSession.is_null(False))
                .group_by(FitsFileModel.fitsFileSession)
                .dicts()
            )
            if row.get("sid")
        }

        # Which sessions have created masters (and which master types)
        self._master_types_by_source_session_id = {}
        for sid, mtype in (
            Masters
            .select(Masters.source_session_id, Masters.master_type)
            .where(
                (Masters.soft_delete == False) &
                (Masters.source_session_id.is_null(False))
            )
            .tuples()
        ):
            if not sid:
                continue
            st = str(mtype or '').strip().lower()
            if not st:
                continue
            self._master_types_by_source_session_id.setdefault(str(sid), set()).add(st)

        self._master_source_session_ids = set(self._master_types_by_source_session_id.keys())

        # Group sessions by object name
        sessions_by_object = {}
        for session in sessions:
            sessions_by_object.setdefault(session.fitsSessionObjectName or "Unknown", []).append(session)

        groups = []
        for object_name in sorted(sessions_by_object):
            object_sessions = sessions_by_object[object_name]
            total_images = sum(self._session_file_counts.get(s.fitsSessionId, 0) for s in object_sessions)

            # Sort sessions by date (newest first)
            rows = []
            calibrated_sessions = 0
            total_light_sessions = 0
            for session in sorted(object_sessions,
                                  key=lambda x: x.fitsSessionDate or datetime.date.min, reverse=True):
                is_light = session.fitsSessionObjectName not in ['Bias', 'Dark', 'Flat']
                calibration_info = self._build_resources_status(session)
                if is_light:
                    total_light_sessions += 1
                    if calibration_info["percentage"] > 0:
                        calibrated_sessions += 1
                thumb_path = ''
                if is_light:
                    path = self._get_thumbnail_path(str(session.fitsSessionId))
                    if path and os.path.exists(path):
                        thumb_path = path
                rows.append({
                    "session": session,
                    "image_count": self._session_file_counts.get(session.fitsSessionId, 0),
                    "calibration": calibration_info,
                    "has_master": session.fitsSessionId in self._master_source_session_ids,
                    "thumb_path": thumb_path,
                    "quality_tooltip": self._build_quality_tooltip(session),
                })
            groups.append((object_name, total_images, calibrated_sessions, total_light_sessions, rows))
        return groups, len(sessions)

    def _populate_sessions_tree(self, groups, session_count):
        """Build the tree from ``_fetch_sessions_data`` output (UI thread)."""
        self.sessions_tree.setUpdatesEnabled(False)
        try:
            for object_name, total_images, calibrated_sessions, total_light_sessions, rows in groups:
                parent_item = QTreeWidgetItem()
                parent_item.setText(0, object_name)
                for col in range(1, 6):
                    parent_item.setText(col, "")    # no thumbnail/date/telescope/imager/filter for parent
                parent_item.setText(6, str(total_images))   # Total images for this object

                # Show resource summary for parent
                if total_light_sessions > 0:
                    cal_percentage = (calibrated_sessions / total_light_sessions) * 100
                    parent_item.setText(7, f"{calibrated_sessions}/{total_light_sessions} ({cal_percentage:.0f}%)")
                    parent_item.setToolTip(7, f"Resource Coverage: {calibrated_sessions} of {total_light_sessions} sessions have calibration resources")
                else:
                    parent_item.setText(7, "")

                font = parent_item.font(0)
                font.setBold(True)
                parent_item.setFont(0, font)

                for row in rows:
                    session = row["session"]
                    calibration_info = row["calibration"]
                    child_item = QTreeWidgetItem()
                    # Show (master) for calibration sessions that have created masters
                    if row["has_master"] and session.fitsSessionObjectName in ['Bias', 'Dark', 'Flat']:
                        child_item.setText(0, "(master)")
                    else:
                        child_item.setText(0, "")  # Empty object name for child
                    child_item.setText(1, "")  # Thumbnail column
                    child_item.setText(2, str(session.fitsSessionDate) if session.fitsSessionDate else "Unknown Date")
                    child_item.setText(3, session.fitsSessionTelescope or "Unknown")
                    child_item.setText(4, session.fitsSessionImager or "Unknown")
                    child_item.setText(5, session.fitsSessionFilter or "Unknown")
                    child_item.setText(6, str(row["image_count"]))

                    # Store session ID in the item for later retrieval
                    child_item.setData(0, Qt.ItemDataRole.UserRole, session.fitsSessionId)

                    # Attach thumbnail icon if it exists (light sessions only)
                    if row["thumb_path"]:
                        pix = QPixmap(row["thumb_path"])
                        if not pix.isNull():
                            pix = pix.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                            child_item.setIcon(1, QIcon(pix))
                            child_item.setToolTip(1, f"Thumbnail: {row['thumb_path']}")

                    child_item.setText(7, calibration_info["text"] or "")

                    # Quality metrics tooltip on every column; column 7 also carries the calibration tooltip
                    quality_tooltip = row["quality_tooltip"]
                    for col in range(8):
                        if col == 7 and calibration_info["tooltip"]:
                            child_item.setToolTip(col, f"{calibration_info['tooltip']}\n\n{quality_tooltip}")
                        else:
                            child_item.setToolTip(col, quality_tooltip)

                    parent_item.addChild(child_item)

                # Only add parent item if it has children
                if parent_item.childCount() > 0:
                    self.sessions_tree.addTopLevelItem(parent_item)
                    parent_item.setExpanded(False)
        finally:
            self.sessions_tree.setUpdatesEnabled(True)

        if session_count > 0:
            logger.debug(f"Loaded {session_count} sessions into hierarchical display")
        else:
            logger.debug("No sessions found in database")

    def _get_thumbnail_path(self, session_id: str) -> str:
        """Return the expected thumbnail path for a session id."""
        try:
            config = load_library_config()
            repo_path = config.get('DEFAULT', 'repo', fallback='')
        except Exception:
            repo_path = ''

        if not repo_path:
            return ''
        return os.path.join(repo_path, 'Thumbnails', f"{session_id}.png")

    def _build_quality_tooltip(self, session):
        """
        Build a tooltip string with quality metrics for a session.

        Args:
            session: fitsSession object

        Returns:
            str: Formatted tooltip with quality metrics
        """
        parts = []
        parts.append("=== Quality Metrics ===")

        if session.fitsSessionAvgFWHMArcsec is not None:
            parts.append(f"Average FWHM: {session.fitsSessionAvgFWHMArcsec:.2f} arcsec")
        else:
            parts.append("Average FWHM: N/A")

        if session.fitsSessionAvgEccentricity is not None:
            parts.append(f"Average Eccentricity: {session.fitsSessionAvgEccentricity:.3f}")
        else:
            parts.append("Average Eccentricity: N/A")

        if session.fitsSessionAvgHFRArcsec is not None:
            parts.append(f"Average HFR: {session.fitsSessionAvgHFRArcsec:.2f} arcsec")
        else:
            parts.append("Average HFR: N/A")

        if session.fitsSessionImageSNR is not None:
            parts.append(f"Average SNR: {session.fitsSessionImageSNR:.1f}")
        else:
            parts.append("Average SNR: N/A")

        if session.fitsSessionStarCount is not None:
            parts.append(f"Average Star Count: {session.fitsSessionStarCount}")
        else:
            parts.append("Average Star Count: N/A")

        if session.fitsSessionImageScale is not None:
            parts.append(f"Image Scale: {session.fitsSessionImageScale:.2f} arcsec/pixel")
        else:
            parts.append("Image Scale: N/A")

        return "\n".join(parts)

    def _create_status_icon(self, icon_type, available=True):
        """Create a colored icon for calibration status."""
        size = 12
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Define colors and shapes for different calibration types
        if icon_type == 'B':  # Bias
            color = QColor(0, 150, 255) if available else QColor(128, 128, 128)  # Blue or gray
            painter.setBrush(QBrush(color))
            painter.setPen(color)
            painter.drawEllipse(1, 1, size-2, size-2)
        elif icon_type == 'D':  # Dark
            color = QColor(80, 80, 80) if available else QColor(180, 180, 180)  # Dark gray or light gray
            painter.setBrush(QBrush(color))
            painter.setPen(color)
            painter.drawRect(1, 1, size-2, size-2)
        elif icon_type == 'F':  # Flat
            color = QColor(255, 165, 0) if available else QColor(200, 200, 200)  # Orange or gray
            painter.setBrush(QBrush(color))
            painter.setPen(color)
            # Draw triangle
            points = [
                Qt.QPoint(size//2, 1),
                Qt.QPoint(size-1, size-1),
                Qt.QPoint(1, size-1)
            ]
            painter.drawPolygon(points)
        elif icon_type == 'M':  # Master frame indicator
            color = QColor(0, 200, 0) if available else QColor(150, 150, 150)  # Green or gray
            painter.setBrush(QBrush(color))
            painter.setPen(color)
            painter.drawEllipse(3, 3, size-6, size-6)  # Small filled circle

        painter.end()
        return QIcon(pixmap)

    def _build_resources_status(self, session):
        """Build resources status showing frame counts or Master availability for light sessions."""
        def masters_for(source_session_id) -> set:
            return _masters_for_source_session(self._master_types_by_source_session_id, source_session_id)

        def matched_masters(s) -> set:
            return _matching_masters_for_session(self._matched_master_types_by_session_id, s)

        if session.fitsSessionObjectName in ['Bias', 'Dark', 'Flat']:
            return _calibration_session_status(session, masters_for, matched_masters)

        precalibrated = _precalibrated_status(session)
        if precalibrated is not None:
            return precalibrated

        # Master availability can come either from explicit session fields or from the Masters table
        dark_masters = masters_for(getattr(session, 'fitsDarkSession', None))
        flat_masters = masters_for(getattr(session, 'fitsFlatSession', None))
        bias_masters = masters_for(getattr(session, 'fitsBiasSession', None))

        # Imported masters may not be tied to a session id; match by session metadata.
        matched = matched_masters(session)

        has_dark_master = bool(getattr(session, 'fitsDarkMaster', None)) or 'dark' in dark_masters or 'dark' in matched
        has_flat_master = bool(getattr(session, 'fitsFlatMaster', None)) or 'flat' in flat_masters or 'flat' in matched
        has_bias_master = bool(getattr(session, 'fitsBiasMaster', None)) or 'bias' in bias_masters or 'bias' in matched

        # Check calibration sessions availability
        has_bias_session = bool(session.fitsBiasSession)
        has_dark_session = bool(session.fitsDarkSession)
        has_flat_session = bool(session.fitsFlatSession)

        counts = self._session_file_counts
        parts = [
            _resource_part("dark", has_dark_master, has_dark_session, counts.get(session.fitsDarkSession)),
            _resource_part("flat", has_flat_master, has_flat_session, counts.get(session.fitsFlatSession)),
            _resource_part("bias", has_bias_master, has_bias_session, counts.get(session.fitsBiasSession)),
        ]
        status_parts = [text for text, _tip in parts]
        tooltip_parts = [tip for _text, tip in parts]

        # Calculate readiness percentage (for color coding)
        available_count = sum([
            has_dark_master or has_dark_session,
            has_flat_master or has_flat_session,
            has_bias_master or has_bias_session
        ])
        readiness_percentage = (available_count / 3.0) * 100

        # Create comprehensive tooltip
        tooltip = f"Calibration Resources ({readiness_percentage:.0f}% ready):\n" + "\n".join(tooltip_parts)

        return {
            "text": ", ".join(status_parts),
            "tooltip": tooltip,
            "percentage": readiness_percentage,
            "has_bias": has_bias_session or has_bias_master,
            "has_dark": has_dark_session or has_dark_master,
            "has_flat": has_flat_session or has_flat_master,
            "has_masters": any([has_bias_master, has_dark_master, has_flat_master])
        }

    def _create_calibration_progress_widget(self, percentage, has_bias, has_dark, has_flat):
        """Create a compact progress widget showing calibration status."""
        widget = QLabel()

        # Create a mini progress representation
        progress_text = "["

        # Add indicators for each calibration type
        progress_text += "●" if has_bias else "○"  # Bias
        progress_text += "●" if has_dark else "○"   # Dark
        progress_text += "●" if has_flat else "○"   # Flat

        progress_text += f"] {percentage:.0f}%"

        widget.setText(progress_text)

        # Color code the text based on completion
        if percentage >= 100:
            widget.setStyleSheet("color: green; font-weight: bold;")
        elif percentage >= 67:
            widget.setStyleSheet("color: orange; font-weight: bold;")
        elif percentage >= 33:
            widget.setStyleSheet("color: #CC8800; font-weight: bold;")
        else:
            widget.setStyleSheet("color: red; font-weight: bold;")

        return widget

    def _get_calibration_status_icon(self, session):
        """Get an overall calibration status icon for the session."""
        calibration_info = self._build_resources_status(session)

        if calibration_info["text"] == "":
            return None

        percentage = calibration_info["percentage"]

        if percentage >= 100:
            return self._create_status_icon('M', True)  # Master/complete indicator
        elif percentage >= 67:
            return self._create_status_icon('B', True)  # Good status
        elif percentage >= 33:
            return self._create_status_icon('D', True)  # Partial status
        else:
            return self._create_status_icon('F', False)  # Poor status
