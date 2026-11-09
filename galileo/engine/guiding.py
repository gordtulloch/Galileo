# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Guiding on the engine (CSURF-160): one ``GuidingService`` per Pier, talking to the PHD2 saved for that Pier.

The host and port are the Pier's saved guider (Equipment > Guider, the same record the Guider screen writes), so the
engine and the desktop never disagree about where PHD2 is. A Pier connects on request; the engine does not connect
to PHD2 by itself, since PHD2 may be started later than Galileo. Once connected, the same service is handed to a
session the engine runs, so a session's Start Guiding and Dither blocks drive the PHD2 a remote client sees.

While any service is connected a small thread publishes ``guiding.state`` and ``guiding.rms`` as observable state, so
a client following the event feed sees guiding start, settle, lose the star and recover without polling.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from galileo.control_surface import ObservableState, Refused
from galileo.guiding import GuidingService

logger = logging.getLogger(__name__)

DRIVER_NAME = "PHD2"                         # what the Guider screen saves as the guider's driver
DEFAULT_HOST, DEFAULT_PORT = "localhost", 4400
COMMAND_TIMEOUT_S = 15.0                     # PHD2 accepting a command, not guiding settling
POLL_S = 2.0
FRAME_WANTED_S = 10.0                        # how long after a client last looked at the guide frame it keeps being fetched
TRACE_SAMPLES = 120                          # the recent error trace a status reply carries


