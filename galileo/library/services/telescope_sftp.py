# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Smart-telescope file transfer over SFTP - mixed into ``SmartTelescopeManager``."""

import logging
from galileo.library.config import get_sftp_settings

logger = logging.getLogger(__name__)


class SftpMixin:
    """SFTP listing / download methods of the smart-telescope manager."""

    @staticmethod
    def _open_sftp(host):
        """A connected SftpSession to *host* using the Options > Library SFTP settings."""
        from galileo.library.adapters.sftp import SftpSession
        s = get_sftp_settings()
        return SftpSession(host, s['username'], s['password'], s['key_path'], s['port'], s['strict_host_keys'])

    def _get_fits_files_sftp(self, host):
        """Every FITS file under the configured remote folder of an SFTP server."""
        try:
            with self._open_sftp(host) as session:
                return session.list_fits(get_sftp_settings()['remote_path']), None
        except Exception as e:
            logger.warning(f"SFTP listing on {host} failed", exc_info=True)
            return [], f"SFTP error: {e}"

    def _download_file_sftp(self, host, file_info, local_path, progress_callback=None):
        from galileo.library.adapters.sftp import SftpDownloadCancelled
        try:
            with self._open_sftp(host) as session:
                session.get(
                    file_info['path'], local_path,
                    (lambda done, total: progress_callback(done)) if progress_callback else None)
            return True, None
        except SftpDownloadCancelled:
            return False, "Download cancelled"
        except Exception as e:
            logger.warning(f"SFTP download of {file_info.get('name')} from {host} failed", exc_info=True)
            return False, f"SFTP error: {e}"

    def _delete_file_sftp(self, host, file_info):
        try:
            with self._open_sftp(host) as session:
                session.remove(file_info['path'])
            return True, None
        except Exception as e:
            logger.warning(f"SFTP delete of {file_info.get('name')} on {host} failed", exc_info=True)
            return False, f"SFTP error: {e}"
