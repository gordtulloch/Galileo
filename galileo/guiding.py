# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Guiding service — PHD2 event-server integration (GUIDE-010 … GUIDE-090).

Two halves, both free of Qt and of any socket code (that lives in
``galileo.adapters.phd2``, behind the ``GuiderAdapter`` interface):

* ``GuideModel`` — a thread-safe mirror of what PHD2 has told us: its app
  state, the guide-step history, running RMS, calibration points, the last
  guide-star image and a human-readable event log. The adapter's reader thread
  feeds it events; the UI (or anything else) reads consistent snapshots.
* ``GuidingService`` — owns one adapter and one model for one Pier
  (``GUIDE-060``), issues the commands (start/stop/dither for the sequencer,
  loop/find-star/exposure/… for the Guider screen) and republishes connection
  loss on the event bus (``GUIDE-050``).
"""

from __future__ import annotations

import base64
import logging
import math
import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEC_GUIDE_MODES = ("Off", "Auto", "North", "South")
MAX_SAMPLES = 1000
MAX_LOG_LINES = 500

# PHD2 AppState → the three-lamp status the Guider screen shows.
_PHASE_BY_STATE = {
    "Guiding": "run",
    "Calibrating": "prep",
    "Looping": "prep",
    "Selected": "prep",
    "LostLock": "prep",
}


class GuiderError(RuntimeError):
    """A guider command failed or the guider connection was lost."""


@dataclass(frozen=True)
class GuideSample:
    """One PHD2 ``GuideStep``. Distances are the guider's raw error in
    pixels; pulses are correction durations in ms, signed West/North positive."""

    t: float
    frame: int
    ra: float
    dec: float
    ra_pulse_ms: float
    dec_pulse_ms: float
    snr: float
    star_mass: float
    hfd: float


@dataclass(frozen=True)
class StarImage:
    """PHD2's cut-out of the guide star (``get_star_image``): 16-bit pixels."""

    frame: int
    width: int
    height: int
    star_pos: tuple[float, float]
    pixels: bytes  # width*height little-endian uint16


@dataclass(frozen=True)
class CalibrationPoint:
    direction: str  # West / East / North / South
    dx: float
    dy: float


@dataclass
class GuideSnapshot:
    """A consistent copy of the model, safe to read on another thread."""

    version: int
    connected: bool
    phd_version: str
    app_state: str
    phase: str
    settling: bool
    equipment_connected: bool
    exposure_ms: float | None
    exposure_options_ms: list[float]
    dec_mode: str | None
    pixel_scale: float | None
    frame_size: tuple[int, int] | None
    star_pos: tuple[float, float] | None
    star_image: StarImage | None
    samples: list[GuideSample]
    calibration_points: list[CalibrationPoint]
    calibration: dict | None
    log: list[str]
    unit: str
    rms_ra: float
    rms_dec: float
    rms_total: float


def _running_stat_update(stat: list, x: float) -> None:
    # Welford: [n, mean, M2]
    stat[0] += 1
    delta = x - stat[1]
    stat[1] += delta / stat[0]
    stat[2] += delta * (x - stat[1])


def _running_stat_rms(stat: list) -> float:
    return math.sqrt(stat[2] / stat[0]) if stat[0] else 0.0


