# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The one configuration store: JSON-valued settings in the shared Peewee database.

All application and user configuration lives in the ``app_settings`` table (migration 028), never
in per-module JSON/ini files. A setting is addressed by ``namespace`` (a module's group, e.g.
``"guiding"``), ``key`` and an optional ``scope`` (empty = global, otherwise e.g. a Pier id).

Reads and writes never raise: with no database initialised (early start-up, a unit test, the
database file unavailable) reads return the caller's default and writes are logged and dropped, so
a settings problem can never take the application down (the watchdog and crash reporter arm early).

:func:`import_legacy_json` is the one-time upgrade path: an old ``*.json`` file in the config
folder is read into the database and renamed ``*.migrated`` (kept, not deleted).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MIGRATED_SUFFIX = ".migrated"


def _model():
    """The ``AppSettingRecord`` model with a live connection, or ``None`` if no database is set."""
    from galileo.library.models.app_setting import AppSettingRecord
    from galileo.library.models.base import db
    if db.database is None:
        return None
    db.connect(reuse_if_open=True)
    return AppSettingRecord


def available() -> bool:
    """Whether the settings table can be used right now."""
    try:
        model = _model()
        if model is None:
            return False
        model.select().limit(1).count()
        return True
    except Exception:
        return False


def get_namespace(namespace: str, scope: str = "") -> dict[str, Any]:
    """Every ``key -> value`` in *namespace* (empty if none are saved or the store is unavailable)."""
    try:
        model = _model()
        if model is None:
            return {}
        out: dict[str, Any] = {}
        for row in model.select().where((model.namespace == namespace) & (model.scope == scope)):
            try:
                out[row.key] = json.loads(row.value)
            except ValueError:
                logger.warning("Ignoring unreadable setting %s.%s", namespace, row.key)
        return out
    except Exception:
        logger.exception("Could not read the %s settings from the database", namespace)
        return {}


def get_setting(namespace: str, key: str, default: Any = None, scope: str = "") -> Any:
    """One value, or *default* if it is not saved (or the store is unavailable)."""
    return get_namespace(namespace, scope).get(key, default)


def _upsert(model, namespace: str, key: str, scope: str, value: Any) -> None:
    payload = json.dumps(value)
    (model.insert(namespace=namespace, key=key, scope=scope, value=payload)
     .on_conflict(conflict_target=[model.namespace, model.key, model.scope],
                  update={model.value: payload}).execute())


def set_setting(namespace: str, key: str, value: Any, scope: str = "") -> bool:
    """Save one value; returns ``False`` (and logs) if it could not be saved."""
    try:
        model = _model()
        if model is None:
            return False
        _upsert(model, namespace, key, scope, value)
        return True
    except Exception:
        logger.exception("Could not save the %s.%s setting", namespace, key)
        return False


def set_namespace(namespace: str, values: dict[str, Any], scope: str = "", *, replace: bool = False) -> bool:
    """Save several values in one transaction; *replace* first removes keys not in *values*."""
    try:
        model = _model()
        if model is None:
            return False
        from galileo.library.models.base import db
        with db.atomic():
            if replace:
                (model.delete().where((model.namespace == namespace) & (model.scope == scope)
                                      & (model.key.not_in(list(values)))).execute())
            for key, value in values.items():
                _upsert(model, namespace, key, scope, value)
        return True
    except Exception:
        logger.exception("Could not save the %s settings", namespace)
        return False


def delete_setting(namespace: str, key: str, scope: str = "") -> bool:
    try:
        model = _model()
        if model is None:
            return False
        model.delete().where((model.namespace == namespace) & (model.key == key)
                             & (model.scope == scope)).execute()
        return True
    except Exception:
        logger.exception("Could not delete the %s.%s setting", namespace, key)
        return False


def import_legacy_json(namespace: str, path: Path | str, scope: str = "") -> dict[str, Any]:
    """One-time upgrade: import an old JSON config file's top-level object into *namespace*.

    Does nothing if the file is absent or the store is unavailable. The values are only imported
    when the namespace holds nothing yet (the database wins); either way, once the database holds
    them the file is renamed ``<name>.migrated``. Returns the namespace's current contents.
    """
    path = Path(path)
    try:
        if not path.exists() or not available():
            return get_namespace(namespace, scope)
        current = get_namespace(namespace, scope)
        if not current:
            raw = json.loads(path.read_text("utf-8"))
            if isinstance(raw, dict) and raw:
                if not set_namespace(namespace, raw, scope):
                    return current
                current = get_namespace(namespace, scope)
        mark_migrated(path)
        return current
    except Exception:
        logger.exception("Could not import the legacy settings file %s", path)
        return get_namespace(namespace, scope)


def mark_migrated(path: Path) -> None:
    target = path.with_name(path.name + MIGRATED_SUFFIX)
    try:
        if target.exists():
            target.unlink()
        path.rename(target)
        logger.info("Imported %s into the database and renamed it %s", path.name, target.name)
    except OSError:
        logger.warning("Could not rename the imported settings file %s", path, exc_info=True)


def load_with_legacy(namespace: str, legacy_filename: str, scope: str = "") -> dict[str, Any]:
    """The namespace's values, importing ``<config dir>/<legacy_filename>`` first if it exists."""
    from galileo.platform import get_config_dir
    try:
        legacy = get_config_dir() / legacy_filename
    except Exception:
        return get_namespace(namespace, scope)
    return import_legacy_json(namespace, legacy, scope)
