# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The user's saved target list (Planning > Targets), persisted in the shared database."""

from __future__ import annotations

import json
import time

from galileo.planning.sky_atlas import DeepSkyObject, ObjectType


def save_target(obj: DeepSkyObject) -> bool:
    """Save *obj*; returns ``False`` if an object of that name was already saved (nothing changes)."""
    from galileo.library.models.saved_target import SavedTargetRecord
    _, created = SavedTargetRecord.get_or_create(
        name=obj.primary_name,
        defaults={
            "designations_json": json.dumps(list(obj.designations)),
            "ra_deg": obj.ra_deg, "dec_deg": obj.dec_deg,
            "object_type": obj.object_type.value, "magnitude": obj.magnitude,
            "size_arcmin": obj.size_arcmin, "description": obj.description,
            "saved_at": time.time(),
        },
    )
    return created


def remove_target(name: str) -> None:
    from galileo.library.models.saved_target import SavedTargetRecord
    SavedTargetRecord.delete().where(SavedTargetRecord.name == name).execute()


def list_targets() -> list[DeepSkyObject]:
    """Every saved target, most recently saved first."""
    from galileo.library.models.saved_target import SavedTargetRecord
    out: list[DeepSkyObject] = []
    for r in SavedTargetRecord.select().order_by(SavedTargetRecord.saved_at.desc(), SavedTargetRecord.id.desc()):
        try:
            otype = ObjectType(r.object_type)
        except ValueError:
            otype = ObjectType.OTHER
        out.append(DeepSkyObject(
            primary_name=r.name, designations=json.loads(r.designations_json or "[]"),
            ra_deg=r.ra_deg, dec_deg=r.dec_deg, object_type=otype, magnitude=r.magnitude,
            size_arcmin=r.size_arcmin, description=r.description,
        ))
    return out
