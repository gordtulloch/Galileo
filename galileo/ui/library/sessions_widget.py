# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
import os
import logging
from PySide6.QtCore import Qt
from PySide6.QtCore import QSize
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QTreeWidget, QAbstractItemView,
                               QMessageBox)

from galileo.library.models import fitsFile as FitsFileModel, fitsSession as FitsSessionModel
from galileo.ui.library.sessions_regenerate import (
    SessionsRegenerateMixin,
)
from galileo.ui.library.sessions_stacking import (
    SessionsStackingMixin,
)
from galileo.ui.library.sessions_tree import (
    SessionsTreeMixin,
)
from galileo.ui.library.sessions_menu import (
    SessionsMenuMixin,
)

logger = logging.getLogger(__name__)


class SessionsWidget(SessionsMenuMixin, SessionsTreeMixin, SessionsStackingMixin, SessionsRegenerateMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._load_generation = 0
        self.init_ui()

        # Caches used to speed up sessions rendering
        self._session_file_counts = {}
        self._master_source_session_ids = set()
        self._master_types_by_source_session_id = {}
        self._matched_master_types_by_session_id = {}

        # Load existing data on startup
        self.load_sessions_data()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Controls
        controls_layout = QHBoxLayout()
        self.regenerate_button = QPushButton("Regenerate")
        self.regenerate_button.setStyleSheet("QPushButton { font-size: 11px; }")
        self.regenerate_button.setToolTip("Clear all sessions and regenerate: Update Lights → Update Calibrations → Link Sessions")

        controls_layout.addWidget(self.regenerate_button)
        controls_layout.addStretch()

        # Sessions list
        self.sessions_tree = QTreeWidget()
        self.sessions_tree.setHeaderLabels(["Object Name", "Thumbnail", "Date", "Telescope", "Imager", "Filter", "Images", "Resources"])
        self.sessions_tree.setIconSize(QSize(150, 150))

        # Enable multi-selection
        self.sessions_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)

        # Set column widths for better display
        self.sessions_tree.setColumnWidth(0, 200)  # Object Name
        self.sessions_tree.setColumnWidth(1, 160)  # Thumbnail
        self.sessions_tree.setColumnWidth(2, 150)  # Date
        self.sessions_tree.setColumnWidth(3, 150)  # Telescope
        self.sessions_tree.setColumnWidth(4, 150)  # Imager
        self.sessions_tree.setColumnWidth(5, 100)  # Filter
        self.sessions_tree.setColumnWidth(6, 80)   # Images
        self.sessions_tree.setColumnWidth(7, 140)  # Resources

        # Enable context menu
        self.sessions_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sessions_tree.customContextMenuRequested.connect(self.show_context_menu)

        # Double-click behavior (e.g., open stack from thumbnail)
        self.sessions_tree.itemDoubleClicked.connect(self.on_item_double_clicked)

        layout.addLayout(controls_layout)
        layout.addWidget(self.sessions_tree)

        # Connect signals
        self.regenerate_button.clicked.connect(self.regenerate_sessions)


    # Checkout options dialog has been extracted to ui/sessions/checkout_options_dialog.py

    # Checkout file materialization helpers have been extracted to ui/sessions/checkout_files.py


        # === SESSION MANAGEMENT METHODS ===


    def show_session_properties(self, session_item):
        """Show detailed properties for a session"""
        try:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox, QTabWidget, QWidget, QTableWidget, QTableWidgetItem, QHeaderView

            parent = session_item.parent()
            if not parent:
                QMessageBox.information(self, "Properties", "Properties view is only available for individual sessions.")
                return

            # Get session information
            object_name = parent.text(0)
            session_date = session_item.text(2)

            # Find session in database
            session = FitsSessionModel.select().where(
                (FitsSessionModel.fitsSessionObjectName == object_name) &
                (FitsSessionModel.fitsSessionDate == session_date)
            ).first()

            if not session:
                QMessageBox.warning(self, "Error", "Session not found in database")
                return

            # Create properties dialog
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Session Properties: {object_name} - {session_date}")
            dialog.setMinimumSize(700, 500)
            layout = QVBoxLayout(dialog)

            # Create tab widget
            tabs = QTabWidget()

            # === SESSION INFO TAB ===
            session_tab = QWidget()
            session_layout = QVBoxLayout(session_tab)

            session_info = QTextEdit()
            session_info.setReadOnly(True)

            info_content = "Session Properties\n"
            info_content += "=" * 50 + "\n\n"
            info_content += f"Session ID: {session.fitsSessionId}\n"
            info_content += f"Object Name: {session.fitsSessionObjectName}\n"
            info_content += f"Date: {session.fitsSessionDate}\n"
            info_content += f"Telescope: {session.fitsSessionTelescope or 'Unknown'}\n"
            info_content += f"Imager: {session.fitsSessionImager or 'Unknown'}\n"
            info_content += f"Exposure: {session.fitsSessionExposure or 'Unknown'}s\n"
            info_content += f"Binning: {session.fitsSessionBinningX or '?'}x{session.fitsSessionBinningY or '?'}\n"
            info_content += f"CCD Temperature: {session.fitsSessionCCDTemp or 'Unknown'}°C\n"
            info_content += f"Gain: {session.fitsSessionGain or 'Unknown'}\n"
            info_content += f"Offset: {session.fitsSessionOffset or 'Unknown'}\n"
            info_content += f"Filter: {session.fitsSessionFilter or 'Unknown'}\n\n"

            info_content += "Calibration Links:\n"
            info_content += f"Bias Session: {session.fitsBiasSession or 'Not linked'}\n"
            info_content += f"Dark Session: {session.fitsDarkSession or 'Not linked'}\n"
            info_content += f"Flat Session: {session.fitsFlatSession or 'Not linked'}\n\n"

            info_content += "Master Frames:\n"
            info_content += f"Bias Master: {session.fitsBiasMaster or 'Not available'}\n"
            info_content += f"Dark Master: {session.fitsDarkMaster or 'Not available'}\n"
            info_content += f"Flat Master: {session.fitsFlatMaster or 'Not available'}\n"

            session_info.setPlainText(info_content)
            session_layout.addWidget(session_info)
            tabs.addTab(session_tab, "Session Info")

            # === FILES TAB ===
            files_tab = QWidget()
            files_layout = QVBoxLayout(files_tab)

            files_table = QTableWidget()
            files_table.setColumnCount(6)
            files_table.setHorizontalHeaderLabels([
                "Filename", "Type", "Date", "Calibrated", "Hash", "Size"
            ])

            # Get session files
            session_files = FitsFileModel.select().where(FitsFileModel.fitsFileSession == session.fitsSessionId)
            files_table.setRowCount(session_files.count())

            for i, file in enumerate(session_files):
                files_table.setItem(i, 0, QTableWidgetItem(os.path.basename(file.fitsFileName or '')))
                files_table.setItem(i, 1, QTableWidgetItem(file.fitsFileType or 'Unknown'))
                files_table.setItem(i, 2, QTableWidgetItem(str(file.fitsFileDate or 'Unknown')))
                files_table.setItem(i, 3, QTableWidgetItem('Yes' if file.fitsFileCalibrated else 'No'))
                files_table.setItem(i, 4, QTableWidgetItem(file.fitsFileHash or 'Unknown'))

                # Get file size
                if file.fitsFileName and os.path.exists(file.fitsFileName):
                    size = os.path.getsize(file.fitsFileName)
                    size_str = f"{size:,} bytes"
                else:
                    size_str = "File not found"
                files_table.setItem(i, 5, QTableWidgetItem(size_str))

            # Configure files table
            header = files_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            files_table.setAlternatingRowColors(True)
            files_table.setSelectionBehavior(QTableWidget.SelectRows)

            files_layout.addWidget(files_table)
            tabs.addTab(files_tab, f"Files ({session_files.count()})")

            layout.addWidget(tabs)

            # Buttons
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            dialog.exec()

        except Exception as e:
            logger.exception("Error showing session properties")
            QMessageBox.critical(self, "Error", f"Failed to show session properties:\n\n{e}")


