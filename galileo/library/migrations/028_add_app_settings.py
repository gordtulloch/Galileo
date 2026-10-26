# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
"""Peewee migrations -- 028_add_app_settings.py.

``app_settings``: the one generic configuration store (see ``galileo.settings_store``). Every
Options page, per-screen preference, layout and equipment profile that used to live in a JSON/ini
file under the config folder is a row here: ``namespace`` groups a module's settings, ``key`` names
one, ``scope`` narrows it (empty = global, otherwise e.g. a Pier id) and ``value`` is JSON text.

Plain SQL with IF NOT EXISTS, so it is safe on a database that already has the table and survives
the fake replay peewee-migrate does to rebuild model state.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql(
        "CREATE TABLE IF NOT EXISTS app_settings ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "namespace TEXT NOT NULL, "
        "key TEXT NOT NULL, "
        "scope TEXT NOT NULL DEFAULT '', "
        "value TEXT NOT NULL DEFAULT 'null')"
    )
    migrator.sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS appsettingrecord_namespace_key_scope "
        "ON app_settings (namespace, key, scope)"
    )


def rollback(migrator: Migrator, database: pw.Database, *, fake=False, **kwargs):
    migrator.sql("DROP TABLE IF EXISTS app_settings")
