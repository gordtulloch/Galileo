# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Starting a saved session template on the engine (CSURF-180): the engine's side of Run.

A template is a named block list in the shared database (``SES-180``). ``EngineSessions.start`` loads it, puts a
chosen target in place of the template's placeholder Target (``SES-190``), builds the Pier's ``SessionContext``
from the device service with the same assembly the desktop uses (``galileo.session_context``), checks it with
``preflight`` and hands it to the runner. Nothing here imports Qt.

What differs from a desktop run: the FITS header context holds the optical tube, camera, site, pointing and focus
position but not the Imaging page's current target, and there is no Guider service yet, so a template that guides
reports "No guider connected" at pre-flight.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from galileo.control_surface.sessions import SessionRefused
from galileo.session_context import assemble_context, build_notify_service
from galileo.session_exec import SessionExecutor, preflight

logger = logging.getLogger(__name__)


_ARBITERS: dict[str, Any] = {}


def _arbiter(observatory_name: str) -> Any:
    """One ``ResourceArbiter`` per Observatory, shared by every Pier's run (OBS-100)."""
    from galileo.observatory import ResourceArbiter
    if observatory_name not in _ARBITERS:
        _ARBITERS[observatory_name] = ResourceArbiter()
    return _ARBITERS[observatory_name]


def template_names() -> list[str]:
    from galileo.library.models.session_template import SessionTemplateRecord
    return [r.name for r in SessionTemplateRecord.select().order_by(SessionTemplateRecord.name)]


def load_template(name: str, target: dict[str, Any] | None) -> list:
    """The template's blocks, its placeholder Target replaced by *target* (``name``, ``ra_deg``, ``dec_deg``)."""
    from galileo.library.models.session_template import SessionTemplateRecord
    from galileo.ui.session_blocks import TargetBlock, block_from_dict
    record = SessionTemplateRecord.get_or_none(SessionTemplateRecord.name == name)
    if record is None:
        raise SessionRefused(f"There is no session template named {name!r}.")
    blocks = [block_from_dict(d) for d in json.loads(record.blocks_json)]
    for i, block in enumerate(blocks):
        if isinstance(block, TargetBlock) and block.is_placeholder_target:
            if not target:
                raise SessionRefused(f"{name!r} needs a target: give a name, ra_deg and dec_deg.")
            blocks[i] = replace(block, name=str(target["name"]), ra_deg=float(target["ra_deg"]),
                                dec_deg=float(target["dec_deg"]), is_placeholder_target=False)
    return blocks


async def frame_context(devices: Any, pier: str, record: Any, camera_slot: str) -> dict:
    """What the FITS header learns about the rig (IMG-150), as far as the engine can tell. Nothing here may stop a run."""
    context: dict = {}
    try:
        from galileo.observatory import get_device_config, list_optical_tubes
        tubes = list_optical_tubes(record)
        if tubes:
            tube = tubes[0]
            context.update(telescope=tube.name, focal_length_mm=tube.focal_length_mm or None,
                           aperture_mm=tube.aperture_mm or None)
        cfg = get_device_config(record, "camera", slot=camera_slot)
        if cfg is not None:
            context.update(instrument=cfg.device_name or cfg.sensor_name, pixel_size_x_um=cfg.pixel_size_um,
                           pixel_size_y_um=cfg.pixel_size_um, bayer_pattern=cfg.bayer_pattern)
        observatory = record.observatory
        context.update(site=observatory.name, observer=observatory.owner,
                       site_lat_deg=observatory.latitude, site_long_deg=observatory.longitude)
    except Exception:
        logger.exception("Pier %s: could not gather the rig for the FITS header", pier)
    mount = devices.controller(pier, "mount")
    if mount is not None:
        try:
            status = await mount.get_status() or {}
            ra_hours, dec = status.get("right_ascension"), status.get("declination")
            if ra_hours is not None and dec is not None:
                from galileo.platesolve import mount_frame_to_j2000
                context["ra_deg"], context["dec_deg"] = mount_frame_to_j2000(
                    ra_hours * 15.0, dec, status.get("equatorial_system"))
            context["pier_side"] = status.get("side_of_pier")
        except Exception:
            logger.warning("Pier %s: could not read the mount's position for the FITS header", pier, exc_info=True)
    position = getattr(devices.controller(pier, "focuser"), "position", None)
    if isinstance(position, int) and position > 0:
        context["focus_position"] = position
    return {k: v for k, v in context.items() if v not in (None, "")}


