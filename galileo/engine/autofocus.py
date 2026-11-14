# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Autofocus on the engine (CSURF-340): the Focus screen's own ``AutofocusService``, assembled from the Pier's camera and
focuser and its saved autofocus settings (Options > Focus).

A Pier runs one autofocus at a time, and none while a session, a plate solve or polar alignment is using the camera. The
service publishes its progress on the event bus as it always does (the desktop's Focus screen follows the same events);
this module listens for the events carrying the Pier's key and keeps them as one dictionary, published as the observable
state ``focus.autofocus`` on every change and returned in the run's result, so a client at the telescope sees each point
of the V-curve as it is measured. The last picture stays readable after the run ends.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from galileo.bus import EventBus, FocusCompleteEvent, FocusFrameEvent, FocusStartedEvent, get_bus
from galileo.control_surface import ObservableState, Refused
from galileo.control_surface.autofocus import STATE_KEY

logger = logging.getLogger(__name__)

Factory = Callable[[str], Awaitable[Any]]


async def build_service(devices: Any, pier: str) -> Any:
    """The Pier's autofocus (``ConfiguredAutofocus``: the service plus its saved sweep), built the way the session
    executor builds it so a remote run and a session's trigger focus identically."""
    from galileo.engine.sessions import build_context
    context = await build_context(devices, pier)
    return context.make_autofocus()


def _blank() -> dict[str, Any]:
    return {"running": False, "phase": "idle", "message": "", "step": 0, "steps": 0, "points": [],
            "best_position": None, "success": None, "cancelled": False, "failure_reason": ""}


class EngineAutofocus:
    """``AutofocusAccess`` (``galileo.control_surface.autofocus``) over the device service and session runner."""

    def __init__(self, devices: Any, runner: Any, state: ObservableState, factory: Factory | None = None,
                 busy: Callable[[str], bool] | None = None, bus: EventBus | None = None,
                 key_of: Callable[[str], Any] | None = None) -> None:
        self._devices, self._runner, self._state = devices, runner, state
        self._factory: Factory = factory or (lambda pier: build_service(devices, pier))
        self._busy = busy or (lambda pier: False)            # whether something else (a plate solve, polar) holds the camera
        self._bus = bus
        self._key_of = key_of or self._default_key
        self._services: dict[str, Any] = {}
        self._picture: dict[str, dict[str, Any]] = {}

    def _default_key(self, pier: str) -> Any:
        from galileo.current_object import pier_key
        return pier_key(self._devices.pier_record(pier))

    def why_not(self, pier: str) -> str | None:
        camera = self._devices.controller(pier, "camera")
        if camera is None:
            return "this Pier has no camera"
        if not getattr(camera, "is_connected", True):
            return "the camera is not connected"
        focuser = self._devices.controller(pier, "focuser")
        if focuser is None:
            return "this Pier has no focuser"
        if not getattr(focuser, "is_connected", True):
            return "the focuser is not connected"
        if self._runner.is_running(pier):
            return "a session is running on this Pier"
        if pier in self._services:
            return "autofocus is already running on this Pier"
        if self._busy(pier):
            return "a plate solve or polar alignment is using the camera on this Pier"
        return None

    def running(self, pier: str) -> bool:
        return pier in self._services

    def _publish(self, pier: str) -> None:
        self._state.publish(pier, STATE_KEY, {**self._picture[pier], "points": list(self._picture[pier]["points"])})

    async def run(self, pier: str, *, progress: Callable[[str], None]) -> dict[str, Any]:
        reason = self.why_not(pier)
        if reason:
            raise Refused(reason)
        picture = _blank()
        picture.update(running=True, phase="sweeping", message="Starting…")
        self._picture[pier] = picture
        self._services[pier] = None                          # claimed, so a second request is refused at once
        self._publish(pier)
        bus = self._bus or get_bus()
        key = self._key_of(pier)

        def mine(event: Any) -> bool:
            return event.payload.get("pier_key") == key

        def on_started(event: Any) -> None:
            if not mine(event):
                return
            picture.update(steps=int(event.payload.get("num_points", 0)), step=0, points=[], phase="sweeping",
                           message=f"Sweeping {event.payload.get('num_points', 0)} points…")
            self._publish(pier)
            progress(picture["message"])

        def on_frame(event: Any) -> None:
            if not mine(event):
                return
            if event.payload.get("confirm"):
                picture.update(phase="confirming", message="Confirming at the best position…")
            else:
                picture["points"].append([event.payload.get("position"), round(float(event.payload.get("hfr", 0.0)), 3)])
                picture.update(step=len(picture["points"]),
                               message=f"Point {len(picture['points'])} of {picture['steps']}")
            self._publish(pier)
            progress(picture["message"])

        def on_complete(event: Any) -> None:
            if not mine(event):
                return
            result = event.payload.get("result")
            picture["success"] = bool(getattr(result, "success", False))

        bus.subscribe(FocusStartedEvent, on_started)
        bus.subscribe(FocusFrameEvent, on_frame)
        bus.subscribe(FocusCompleteEvent, on_complete)
        result = None
        try:
            service = await self._factory(pier)
            self._services[pier] = service
            result = await service.run()
            picture.update(success=bool(result.success), best_position=result.best_position if result.success else None,
                           failure_reason="" if result.success else result.failure_reason,
                           cancelled=(not result.success) and result.failure_reason == "Cancelled")
            samples = getattr(result, "sample_points", None)
            if samples:
                picture["points"] = [[p, round(float(h), 3)] for p, h in samples]
            return {"success": picture["success"], "best_position": picture["best_position"],
                    "cancelled": picture["cancelled"], "failure_reason": picture["failure_reason"],
                    "points": list(picture["points"])}
        except Exception as exc:
            picture.update(success=False, failure_reason=str(exc) or type(exc).__name__)
            raise
        finally:
            bus.unsubscribe(FocusStartedEvent, on_started)
            bus.unsubscribe(FocusFrameEvent, on_frame)
            bus.unsubscribe(FocusCompleteEvent, on_complete)
            self._services.pop(pier, None)
            picture.update(running=False, phase="finished",
                           message="Cancelled" if picture["cancelled"] else (
                               f"Best focus at {picture['best_position']}" if picture["success"] else picture["failure_reason"]))
            self._publish(pier)

    def cancel(self, pier: str) -> bool:
        service = self._services.get(pier)
        if service is None:
            return False
        service.cancel()
        return True

    def status(self, pier: str) -> dict[str, Any]:
        picture = self._picture.get(pier) or _blank()
        return {**picture, "points": list(picture["points"]), "running": pier in self._services,
                "why_not": self.why_not(pier) or ""}


__all__ = ["EngineAutofocus", "build_service"]
