# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Alpaca adapter(s): camera."""

from __future__ import annotations

import asyncio
import logging

from galileo.adapters.alpaca._base import AlpacaAdapter
from galileo.core.capabilities import DeviceCapabilities
from galileo.core.devices import DeviceCategory
from galileo.exceptions import DeviceError

logger = logging.getLogger(__name__)


class AlpacaCameraAdapter(AlpacaAdapter):
    def __init__(self, host: str = "localhost", port: int = 11111, **kwargs) -> None:
        super().__init__(DeviceCategory.CAMERA, host, port, **kwargs)
        self._exposure_s = 0.0

    # Allowed on top of the exposure time for readout and a slow Wi-Fi download.
    _IMAGE_MARGIN_S = 60.0
    _IMAGE_POLL_S = 0.5
    _CAMERA_ERROR = 5          # ASCOM CameraStates.cameraError

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(has_cooler=True, can_set_gain=True, can_bin=True)

    async def start_exposure(self, duration: float, gain: int = 0, frame_type: str = "Light", **kwargs) -> None:
        # gain 0 means "leave as configured", as for INDI. Not every camera has an adjustable gain,
        # and a refusal shouldn't cost the exposure.
        if gain:
            try:
                await self._put("gain", Gain=int(gain))
            except Exception:
                logger.warning("Could not set gain %s on %s; exposing with its current gain", gain, self.base_url)
        binning = int(kwargs.get("binning") or 1)
        if binning != getattr(self, "_binning", 1):
            try:
                await self._put("binx", BinX=binning)
                await self._put("biny", BinY=binning)
                self._binning = binning
            except Exception:
                logger.warning("Could not set %sx%s binning on %s; exposing with its current binning",
                               binning, binning, self.base_url)
        # ASCOM's Light flag is False for frames taken with the shutter closed.
        dark = any(word in frame_type.lower() for word in ("dark", "bias"))
        await self._put("startexposure", Duration=duration, Light=not dark)
        self._exposure_s = float(duration)

    async def abort_exposure(self) -> None:
        await self._put("abortexposure")

    async def get_image_array(self):
        """Wait for the exposure started by :meth:`start_exposure` to finish, then
        download it as a numpy array shaped ``(height, width)`` — ``(height,
        width, planes)`` for a colour camera. ``startexposure`` returns at once,
        so asking for ``imagearray`` straight away fails with "no image
        available" until the driver reports ``imageready``."""
        import numpy as np
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._exposure_s + self._IMAGE_MARGIN_S
        while True:
            ready = await self._get("imageready")
            if ready is None or ready:          # None: the driver can't say — just try the download
                break
            if await self._get("camerastate") == self._CAMERA_ERROR:
                raise DeviceError(f"Alpaca Camera at {self.base_url} reported an error during the exposure.")
            if loop.time() > deadline:
                raise DeviceError(
                    f"Alpaca Camera at {self.base_url} did not finish a {self._exposure_s:g} s exposure "
                    f"within {self._IMAGE_MARGIN_S:g} s of its end.")
            await asyncio.sleep(self._IMAGE_POLL_S)
        value = await self._get("imagearray", timeout=self._exposure_s + self._IMAGE_MARGIN_S)
        if value is None:
            raise DeviceError(f"Alpaca Camera at {self.base_url} returned no image data.")
        # ASCOM sends the image as columns (X first); numpy/FITS want rows (Y first).
        return np.asarray(value).swapaxes(0, 1)

    async def set_temperature(self, temp_c: float) -> None:
        await self._put("setccdtemperature", SetCCDTemperature=temp_c)

    def get_temperature(self) -> float:
        """Sensor temperature in °C, or NaN when none has been read (nothing polls it yet)."""
        value = self._properties.get("CCD_TEMPERATURE")
        return float("nan") if value is None else float(value)

    def get_cooler_power(self) -> float:
        return float(self._properties.get("COOLER_POWER", 0.0))

    async def warm_up(self) -> None:
        await self._put("cooleron", CoolerOn=False)

    async def get_sensor_info(self) -> dict:
        """Live-query this camera's sensor configuration from the standard
        ASCOM Camera properties (PixelSizeX/Y, CameraXSize/YSize, SensorName)
        — the "Download Info" action on the Equipment Camera page. Every
        Alpaca-compliant camera exposes these, including a Seestar's second
        (wide-field) camera device, so no device-specific handling is needed
        here beyond already targeting the right device_number/base_url."""
        info: dict[str, float | int | str | None] = {
            "pixel_size_um": None, "sensor_width_px": None,
            "sensor_height_px": None, "sensor_name": None,
        }
        try:
            pixel_size_x = await self._get("pixelsizex")
            info["pixel_size_um"] = float(pixel_size_x) if pixel_size_x is not None else None
        except Exception:
            logger.exception("Could not read PixelSizeX from %s", self.base_url)
        try:
            width = await self._get("cameraxsize")
            height = await self._get("cameraysize")
            info["sensor_width_px"] = int(width) if width is not None else None
            info["sensor_height_px"] = int(height) if height is not None else None
        except Exception:
            logger.exception("Could not read CameraXSize/YSize from %s", self.base_url)
        try:
            info["sensor_name"] = await self._get("sensorname")
        except Exception:
            # SensorName is optional in the ASCOM spec — many drivers omit it.
            logger.debug("SensorName not available from %s", self.base_url)
        return info