async def build_context(devices: Any, pier: str, camera_slot: str = "primary") -> Any:
    from galileo.current_object import pier_key
    record = devices.pier_record(pier)
    if record is None:
        raise SessionRefused(f"There is no Pier {pier}.")
    observatory = None
    location = None
    try:
        observatory = record.observatory
        if observatory.latitude is not None and observatory.longitude is not None:
            from galileo.planning.visibility import ObservingLocation
            location = ObservingLocation(name=observatory.name, latitude=observatory.latitude,
                                         longitude=observatory.longitude,
                                         elevation_m=getattr(observatory, "elevation_m", None) or 0.0)
    except Exception:
        logger.exception("Pier %s: could not read its Observatory", pier)
    cameras = devices.controllers(pier, "camera")
    return assemble_context(
        pier=record, key=pier_key(record), camera_slot=camera_slot,
        camera=cameras.get(camera_slot) or devices.controller(pier, "camera"),
        mount=devices.controller(pier, "mount"), filter_wheel=devices.controller(pier, "filter_wheel"),
        focuser=devices.controller(pier, "focuser"), rotator=devices.controller(pier, "rotator"),
        dome=devices.controller(pier, "dome"), dome_service=None,
        guider=None,                      # the guider service is not built in the engine yet
        flat_panel=devices.controller(pier, "flat_panel"),
        arbiter=_arbiter(getattr(observatory, "name", "") or ""), observatory=observatory,
        notify_service=build_notify_service(observatory), location=location,
        frame_context=await frame_context(devices, pier, record, camera_slot))


class EngineSessions:
    """``SessionAccess`` (``galileo.control_surface.sessions``) over the engine's runner and device service."""

    def __init__(self, devices: Any, runner: Any) -> None:
        self._devices, self._runner = devices, runner

    # -- reading and controlling a run (the runner's own view) -----------------------------------
    def progress(self, pier: str) -> dict[str, Any] | None:
        from galileo.control_surface.sessions import RunnerSessions
        return RunnerSessions(self._runner).progress(pier)

    def pause(self, pier: str) -> bool:
        return bool(self._runner.pause(pier))

    def resume(self, pier: str) -> bool:
        return bool(self._runner.resume(pier))

    def stop(self, pier: str) -> bool:
        return bool(self._runner.stop(pier))

    # -- templates and starting ------------------------------------------------------------------
    def templates(self) -> list[str]:
        return template_names()

    async def start(self, pier: str, template: str, target: dict[str, Any] | None = None,
                    camera_slot: str = "primary") -> None:
        """Start *template* on *pier*; raises ``SessionRefused`` saying why not."""
        from galileo.engine.runner import RunnerBusy
        if self._runner.is_running(pier):
            raise SessionRefused("A session is already running on this Pier.")
        blocks = load_template(template, target)
        if not blocks:
            raise SessionRefused("This session has no blocks to run.")
        context = await build_context(self._devices, pier, camera_slot)
        problems = preflight(blocks, context)
        if problems:
            raise SessionRefused(" ".join(problems))
        safety = self._devices.controller(pier, "safety")
        if safety is not None and getattr(safety, "is_connected", False) and not safety.is_safe:
            raise SessionRefused(f"Conditions are unsafe: {safety.explanation}.")
        try:
            self._runner.start(pier, template, SessionExecutor(context, name=template), blocks, manual=True)
        except RunnerBusy as exc:
            raise SessionRefused(str(exc)) from exc


__all__ = ["EngineSessions", "SessionRefused", "build_context", "frame_context", "load_template", "template_names"]
