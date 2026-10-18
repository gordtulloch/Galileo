# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Smart-telescope file transfer over plain FTP (DWARF) - mixed into ``SmartTelescopeManager``."""

import logging
import os
import time
import ftplib  # nosec B402 -- plain FTP is the only protocol some smart telescopes offer

logger = logging.getLogger(__name__)


class FtpMixin:
    """plain FTP (DWARF) listing / download methods of the smart-telescope manager."""

    def _get_fits_files_ftp(self, telescope_type, ip, username=None, password=None):
        """Get FITS files via FTP protocol (DWARF)."""
        logger.info(f"Using FTP connection for {telescope_type}")

        try:
            # Create FTP connection (no authentication for DWARF)
            ftp = ftplib.FTP()  # noqa: S321  # nosec B321 -- plain FTP: the device offers nothing else (LAN-only)
            logger.debug(f"Attempting FTP connection to {ip}:21...")
            ftp.connect(ip, 21, timeout=10)

            # Anonymous login (no username/password for DWARF)
            ftp.login()
            logger.info(f"Successfully connected to FTP service at {ip}")

            try:
                # Check for DWARF folder structure
                if not self._validate_dwarf_structure(ftp):
                    ftp.quit()
                    return [], "DWARF folder structure not recognized"

                # Get FITS files from DWARF structure
                start_time = time.time()
                fits_files = self._get_fits_files_from_dwarf_ftp(ftp)
                scan_time = time.time() - start_time

                ftp.quit()
                logger.info(f"Found {len(fits_files)} FITS files in {scan_time:.2f} seconds")
                return fits_files, None

            except Exception as e:
                ftp.quit()
                logger.exception(f"Error accessing files on {ip}")
                return [], f"Error accessing files: {e}"

        except Exception as e:
            logger.exception(f"FTP connection error to {ip}")
            return [], f"FTP connection error: {e}"

    def _validate_dwarf_structure(self, ftp):
        """Validate that FTP root contains required DWARF folder structure."""
        try:
            files = ftp.nlst('/')
            required_folders = ['CALI_FRAME', 'DWARF_DARK']
            dwarf_raw_folders = [f for f in files if f.startswith('DWARF_RAW')]

            has_required = all(folder in files for folder in required_folders)
            has_dwarf_raw = len(dwarf_raw_folders) > 0

            if has_required and has_dwarf_raw:
                logger.info(f"Valid DWARF structure found: {required_folders} + {len(dwarf_raw_folders)} DWARF_RAW folders")
                return True
            else:
                logger.warning(f"DWARF folder structure not recognized. Found: {files}")
                return False

        except Exception:
            logger.exception("Error validating DWARF structure")
            return False

    def _get_fits_files_from_dwarf_ftp(self, ftp):
        """Get FITS files from DWARF telescope via FTP."""
        fits_files = []

        try:
            # Scan root directory for DWARF_RAW folders (light files)
            files = ftp.nlst('/')
            dwarf_raw_folders = [f for f in files if f.startswith('DWARF_RAW')]

            for folder in dwarf_raw_folders:
                logger.debug(f"Scanning DWARF_RAW folder: {folder}")
                self._scan_dwarf_raw_folder(ftp, folder, fits_files)

            # Scan calibration folders
            if 'CALI_FRAME' in files:
                logger.debug("Scanning CALI_FRAME folder")
                self._scan_dwarf_cali_folder(ftp, 'CALI_FRAME', fits_files)

            if 'DWARF_DARK' in files:
                logger.debug("Scanning DWARF_DARK folder")
                self._scan_dwarf_dark_folder(ftp, 'DWARF_DARK', fits_files)

        except Exception:
            logger.exception("Error scanning DWARF FTP structure")

        return fits_files

    def _scan_dwarf_raw_folder(self, ftp, folder_name, fits_files):
        """Scan a DWARF_RAW folder for light frame FITS files."""
        try:
            # Parse folder name to extract metadata
            # Expected format: DWARF_RAW_(INSTRUMEN)_(OBJECT)_EXP_(EXPTIME)_GAIN_(GAIN)_(DATE-OBS)
            folder_parts = folder_name.split("_")
            object_name = "Unknown"
            instrument = "Unknown"
            exptime = "Unknown"
            gain = "Unknown"

            if len(folder_parts) >= 8:
                try:
                    instrument = folder_parts[2]  # INSTRUMEN
                    object_name = folder_parts[3]  # OBJECT
                    exptime = folder_parts[5]  # EXPTIME (after EXP)
                    gain = folder_parts[7]  # GAIN (after GAIN)
                except IndexError:
                    logger.warning(f"Could not parse DWARF_RAW folder name: {folder_name}")

            ftp.cwd('/')
            ftp.cwd(folder_name)
            files = ftp.nlst('.')

            for file in files:
                if file.startswith('failed_'):
                    logger.debug(f"Ignoring failed image: {file}")
                    continue

                if file.lower().endswith('.fits') or file.lower().endswith('.fit'):
                    file_path = f"{folder_name}/{file}"
                    try:
                        size = ftp.size(file)
                    except Exception:
                        size = 0

                    fits_files.append({
                        "name": file,
                        "path": file_path,
                        "size": size,
                        "date": "Unknown",
                        "share_name": "ftp_root",
                        "folder_name": folder_name,
                        "telescope_type": "DWARF 3",
                        "file_type": "light",
                        "object": object_name,
                        "instrument": instrument,
                        "exptime": exptime,
                        "gain": gain
                    })
                    logger.debug(f"Found DWARF light file: {file_path} (Object: {object_name}, Instrument: {instrument})")

        except Exception:
            logger.exception(f"Error scanning DWARF_RAW folder {folder_name}")

    def _scan_dwarf_cali_folder(self, ftp, folder_name, fits_files):
        """Scan CALI_FRAME folder for calibration master frames."""
        try:
            ftp.cwd('/')
            ftp.cwd(folder_name)

            # Look for bias, dark, flat folders
            cali_types = ['bias', 'dark', 'flat']
            folders = ftp.nlst('.')

            for cali_type in cali_types:
                if cali_type in folders:
                    self._scan_dwarf_cali_type_folder(ftp, f"{folder_name}/{cali_type}", cali_type, fits_files)

        except Exception:
            logger.exception("Error scanning CALI_FRAME folder")

    def _scan_dwarf_cali_type_folder(self, ftp, folder_path, cali_type, fits_files):
        """Scan a calibration type folder (bias/dark/flat) for cam_0 and cam_1 subfolders."""
        try:
            ftp.cwd('/')
            ftp.cwd(folder_path)
            folders = ftp.nlst('.')

            # Look for cam_0 (TELE) and cam_1 (WIDE) folders
            for cam_folder in ['cam_0', 'cam_1']:
                if cam_folder in folders:
                    instrument = 'TELE' if cam_folder == 'cam_0' else 'WIDE'
                    self._scan_dwarf_cam_folder(ftp, f"{folder_path}/{cam_folder}", cali_type, instrument, fits_files)

        except Exception:
            logger.exception(f"Error scanning calibration type folder {folder_path}")

    def _scan_dwarf_cam_folder(self, ftp, folder_path, cali_type, instrument, fits_files):
        """Scan a camera folder for FITS files."""
        try:
            ftp.cwd('/')
            ftp.cwd(folder_path)
            files = ftp.nlst('.')

            for file in files:
                if file.lower().endswith('.fits') or file.lower().endswith('.fit'):
                    try:
                        size = ftp.size(file)
                    except Exception:
                        size = 0

                    fits_files.append({
                        "name": file,
                        "path": f"{folder_path}/{file}",
                        "size": size,
                        "date": "Unknown",
                        "share_name": "ftp_root",
                        "folder_name": os.path.basename(folder_path),
                        "telescope_type": "DWARF 3",
                        "file_type": f"master_{cali_type}",
                        "instrument": instrument,
                        "calibration_type": cali_type
                    })
                    logger.debug(f"Found DWARF {cali_type} master file: {folder_path}/{file}")

        except Exception:
            logger.exception(f"Error scanning camera folder {folder_path}")

    def _scan_dwarf_dark_folder(self, ftp, folder_name, fits_files):
        """Scan DWARF_DARK folder for dark library files."""
        try:
            ftp.cwd('/')
            ftp.cwd(folder_name)
            files = ftp.nlst('.')

            for file in files:
                if file.startswith('tele_') and (file.lower().endswith('.fits') or file.lower().endswith('.fit')):
                    try:
                        size = ftp.size(file)
                    except Exception:
                        size = 0

                    fits_files.append({
                        "name": file,
                        "path": f"{folder_name}/{file}",
                        "size": size,
                        "date": "Unknown",
                        "share_name": "ftp_root",
                        "folder_name": folder_name,
                        "telescope_type": "DWARF 3",
                        "file_type": "dark_library",
                        "instrument": "TELE"
                    })
                    logger.debug(f"Found DWARF dark library file: {folder_name}/{file}")

        except Exception:
            logger.exception("Error scanning DWARF_DARK folder")

    def _download_file_ftp(self, telescope_type, ip, file_info, local_path, progress_callback=None):
        """Download file via FTP protocol."""
        file_name = os.path.basename(file_info['path'])

        try:
            # Create FTP connection
            ftp = ftplib.FTP()  # noqa: S321  # nosec B321 -- plain FTP: the device offers nothing else (LAN-only)
            logger.debug(f"Connecting to {ip} for FTP file download...")
            ftp.connect(ip, 21, timeout=10)
            ftp.login()  # Anonymous login for DWARF

            try:
                # Create local directory if it doesn't exist
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                logger.debug(f"Downloading to local path: {local_path}")

                # Download the file
                start_time = time.time()

                with open(local_path, 'wb') as local_file:
                    def progress_wrapper(data):
                        if progress_callback:
                            # Simple progress tracking for FTP (not as detailed as SMB)
                            progress_callback(50)  # Basic progress indication
                        local_file.write(data)

                    ftp.retrbinary(f'RETR {file_info["path"]}', progress_wrapper)

                download_time = time.time() - start_time
                download_speed = (file_info['size'] / 1024 / 1024) / download_time if download_time > 0 else 0
                logger.info(f"Successfully downloaded {file_name} in {download_time:.2f}s ({download_speed:.2f} MB/s)")

                ftp.quit()
                return True, None

            except Exception as e:
                ftp.quit()
                logger.exception(f"Error downloading {file_name}")
                return False, f"Error downloading file: {e}"

        except Exception as e:
            logger.exception(f"FTP connection error during download of {file_name}")
            return False, f"FTP connection error: {e}"
