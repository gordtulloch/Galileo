"""Persisted per-Pier device configuration (Equipment page Save button).

One record per (Pier, device category, slot) holds the driver/server/port and
the device name picked from the last scan, so the Equipment page's fields —
and the camera's auto-connect-at-startup behaviour — survive an application
restart. Distinct from ``galileo.equipment.profiles``' file-based named
profiles: this is the live "what is Pier X's camera right now" setting the
top bar's Observatory/Pier selectors already read and write against.

*slot* distinguishes multiple devices sharing one category and one physical
connection — currently only used by Camera, where any number of additional,
non-guide cameras (e.g. a Seestar S30 Pro's wide-field camera, exposed as a
second device on the same Alpaca/INDI server) can be added from the Camera
page's "+" control and are saved as slots ``"camera_2"``, ``"camera_3"``, …
alongside the always-present ``"primary"`` imaging camera. Every other
category always uses ``"primary"``.
"""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel
from galileo.library.models.observatory import PierRecord

PRIMARY_SLOT = "primary"


class DeviceConfigRecord(BaseModel):
    """One saved device-category/slot configuration, scoped to its owning Pier."""

    pier = pw.ForeignKeyField(PierRecord, backref="device_configs", on_delete="CASCADE")
    category = pw.TextField()
    slot = pw.TextField(default=PRIMARY_SLOT)
    driver = pw.TextField()
    server = pw.TextField()
    port = pw.IntegerField()
    device_name = pw.TextField(null=True)
    # Camera-specific configuration, either typed in by hand or fetched live
    # from the device's own standard properties (ASCOM PixelSizeX/Y and
    # CameraXSize/YSize, or INDI's CCD_INFO vector) via a "Download Info"
    # button — see galileo.adapters.alpaca/indi's get_sensor_info().
    pixel_size_um = pw.FloatField(null=True)
    sensor_width_px = pw.IntegerField(null=True)
    sensor_height_px = pw.IntegerField(null=True)
    sensor_name = pw.TextField(null=True)

    class Meta:
        table_name = "device_configs"
        indexes = ((("pier", "category", "slot"), True),)
