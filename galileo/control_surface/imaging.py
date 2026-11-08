# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Control Surface catalogue for imaging (CSURF-120): take a frame or a series, stop, and read the current frame.

``imaging.capture`` is long-running: it answers at once with a correlation id, reports ``progress`` as each frame is
taken, and ends with one ``finished`` event. Whether a capture can start is part of availability, so a client is told
why not (no camera, a session running, a capture already under way) before anything moves. ``imaging.status`` returns
the series progress, the exposure under way, the live stack's size and the current frame's statistics and histogram as
plain data; the pictures themselves (the frame and the stack) are served by ``galileo.control_surface.frames``.

``register_imaging_operations(registry, access)`` takes an :class:`ImagingAccess` so this module imports no camera,
service or screen.
"""

from __future__ import annotations

from typing import Any, Protocol

from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry
from galileo.control_surface.schema import Arg


class ImagingAccess(Protocol):
    def why_not(self, pier: str) -> str | None:
        """Why a capture cannot start on *pier* now, or ``None``."""

    async def capture(self, pier: str, count: int, seconds: float, filter_name: str, frame_type: str,
                      gain: int, offset: int, camera_slot: str, progress: Any,
                      live_stack: bool = False) -> dict[str, Any]:
        """Take the series; calls ``progress(done, total)`` after each frame; returns a summary."""

    async def stop(self, pier: str) -> bool:
        """End the running series after aborting the frame in progress; ``False`` when none is running."""

    def status(self, pier: str) -> dict[str, Any]: ...


def register_imaging_operations(registry: Registry, access: ImagingAccess) -> None:
    def capture_available(pier: str) -> str | None:
        return access.why_not(pier)

    async def capture(ctx: OperationContext, args: dict[str, Any]) -> Any:
        total = int(args["count"])

        def progress(done: int, count: int) -> None:
            ctx.progress(done / count if count else None, f"frame {done} of {count}")

        return await access.capture(
            ctx.pier, total, float(args["seconds"]), args.get("filter") or "", args["frame_type"],
            int(args["gain"]), int(args["offset"]), args.get("camera_slot") or "primary", progress,
            bool(args.get("live_stack", False)))

    async def stop(ctx: OperationContext, args: dict[str, Any]) -> Any:
        if not await access.stop(ctx.pier):
            raise Refused("no capture is running on this Pier")
        return {"stopping": True}

    async def status(ctx: OperationContext, args: dict[str, Any]) -> Any:
        return access.status(ctx.pier)

    registry.register(OperationSpec(
        "imaging.capture", "operate",
        (Arg("seconds", "float", minimum=0.001, maximum=3600, unit="s"),
         Arg("count", "int", required=False, default=1, minimum=1, maximum=1000),
         Arg("filter", "str", required=False),
         Arg("frame_type", "enum", required=False, default="Light", choices=("Light", "Dark", "Flat", "Bias")),
         Arg("gain", "int", required=False, default=0, minimum=0, maximum=10000),
         Arg("offset", "int", required=False, default=0, minimum=0, maximum=10000),
         Arg("camera_slot", "str", required=False),
         Arg("live_stack", "bool", required=False, default=False)),
        needs_lease=True, long_running=True, available=capture_available,
        description="Take one frame or a series; each frame is saved to the Library. With live_stack, a series of "
                    "three or more frames is also registered and averaged into a stack, shown as it builds"), capture)
    registry.register(OperationSpec("imaging.stop", "operate", (), needs_lease=True,
                                    description="Stop the running capture after aborting the frame in progress"), stop)
    registry.register(OperationSpec("imaging.status", "read", (), needs_lease=False,
                                    description="Capture progress and the current frame's statistics and histogram"),
                      status)


__all__ = ["ImagingAccess", "register_imaging_operations"]
