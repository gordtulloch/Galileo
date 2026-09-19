# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Persisted per-Pier optical tube configuration (Equipment > Optics page).

One record per optical tube on a Pier — the telescope/lens that a camera,
guider, focuser, etc. actually sits behind. Holds the tube's optical
parameters (focal length, aperture, optical design, image orientation) and
the list of the Pier's other configured devices associated with it, each
stored as a ``"<category>:<slot>"`` key matching a ``DeviceConfigRecord``
(``galileo.library.models.device_config``), e.g. ``"camera:primary"`` or
``"focuser:focuser_2"``. Associations are kept as keys rather than a foreign
key to ``DeviceConfigRecord`` because those rows are pruned/recreated by the
device pages' Save buttons, and an association to a since-removed device
should degrade to a dangling label, not a cascade-deleted tube.
"""

from __future__ import annotations

import json

import peewee as pw

from galileo.library.models.base import BaseModel
from galileo.library.models.observatory import PierRecord

OPTICAL_SYSTEMS = ("Newtonian", "Schmidt-Cassegrain", "Mak-Cassegrain", "Refractor", "Other")


class OpticalTubeRecord(BaseModel):
    """One saved optical tube, scoped to its owning Pier and ordered by *position*."""

    pier = pw.ForeignKeyField(PierRecord, backref="optical_tubes", on_delete="CASCADE")
    position = pw.IntegerField(default=0)
    name = pw.TextField(default="")
    focal_length_mm = pw.FloatField(default=0.0)
    aperture_mm = pw.FloatField(default=0.0)
    optical_system = pw.TextField(default=OPTICAL_SYSTEMS[0])
    # Image orientation the optical path produces at the camera: mirrored
    # left-right ("reversed", e.g. a refractor with a star diagonal) and/or
    # flipped top-bottom ("inverted", e.g. a Newtonian or a bare Cassegrain).
    image_reversed = pw.BooleanField(default=False)
    image_inverted = pw.BooleanField(default=False)
    associated_devices = pw.TextField(default="[]")  # JSON list of "<category>:<slot>"

    class Meta:
        table_name = "optical_tubes"
        indexes = ((("pier", "position"), True),)

    @property
    def associated(self) -> list[str]:
        try:
            keys = json.loads(self.associated_devices or "[]")
        except ValueError:
            return []
        return [k for k in keys if isinstance(k, str)]

    @associated.setter
    def associated(self, keys: list[str]) -> None:
        self.associated_devices = json.dumps(list(keys))
