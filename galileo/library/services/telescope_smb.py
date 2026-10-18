# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Smart-telescope file transfer over SMB (Seestar, StellarMate) - mixed into ``SmartTelescopeManager``."""

import logging
import os
import time
from galileo.library.exceptions import TelescopeConnectionError

logger = logging.getLogger(__name__)

try:
    from smb.SMBConnection import SMBConnection
    SMB_AVAILABLE = True
except ImportError:
    SMBConnection = None  # type: ignore[assignment,misc]
    SMB_AVAILABLE = False


class SmbMixin:
    """SMB (Seestar, StellarMate) listing / download methods of the smart-telescope manager."""

    def _get_fits_files_smb(self, telescope_type, ip, username=None, password=None):
        """Get FITS files via SMB protocol (SeeStar)."""
        if not SMB_AVAILABLE:
            logger.error("SMB protocol not available")
            return [], "SMB protocol not available"

        config = self.supported_telescopes.get(telescope_type)
        username = username or config['default_username']
        password = password or config['default_password']
        share_name = config['share_name']
        fits_path = config['fits_path']

        logger.debug(f"Using SMB share: {share_name}, path: {fits_path}, username: {username}")

        try:
            # Create SMB connection
            conn = SMBConnection(username, password, "client", "server", use_ntlm_v2=True)

            # Try to connect
            logger.debug(f"Attempting SMB connection to {ip}:445...")
            connected = conn.connect(str(ip), 445, timeout=10)

            if not connected:
                logger.error(f"Failed to connect to SMB service at {ip}")
                return [], "Failed to connect to SMB service"

            logger.info(f"Successfully connected to SMB service at {ip}")

            try:
                # Get FITS files from the specified path
                logger.debug(f"Scanning for FITS files in {share_name}/{fits_path}")
                start_time = time.time()
                fits_files = self._get_fits_files_from_path_smb(conn, share_name, fits_path, telescope_type)
                scan_time = time.time() - start_time

                conn.close()
                logger.info(f"Found {len(fits_files)} FITS files in {scan_time:.2f} seconds")
                return fits_files, None

            except Exception as e:
                conn.close()
                logger.exception(f"Error accessing files on {ip}")
                return [], f"Error accessing files: {e}"

        except Exception as e:
            logger.exception(f"Connection error to {ip}")
            return [], f"Connection error: {e}"

    def _get_fits_files_from_path_smb(self, conn, share_name, target_path, telescope_type):
        """Get all FITS files from folders ending in '_sub' within the target path."""
        fits_files = []
        visited_paths = set()  # Prevent infinite loops
        max_depth = 10  # Limit recursion depth

        def scan_directory(path="", depth=0):
            # Prevent infinite recursion
            if depth > max_depth:
                logger.debug(f"Maximum depth reached at '{path}', stopping recursion")
                return

            # Prevent revisiting the same path
            if path in visited_paths:
                return
            visited_paths.add(path)

            try:
                # List files in the directory
                logger.debug(f"Scanning directory: '{path}' (depth: {depth})")
                files = conn.listPath(share_name, path or "/")

                for file_info in files:
                    if file_info.filename in ['.', '..']:
                        continue

                    item_path = os.path.join(path, file_info.filename).replace('\\', '/') if path else file_info.filename

                    if file_info.isDirectory:
                        # If we haven't found the target directory yet, keep looking
                        if not path and file_info.filename == target_path:
                            logger.debug(f"Found target directory: {target_path}")
                            scan_directory(item_path, depth + 1)
                        elif path.startswith(target_path + "/") or path == target_path:
                            # We're inside the target directory
                            # Only scan subdirectories that end with '_sub'
                            if file_info.filename.endswith('_sub'):
                                logger.debug(f"Found _sub directory: {file_info.filename}")
                                scan_directory(item_path, depth + 1)
                            else:
                                logger.debug(f"Skipping non-_sub directory: {file_info.filename}")
                        elif not path:
                            # Still looking for the target directory at root level
                            scan_directory(item_path, depth + 1)
                    else:
                        # Check if it's a FITS file and we're in a _sub folder within the target path
                        current_folder = os.path.basename(path) if path else ""
                        if ((path == target_path or path.startswith(target_path + "/")) and
                            current_folder.endswith('_sub') and
                            (file_info.filename.lower().endswith('.fits') or
                             file_info.filename.lower().endswith('.fit'))):

                            logger.debug(f"Found FITS file: {file_info.filename} in {path}")
                            fits_files.append({
                                "name": file_info.filename,
                                "path": item_path,
                                "size": file_info.file_size,
                                "date": str(file_info.last_write_time),
                                "share_name": share_name,
                                "folder_name": current_folder  # Add folder name for header processing
                            })

            except Exception as e:
                logger.debug(f"Error scanning directory '{path}': {e}")

        # Start scanning from root
        logger.debug(f"Starting scan for target directory: {target_path} (looking for folders ending in '_sub')")
        scan_directory()

        logger.debug(f"Scan complete. Found {len(fits_files)} FITS files in _sub folders.")
        return fits_files

    def _download_file_smb(self, telescope_type, ip, file_info, local_path, username=None, password=None, progress_callback=None):
        """Download file via SMB protocol."""
        file_name = os.path.basename(file_info['path'])

        if not SMB_AVAILABLE:
            logger.error("SMB protocol not available for download")
            return False, "SMB protocol not available"

        config = self.supported_telescopes.get(telescope_type)
        username = username or config['default_username']
        password = password or config['default_password']

        try:
            # Create SMB connection
            conn = SMBConnection(username, password, "client", "server", use_ntlm_v2=True)

            # Try to connect
            logger.debug(f"Connecting to {ip} for file download...")
            connected = conn.connect(str(ip), 445, timeout=10)

            if not connected:
                logger.error(f"Failed to connect to SMB service at {ip} for download")
                return False, "Failed to connect to SMB service"

            try:
                # Create local directory if it doesn't exist
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                logger.debug(f"Downloading to local path: {local_path}")

                # Download the file
                start_time = time.time()
                with open(local_path, 'wb') as local_file:
                    file_size = file_info['size']

                    # Use a wrapper class to handle progress tracking and cancellation
                    class ProgressFileWrapper:
                        def __init__(self, file_obj, progress_callback, total_size):
                            self.file_obj = file_obj
                            self.progress_callback = progress_callback
                            self.total_size = total_size
                            self.bytes_written = 0
                            self.cancelled = False

                        def write(self, data):
                            if self.cancelled:
                                raise TelescopeConnectionError("Download cancelled by user")

                            result = self.file_obj.write(data)
                            self.bytes_written += len(data)
                            if self.progress_callback:
                                progress = (self.bytes_written / self.total_size) * 100 if self.total_size > 0 else 0
                                # Check if callback returns False (cancellation request)
                                if self.progress_callback(progress) is False:
                                    self.cancelled = True
                                    raise TelescopeConnectionError("Download cancelled by user")
                            return result

                        def __getattr__(self, name):
                            return getattr(self.file_obj, name)

                    # Wrap the file object for progress tracking
                    wrapped_file = ProgressFileWrapper(local_file, progress_callback, file_size)

                    conn.retrieveFile(file_info['share_name'], file_info['path'], wrapped_file)

                download_time = time.time() - start_time
                download_speed = (file_info['size'] / 1024 / 1024) / download_time if download_time > 0 else 0
                logger.info(f"Successfully downloaded {file_name} in {download_time:.2f}s ({download_speed:.2f} MB/s)")

                conn.close()
                return True, None

            except Exception as e:
                conn.close()
                logger.exception(f"Error downloading {file_name}")
                return False, f"Error downloading file: {e}"

        except Exception as e:
            logger.exception(f"Connection error during download of {file_name}")
            return False, f"Connection error: {e}"
