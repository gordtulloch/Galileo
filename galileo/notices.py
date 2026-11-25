# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Event notices: the short, human-readable "something just happened" messages (NOTE-010 ... NOTE-050).

Every significant event — an exposure starting, a slew beginning or ending, a plate solve resolving, a focus
result, a device connecting — is posted on the event bus as one :class:`NoticeEvent`. The desktop shows each as a
brief floating panel in the top-right corner of the window (``galileo.ui.notice_toast``) and the mobile apps
show the same notice through the engine feed (``MobileConnect``), so there is one source of truth and no
per-screen log pane.

Two ways in:

* :func:`post_notice` — called directly where an event happens.
* :class:`NoticeBridge` (:func:`install_bridge`) — translates events other modules already publish (device
  connect/disconnect, solves, autofocus, safety, sessions) into notices, so those modules need no change.

Device *commands* (exposures, slews, parks, focuser/filter/rotator/dome moves) are described by
:func:`notice_for_command`, which the INDI and Alpaca adapters call from the one place each already logs
device commands.

Nothing here may raise into a caller: a notice is a courtesy, never a reason for a command to fail.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from galileo.bus import (
    DeviceConnectedEvent,
    DeviceDisconnectedEvent,
    DeviceErrorEvent,
    Event,
    EventBus,
    FocusCompleteEvent,
    FocusStartedEvent,
    SafetyUnsafeEvent,
    SequenceAbortEvent,
    SequenceCompleteEvent,
    SequenceErrorEvent,
    SolveCompleteEvent,
    SolveStartedEvent,
    get_bus,
)

logger = logging.getLogger(__name__)

INFO, SUCCESS, WARNING, ERROR = "info", "success", "warning", "error"
SEVERITIES = (INFO, SUCCESS, WARNING, ERROR)

_DUPLICATE_WINDOW_S = 0.75


class NoticeEvent(Event):
    """Payload: ``kind`` (a dotted id such as ``exposure.started``), ``title``, ``message``, ``severity``
    (``info``/``success``/``warning``/``error``), ``device`` and ``pier`` (either may be empty), ``time`` (epoch s)."""


_enabled = True          # the desktop closes this gate during start-up, so initial connections stay quiet (NOTE-060)


def set_notices_enabled(enabled: bool) -> None:
    """Open or close the gate. While closed, notices are dropped, not queued — so nothing that happened during
    start-up (auto-connecting equipment, say) is announced once the window is up."""
    global _enabled
    _enabled = bool(enabled)


def notices_enabled() -> bool:
    return _enabled


_local = threading.local()      # the bus a bridge handler is running for, so its notices go out on that same bus
_recent: dict[tuple[str, str, str], float] = {}
_recent_lock = threading.Lock()


def post_notice(kind: str, title: str, message: str = "", severity: str = INFO, *, device: str = "",
                pier: str = "", bus: EventBus | None = None) -> None:
    """Publish one notice. Identical notices within a moment are dropped (a command echoed by two layers)."""
    if not _enabled:
        return
    try:
        now = time.monotonic()
        key = (kind, title, message)
        with _recent_lock:
            last = _recent.get(key)
            if last is not None and now - last < _DUPLICATE_WINDOW_S:
                return
            _recent[key] = now
            if len(_recent) > 256:
                for stale in [k for k, t in _recent.items() if now - t > 5.0]:
                    del _recent[stale]
        (bus or getattr(_local, "bus", None) or get_bus()).publish(NoticeEvent(
            "notices", kind=kind, title=title, message=message,
            severity=severity if severity in SEVERITIES else INFO,
            device=device, pier=pier, time=time.time()))
    except Exception:
        logger.debug("Could not post notice %r", kind, exc_info=True)


# ---------------------------------------------------------------------------------------------------------
# Device commands
# ---------------------------------------------------------------------------------------------------------

def _hms(ra_deg: float) -> str:
    hours = (ra_deg / 15.0) % 24.0
    h = int(hours)
    m = (hours - h) * 60.0
    return f"{h:02d}h{m:04.1f}m"


def _dms(dec: float) -> str:
    sign = "-" if dec < 0 else "+"
    dec = abs(dec)
    d = int(dec)
    return f"{sign}{d:02d}°{(dec - d) * 60.0:02.0f}′"


