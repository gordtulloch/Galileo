import os
import logging
import zipfile
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                               QFormLayout, QListWidget, QLineEdit, QPushButton,
                               QCheckBox, QFileDialog, QMessageBox, QProgressDialog,
                               QApplication)

from astropy.io import fits
from galileo.library.core import fitsProcessing
from galileo.library.services.telescope import smart_telescope_manager
from galileo.library.config import get_sftp_settings, load_config as load_library_config

logger = logging.getLogger(__name__)


class TelescopeDownloadWorker(QThread):
    """Worker thread for downloading files from smart telescopes."""

    # Signals for thread-safe communication
    progress_updated = Signal(str)
    progress_percent_updated = Signal(int)
    download_completed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, telescope_type, hostname, network, target_directory, delete_files=False):
        super().__init__()
        self.telescope_type = telescope_type
        self.hostname = hostname
        self.network = network
        self.target_directory = target_directory
        self.delete_files = delete_files
        self._stop_requested = False

    def _modify_fits_headers(self, fits_path, folder_name, telescope_type=None):
        """Modify FITS headers based on folder name."""
        try:
            with fits.open(fits_path, mode='update') as hdul:
                header = hdul[0].header

                # For iTelescope, preserve the original OBJECT header and don't modify it
                if "seestar" in telescope_type.lower():
                    # Extract OBJECT from folder name (strip _sub or _mosaic_sub suffix)
                    object_name = folder_name
                    if folder_name.endswith('_mosaic_sub'):
                        object_name = folder_name[:-11]  # Remove '_mosaic_sub'
                    elif folder_name.endswith('_sub'):
                        object_name = folder_name[:-4]   # Remove '_sub'

                    # Set OBJECT header
                    header['OBJECT'] = object_name

                    # Set MOSAIC header for mosaic folders (for all telescope types)
                    if folder_name.endswith('_mosaic_sub'):
                        header['MOSAIC'] = True
                    else:
                        header['MOSAIC'] = False

                hdul.flush()

        except Exception as e:
            self.progress_updated.emit(f"Warning: Could not modify headers for {os.path.basename(fits_path)}: {e!s}")

    def _unzip_file(self, zip_path):
        """Unzip a file and return the path to the extracted file."""
        try:
            # Get the directory where the zip file is located
            zip_dir = os.path.dirname(zip_path)

            extracted_files = []
            main_file = None

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # List all files in the zip
                file_list = zip_ref.namelist()

                if not file_list:
                    logger.warning(f"No files found in zip archive {zip_path}")
                    return None

                # Extract all files to the same directory as the zip file
                zip_ref.extractall(zip_dir)

                # Find the main file (usually the largest or first .fit/.fits file)
                for file_name in file_list:
                    if file_name.lower().endswith(('.fit', '.fits')):
                        extracted_path = os.path.join(zip_dir, file_name)
                        if os.path.exists(extracted_path):
                            extracted_files.append(extracted_path)

                if extracted_files:
                    # Return the first FITS file found
                    main_file = extracted_files[0]
                    logger.info(f"Successfully extracted {len(extracted_files)} file(s) from {os.path.basename(zip_path)}")
                else:
                    logger.warning(f"No FITS files found in zip archive {zip_path}")
                    return None

            # Important on Windows: delete only after the ZipFile is closed.
            if main_file:
                try:
                    os.remove(zip_path)
                    logger.debug(f"Removed original zip file {zip_path}")
                except Exception as e:
                    logger.warning(f"Could not remove original zip file {zip_path}: {e}")

            return main_file

        except zipfile.BadZipFile:
            logger.exception(f"Invalid zip file: {zip_path}")
            return None
        except Exception:
            logger.exception(f"Error extracting zip file {zip_path}")
            return None

    def stop(self):
        """Request the worker to stop."""
        logger.debug("Worker thread stop requested")
        self._stop_requested = True

    def run(self):
        """Perform the actual download process."""
        try:
            if self._stop_requested:
                return

            ip = self._find_telescope()
            if ip is None:
                return

            fits_files = self._list_fits_files(ip)
            if fits_files is None:
                return

            tally = _DownloadTally()
            for i, file_info in enumerate(fits_files):
                if self._stop_requested:
                    break
                self._download_one(i, len(fits_files), file_info, ip, tally)

            if self._stop_requested:
                self.progress_updated.emit("Download cancelled")
                return

            self.progress_percent_updated.emit(95)
            completion_message = self._completion_message(tally)
            self.progress_percent_updated.emit(100)
            self.download_completed.emit(completion_message)
            logger.info(f"Download process completed: {tally.downloaded} downloaded, {tally.registered} registered, {len(tally.failed)} failed")

        except Exception as e:
            if not self._stop_requested:
                self.error_occurred.emit(f"Unexpected error during download: {e!s}")
                logger.exception("Unexpected error during download")

    def _fail(self, message: str) -> None:
        """Report *message* to the dialog and the log."""
        self.error_occurred.emit(message)
        logger.error(message)

    def _protocol_label(self) -> str:
        if self.telescope_type in ["SeeStar", "StellarMate"]:
            return "SMB"
        if self.telescope_type == "iTelescope":
            return "FTPS"
        if self.telescope_type == "SFTP":
            return "SFTP"
        return "FTP"

    def _find_telescope(self) -> str | None:
        """Step 1 (to 10% of progress): locate the telescope on the network; its address, or None."""
        message = f"Scanning network for {self.telescope_type} telescope ({self._protocol_label()})..."
        self.progress_updated.emit(message)
        logger.info(message)
        self.progress_percent_updated.emit(5)

        ip, error = smart_telescope_manager.find_telescope(
            self.telescope_type,
            network_range=self.network or None,
            hostname=self.hostname or None
        )

        if self._stop_requested:
            return None

        if not ip:
            self._fail(f"Failed to find telescope: {error}")
            return None

        self.progress_updated.emit(f"Connected to {self.telescope_type} at {ip}")
        logger.info(f"Connected to {self.telescope_type} at {ip}")
        self.progress_percent_updated.emit(10)
        return ip

    def _list_fits_files(self, ip: str) -> list | None:
        """Step 2 (to 30%): the FITS files on the telescope; None on stop, error or when there are none."""
        if self._stop_requested:
            return None

        self.progress_updated.emit("Scanning for FITS files...")
        logger.info("Scanning for FITS files...")
        self.progress_percent_updated.emit(20)

        # Get credentials for iTelescope if needed
        self.username = None
        self.password = None
        if self.telescope_type == "iTelescope":
            self.username, self.password = smart_telescope_manager.get_itelescope_credentials()
            if not self.username or not self.password:
                self._fail("iTelescope credentials not configured. Please configure in Config → Smart Telescopes tab.")
                return None

        if self.telescope_type == "SFTP" and not get_sftp_settings()["username"]:
            self._fail("SFTP account not configured. Please set it in Options > Library > Smart Telescopes.")
            return None

        fits_files, error = smart_telescope_manager.get_fits_files(self.telescope_type, ip, self.username, self.password)

        if self._stop_requested:
            return None

        if error:
            self._fail(f"Failed to get file list: {error}")
            return None

        if not fits_files:
            self.download_completed.emit("No FITS files found on telescope")
            logger.info("No FITS files found on telescope")
            return None

        self.progress_updated.emit(f"Found {len(fits_files)} FITS files")
        logger.info(f"Found {len(fits_files)} FITS files")
        self.progress_percent_updated.emit(30)

        if self._stop_requested:
            return None
        return fits_files

    def _local_path_for(self, file_info: dict) -> str:
        """Where a telescope file is saved: iTelescope flat in the target folder, others keep their folder."""
        file_name = file_info['name']
        if self.telescope_type == 'iTelescope':
            return os.path.join(self.target_directory, file_name)
        return os.path.join(self.target_directory, file_info.get('folder_name', 'unknown'), file_name)

    def _download_one(self, i: int, total: int, file_info: dict, ip: str, tally: "_DownloadTally") -> None:
        """Step 3 (30% to 90%): download, unzip, fix headers, register and (optionally) delete one file."""
        file_name = file_info['name']
        self.progress_updated.emit(f"Processing {file_name} ({i+1}/{total})...")
        self.progress_percent_updated.emit(30 + int((i / total) * 60))

        folder_name = file_info.get('folder_name', 'unknown')
        local_path = self._local_path_for(file_info)

        success, error = smart_telescope_manager.download_file(
            self.telescope_type, ip, file_info, local_path,
            self.username, self.password,
            progress_callback=lambda progress: not self._stop_requested
        )

        if self._stop_requested:
            return

        if not success:
            tally.failed.append(f"{file_name}: {error}")
            logger.error(f"Failed to download {file_name}: {error}")
            return

        tally.downloaded += 1
        logger.info(f"Downloaded {file_name}")

        if file_name.lower().endswith('.zip'):
            local_path = self._try_unzip(local_path, file_name)
            file_name = os.path.basename(local_path)

        # Modify FITS headers based on folder name
        self._modify_fits_headers(local_path, folder_name, self.telescope_type)

        if self._register_download(local_path, file_name):
            tally.registered += 1

        if self.delete_files:
            delete_success, delete_error = smart_telescope_manager.delete_file(self.telescope_type, ip, file_info)
            if delete_success:
                tally.deleted += 1
                logger.info(f"Deleted {file_name} from telescope")
            else:
                logger.warning(f"Failed to delete {file_name}: {delete_error}")

    def _try_unzip(self, local_path: str, file_name: str) -> str:
        """The extracted file's path if *local_path* unzipped, else *local_path* (the zip is kept)."""
        try:
            unzipped_path = self._unzip_file(local_path)
            if unzipped_path:
                logger.info(f"Unzipped {file_name} to {os.path.basename(unzipped_path)}")
                return unzipped_path
            logger.warning(f"Failed to unzip {file_name}, continuing with zip file")
        except Exception:
            logger.exception(f"Error unzipping {file_name}, continuing with zip file")
        return local_path

    @staticmethod
    def _register_download(local_path: str, file_name: str) -> bool:
        """Register the downloaded FITS in the database (moving it into the repository); True if registered."""
        try:
            processor = fitsProcessing()
            registered_id = processor.registerFitsImage(
                os.path.dirname(local_path), os.path.basename(local_path), moveFiles=True)
            if registered_id:
                logger.info(f"Successfully registered {file_name} in database with ID {registered_id}")
                return True
            logger.warning(f"Failed to register {file_name} in database")
        except Exception:
            logger.exception(f"Error registering {file_name} in database")
        return False

    def _completion_message(self, tally: "_DownloadTally") -> str:
        """Step 5: the summary shown when the download finishes."""
        message = "Download completed!\n\n"
        message += f"Downloaded: {tally.downloaded} files\n"
        message += f"Registered in database: {tally.registered} files\n"

        if tally.failed:
            message += f"Failed: {len(tally.failed)} files\n"
            message += "Failed files:\n" + "\n".join(tally.failed[:5])
            if len(tally.failed) > 5:
                message += f"\n... and {len(tally.failed) - 5} more"

        if self.delete_files:
            message += f"\nDeleted from telescope: {tally.deleted} files"

        return message + "\n\nFiles processed and moved to repository structure"


