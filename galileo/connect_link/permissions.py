# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Connect Link permissions (LINK-030)."""

from __future__ import annotations

from collections.abc import Iterable

PAIRED_PERMISSIONS = frozenset({"config.read", "config.write", "data.push", "data.pull", "control", "view"})
PERMISSION_OUTREACH_VIEW = "outreach.view"      # guests only, never a paired peer
CONFIG_PERMISSIONS = frozenset({"config.read", "config.write"})


class GrantError(ValueError):
    """A permission set that Connect Link refuses to grant."""


def validate_grant(
    requested: Iterable[str], allowed_by_plugin: Iterable[str], *, is_service: bool = False,
) -> frozenset[str]:
    """The permission set for a paired peer, or :class:`GrantError`.

    Only paired-peer permissions exist (``outreach.view`` is a guest's and is never granted here),
    only those the pairing plugin declares may be granted, and a service credential never holds
    ``config.*`` (LINK-030, LINK-090).
    """
    granted = frozenset(requested)
    unknown = granted - PAIRED_PERMISSIONS
    if unknown:
        raise GrantError(f"not a permission a paired peer can hold: {sorted(unknown)}")
    outside = granted - frozenset(allowed_by_plugin)
    if outside:
        raise GrantError(f"the plugin does not declare: {sorted(outside)}")
    if is_service and granted & CONFIG_PERMISSIONS:
        raise GrantError("a service credential never holds config.*")
    return granted
