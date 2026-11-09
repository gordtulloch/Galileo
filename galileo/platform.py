# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Platform-specific path resolution for Galileo.

All platform-specific code is isolated here per NFR-PORT-010.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _app_data_root() -> Path:
    """Return the OS-standard application-data root directory."""
    if sys.platform == "win32":
        import os
        base = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        return Path(base) / "Galileo"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Galileo"
    # Linux / other POSIX
    import os
    xdg = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    return Path(xdg) / "galileo"


def get_data_dir() -> Path:
    """Return the application data directory, creating it if needed."""
    d = _app_data_root()
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_config_dir() -> Path:
    """Return the user config directory, creating it if needed."""
    if sys.platform == "win32":
        return get_data_dir()  # same place on Windows
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Preferences" / "Galileo"
    else:
        import os
        xdg = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        d = Path(xdg) / "galileo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_log_dir() -> Path:
    """Return the log directory, creating it if needed."""
    if sys.platform == "win32":
        d = get_data_dir() / "logs"
    elif sys.platform == "darwin":
        d = Path.home() / "Library" / "Logs" / "Galileo"
    else:
        d = get_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_cache_dir() -> Path:
    """Return the cache directory (e.g. sky-atlas catalog), creating it if needed."""
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Caches" / "Galileo"
    else:
        d = get_data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_db_path(filename: str = "galileo.db") -> Path:
    """Return the path to the application SQLite database file."""
    return get_data_dir() / filename


def get_reports_dir() -> Path:
    """Return the directory generated reports (e.g. Library quality reports) are written to, creating it if needed."""
    d = get_data_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_crash_reports_dir() -> Path:
    """Return the directory crash reports are written to (``reports/crash``), creating it if needed."""
    d = get_reports_dir() / "crash"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_plugins_dir() -> Path:
    """Return the directory where installed plugin packages live, creating it if needed."""
    d = get_data_dir() / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def power_command(action: str) -> list[str]:
    """The command that restarts (``"restart"``) or powers off (``"shutdown"``) this computer, for the node-health
    controls (NODE-030). Raises ``ValueError`` for any other action."""
    if action not in ("restart", "shutdown"):
        raise ValueError(f"unknown power action {action!r}")
    if sys.platform == "win32":
        return ["shutdown", "/r" if action == "restart" else "/s", "/t", "5"]
    if sys.platform == "darwin":
        # System Events asks the logged-in user's session, so it needs no root and lets apps close cleanly.
        return ["osascript", "-e", f'tell application "System Events" to {"restart" if action == "restart" else "shut down"}']
    return ["systemctl", "reboot" if action == "restart" else "poweroff"]
