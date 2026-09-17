"""FITS file catalog model (adapted from AstroFiler models/fits_file.py)."""

from __future__ import annotations

import datetime

import peewee as pw

from galileo.library.models.base import BaseModel


class FitsFile(BaseModel):
    """One FITS file entry in the repository catalog."""

    id = pw.TextField(primary_key=True)
    file_name = pw.TextField(null=True)
    file_path = pw.TextField(null=True)
    file_date = pw.DateField(null=True)
    file_hash = pw.TextField(null=True, index=True)

    # FITS header metadata
    object_name = pw.TextField(null=True, column_name="object")
    frame_type = pw.TextField(null=True)   # Light Frame, Dark Frame, Flat Field, Bias Frame
    exposure_time = pw.TextField(null=True)
    filter_name = pw.TextField(null=True)
    telescope = pw.TextField(null=True)
    instrument = pw.TextField(null=True)
    gain = pw.TextField(null=True)
    offset = pw.TextField(null=True)
    binning_x = pw.TextField(null=True)
    binning_y = pw.TextField(null=True)
    ccd_temp = pw.TextField(null=True)
    date_obs = pw.TextField(null=True)
    observer = pw.TextField(null=True)

    # Derived / quality metrics
    fwhm = pw.FloatField(null=True)
    hfr = pw.FloatField(null=True)
    eccentricity = pw.FloatField(null=True)
    snr = pw.FloatField(null=True)
    star_count = pw.IntegerField(null=True)
    image_scale = pw.FloatField(null=True)

    # Lifecycle flags
    is_calibrated = pw.BooleanField(default=False)
    is_stacked = pw.BooleanField(default=False)
    is_soft_deleted = pw.BooleanField(default=False)
    calibration_date = pw.DateTimeField(null=True)
    cloud_url = pw.TextField(null=True)

    # Session / sequence linkage
    session_id = pw.TextField(null=True)

    class Meta:
        table_name = "fits_files"

    def is_calibration_frame(self) -> bool:
        return self.frame_type in ("Bias Frame", "Dark Frame", "Flat Field")

    def is_light_frame(self) -> bool:
        return self.frame_type == "Light Frame"

    def mark_as_calibrated(self) -> None:
        self.is_calibrated = True
        self.calibration_date = datetime.datetime.utcnow()
        self.save()
