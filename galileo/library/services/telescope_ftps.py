# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Smart-telescope file transfer over FTP over TLS (iTelescope) - mixed into ``SmartTelescopeManager``."""

import logging
import os
from galileo.library.config import get_itelescope_verify_tls
import time
import ftplib  # nosec B402 -- plain FTP is the only protocol some smart telescopes offer
import ssl

logger = logging.getLogger(__name__)

def _new_ftps_client() -> ftplib.FTP_TLS:
    """An FTP-over-TLS client that verifies the server certificate and host name.

    Verification can be switched off in Options > Library > Smart Telescopes for a server whose
    certificate does not validate; the connection is then still encrypted but not authenticated."""
    if get_itelescope_verify_tls():
        return ftplib.FTP_TLS(context=ssl.create_default_context())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # explicit user opt-out
    return ftplib.FTP_TLS(context=context)  # noqa: S321 -- FTP over TLS



class FtpsMixin:
    """FTP over TLS (iTelescope) listing / download methods of the smart-telescope manager."""

    def _get_fits_files_ftps(self, telescope_type, hostname, username=None, password=None):
        """Get FITS files via FTPS protocol (iTelescope)."""
        logger.info(f"Using FTPS connection for {telescope_type}")

        if not username or not password:
            logger.error("Username and password required for iTelescope FTPS connection")
            return [], "Username and password required for iTelescope FTPS connection"

        try:
            # Create FTPS connection (FTP over TLS)
            ftps = _new_ftps_client()
            logger.debug(f"Attempting FTPS connection to {hostname}:21...")
            ftps.connect(hostname, 21, timeout=30)

            # Login with user credentials
            ftps.login(username, password)

            # Switch to secure data connection
            ftps.prot_p()
            logger.info(f"Successfully connected to FTPS service at {hostname}")

            try:
                # Get FITS files from iTelescope structure
                start_time = time.time()
                fits_files = self._get_fits_files_from_itelescope_ftps(ftps, hostname)
                scan_time = time.time() - start_time

                ftps.quit()
                logger.info(f"Found {len(fits_files)} FITS files in {scan_time:.2f} seconds")
                return fits_files, None

            except Exception as e:
                ftps.quit()
                logger.exception(f"Error accessing files on {hostname}")
                return [], f"Error accessing files: {e}"

        except Exception as e:
            logger.exception(f"FTPS connection error to {hostname}")
            return [], f"FTPS connection error: {e}"

    def _get_fits_files_from_itelescope_ftps(self, ftps, hostname):
        """Get all calibrated FITS files from iTelescope FTPS server."""
        fits_files = []

        try:
            # Start from root directory
            ftps.cwd('/')

            # Recursively scan all directories for files starting with 'calibrated'
            self._scan_itelescope_directory(ftps, '', fits_files, hostname)

        except Exception:
            logger.exception("Error scanning iTelescope directories")

        return fits_files

    def _scan_itelescope_directory(self, ftps, current_path, fits_files, hostname, max_depth=10, current_depth=0):
        """Recursively scan iTelescope directory structure for calibrated files."""
        if current_depth > max_depth:
            logger.debug(f"Maximum depth reached at '{current_path}', stopping recursion")
            return

        try:
            # Change to the current directory
            if current_path:
                ftps.cwd('/')
                ftps.cwd(current_path)

            # List files and directories
            items = []
            try:
                ftps.retrlines('LIST', items.append)
            except Exception as e:
                logger.debug(f"Could not list directory {current_path}: {e}")
                return

            for item_line in items:
                # Parse FTP LIST output (Unix-style)
                # Example: -rw-r--r--   1 user group      1234 Jan 01 12:00 filename.fits
                parts = item_line.split()
                if len(parts) < 9:
                    continue

                permissions = parts[0]
                filename = ' '.join(parts[8:])  # Handle filenames with spaces

                # Skip hidden files and current/parent directory references
                if filename.startswith('.'):
                    continue

                item_path = f"{current_path}/{filename}" if current_path else filename

                if permissions.startswith('d'):
                    # It's a directory
                    if not current_path:
                        # Root level - only scan directories that start with 'T' or 't'
                        if filename.lower().startswith('t'):
                            logger.debug(f"Scanning root telescope directory: {item_path}")
                            self._scan_itelescope_directory(ftps, item_path, fits_files, hostname, max_depth, current_depth + 1)
                        else:
                            logger.debug(f"Skipping non-telescope root directory: {filename}")
                    else:
                        # Subfolder within telescope directory - scan all subdirectories
                        logger.debug(f"Scanning telescope subdirectory: {item_path}")
                        self._scan_itelescope_directory(ftps, item_path, fits_files, hostname, max_depth, current_depth + 1)

                elif filename.lower().startswith('calibrated') and filename.lower().endswith('.fit.zip'):
                    # It's a calibrated FIT zip file
                    try:
                        # Get file size
                        if current_path:
                            ftps.cwd('/')
                            ftps.cwd(current_path)
                        size = ftps.size(filename)
                    except Exception:
                        size = 0

                    # Extract date from LIST output if possible
                    try:
                        date_str = f"{parts[5]} {parts[6]} {parts[7]}"
                    except Exception:
                        date_str = "Unknown"

                    fits_files.append({
                        "name": filename,
                        "path": item_path,
                        "size": size,
                        "date": date_str,
                        "share_name": "ftps_root",
                        "folder_name": os.path.basename(current_path) if current_path else "root",
                        "telescope_type": "iTelescope",
                        "file_type": "calibrated_light_zip",
                        "object": self._extract_object_from_filename(filename),
                        "instrument": "iTelescope",
                        "hostname": hostname
                    })
                    logger.debug(f"Found iTelescope calibrated file: {item_path}")

        except Exception:
            logger.exception(f"Error scanning iTelescope directory {current_path}")

    def _download_file_ftps(self, telescope_type, hostname, file_info, local_path, username=None, password=None, progress_callback=None):
        """Download file via FTPS protocol (iTelescope)."""
        file_name = os.path.basename(file_info['path'])

        if not username or not password:
            logger.error("Username and password required for iTelescope FTPS download")
            return False, "Username and password required"

        try:
            # Create FTPS connection
            ftps = _new_ftps_client()
            ftps.connect(hostname, 21, timeout=30)
            ftps.login(username, password)
            ftps.prot_p()  # Switch to secure data connection

            try:
                # Navigate to the directory containing the file
                file_dir = os.path.dirname(file_info['path'])
                if file_dir:
                    ftps.cwd('/')
                    ftps.cwd(file_dir)

                # Download the file with progress tracking
                total_size = file_info.get('size', 0)
                downloaded = 0

                def progress_handler(data):
                    nonlocal downloaded
                    downloaded += len(data)
                    if progress_callback and total_size > 0:
                        progress = int((downloaded / total_size) * 100)
                        progress_callback(f"Downloading {file_name}: {progress}%")
                    local_file.write(data)

                with open(local_path, 'wb') as local_file:
                    ftps.retrbinary(f'RETR {file_name}', progress_handler)

                ftps.quit()
                logger.info(f"Successfully downloaded {file_name} to {local_path}")
                return True, None

            except Exception as e:
                ftps.quit()
                logger.exception(f"Error downloading {file_name}")
                return False, f"Error downloading file: {e}"

        except Exception as e:
            logger.exception(f"FTPS connection error during download of {file_name}")
            return False, f"FTPS connection error: {e}"
