# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Library settings — the ``library.ini`` file edited under Options > Library.

AstroFiler read a ``astrofiler.ini`` from whatever directory it was launched in.
Galileo keeps one per-user file in the platform config directory instead
(``galileo.platform``), so the GUI and the command-line utilities always agree
on where the repository lives. Values sit in the ``[DEFAULT]`` section, as they
did in AstroFiler, so ``config.get("DEFAULT", "repo")`` keeps working.

Recognised keys (all optional): ``source`` (incoming folder), ``repo``
(repository folder), ``temp_folder``, ``refresh_on_startup``, ``min_files_per_master``,
the ``cloud_*`` / ``bucket_url`` / ``auth_file_path`` / ``sync_profile`` group, the
``compress_*`` group, and the smart-telescope host/credential keys.
"""

from __future__ import annotations

import configparser
import logging
import os
import tempfile
from pathlib import Path

from galileo.platform import get_config_dir

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "library.ini"

# Set by command-line utilities' ``--config`` option; ``None`` means the default file.
_config_path_override: Path | None = None


def set_config_path(path: Path | str | None) -> None:
    """Point every later :func:`load_config` / :func:`save_config` at *path*."""
    global _config_path_override
    _config_path_override = Path(path) if path else None


def get_config_path() -> Path:
    """The settings file in use: the ``--config`` override, else ``library.ini``."""
    return _config_path_override or (get_config_dir() / CONFIG_FILENAME)


def load_config(path: Path | str | None = None) -> configparser.ConfigParser:
    """Return the library settings, empty if the file doesn't exist yet."""
    config = configparser.ConfigParser()
    target = Path(path) if path else get_config_path()
    if target.exists():
        config.read(target, encoding="utf-8")
    return config


def save_config(config: configparser.ConfigParser, path: Path | str | None = None) -> Path:
    """Write *config* to disk, creating the directory if needed. Returns the path written."""
    target = Path(path) if path else get_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        config.write(fh)
    return target


def get_setting(key: str, fallback: str = "") -> str:
    """One ``[DEFAULT]`` value, stripped, or *fallback*."""
    return load_config().get("DEFAULT", key, fallback=fallback).strip()


def get_repository_path() -> str:
    """The configured repository folder (may be empty when unconfigured)."""
    return get_setting("repo")


def get_incoming_path() -> str:
    """The configured incoming (source) folder (may be empty when unconfigured)."""
    return get_setting("source")


def get_temp_folder() -> str:
    """The configured scratch folder (created if needed), else the system temp directory."""
    temp_folder = get_setting("temp_folder")
    if temp_folder:
        os.makedirs(temp_folder, exist_ok=True)
        return os.path.abspath(temp_folder)
    return tempfile.gettempdir()


# ---------------------------------------------------------------------------
# iTelescope password (NFR-SEC-010): the OS keychain, not library.ini in plain text
# ---------------------------------------------------------------------------

_KEYRING_SERVICE = "galileo-library"
_KEYRING_ITELESCOPE_USER = "itelescope"


def get_itelescope_password() -> str:
    """The iTelescope FTPS password, from the OS keychain.

    A plaintext ``itelescope_password`` left in ``library.ini`` by an older version is migrated
    into the keychain and stripped from the file the first time this is called. If the keychain
    itself is unavailable (no backend on a headless Linux box, a locked keychain, …) this logs a
    warning and returns an empty string rather than raising — the caller is expected to treat that
    the same as "no password configured".
    """
    stored = None
    try:
        import keyring
        stored = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ITELESCOPE_USER)
    except Exception:
        logger.warning("Could not read the iTelescope password from the OS keychain", exc_info=True)

    if stored:
        return stored

    config = load_config()
    legacy = config.get("DEFAULT", "itelescope_password", fallback="").strip()
    if legacy:
        set_itelescope_password(legacy)
        config.remove_option("DEFAULT", "itelescope_password")
        save_config(config)
        logger.info("Migrated the iTelescope password from library.ini into the OS keychain")
        return legacy

    return ""


def set_itelescope_password(password: str) -> None:
    """Store the iTelescope FTPS password in the OS keychain rather than ``library.ini``."""
    try:
        import keyring
        if password:
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_ITELESCOPE_USER, password)
        else:
            try:
                keyring.delete_password(_KEYRING_SERVICE, _KEYRING_ITELESCOPE_USER)
            except Exception:
                # nothing was stored, or this backend can't delete — either way, nothing to do
                logger.debug("Could not delete iTelescope password from the OS keychain", exc_info=True)
    except Exception:
        logger.warning("Could not save the iTelescope password to the OS keychain", exc_info=True)
