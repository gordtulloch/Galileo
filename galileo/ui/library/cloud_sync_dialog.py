# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
import os
import logging
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QFrame, QMessageBox, QGroupBox)
from PySide6.QtGui import QFont

from galileo.library.config import load_config as load_library_config
from galileo.ui.library.cloud_sync_complete import (
    CloudCompleteSyncMixin,
)
from galileo.ui.library.cloud_sync_backup import (
    CloudBackupSyncMixin,
)
from galileo.ui.library.cloud_sync_analysis import (
    CloudAnalysisMixin,
)

logger = logging.getLogger(__name__)


class CloudSyncWidget(CloudAnalysisMixin, CloudBackupSyncMixin, CloudCompleteSyncMixin, QWidget):
    """Cloud Sync page of the Library section: shows the cloud settings and runs Analyze / Sync."""

    # Asks the host to open Options > Library, where the cloud settings live.
    configure_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cloud_config = self.load_cloud_config()
        self.init_ui()

    def showEvent(self, event):
        """Pick up settings changed under Options > Library since the page was last shown."""
        self.cloud_config = self.load_cloud_config()
        self.refresh_config_display()
        super().showEvent(event)

    def load_cloud_config(self):
        """Load cloud configuration from library.ini"""
        try:
            config = load_library_config()

            return {
                'vendor': config.get('DEFAULT', 'cloud_vendor', fallback='Not configured'),
                'bucket_url': config.get('DEFAULT', 'bucket_url', fallback='Not configured'),
                'auth_file_path': config.get('DEFAULT', 'auth_file_path', fallback='Not configured'),
                'sync_profile': config.get('DEFAULT', 'sync_profile', fallback='complete')
            }
        except Exception:
            logger.exception("Error loading cloud config")
            return {
                'vendor': 'Error loading config',
                'bucket_url': 'Error loading config',
                'auth_file_path': 'Error loading config',
                'sync_profile': 'complete'
            }

    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title_label = QLabel("Cloud Sync Operations")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Configuration info
        config_group = QGroupBox("Current Configuration")
        config_layout = QVBoxLayout(config_group)

        # Display current settings
        self.vendor_label = QLabel()
        self.bucket_label = QLabel()
        self.auth_label = QLabel()
        self.sync_label = QLabel()
        self.refresh_config_display()

        config_layout.addWidget(self.vendor_label)
        config_layout.addWidget(self.bucket_label)
        config_layout.addWidget(self.auth_label)
        config_layout.addWidget(self.sync_label)

        # Add Configure button to the config group
        config_button_layout = QHBoxLayout()
        config_button_layout.addStretch()
        configure_button = QPushButton("Configure...")
        configure_button.setMinimumSize(100, 30)
        configure_button.clicked.connect(self.on_configure_clicked)
        config_button_layout.addWidget(configure_button)
        config_layout.addLayout(config_button_layout)

        layout.addWidget(config_group)

        # Add some spacing
        layout.addSpacing(10)

        # Analyze section
        analyze_frame = self.create_operation_frame(
            "Analyze",
            "Compare local with the Cloud",
            self.on_analyze_clicked
        )
        layout.addWidget(analyze_frame)

        # Sync section
        sync_frame = self.create_operation_frame(
            "Sync",
            "Move files to / from the Cloud based on Profile",
            self.on_sync_clicked
        )
        layout.addWidget(sync_frame)

        layout.addStretch()

    def create_operation_frame(self, button_text, description, callback):
        """Create a frame for an operation with button and description"""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.Box)
        frame.setStyleSheet("QFrame { border: 1px solid gray; border-radius: 5px; padding: 10px; }")

        frame_layout = QHBoxLayout(frame)
        frame_layout.setContentsMargins(15, 15, 15, 15)

        # Operation button
        button = QPushButton(button_text)
        button.setMinimumSize(100, 40)
        button.setMaximumSize(120, 40)
        button.clicked.connect(callback)
        frame_layout.addWidget(button)

        # Description label
        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        frame_layout.addWidget(desc_label, 1)  # Stretch factor of 1

        return frame


    def on_sync_clicked(self):
        """Handle Sync button click"""
        logger.info("Cloud Sync: Sync operation requested")

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

        # First validate bucket access
        if not self.validate_bucket_access():
            return

        # Check sync profile and handle accordingly
        sync_profile = self.cloud_config['sync_profile'].lower()

        if sync_profile == 'backup':
            self.perform_backup_sync()
        elif sync_profile == 'complete':
            self.perform_complete_sync()
        elif sync_profile == 'on demand':
            self.perform_on_demand_sync()
        else:
            QMessageBox.warning(
                self,
                "Unknown Sync Profile",
                f"Unknown sync profile: {sync_profile}\n\n"
                f"Please check your configuration."
            )


    def on_configure_clicked(self):
        """The cloud settings live under Options > Library; ask the host to go there."""
        logger.info("Cloud Sync: Configure button clicked")
        self.configure_requested.emit()

    def refresh_config_display(self):
        """Show the current cloud settings (the auth file's path is never displayed)."""
        cfg = self.cloud_config
        auth_ok = bool(cfg['auth_file_path']) and cfg['auth_file_path'] != 'Not configured'
        sync_descriptions = {
            'complete': 'Complete Sync (All files kept both local and in the Cloud)',
            'backup': "Backup Only (Upload to Cloud, don't download missing)",
            'ondemand': 'On Demand (Upload soft-deleted files and remove from local storage)'
        }
        self.vendor_label.setText(f"Cloud Vendor: {cfg['vendor']}")
        self.bucket_label.setText(f"Bucket: {cfg['bucket_url']}")
        self.auth_label.setText(f"Authentication: {'Configured' if auth_ok else 'Not configured'}")
        self.sync_label.setText(f"Sync Profile: {sync_descriptions.get(cfg['sync_profile'], cfg['sync_profile'])}")
