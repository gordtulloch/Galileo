"""Master calibration frame model."""

from __future__ import annotations

import peewee as pw

from galileo.library.models.base import BaseModel


class MasterFrame(BaseModel):
    """A master calibration frame (bias, dark, or flat) created from a session."""

    id = pw.TextField(primary_key=True)
    frame_type = pw.TextField()          # MasterBias | MasterDark | MasterFlat
    file_path = pw.TextField(null=True)
    instrument = pw.TextField(null=True)
    binning_x = pw.TextField(null=True)
    binning_y = pw.TextField(null=True)
    ccd_temp = pw.TextField(null=True)
    exposure_time = pw.TextField(null=True)
    filter_name = pw.TextField(null=True)
    created_date = pw.DateTimeField(null=True)
    source_session_id = pw.TextField(null=True)

    class Meta:
        table_name = "master_frames"