class EngineGuiding:
    """``GuidingAccess`` (``galileo.control_surface.guiding``) over the device service."""

    def __init__(self, devices: Any, state: ObservableState,
                 factory: Callable[[str, int], GuidingService] = GuidingService, poll_s: float = POLL_S) -> None:
        self._devices, self._state, self._factory, self._poll_s = devices, state, factory, poll_s
        self._services: dict[str, GuidingService] = {}
        self._connecting: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._frame_wanted: dict[str, float] = {}
        self._star_wanted: dict[str, float] = {}

    # -- where PHD2 is -------------------------------------------------------------------------------
    def _saved(self, pier: str) -> tuple[str, int] | None:
        record = self._devices.pier_record(pier)
        if record is None:
            return None
        from galileo.observatory import get_device_config
        try:
            cfg = get_device_config(record, "guider")
        except Exception:
            logger.exception("Pier %s: could not read the saved guider", pier)
            return None
        if cfg is None or cfg.driver != DRIVER_NAME:
            return None
        return cfg.server or DEFAULT_HOST, int(cfg.port or DEFAULT_PORT)

    def service(self, pier: str) -> GuidingService | None:
        """The Pier's PHD2 service if it is connected, for a session to use; otherwise ``None``."""
        service = self._services.get(pier)
        return service if service is not None and service.is_connected else None

    def why_not_connect(self, pier: str) -> str | None:
        if self._devices.pier_record(pier) is None:
            return "there is no such Pier"
        if self._saved(pier) is None:
            return "this Pier has no PHD2 guider saved (Equipment > Guider)"
        if self.service(pier) is not None:
            return "already connected to PHD2"
        if pier in self._connecting:
            return "already connecting to PHD2"
        return None

    def why_not_command(self, pier: str) -> str | None:
        return None if self.service(pier) is not None else "not connected to PHD2"

    # -- connect and disconnect ----------------------------------------------------------------------
    async def connect(self, pier: str) -> dict[str, Any]:
        reason = self.why_not_connect(pier)
        if reason:
            raise Refused(reason)
        host, port = self._saved(pier) or (DEFAULT_HOST, DEFAULT_PORT)
        service = self._services.get(pier)
        if service is None or (service.host, service.port) != (host, port):
            service = self._services[pier] = self._factory(host, port)
        self._connecting.add(pier)
        try:
            await service.connect()
            await asyncio.to_thread(service.sync_state)
        except Exception as exc:
            logger.warning("Pier %s: could not connect to PHD2 at %s:%s: %s", pier, host, port, exc)
            raise Refused(f"could not connect to PHD2 at {host}:{port}: {exc}") from exc
        finally:
            self._connecting.discard(pier)
        self._publish(pier)
        self._ensure_poller()
        return {"connected": True, "host": host, "port": port}

    async def disconnect(self, pier: str) -> None:
        service = self._services.get(pier)
        if service is not None:
            await service.disconnect()
        self._publish(pier)

    # -- commands ------------------------------------------------------------------------------------
    async def command(self, pier: str, name: str, **kwargs: Any) -> None:
        service = self.service(pier)
        if service is None:
            raise Refused("not connected to PHD2")
        try:
            if name == "guide":
                future = service.guide(recalibrate=bool(kwargs.get("recalibrate")))
            elif name == "stop":
                future = service.stop()
            elif name == "dither":
                future = service.request_dither()
            elif name == "find_star":
                future = service.find_star()
            elif name == "select_star":
                x, y = float(kwargs["x"]), float(kwargs["y"])
                if kwargs.get("space") == "cutout":
                    mapped = service.cutout_to_frame(x, y)
                    if mapped is None:
                        raise Refused("there is no guide-star cut-out to tap yet")
                    x, y = mapped
                future = service.select_star(x, y)
            else:
                raise Refused(f"unknown guiding command {name!r}")
            await asyncio.wait_for(asyncio.wrap_future(future), COMMAND_TIMEOUT_S)
        except Refused:
            raise
        except TimeoutError as exc:
            raise Refused("PHD2 did not answer in time") from exc
        except Exception as exc:
            raise Refused(f"PHD2 rejected it: {exc}") from exc
        self._publish(pier)

    # -- reading -------------------------------------------------------------------------------------
    def status(self, pier: str) -> dict[str, Any]:
        saved = self._saved(pier)
        out: dict[str, Any] = {"configured": saved is not None, "connected": False,
                               "host": saved[0] if saved else "", "port": saved[1] if saved else 0,
                               "why_not_connect": self.why_not_connect(pier) or ""}
        service = self.service(pier)
        if service is None:
            return out
        snap = service.model.snapshot()
        out.update(
            connected=True, phd_version=snap.phd_version, app_state=snap.app_state, phase=snap.phase,
            guiding=snap.app_state == "Guiding", settling=snap.settling, equipment_connected=snap.equipment_connected,
            exposure_ms=snap.exposure_ms, pixel_scale=snap.pixel_scale, dec_mode=snap.dec_mode,
            star_pos=list(snap.star_pos) if snap.star_pos else None, unit=snap.unit,
            frame={"ref": f"guide:{pier}", "version": snap.frame_version, "available": snap.frame is not None,
                   "width": int(snap.frame.shape[1]) if snap.frame is not None else None,
                   "height": int(snap.frame.shape[0]) if snap.frame is not None else None},
            rms={"ra": snap.rms_ra, "dec": snap.rms_dec, "total": snap.rms_total},
            calibrated=snap.calibration is not None,
            trace=[[round(s.t, 2), s.frame, s.ra, s.dec, s.snr] for s in snap.samples[-TRACE_SAMPLES:]],
            log=snap.log[-10:])
        return out

    def star(self, pier: str) -> dict[str, Any] | None:
        self._star_wanted[pier] = time.monotonic()      # the poller only fetches the cut-out while a client is looking
        service = self.service(pier)
        image = service.model.snapshot().star_image if service is not None else None
        if image is None:
            if service is not None:
                service.poll(want_star_image=True)      # the first look should not wait for the poller
            return None
        return {"available": True, "frame": image.frame, "width": image.width, "height": image.height,
                "star_pos": list(image.star_pos), "format": "uint16 little-endian, row-major",
                "pixels": base64.b64encode(image.pixels).decode("ascii")}

    def frame(self, pier: str) -> tuple[str, Any] | None:
        """The whole guide frame as a preview source: ``(version, pixels)``, or ``None`` while there is none. Asking
        for it also tells the poller to keep fetching it (PHD2 writes a file for each), until nobody asks for a while."""
        self._frame_wanted[pier] = time.monotonic()
        service = self._services.get(pier)
        if service is None:
            return None
        snap = service.model.snapshot()
        if snap.frame is None:
            service.poll(want_star_image=False, want_frame=True)       # the first look should not wait for the poller
            return None
        return str(snap.frame_version), snap.frame

    # -- observable state ------------------------------------------------------------------------------
    def _publish(self, pier: str) -> None:
        service = self._services.get(pier)
        if service is None or not service.is_connected:
            self._state.publish(pier, "guiding.state", {"connected": False})
            self._state.publish(pier, "guiding.rms", None)
            return
        snap = service.model.snapshot()
        self._state.publish(pier, "guiding.state", {
            "connected": True, "app_state": snap.app_state, "guiding": snap.app_state == "Guiding", "settling": snap.settling})
        self._state.publish(pier, "guiding.rms", {
            "ra": round(snap.rms_ra, 3), "dec": round(snap.rms_dec, 3), "total": round(snap.rms_total, 3),
            "unit": snap.unit})

    def _ensure_poller(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="engine-guiding", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._poll_s):
            for pier, service in list(self._services.items()):
                try:
                    if service.is_connected:
                        service.poll(want_star_image=self._wants(self._star_wanted, pier),
                                     want_frame=self._wants(self._frame_wanted, pier))
                    self._publish(pier)
                except Exception:
                    logger.exception("Pier %s: could not refresh guiding state", pier)

    @staticmethod
    def _wants(asked: dict[str, float], pier: str) -> bool:
        return time.monotonic() - asked.get(pier, float("-inf")) < FRAME_WANTED_S

    def close(self) -> None:
        """Stop publishing and let go of every PHD2 connection."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(5)
        for service in list(self._services.values()):
            if not service.is_connected:
                continue
            try:
                asyncio.run(service.disconnect())
            except Exception:
                logger.exception("Could not disconnect from PHD2")
        self._services.clear()


__all__ = ["DRIVER_NAME", "EngineGuiding"]