_series: tuple[int, int] | None = None     # (frame number, frames in the set) while a multi-frame series runs


def set_series_progress(index: int, count: int) -> None:
    """Record which frame of a multi-frame set is about to start, so the exposure notice can say
    "Exposure 4 of 99 starting". Call :func:`clear_series_progress` when the set ends."""
    global _series
    _series = (int(index), int(count)) if int(count) > 1 else None


def clear_series_progress() -> None:
    global _series
    _series = None


def _exposure_text(p: dict[str, Any]) -> str:
    duration = p.get("duration")
    kind = str(p.get("frame_type") or "Light")
    text = f"{float(duration):g} s {kind}" if isinstance(duration, (int, float)) else kind
    series = _series
    return f"Exposure {series[0]} of {series[1]} starting: {text}" if series else text


# action -> (kind, title, severity, message builder)
_COMMANDS: dict[str, tuple[str, str, str, Any]] = {
    "start_exposure": ("exposure.started", "Exposure started", INFO, _exposure_text),
    "abort_exposure": ("exposure.aborted", "Exposure aborted", WARNING, None),
    "slew_to_coordinates": ("slew.started", "Slew started", INFO,
                            lambda p: f"RA {_hms(float(p['ra']))}  Dec {_dms(float(p['dec']))}" if "ra" in p and "dec" in p else ""),
    "slew_to_altaz": ("slew.started", "Slew started", INFO,
                      lambda p: f"Alt {float(p['alt']):.1f}°  Az {float(p['az']):.1f}°" if "alt" in p and "az" in p else ""),
    "abort_slew": ("slew.aborted", "Slew stopped", WARNING, None),
    "park": ("park.started", "Parking", INFO, None),
    "unpark": ("park.ended", "Unparking", INFO, None),
    "find_home": ("home.started", "Finding home", INFO, None),
    "sync_to_coordinates": ("mount.synced", "Mount synced", INFO,
                            lambda p: f"RA {_hms(float(p['ra']))}  Dec {_dms(float(p['dec']))}" if "ra" in p and "dec" in p else ""),
    "set_tracking": ("tracking.changed", "Tracking", INFO, lambda p: "on" if p.get("enabled") else "off"),
    "move_to": ("move.started", "Moving", INFO, None),
    "move_by": ("move.started", "Moving", INFO, lambda p: f"{int(p['steps']):+d} steps" if "steps" in p else ""),
    "move_to_angle": ("rotator.moving", "Rotator moving", INFO, lambda p: f"to {float(p['angle']):.1f}°" if "angle" in p else ""),
    "slew_to_azimuth": ("dome.slewing", "Dome slewing", INFO, lambda p: f"to {float(p['azimuth']):.0f}°" if "azimuth" in p else ""),
    "open_shutter": ("dome.shutter", "Dome shutter opening", INFO, None),
    "close_shutter": ("dome.shutter", "Dome shutter closing", INFO, None),
    "open_cover": ("flatpanel.cover", "Flat panel cover opening", INFO, None),
    "close_cover": ("flatpanel.cover", "Flat panel cover closing", INFO, None),
    "light_on": ("flatpanel.light", "Flat panel light on", INFO, None),
    "light_off": ("flatpanel.light", "Flat panel light off", INFO, None),
    "set_temperature": ("camera.cooling", "Cooler target set", INFO, lambda p: f"{float(p['temp_c']):g} °C" if "temp_c" in p else ""),
    "warm_up": ("camera.warming", "Camera warming up", INFO, None),
}

# Alpaca attribute -> the action above that it is.
_ALPACA = {
    "startexposure": "start_exposure", "abortexposure": "abort_exposure",
    "slewtocoordinatesasync": "slew_to_coordinates", "slewtoaltazasync": "slew_to_altaz",
    "abortslew": "abort_slew", "park": "park", "unpark": "unpark", "findhome": "find_home",
    "synctocoordinates": "sync_to_coordinates", "tracking": "set_tracking",
    "slewtoazimuth": "slew_to_azimuth", "openshutter": "open_shutter", "closeshutter": "close_shutter",
    "move": "move_to", "position": "move_to", "setccdtemperature": "set_temperature",
}


