# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The engine's configuration (HEAD-130, HEAD-140): read from the database, never from a file of its own.

Everything lives in the shared settings store under the ``engine`` namespace:

* ``observatory`` — the name of the Observatory the engine runs. Unset means *the last one the desktop used*
  (the desktop records it with :func:`remember_observatory` when the person picks one), and failing that the first;
* ``retry_limit`` — how many more times to try a Pier whose devices would not all connect (default 5);
* ``retry_interval_s`` — seconds between those tries (default 30).

The values are read when the engine starts and again when the settings-changed event (``REPL-050``) arrives, so an
Options page change reaches a running engine. Nothing here is reachable through the Control Surface: a remote
client cannot change it (``CSURF-020`` refuses a *config* operation at registration).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

NAMESPACE = "engine"
LAST_OBSERVATORY = "last_observatory"      # written by the desktop; the engine only reads it
DEFAULT_RETRY_LIMIT = 5
DEFAULT_RETRY_INTERVAL_S = 30.0


@dataclass(frozen=True)
class EngineConfig:
    observatory: str = ""                  # "" = the last one the desktop used, else the first
    retry_limit: int = DEFAULT_RETRY_LIMIT
    retry_interval_s: float = DEFAULT_RETRY_INTERVAL_S


def _number(value: Any, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        return default


def load_config() -> EngineConfig:
    from galileo.settings_store import get_namespace
    values = get_namespace(NAMESPACE)
    return EngineConfig(
        observatory=str(values.get("observatory") or ""),
        retry_limit=int(_number(values.get("retry_limit"), DEFAULT_RETRY_LIMIT, 0)),
        retry_interval_s=_number(values.get("retry_interval_s"), DEFAULT_RETRY_INTERVAL_S, 1.0))


def remember_observatory(name: str) -> bool:
    """The desktop calls this when the person selects an Observatory, so a headless engine starts on the same one."""
    from galileo.settings_store import set_setting
    return set_setting(NAMESPACE, LAST_OBSERVATORY, name)


def resolve_observatory(config: EngineConfig, names: list[str]) -> str | None:
    """The Observatory to run, from *names* (all that exist): the configured one, else the last one the desktop
    used, else the first. ``None`` when there are none. A configured name that no longer exists is logged and
    falls back, so a rename never leaves the engine with nothing to run."""
    if not names:
        return None
    from galileo.settings_store import get_setting
    for source, name in (("configured", config.observatory), ("last used", get_setting(NAMESPACE, LAST_OBSERVATORY, ""))):
        if name and name in names:
            return str(name)
        if name:
            logger.warning("The %s Observatory %r no longer exists", source, name)
    return names[0]


__all__ = ["DEFAULT_RETRY_INTERVAL_S", "DEFAULT_RETRY_LIMIT", "EngineConfig", "load_config",
           "remember_observatory", "resolve_observatory"]
