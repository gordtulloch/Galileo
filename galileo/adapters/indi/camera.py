# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""INDI adapter(s) for camera devices."""

from __future__ import annotations

import asyncio

from galileo.adapters import indi_client as ic
from galileo.adapters.indi._base import IndiAdapter
from galileo.core.capabilities import DeviceCapabilities
from galileo.core.devices import DeviceCategory
from galileo.exceptions import DeviceError, DevicePropertyError


class IndiCameraAdapter(IndiAdapter):
    """INDI camera adapter (EQP-CAM-010 … EQP-CAM-040), for drivers exposing
    the standard ``INDI::CCD`` properties."""

    _FRAME_TYPES = (("dark", "FRAME_DARK"), ("bias", "FRAME_BIAS"), ("flat", "FRAME_FLAT"))

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.CAMERA, host, port, **kwargs)
        self._image_data = None
        self._blob_seq0 = 0
        self._exposure_s = 0.0

    def _on_connected(self) -> None:
        # Without this the server never sends this client the image BLOB.
        self._c().enable_blob(self.device_name, "Also")

    def get_capabilities(self) -> DeviceCapabilities:
        if self._client is None:
            return DeviceCapabilities()
        binning = self._client.get_property(self.device_name, "CCD_BINNING")
        def max_bin(el):
            return int(binning.elements[el].max or 1) if binning and el in binning.elements else 1

        return DeviceCapabilities(
            has_cooler=self._has("CCD_TEMPERATURE"),
            can_set_gain=self._has("CCD_GAIN") or self._sw_or_num_gain() is not None,
            can_set_offset=self._has("CCD_OFFSET"),
            can_bin=binning is not None and binning.perm != "ro",
            max_bin_x=max_bin("HOR_BIN"),
            max_bin_y=max_bin("VER_BIN"),
            has_shutter=self._has("CCD_FRAME_TYPE"),
            sensor_width=int(self._num("CCD_INFO", "CCD_MAX_X") or 0),
            sensor_height=int(self._num("CCD_INFO", "CCD_MAX_Y") or 0),
            pixel_size_x=self._num("CCD_INFO", "CCD_PIXEL_SIZE_X") or self._num("CCD_INFO", "CCD_PIXEL_SIZE") or 0.0,
            pixel_size_y=self._num("CCD_INFO", "CCD_PIXEL_SIZE_Y") or self._num("CCD_INFO", "CCD_PIXEL_SIZE") or 0.0,
        )

    def _sw_or_num_gain(self) -> float | None:
        # Older drivers expose gain through the generic CCD_CONTROLS vector.
        return self._num("CCD_CONTROLS", "Gain")

    def _frame_type_element(self, frame_type: str) -> str:
        lowered = frame_type.lower()
        for needle, element in self._FRAME_TYPES:
            if needle in lowered:
                return element
        return "FRAME_LIGHT"

    def _prepare_transfer(self) -> None:
        """Make sure the finished frame is delivered to *this* client as an
        uncompressed FITS, not saved on the server or sent in a native raw
        format Galileo can't read."""
        client = self._c()
        for prop, wanted in (("UPLOAD_MODE", "UPLOAD_CLIENT"), ("CCD_TRANSFER_FORMAT", "FORMAT_FITS"),
                             ("CCD_COMPRESSION", "CCD_RAW")):
            found = client.get_property(self.device_name, prop)
            if found is not None and not found.value(wanted) and wanted in found.elements:
                self._select(prop, wanted)

    async def start_exposure(self, duration: float, gain: int = 0, offset: int = 0,
                              binning: int = 1, frame_type: str = "Light") -> None:
        self._log_interaction("start_exposure", duration=duration, gain=gain, offset=offset,
                               binning=binning, frame_type=frame_type)
        self._require("CCD_EXPOSURE")
        self._prepare_transfer()
        # gain/offset default to 0 meaning "leave as configured" — a camera's
        # real gain is usually set by the user on the driver, and 0 is also
        # the signature's default, so only an explicit nonzero value is applied.
        if gain:
            if self._has("CCD_GAIN"):
                self._set_num("CCD_GAIN", {"GAIN": gain})
            elif self._sw_or_num_gain() is not None:
                self._set_num("CCD_CONTROLS", {"Gain": gain})
        if offset and self._has("CCD_OFFSET"):
            self._set_num("CCD_OFFSET", {"OFFSET": offset})
        if self._has("CCD_BINNING") and self._num("CCD_BINNING", "HOR_BIN") != binning:
            self._set_num("CCD_BINNING", {"HOR_BIN": binning, "VER_BIN": binning})
        if self._has("CCD_FRAME_TYPE"):
            self._select("CCD_FRAME_TYPE", self._frame_type_element(frame_type))
        self._exposure_s = float(duration)
        self._blob_seq0 = self._c().blob_seq(self.device_name, "CCD1")
        self._c().send_number(self.device_name, "CCD_EXPOSURE", {"CCD_EXPOSURE_VALUE": duration})

    async def abort_exposure(self) -> None:
        self._log_interaction("abort_exposure")
        self._set_sw("CCD_ABORT_EXPOSURE", {"ABORT": True})

    async def get_image_array(self):
        """Wait for the exposure started by :meth:`start_exposure` to finish
        downloading, and return it as a numpy array (FITS is the only
        transfer format Galileo works with)."""
        client = self._c()
        name = self.device_name

        def _ready() -> bool:
            return (client.blob_seq(name, "CCD1") > self._blob_seq0
                    or client.get_state(name, "CCD_EXPOSURE") == ic.ALERT)

        # Exposure time plus generous margin for readout and a slow Wi-Fi download.
        await asyncio.to_thread(client.wait_for, _ready, self._exposure_s + 90.0, "the exposure to download")
        if client.blob_seq(name, "CCD1") <= self._blob_seq0:
            last = client.messages[-1] if client.messages else "no message from driver"
            raise DeviceError(f"INDI camera {name!r} exposure failed: {last}")
        blob = client.latest_blob(name, "CCD1")
        if blob is None:
            raise DeviceError(f"INDI camera {name!r} reported an image but sent no data.")
        self._image_data = await asyncio.to_thread(self._decode_fits, *blob)
        return self._image_data

    @staticmethod
    def _decode_fits(data: bytes, fmt: str):
        if "fit" not in fmt.lower():
            raise DevicePropertyError(
                f"INDI camera sent an image in unsupported format {fmt!r}; Galileo needs FITS "
                "(set the driver's transfer format to FITS)."
            )
        import io

        from astropy.io import fits
        with fits.open(io.BytesIO(data), memmap=False) as hdul:
            return hdul[0].data.copy()

    async def set_temperature(self, temp_c: float) -> None:
        self._log_interaction("set_temperature", temp_c=temp_c)
        self._set_num("CCD_TEMPERATURE", {"CCD_TEMPERATURE_VALUE": temp_c})
        if self._has("CCD_COOLER") and not self._sw("CCD_COOLER", "COOLER_ON"):
            self._set_sw("CCD_COOLER", {"COOLER_ON": True, "COOLER_OFF": False})

    def get_temperature(self) -> float:
        """Sensor temperature in °C, or NaN if the driver reports none."""
        value = self._num("CCD_TEMPERATURE", "CCD_TEMPERATURE_VALUE")
        return float("nan") if value is None else value

    def get_cooler_power(self) -> float:
        return self._num("CCD_COOLER_POWER", "CCD_COOLER_VALUE") or 0.0

    async def warm_up(self) -> None:
        self._log_interaction("warm_up")
        self._set_sw("CCD_COOLER", {"COOLER_ON": False, "COOLER_OFF": True})

    async def get_sensor_info(self) -> dict:
        """Live-query this camera's sensor configuration from INDI's standard
        ``CCD_INFO`` property vector — the "Download Info" action on the
        Equipment Camera page. INDI has no separate sensor-model property, so
        ``sensor_name`` is the INDI device name, which drivers normally set to
        the camera model."""
        pixel = self._num("CCD_INFO", "CCD_PIXEL_SIZE") or self._num("CCD_INFO", "CCD_PIXEL_SIZE_X")
        width, height = self._num("CCD_INFO", "CCD_MAX_X"), self._num("CCD_INFO", "CCD_MAX_Y")
        return {
            "pixel_size_um": pixel,
            "sensor_width_px": int(width) if width else None,
            "sensor_height_px": int(height) if height else None,
            "sensor_name": self.device_name or None,
        }


class IndiCameraSimulator(IndiCameraAdapter):
    """Simulator camera backend for development without hardware (EQP-CAM-040).
    Fully offline — never opens a connection to an INDI server."""
    is_simulator = True
    device_type = "Camera"

    def __init__(self) -> None:
        super().__init__(host="localhost", port=7624, device_name="CCD Simulator")
        self._connected = True

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def start_exposure(self, *args, **kwargs) -> None:
        pass

    async def abort_exposure(self) -> None:
        pass

    async def get_image_array(self):
        import numpy as np
        return np.zeros((1080, 1920), dtype=np.uint16)