def notice_for_command(device_type: str, action: str, device: str = "", **params: Any) -> None:
    """Post the notice for a device command, if it is one worth showing. *action* is the INDI adapter's action
    name, or an Alpaca attribute (mapped to the same set). Never raises."""
    try:
        action = _ALPACA.get(action, action)
        entry = _COMMANDS.get(action)
        if entry is None:
            return
        kind, title, severity, build = entry
        if action == "set_tracking" and "enabled" not in params:
            if "Tracking" in params:
                params = {"enabled": params["Tracking"]}
            else:
                return
        if action == "slew_to_coordinates" and "RightAscension" in params:   # an Alpaca body
            params = {"ra": float(params["RightAscension"]) * 15.0, "dec": float(params["Declination"])}
        if action == "slew_to_altaz" and "Azimuth" in params:
            params = {"alt": float(params["Altitude"]), "az": float(params["Azimuth"])}
        if action == "start_exposure" and "Duration" in params:
            params = {"duration": params["Duration"],
                      "frame_type": "Light" if params.get("Light", True) else "Dark"}
        if action == "move_to":
            title, text = _move_text(device_type, params)
        else:
            text = build(params) if build else ""
        label = f"{device_type} {device}".strip() if device else device_type
        message = f"{text} — {label}" if text and label else (text or label)
        post_notice(kind, title, message, severity, device=device)
    except Exception:
        logger.debug("Could not describe command %r", action, exc_info=True)


def _move_text(device_type: str, p: dict[str, Any]) -> tuple[str, str]:
    kind = (device_type or "").lower()
    if "filter" in kind:
        return "Filter wheel moving", f"to slot {p['index']}" if "index" in p else ""
    if "rotator" in kind:
        return "Rotator moving", ""
    value = p.get("position", p.get("Position"))
    return "Focuser moving", f"to {value}" if value is not None else ""


def post_guiding_notice(message: str) -> None:
    """A line of PHD2/guiding progress (guiding started, star lost, a command rejected, …) as a notice."""
    text = message.rstrip(".")
    low = text.lower()
    bad = any(w in low for w in ("lost", "failed", "rejected", "could not", "error", "warning"))
    good = any(low.startswith(w) for w in ("guiding started", "calibration complete", "settle done", "connected to phd2"))
    post_notice("guiding.event", "Guiding", text, WARNING if bad else SUCCESS if good else INFO)


def note_slew_state(device: str, was_slewing: bool, is_slewing: bool) -> None:
    """Called by a mount adapter each time it learns whether the mount is slewing; posts when a slew ends."""
    if was_slewing and not is_slewing:
        post_notice("slew.ended", "Slew complete", device, SUCCESS, device=device)


# ---------------------------------------------------------------------------------------------------------
# Events other modules already publish
# ---------------------------------------------------------------------------------------------------------

def _device_label(event: Event) -> str:
    p = event.payload
    name = p.get("device") or p.get("category") or event.source or "Device"
    slot = p.get("slot")
    name = str(name).replace("_", " ")
    return f"{name} ({slot})" if slot and slot not in ("primary", "PRIMARY") else name


def _on_connected(e: Event) -> None:
    post_notice("device.connected", "Connected", _device_label(e), SUCCESS, pier=str(e.payload.get("pier") or ""))


def _on_disconnected(e: Event) -> None:
    post_notice("device.disconnected", "Disconnected", _device_label(e), WARNING, pier=str(e.payload.get("pier") or ""))


def _on_device_error(e: Event) -> None:
    detail = str(e.payload.get("error") or "")
    post_notice("device.error", "Device error", f"{_device_label(e)}: {detail}" if detail else _device_label(e),
                ERROR, pier=str(e.payload.get("pier") or ""))


def _name(path: Any) -> str:
    import os
    return os.path.basename(str(path)) if path else ""


def _on_solve_started(e: Event) -> None:
    post_notice("solve.started", "Plate solve started", _name(e.payload.get("fits_path")), INFO)


def _on_solve_complete(e: Event) -> None:
    result = e.payload.get("result")
    if result is not None and getattr(result, "success", False):
        try:
            where = f"RA {_hms(float(result.ra_deg))}  Dec {_dms(float(result.dec_deg))}"
        except Exception:
            where = _name(e.payload.get("fits_path"))
        post_notice("solve.resolved", "Plate solve resolved", where, SUCCESS)
    else:
        why = str(getattr(result, "failure_reason", "") or "no solution")
        if why == "Cancelled":
            post_notice("solve.cancelled", "Plate solve cancelled", "", INFO)
        else:
            post_notice("solve.failed", "Plate solve failed", why, WARNING)