@dataclass
class _DownloadTally:
    """Running totals of a download run."""

    downloaded: int = 0
    registered: int = 0
    deleted: int = 0
    failed: list[str] = field(default_factory=list)


class SmartTelescopeDownloadDialog(QDialog):
    """Dialog for downloading files from smart telescopes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Download Repository")
        self.setModal(True)
        self.resize(400, 300)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Telescope selection
        telescope_group = QGroupBox("Smart Telescope")
        telescope_layout = QFormLayout(telescope_group)

        self.telescope_list = QListWidget()
        self.telescope_list.addItem("SeeStar")
        self.telescope_list.addItem("StellarMate")
        self.telescope_list.addItem("DWARF 3")
        self.telescope_list.addItem("iTelescope")
        self.telescope_list.addItem("Celestron Origin")
        self.telescope_list.addItem("SFTP")
        self.telescope_list.setCurrentRow(0)
        self.telescope_list.setMaximumHeight(100)

        telescope_layout.addRow("Telescope Type:", self.telescope_list)

        # Connection settings
        connection_group = QGroupBox("Connection Settings")
        connection_layout = QFormLayout(connection_group)

        self.hostname_edit = QLineEdit("seestar.local")
        self.hostname_edit.setToolTip("Hostname or IP address of the telescope")

        self.network_edit = QLineEdit()
        default_network = smart_telescope_manager.get_local_network()
        self.network_edit.setText(default_network)
        self.network_edit.setToolTip("Network range to scan (e.g., 10.0.0.0/24)")

        # Target directory for downloads
        self.target_dir_edit = QLineEdit()
        self.target_dir_edit.setToolTip("Directory where downloaded files will be stored")

        default_target_dir = self.get_default_target_directory()
        self.target_dir_edit.setText(default_target_dir)

        self.browse_target_button = QPushButton("Browse...")
        self.browse_target_button.setStyleSheet("QPushButton { font-size: 10px; }")
        self.browse_target_button.clicked.connect(self.browse_target_directory)

        target_dir_layout = QHBoxLayout()
        target_dir_layout.addWidget(self.target_dir_edit)
        target_dir_layout.addWidget(self.browse_target_button)

        connection_layout.addRow("Hostname:", self.hostname_edit)
        connection_layout.addRow("Network:", self.network_edit)
        connection_layout.addRow("Target Directory:", target_dir_layout)

        # Delete files option
        self.delete_files_checkbox = QCheckBox("Delete files on host after download")
        self.delete_files_checkbox.setChecked(False)
        self.delete_files_checkbox.setToolTip("WARNING: This will permanently delete files from the telescope after successful download")
        connection_layout.addRow("", self.delete_files_checkbox)

        # Buttons
        button_layout = QHBoxLayout()
        self.download_button = QPushButton("Download")
        self.download_button.setStyleSheet("QPushButton { font-size: 11px; }")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet("QPushButton { font-size: 11px; }")

        button_layout.addStretch()
        button_layout.addWidget(self.download_button)
        button_layout.addWidget(self.cancel_button)

        layout.addWidget(telescope_group)
        layout.addWidget(connection_group)
        layout.addStretch()
        layout.addLayout(button_layout)

        # Connect signals
        self.telescope_list.currentTextChanged.connect(self.on_telescope_changed)
        self.download_button.clicked.connect(self.start_download)
        self.cancel_button.clicked.connect(self.reject)

        self.on_telescope_changed()

    def get_default_target_directory(self):
        """Get the default target directory from configuration (source path)."""
        try:
            config = load_library_config()

            if config.has_option('DEFAULT', 'source'):
                source_path = config.get('DEFAULT', 'source')
                if source_path and os.path.exists(source_path):
                    return source_path

            return os.getcwd()

        except Exception as e:
            logger.debug(f"Error reading configuration: {e}")
            return os.getcwd()

    def browse_target_directory(self):
        """Open directory picker for target directory."""
        current_dir = self.target_dir_edit.text().strip()
        if not current_dir or not os.path.exists(current_dir):
            current_dir = os.getcwd()

        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Target Directory for Downloads",
            current_dir,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )

        if directory:
            self.target_dir_edit.setText(directory)

    def on_telescope_changed(self):
        """Handle telescope selection change."""
        current_telescope = self.telescope_list.currentItem()
        if current_telescope:
            telescope_type = current_telescope.text()
            if telescope_type == "SeeStar":
                self.hostname_edit.setText("seestar.local")
            elif telescope_type == "StellarMate":
                self.hostname_edit.setText("stellarmate.local")
            elif telescope_type == "DWARF 3":
                self.hostname_edit.setText("dwarf.local")
            elif telescope_type == "iTelescope":
                self.hostname_edit.setText("data.itelescope.net")
            elif telescope_type == "Celestron Origin":
                # Prefer the address saved under Options > Library; the Origin's hotspot default otherwise
                self.hostname_edit.setText(smart_telescope_manager.get_celestron_hostname() or "192.168.1.208")
            elif telescope_type == "SFTP":
                self.hostname_edit.setText("")
            self.network_edit.setEnabled(telescope_type != "SFTP")   # an SFTP server is addressed, never scanned for

    def start_download(self):
        """Start the download process."""
        current_telescope = self.telescope_list.currentItem()
        if not current_telescope:
            QMessageBox.warning(self, "Warning", "Please select a telescope type.")
            return

        telescope_type = current_telescope.text()
        hostname = self.hostname_edit.text().strip()
        network = self.network_edit.text().strip()
        target_directory = self.target_dir_edit.text().strip()
        delete_files = self.delete_files_checkbox.isChecked()

        if telescope_type == "SFTP" and not hostname:
            QMessageBox.warning(self, "Warning", "Please enter the SFTP server's hostname or IP address.")
            return

        if not network and telescope_type != "SFTP":
            QMessageBox.warning(self, "Warning", "Please enter a network range.")
            return

        if not target_directory:
            QMessageBox.warning(self, "Warning", "Please specify a target directory.")
            return

        # Create progress dialog
        self.progress_dialog = QProgressDialog("Initializing download...", "Cancel", 0, 100, self)
        self.progress_dialog.setWindowTitle("Downloading from Smart Telescope")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)
        self.progress_dialog.show()

        # Create and configure worker thread
        self.worker = TelescopeDownloadWorker(telescope_type, hostname, network, target_directory, delete_files)

        # Connect worker signals to handlers
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.progress_percent_updated.connect(self.on_progress_percent_updated)
        self.worker.download_completed.connect(self.on_download_completed)
        self.worker.error_occurred.connect(self.on_error_occurred)

        # Connect progress dialog cancel to worker stop
        self.progress_dialog.canceled.connect(self.on_download_cancelled)

        # Start the worker thread
        self.worker.start()
        logger.info(f"Started download from {telescope_type} to {target_directory}")

    def on_progress_updated(self, message):
        """Handle progress text updates from worker thread."""
        if hasattr(self, 'progress_dialog') and self.progress_dialog is not None:
            self.progress_dialog.setLabelText(message)
            QApplication.processEvents()

    def on_progress_percent_updated(self, percent):
        """Handle progress percentage updates from worker thread."""
        if hasattr(self, 'progress_dialog') and self.progress_dialog is not None:
            self.progress_dialog.setValue(percent)
            QApplication.processEvents()

    def on_download_completed(self, message):
        """Handle download completion from worker thread."""
        logger.info(f"Download completed: {message}")

        # Close progress dialog
        self.close_progress_dialog()

        # Show completion message
        QMessageBox.information(self, "Download Complete", message)

        # Refresh the Images view in the main window if available
        if self.parent() and hasattr(self.parent(), 'images_widget') and hasattr(self.parent().images_widget, 'load_fits_data'):
            logger.info("Refreshing Images view after download completion")
            self.parent().images_widget.load_fits_data()

        # Close the download dialog
        self.accept()

    def on_error_occurred(self, error_message):
        """Handle errors from worker thread."""
        logger.error(f"Download error: {error_message}")

        # Close progress dialog
        self.close_progress_dialog()

        # Show error message
        QMessageBox.critical(self, "Download Error", error_message)

    def on_download_cancelled(self):
        """Handle download cancellation."""
        logger.info("Download cancelled by user")

        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            if not self.worker.wait(3000):
                self.worker.terminate()
                self.worker.wait(1000)

        # Close progress dialog
        self.close_progress_dialog()

    def closeEvent(self, event):
        """Handle dialog close event to ensure worker thread is stopped."""
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            if not self.worker.wait(3000):
                self.worker.terminate()
                self.worker.wait(1000)
        event.accept()

    def reject(self):
        """Handle dialog rejection (ESC key, X button, etc.)."""
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            if not self.worker.wait(3000):
                self.worker.terminate()
                self.worker.wait(1000)
        super().reject()

    # ...existing code for progress handling methods...

    def close_progress_dialog(self):
        """Close the progress dialog safely."""
        if hasattr(self, 'progress_dialog') and self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog = None
