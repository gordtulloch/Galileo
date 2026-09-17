"""FTP/FTPS smart telescope adapter (iTelescope, DWARF) (LIB-100, LIB-110)."""

from __future__ import annotations

import asyncio
import ftplib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SmartTelescopeFtpAdapter:
    """Browse and download FITS files from iTelescope/DWARF via FTP/FTPS."""

    def __init__(self, host: str = "", user: str = "", password: str = "") -> None:
        self.host = host
        self.user = user
        self.password = password

    async def browse(
        self,
        host: str = "",
        use_tls: bool = True,
        path: str = "/",
    ) -> list[str]:
        """Return a list of remote FITS file paths."""
        host = host or self.host
        return await asyncio.to_thread(self._browse_sync, host, use_tls, path)

    def _browse_sync(self, host: str, use_tls: bool, path: str) -> list[str]:
        try:
            cls = ftplib.FTP_TLS if use_tls else ftplib.FTP
            with cls() as ftp:
                ftp.connect(host, 21, timeout=10)
                ftp.login(self.user, self.password)
                if use_tls and isinstance(ftp, ftplib.FTP_TLS):
                    ftp.prot_p()
                files = []
                ftp.cwd(path)
                ftp.retrlines("LIST", lambda line: files.append(line.split()[-1] if line else ""))
                return [f for f in files if f.endswith((".fits", ".fit", ".zip"))]
        except Exception as exc:
            logger.debug("FTP browse error: %s", exc)
            return []

    async def download(self, remote_path: str, dest: "Path | str") -> Path:
        """Download *remote_path* to *dest*."""
        dest_path = Path(dest) / Path(remote_path).name
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._download_sync, remote_path, dest_path)
        return dest_path

    def _download_sync(self, remote_path: str, dest_path: Path) -> None:
        try:
            with ftplib.FTP_TLS() as ftp:
                ftp.connect(self.host, 21, timeout=30)
                ftp.login(self.user, self.password)
                ftp.prot_p()
                with open(dest_path, "wb") as fh:
                    ftp.retrbinary(f"RETR {remote_path}", fh.write)
        except Exception as exc:
            logger.warning("FTP download error: %s", exc)
