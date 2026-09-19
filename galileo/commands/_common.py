# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Helpers shared by the library command-line utilities (LIB-130, EXT-140).

AstroFiler's utilities each carried their own ``sys.path`` bootstrap, log-file
name and ``astrofiler.ini`` lookup. Here they all read the same ``library.ini``
the GUI edits under Options > Library (or the file named by ``-c/--config``)
and append to one log file in the Galileo log directory.
"""

from __future__ import annotations

import configparser
import os
from pathlib import Path

from galileo.library.config import get_config_path, load_config as _load_library_config, set_config_path

LOG_FILENAME = "library.log"


def get_log_path() -> Path:
    """The file the command-line utilities append their log to."""
    from galileo.platform import get_log_dir
    return get_log_dir() / LOG_FILENAME


def load_config(config_path: str | None = None) -> configparser.ConfigParser:
    """Select the settings file (``-c/--config``, default ``library.ini``) and load it.

    Selecting it also redirects every later read of the library settings inside
    ``galileo.library`` to the same file. Raises :class:`FileNotFoundError` if
    the file doesn't exist, so a mistyped ``--config`` fails loudly rather than
    silently running on defaults.
    """
    if config_path:
        set_config_path(config_path)
    target = get_config_path()
    if not os.path.exists(target):
        raise FileNotFoundError(
            f"Configuration file not found: {target} "
            "(set the repository folders under Options > Library, or pass --config)"
        )
    return _load_library_config()