class GuideModel:
    """Everything PHD2 has reported, updated one event at a time."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._version = 0
        self.connected = False
        self.phd_version = ""
        self.app_state = "Stopped"
        self.settling = False
        self.equipment_connected = False
        self.exposure_ms: float | None = None
        self.exposure_options_ms: list[float] = []
        self.dec_mode: str | None = None
        self.pixel_scale: float | None = None  # arcsec per guide-camera pixel
        self.frame_size: tuple[int, int] | None = None
        self.star_pos: tuple[float, float] | None = None
        self.star_image: StarImage | None = None
        self.calibration: dict | None = None
        self._samples: deque[GuideSample] = deque(maxlen=MAX_SAMPLES)
        self._cal_points: list[CalibrationPoint] = []
        self._log: deque[str] = deque(maxlen=MAX_LOG_LINES)
        self._ra_stat = [0, 0.0, 0.0]
        self._dec_stat = [0, 0.0, 0.0]

    # --- Reading ----------------------------------------------------------

    @property
    def version(self) -> int:
        """Bumps on every change; lets a poller skip redrawing when nothing moved."""
        return self._version

    @property
    def phase(self) -> str:
        """``"idle"``, ``"prep"`` (looping, calibrating, star picked/lost, settling) or ``"run"``."""
        if self.settling:
            return "prep"
        return _PHASE_BY_STATE.get(self.app_state, "idle")

    @property
    def unit(self) -> str:
        return "arcsec" if self.pixel_scale else "px"

    def rms(self) -> tuple[float, float, float]:
        """RA, Dec and total guide RMS since guiding started, in ``unit``."""
        with self._lock:
            scale = self.pixel_scale or 1.0
            ra = _running_stat_rms(self._ra_stat) * scale
            dec = _running_stat_rms(self._dec_stat) * scale
        return ra, dec, math.hypot(ra, dec)

    def snapshot(self) -> GuideSnapshot:
        with self._lock:
            ra, dec, total = self.rms()
            return GuideSnapshot(
                version=self._version, connected=self.connected, phd_version=self.phd_version,
                app_state=self.app_state, phase=self.phase, settling=self.settling,
                equipment_connected=self.equipment_connected, exposure_ms=self.exposure_ms,
                exposure_options_ms=list(self.exposure_options_ms), dec_mode=self.dec_mode,
                pixel_scale=self.pixel_scale, frame_size=self.frame_size, star_pos=self.star_pos,
                star_image=self.star_image, samples=list(self._samples),
                calibration_points=list(self._cal_points), calibration=self.calibration,
                log=list(self._log), unit=self.unit, rms_ra=ra, rms_dec=dec, rms_total=total,
            )

    # --- Writing ----------------------------------------------------------

    def _touch(self) -> None:
        self._version += 1

    def log(self, message: str) -> None:
        with self._lock:
            self._log.append(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}")
            self._touch()

    def update(self, **fields) -> None:
        """Set plain attributes (``connected``, ``exposure_ms``, …) under the lock."""
        with self._lock:
            for name, value in fields.items():
                setattr(self, name, value)
            self._touch()

    def reset(self) -> None:
        """Forget everything session-specific (the connection was dropped)."""
        with self._lock:
            self.connected = False
            self.app_state = "Stopped"
            self.settling = False
            self.equipment_connected = False
            self.star_image = None
            self._touch()

    def set_star_image(self, result: dict) -> None:
        """Store a ``get_star_image`` result."""
        try:
            width, height = int(result["width"]), int(result["height"])
            pixels = base64.b64decode(result["pixels"])
            if len(pixels) != width * height * 2:
                return
            pos = result.get("star_pos") or [width / 2, height / 2]
            image = StarImage(int(result.get("frame", 0)), width, height, (float(pos[0]), float(pos[1])), pixels)
        except (KeyError, TypeError, ValueError):
            return
        with self._lock:
            self.star_image = image
            self._touch()

    def apply_event(self, event: dict) -> None:
        """Fold one PHD2 event (``{"Event": name, …}``) into the model."""
        name = event.get("Event")
        handler = getattr(self, f"_on_{name}", None)
        if handler is None:
            return
        with self._lock:
            handler(event)
            self._touch()

    # Each handler runs with the lock held.

    def _on_Version(self, e: dict) -> None:
        self.phd_version = f"{e.get('PHDVersion', '?')}{('.' + str(e['PHDSubver'])) if e.get('PHDSubver') else ''}"

    def _on_AppState(self, e: dict) -> None:
        self.app_state = e.get("State", self.app_state)
        if self.app_state != "Guiding":
            self.settling = False

    def _on_StartCalibration(self, e: dict) -> None:
        self.app_state = "Calibrating"
        self._cal_points = []
        self.calibration = None
        self._note("Calibration started.")

    def _on_Calibrating(self, e: dict) -> None:
        self.app_state = "Calibrating"
        if "dx" in e and "dy" in e:
            self._cal_points.append(CalibrationPoint(str(e.get("dir", "")), float(e["dx"]), float(e["dy"])))

    def _on_CalibrationComplete(self, e: dict) -> None:
        self._note("Calibration complete.")

    def _on_CalibrationFailed(self, e: dict) -> None:
        self._note(f"Calibration failed: {e.get('Reason', 'unknown reason')}")

    def _on_CalibrationDataFlipped(self, e: dict) -> None:
        self._note("Calibration data flipped.")

    def _on_StarSelected(self, e: dict) -> None:
        self.star_pos = (float(e.get("X", 0.0)), float(e.get("Y", 0.0)))
        if self.app_state == "Stopped":
            self.app_state = "Selected"
        self._note(f"Star selected at {self.star_pos[0]:.1f}, {self.star_pos[1]:.1f}.")

    def _on_LockPositionSet(self, e: dict) -> None:
        self._note(f"Lock position set to {float(e.get('X', 0.0)):.1f}, {float(e.get('Y', 0.0)):.1f}.")

    def _on_LockPositionLost(self, e: dict) -> None:
        self._note("Lock position lost.")

    def _on_StarLost(self, e: dict) -> None:
        self.app_state = "LostLock"
        self._note("Lost track of the guide star. Try increasing the square size or reducing pulse duration.")

    def _on_LoopingExposures(self, e: dict) -> None:
        if self.app_state != "Looping":
            self._note("Looping exposures.")
        self.app_state = "Looping"

    def _on_LoopingExposuresStopped(self, e: dict) -> None:
        self.app_state = "Stopped"
        self._note("Looping stopped.")

    def _on_StartGuiding(self, e: dict) -> None:
        self.app_state = "Guiding"
        self._samples.clear()
        self._ra_stat = [0, 0.0, 0.0]
        self._dec_stat = [0, 0.0, 0.0]
        self._note("Guiding started.")

    def _on_GuidingStopped(self, e: dict) -> None:
        self.app_state = "Stopped"
        self.settling = False
        self._note("Guiding stopped.")

    def _on_Paused(self, e: dict) -> None:
        self.app_state = "Paused"
        self._note("Guiding paused.")

    def _on_Resumed(self, e: dict) -> None:
        self.app_state = "Guiding"
        self._note("Guiding resumed.")

    def _on_SettleBegin(self, e: dict) -> None:
        self.settling = True
        self._note("Settling…")

    def _on_SettleDone(self, e: dict) -> None:
        self.settling = False
        if e.get("Status", 0) == 0:
            self._note("Settle done.")
        else:
            self._note(f"Settle failed: {e.get('Error', 'unknown error')}")

    def _on_GuidingDithered(self, e: dict) -> None:
        self._note(f"Dithered by {float(e.get('dx', 0.0)):.1f}, {float(e.get('dy', 0.0)):.1f} px.")

    def _on_Alert(self, e: dict) -> None:
        self._note(f"PHD2 {str(e.get('Type', 'info')).lower()}: {e.get('Msg', '')}")

    def _on_GuideStep(self, e: dict) -> None:
        self.app_state = "Guiding"
        ra_pulse = float(e.get("RADuration", 0) or 0)
        if e.get("RADirection") == "East":
            ra_pulse = -ra_pulse
        dec_pulse = float(e.get("DECDuration", 0) or 0)
        if e.get("DECDirection") == "South":
            dec_pulse = -dec_pulse
        sample = GuideSample(
            t=float(e.get("Time", time.monotonic())), frame=int(e.get("Frame", 0)),
            ra=float(e.get("RADistanceRaw", 0.0)), dec=float(e.get("DECDistanceRaw", 0.0)),
            ra_pulse_ms=ra_pulse, dec_pulse_ms=dec_pulse, snr=float(e.get("SNR", 0.0)),
            star_mass=float(e.get("StarMass", 0.0)), hfd=float(e.get("HFD", 0.0)),
        )
        self._samples.append(sample)
        _running_stat_update(self._ra_stat, sample.ra)
        _running_stat_update(self._dec_stat, sample.dec)

    def _note(self, message: str) -> None:
        self._log.append(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}")


class GuidingService:
    """Drives one PHD2 instance (GUIDE-010 … GUIDE-090)."""

    def __init__(self, host: str = "localhost", port: int = 4400, client=None) -> None:
        self.host = host
        self.port = port
        self.model = GuideModel()
        self._client = client  # a GuiderAdapter; created on connect() when not injected
        self._event_bus = None
        self._is_guiding = False

    @property
    def is_connected(self) -> bool:
        return self._client is not None and getattr(self._client, "is_connected", True)

    @property
    def is_guiding(self) -> bool:
        return self._is_guiding

    # --- Connection -------------------------------------------------------

    def _ensure_client(self):
        if self._client is None:
            from galileo.adapters.phd2 import Phd2Adapter
            self._client = Phd2Adapter(self.host, self.port)
        self._client.on_event = self._handle_event
        self._client.on_disconnect = self._handle_disconnect
        return self._client

    async def connect(self) -> None:
        """Open the connection to PHD2."""
        client = self._ensure_client()
        try:
            await client.connect()
        except Exception as exc:
            logger.error("Failed to connect to guider at %s:%d: %s", self.host, self.port, exc)
            raise
        self.model.update(connected=True)
        self.model.log(f"Connected to PHD2 at {self.host}:{self.port}.")

    async def disconnect(self) -> None:
        if self._client is not None and hasattr(self._client, "disconnect"):
            await self._client.disconnect()
        self._is_guiding = False
        self.model.reset()
        self.model.log("Disconnected from PHD2.")

    def sync_state(self) -> None:
        """Blocking: read PHD2's current state after connecting (call from a
        worker thread). Each query is optional — an older PHD2 that lacks one
        just leaves that field unset."""
        client = self._client

        def ask(method: str, params=None):
            try:
                return client.call(method, params)
            except Exception as exc:  # noqa: BLE001 — every query is optional; older PHD2s lack some
                logger.debug("PHD2 %s failed: %s", method, exc)
                return None

        state = ask("get_app_state")
        if state:
            self.model.apply_event({"Event": "AppState", "State": state})
            self._is_guiding = state == "Guiding"
        fields: dict = {}
        if (exposure := ask("get_exposure")) is not None:
            fields["exposure_ms"] = float(exposure)
        if (options := ask("get_exposure_durations")):
            fields["exposure_options_ms"] = [float(x) for x in options]
        if (scale := ask("get_pixel_scale")):
            fields["pixel_scale"] = float(scale)
        if (size := ask("get_camera_frame_size")):
            fields["frame_size"] = (int(size[0]), int(size[1]))
        if (mode := ask("get_dec_guide_mode")):
            fields["dec_mode"] = mode
        if (connected := ask("get_connected")) is not None:
            fields["equipment_connected"] = bool(connected)
        if fields:
            self.model.update(**fields)
        if ask("get_calibrated"):
            self._request_calibration_data()

    def poll(self, want_star_image: bool = True) -> None:
        """Non-blocking refresh of the things PHD2 doesn't push as events.
        Answers land in the model from the adapter's reader thread."""
        if not self.is_connected:
            return
        self._ask("get_connected", None, lambda v: self.model.update(equipment_connected=bool(v)))
        if want_star_image and self.model.app_state in ("Looping", "Guiding", "Selected", "LostLock"):
            self._ask("get_star_image", [100], self.model.set_star_image)

    # --- Commands (sequencer-facing, async) -------------------------------

    async def start_guiding(self) -> None:
        """Issue guide and wait for PHD2 to confirm it has settled (GUIDE-020)."""
        await self._client.start_guiding()
        self._is_guiding = True
        await self._wait_for_guiding_state()

    async def stop_guiding(self) -> None:
        await self._client.stop_guiding()
        self._is_guiding = False

    async def dither_and_wait(
        self,
        settle_timeout_s: float = 30.0,
        settle_pixels: float = 0.5,
    ) -> None:
        """Send dither command and wait for the guider to settle (GUIDE-030)."""
        await self._client.dither(settle_pixels=settle_pixels, settle_timeout_s=settle_timeout_s)
        await self._client.wait_for_settle(settle_timeout_s)

    async def dither(self) -> None:
        await self.dither_and_wait()

    async def _wait_for_guiding_state(self) -> bool:
        return bool(await self._client.wait_for_settle())

    # --- Commands (Guider screen, non-blocking) ---------------------------

    def loop(self) -> Future:
        return self._command("loop", None, "Looping exposures requested")

    def guide(self, recalibrate: bool = False, settle_pixels: float = 1.5,
              settle_time_s: float = 10, settle_timeout_s: float = 100) -> Future:
        return self._command(
            "guide",
            [{"pixels": settle_pixels, "time": settle_time_s, "timeout": settle_timeout_s}, recalibrate],
            "Guide requested",
        )

    def stop(self) -> Future:
        return self._command("stop_capture", None, "Stop requested")

    def find_star(self) -> Future:
        return self._command("find_star", None, "Auto star selection requested")

    def request_dither(self, amount_px: float = 3.0, ra_only: bool = False,
                       settle_pixels: float = 1.5, settle_time_s: float = 10,
                       settle_timeout_s: float = 100) -> Future:
        return self._command(
            "dither",
            [amount_px, ra_only, {"pixels": settle_pixels, "time": settle_time_s, "timeout": settle_timeout_s}],
            "Dither requested",
        )

    def set_exposure(self, ms: float) -> Future:
        return self._command_then("set_exposure", [int(ms)], exposure_ms=float(ms))

    def set_dec_guide_mode(self, mode: str) -> Future:
        if mode not in DEC_GUIDE_MODES:
            raise ValueError(f"Dec guide mode must be one of {DEC_GUIDE_MODES}, not {mode!r}")
        return self._command_then("set_dec_guide_mode", [mode], dec_mode=mode)

    def clear_calibration(self) -> Future:
        return self._command("clear_calibration", ["both"], "Calibration cleared")

    def set_equipment_connected(self, connected: bool) -> Future:
        self.model.log("Connecting PHD2 equipment…" if connected else "Disconnecting PHD2 equipment…")
        return self._command_then("set_connected", [connected], equipment_connected=connected)

    # --- Telemetry --------------------------------------------------------

    def get_rms(self) -> dict:
        """Return guide RMS (GUIDE-040), in arcsec once PHD2 has told us its
        pixel scale, otherwise in guide-camera pixels."""
        ra = getattr(self._client, "rms_ra", None) if self._client is not None else None
        dec = getattr(self._client, "rms_dec", None) if self._client is not None else None
        model_ra, model_dec, _ = self.model.rms()
        ra = model_ra if ra is None else ra
        dec = model_dec if dec is None else dec
        return {"ra": ra, "dec": dec, "total": math.hypot(ra, dec)}

    async def check_health(self) -> None:
        """Check connection health; publish recoverable error if lost (GUIDE-050)."""
        if not self.is_connected:
            self._publish_connection_lost()

    # --- Internal ---------------------------------------------------------

    def _handle_event(self, event: dict) -> None:
        self.model.apply_event(event)
        name = event.get("Event")
        if name in ("StartGuiding", "Resumed") or (name == "GuideStep"):
            self._is_guiding = True
        elif name in ("GuidingStopped", "LoopingExposuresStopped", "Paused", "StarLost"):
            self._is_guiding = False
        elif name == "AppState":
            self._is_guiding = event.get("State") == "Guiding"
        elif name == "CalibrationComplete":
            self._request_calibration_data()

    def _handle_disconnect(self) -> None:
        self._is_guiding = False
        self.model.reset()
        self.model.log("Lost connection to PHD2.")
        self._publish_connection_lost()

    def _publish_connection_lost(self) -> None:
        if self._event_bus is None:
            return
        import datetime

        from galileo.bus import DeviceErrorEvent
        self._event_bus.publish(DeviceErrorEvent(
            source="guider",
            timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
            error="guiding connection lost",
            recoverable=True,
        ))

    def _request_calibration_data(self) -> None:
        self._ask("get_calibration_data", ["Mount"], lambda data: self.model.update(calibration=data))

    def _ask(self, method: str, params, on_result) -> None:
        """Fire a request and hand its result to *on_result*; failures are
        logged at debug level only (this is best-effort background refresh)."""
        def done(future: Future) -> None:
            exc = future.exception()
            if exc is not None:
                logger.debug("PHD2 %s failed: %s", method, exc)
            elif future.result() is not None:
                on_result(future.result())
        self._client.request(method, params).add_done_callback(done)

    def _command_then(self, method: str, params, **model_fields) -> Future:
        """A command whose effect PHD2 doesn't announce as an event: once PHD2
        accepts it, record *model_fields* in the model."""
        future = self._command(method, params, None)

        def accepted(f: Future) -> None:
            if f.exception() is None:
                self.model.update(**model_fields)
        future.add_done_callback(accepted)
        return future

    def _command(self, method: str, params, message: str | None) -> Future:
        """Send a user-issued command; log it, and log the failure if PHD2
        rejects it so the Guider screen's log shows why nothing happened."""
        if message:
            self.model.log(f"{message}.")
        future = self._client.request(method, params) if self._client is not None else _failed("not connected")

        def done(f: Future) -> None:
            exc = f.exception()
            if exc is not None:
                self.model.log(f"PHD2 rejected {method}: {exc}")
        future.add_done_callback(done)
        return future


def _failed(message: str) -> Future:
    future: Future = Future()
    future.set_exception(GuiderError(message))
    return future