def _on_focus_started(e: Event) -> None:
    points = e.payload.get("num_points")
    post_notice("focus.started", "Autofocus started", f"{points} points" if points else "", INFO)


def _on_focus_complete(e: Event) -> None:
    result = e.payload.get("result")
    ok = bool(getattr(result, "success", False))
    if ok:
        pos = getattr(result, "best_position", None)
        points = getattr(result, "sample_points", None) or []
        bits = [f"best position {pos}" if pos is not None else "", f"{len(points)} samples" if points else ""]
        post_notice("focus.result", "Autofocus complete", ", ".join(b for b in bits if b), SUCCESS)
    else:
        why = getattr(result, "failure_reason", "") or "no result"
        post_notice("focus.failed", "Autofocus failed", str(why), WARNING)


def _on_unsafe(e: Event) -> None:
    post_notice("safety.unsafe", "Unsafe conditions", str(e.payload.get("explanation") or ""), ERROR,
                pier=str(e.payload.get("pier") or ""))


def _on_session_started(e: Event) -> None:
    post_notice("session.started", "Session started", str(e.payload.get("name") or e.source or ""), INFO)


def _on_session_finished(e: Event) -> None:
    state = str(e.payload.get("state") or "")
    name = str(e.payload.get("name") or "")
    ok = state in ("", "completed")
    post_notice("session.finished", "Session finished" if ok else f"Session {state}", name,
                SUCCESS if ok else WARNING)


def _on_sequence(kind: str, title: str, severity: str):
    def handler(e: Event) -> None:
        post_notice(kind, title, str(e.payload.get("message") or e.payload.get("error") or ""), severity)
    return handler


_installed: dict[int, list[tuple[type, Any]]] = {}


def _bound(handler: Any, bus: EventBus) -> Any:
    def run(event: Event) -> None:
        previous = getattr(_local, "bus", None)
        _local.bus = bus
        try:
            handler(event)
        finally:
            _local.bus = previous
    return run


def install_bridge(bus: EventBus | None = None) -> None:
    """Subscribe the translators to *bus* (the process bus by default). Safe to call more than once."""
    from galileo.engine.runner import SessionFinishedEvent, SessionStartedEvent
    bus = bus or get_bus()
    if id(bus) in _installed:
        return
    pairs: list[tuple[type, Any]] = [
        (DeviceConnectedEvent, _on_connected), (DeviceDisconnectedEvent, _on_disconnected),
        (DeviceErrorEvent, _on_device_error),
        (SolveStartedEvent, _on_solve_started), (SolveCompleteEvent, _on_solve_complete),
        (FocusStartedEvent, _on_focus_started), (FocusCompleteEvent, _on_focus_complete),
        (SafetyUnsafeEvent, _on_unsafe),
        (SessionStartedEvent, _on_session_started), (SessionFinishedEvent, _on_session_finished),
        (SequenceCompleteEvent, _on_sequence("session.finished", "Sequence complete", SUCCESS)),
        (SequenceErrorEvent, _on_sequence("session.error", "Sequence error", ERROR)),
        (SequenceAbortEvent, _on_sequence("session.aborted", "Sequence aborted", WARNING)),
    ]
    pairs = [(event_type, _bound(handler, bus)) for event_type, handler in pairs]
    for event_type, handler in pairs:
        bus.subscribe(event_type, handler)
    _installed[id(bus)] = pairs


def uninstall_bridge(bus: EventBus | None = None) -> None:
    bus = bus or get_bus()
    for event_type, handler in _installed.pop(id(bus), []):
        bus.unsubscribe(event_type, handler)


__all__ = [
    "ERROR",
    "INFO",
    "SUCCESS",
    "WARNING",
    "NoticeEvent",
    "clear_series_progress",
    "install_bridge",
    "note_slew_state",
    "notice_for_command",
    "notices_enabled",
    "post_guiding_notice",
    "post_notice",
    "set_notices_enabled",
    "set_series_progress",
    "uninstall_bridge",
]
