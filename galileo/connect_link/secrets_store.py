# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Where Connect Link keeps secrets that must never be in the database or a file (LINK-260).

TLS private keys go to the OS credential store through ``keyring`` (NFR-SEC-030). A test or a host
with no credential store supplies :class:`MemorySecretStore`; there is deliberately no file fallback.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

_SERVICE = "Galileo Connect Link"


class SecretStoreError(Exception):
    """The secret store is unavailable or refused the operation."""


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class KeyringSecretStore:
    """The OS credential store."""

    def get(self, name: str) -> str | None:
        try:
            import keyring
            return keyring.get_password(_SERVICE, name)
        except Exception as exc:
            raise SecretStoreError(f"could not read the OS credential store: {exc}") from exc

    def set(self, name: str, value: str) -> None:
        try:
            import keyring
            keyring.set_password(_SERVICE, name, value)
        except Exception as exc:
            raise SecretStoreError(f"could not write the OS credential store: {exc}") from exc

    def delete(self, name: str) -> None:
        try:
            import keyring
            keyring.delete_password(_SERVICE, name)
        except Exception:
            logger.debug("Could not delete %r from the OS credential store", name, exc_info=True)


class MemorySecretStore:
    """Process-lifetime store for tests."""

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._items.get(name)

    def set(self, name: str, value: str) -> None:
        self._items[name] = value

    def delete(self, name: str) -> None:
        self._items.pop(name, None)
