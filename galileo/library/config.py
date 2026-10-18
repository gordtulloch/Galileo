# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Library settings — edited under Options > Library, stored in the shared database.

AstroFiler read a ``astrofiler.ini`` from whatever directory it was launched in.
Galileo keeps the settings in the shared database instead (``app_settings``, namespace
``library``; see ``galileo.settings_store``), so the GUI and the command-line utilities always
agree on where the repository lives. They are still presented as a ``ConfigParser`` with the
values in the ``[DEFAULT]`` section, as in AstroFiler, so ``config.get("DEFAULT", "repo")`` keeps
working. Passwords are never stored here -- they go to the OS keychain. An old ``library.ini`` in
the config folder is imported once and renamed ``library.ini.migrated``; a ``--config`` file
named on the command line is a user-chosen file and is read and written as an ``.ini``.

Recognised keys (all optional): ``source`` (incoming folder), ``repo``
(repository folder), ``temp_folder``, ``refresh_on_startup``, ``min_files_per_master``,
the ``cloud_*`` / ``bucket_url`` / ``auth_file_path`` / ``sync_profile`` group, the
``compress_*`` group, the smart-telescope host/credential keys, and ``Registration``
(set ``False`` to opt out of the startup registration ping, see ``galileo.registration``).
"""

from __future__ import annotations

import configparser
import logging
import os
import tempfile
from pathlib import Path

from galileo.platform import get_config_dir

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "library.ini"   # legacy file (imported once) / default name for --config files
LIBRARY_NAMESPACE = "library"

# Set by command-line utilities' ``--config`` option; ``None`` means the default file.
_config_path_override: Path | None = None


def set_config_path(path: Path | str | None) -> None:
    """Point every later :func:`load_config` / :func:`save_config` at *path*."""
    global _config_path_override
    _config_path_override = Path(path) if path else None


def get_config_path() -> Path:
    """The settings file in use: the ``--config`` override, else the legacy ``library.ini`` location.

    Without an override the settings live in the database (``app_settings``, namespace
    ``library``); the legacy path is then only where an old ``library.ini`` is imported from."""
    return _config_path_override or (get_config_dir() / CONFIG_FILENAME)


def has_config_override() -> bool:
    """Whether a ``--config`` file has been selected (so settings come from that file, not the database)."""
    return _config_path_override is not None


def _use_database(path: Path | str | None) -> bool:
    """Database mode unless a file was named: ``--config`` files are user-chosen interchange files."""
    return path is None and _config_path_override is None


def _is_secret(key: str) -> bool:
    """Passwords never go into the database (or ``library.ini``) -- they belong in the OS keychain."""
    return "password" in key.lower()


def _import_legacy_ini() -> None:
    """One-time upgrade: copy the non-secret ``[DEFAULT]`` values of an old ``library.ini`` into the
    database (a plaintext iTelescope/SFTP password goes to the keychain), then rename it ``*.migrated``."""
    from galileo import settings_store
    legacy = get_config_dir() / CONFIG_FILENAME
    if not legacy.exists() or not settings_store.available():
        return
    try:
        parser = configparser.ConfigParser()
        parser.read(legacy, encoding="utf-8")
        values = {k: v for k, v in parser.defaults().items() if not _is_secret(k)}
        if not settings_store.get_namespace(LIBRARY_NAMESPACE) and values and not settings_store.set_namespace(LIBRARY_NAMESPACE, values):
            return
        legacy_password = parser.defaults().get("itelescope_password", "").strip()
        if legacy_password:
            set_itelescope_password(legacy_password)
        settings_store.mark_migrated(legacy)
    except Exception:
        logger.exception("Could not import the legacy library.ini")


def config_exists() -> bool:
    """Whether any library settings have been saved (the named file exists, or the database has some)."""
    if not _use_database(None):
        return get_config_path().exists()
    from galileo import settings_store
    _import_legacy_ini()
    return bool(settings_store.get_namespace(LIBRARY_NAMESPACE))


def load_config(path: Path | str | None = None) -> configparser.ConfigParser:
    """Return the library settings, empty if none are saved yet.

    Normally these come from the database; a *path* (or the ``--config`` override) reads that
    user-chosen ``.ini`` file instead."""
    config = configparser.ConfigParser()
    if _use_database(path):
        from galileo import settings_store
        _import_legacy_ini()
        for key, value in settings_store.get_namespace(LIBRARY_NAMESPACE).items():
            config.set("DEFAULT", key, str(value).replace("%", "%%"))
        return config
    target = Path(path) if path else get_config_path()
    if target.exists():
        config.read(target, encoding="utf-8")
    return config


def save_config(config: configparser.ConfigParser, path: Path | str | None = None) -> Path | None:
    """Save *config*'s ``[DEFAULT]`` values (never passwords) to the database.

    With a *path* (or the ``--config`` override) it writes that user-chosen ``.ini`` file instead
    and returns its path; the database case returns ``None``."""
    if _use_database(path):
        from galileo import settings_store
        values = {k: v for k, v in config.defaults().items() if not _is_secret(k)}
        settings_store.set_namespace(LIBRARY_NAMESPACE, values, replace=True)
        return None
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


def get_itelescope_verify_tls() -> bool:
    """Whether to verify the iTelescope FTPS server certificate (Options > Library; on by default)."""
    value = load_config().get("DEFAULT", "itelescope_verify_tls", fallback="True")
    return value.strip().lower() in ("true", "1", "yes", "on")


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


# ---------------------------------------------------------------------------
# SFTP server (EXT-120, LIB-170): the connection settings live in library.ini, the password in the keychain
# ---------------------------------------------------------------------------

_KEYRING_SFTP_USER = "sftp"


def get_sftp_password() -> str:
    """The SFTP server password, from the OS keychain ("" if unset or the keychain is unavailable)."""
    try:
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_SFTP_USER) or ""
    except Exception:
        logger.warning("Could not read the SFTP password from the OS keychain", exc_info=True)
        return ""


def set_sftp_password(password: str) -> None:
    """Store the SFTP server password in the OS keychain (an empty string clears it)."""
    try:
        import keyring
        if password:
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_SFTP_USER, password)
        else:
            try:
                keyring.delete_password(_KEYRING_SERVICE, _KEYRING_SFTP_USER)
            except Exception:
                logger.debug("Could not delete SFTP password from the OS keychain", exc_info=True)
    except Exception:
        logger.warning("Could not save the SFTP password to the OS keychain", exc_info=True)


def get_sftp_settings() -> dict:
    """The configured SFTP server's connection settings (Options > Library > Smart Telescopes)."""
    config = load_config()
    port_text = config.get("DEFAULT", "sftp_port", fallback="22").strip()
    return {
        "username": config.get("DEFAULT", "sftp_username", fallback="").strip(),
        "password": get_sftp_password(),
        "key_path": config.get("DEFAULT", "sftp_key_path", fallback="").strip(),
        "remote_path": config.get("DEFAULT", "sftp_remote_path", fallback="/").strip() or "/",
        "port": int(port_text) if port_text.isdigit() else 22,
        "strict_host_keys": config.get("DEFAULT", "sftp_strict_host_keys", fallback="False").strip().lower()
                            in ("true", "1", "yes", "on"),
    }
