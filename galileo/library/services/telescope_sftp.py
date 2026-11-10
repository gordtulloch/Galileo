# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Smart-telescope file transfer over SFTP - mixed into ``SmartTelescopeManager``."""

import atexit
import logging
import threading
from galileo.library.config import get_sftp_settings

logger = logging.getLogger(__name__)


class SftpMixin:
    """SFTP listing / download methods of the smart-telescope manager."""

    # One open connection per host, shared by every download/delete of a batch. Opening an SSH
    # connection (key exchange + login) costs far more than it should on a Raspberry Pi, and used to be
    # paid once per file. Callers end a batch with close_sftp_sessions(); atexit is the safety net.
    _sftp_sessions: dict = {}
    _sftp_lock = threading.Lock()

    @staticmethod
    def _open_sftp(host):
        """A connected SftpSession to *host* using the Options > Library SFTP settings."""
        from galileo.library.adapters.sftp import SftpSession
        s = get_sftp_settings()
        return SftpSession(host, s['username'], s['password'], s['key_path'], s['port'], s['strict_host_keys'])

    def _shared_sftp(self, host):
        """The cached, still-alive session to *host*, opened on first use (or after it dropped)."""
        with self._sftp_lock:
            session = self._sftp_sessions.get(host)
            if session is not None and not session.is_alive():
                session.close()
                session = None
            if session is None:
                session = self._open_sftp(host)
                session.open()
                self._sftp_sessions[host] = session
            return session

    def _drop_shared_sftp(self, host):
        with self._sftp_lock:
            session = self._sftp_sessions.pop(host, None)
        if session is not None:
            session.close()

    def close_sftp_sessions(self):
        """Close every cached SFTP connection - call when a download batch is finished."""
        with self._sftp_lock:
            sessions = list(self._sftp_sessions.values())
            self._sftp_sessions.clear()
        for session in sessions:
            session.close()

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
            session = self._shared_sftp(host)
            session.get(
                file_info['path'], local_path,
                (lambda done, total: progress_callback(done)) if progress_callback else None)
            return True, None
        except SftpDownloadCancelled:
            return False, "Download cancelled"
        except Exception as e:
            self._drop_shared_sftp(host)        # the connection may be the problem; reopen next time
            logger.warning(f"SFTP download of {file_info.get('name')} from {host} failed", exc_info=True)
            return False, f"SFTP error: {e}"

    def _delete_file_sftp(self, host, file_info):
        try:
            self._shared_sftp(host).remove(file_info['path'])
            return True, None
        except Exception as e:
            self._drop_shared_sftp(host)
            logger.warning(f"SFTP delete of {file_info.get('name')} on {host} failed", exc_info=True)
            return False, f"SFTP error: {e}"


def _close_all_at_exit():
    for session in list(SftpMixin._sftp_sessions.values()):
        try:
            session.close()
        except Exception:
            logger.debug("SFTP: error closing at exit", exc_info=True)


atexit.register(_close_all_at_exit)
