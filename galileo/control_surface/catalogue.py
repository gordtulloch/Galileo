# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Control Surface catalogue for devices, focus and safety (CSURF-110, CSURF-150, CSURF-220, CSURF-300).

Each operation calls the same controller method the desktop screen calls, so a remote client gets the same
limits and interlocks; a refusal by the device layer (a parked mount, an obstructed slew, a mount limit) is
returned word for word. Nothing here edits a stored definition of the observatory. Operations are available
only where the Pier has that device connected, and say why not otherwise (CSURF-030).

``register_device_operations(registry, access)`` takes a :class:`DeviceAccess` — the one place that knows how
to find a Pier's controllers — so this module imports no adapter, screen or global.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from galileo.autofocus import ManualFocus
from galileo.control_surface.emergency import register_emergency
from galileo.control_surface.holds import HoldManager
from galileo.control_surface.registry import OperationContext, OperationSpec, Refused, Registry, Unreachable
from galileo.control_surface.schema import Arg
from galileo.exceptions import DeviceConnectionError, DeviceError, DeviceTimeoutError, SafetyError

logger = logging.getLogger(__name__)


class DeviceAccess(Protocol):
    """How the catalogue reaches a Pier's devices."""

    def controller(self, pier: str, category: str) -> Any | None:
        """The controller for *category* (``mount``, ``camera``, ``filter_wheel``, ``focuser``, ``rotator``,
        ``dome``, ``flat_panel``, ``weather``, ``safety``) on *pier*, or ``None`` if there is none."""

    def manual_focus(self, pier: str) -> ManualFocus | None:
        """The Pier's manual-focus function, or ``None`` without a focuser."""

    def stop_session(self, pier: str) -> Any:
        """Stop the Pier's running session, if any (used by the emergency stop)."""


def _device(handler: Callable[..., Awaitable[Any] | Any]) -> Callable[..., Awaitable[Any]]:
    """Run a controller call and turn the device layer's own refusals into typed outcomes."""
    async def run(ctx: OperationContext, args: dict[str, Any]) -> Any:
        try:
            result = handler(ctx, args)
            if hasattr(result, "__await__"):
                result = await result
            return result
        except (DeviceConnectionError, DeviceTimeoutError) as exc:
            raise Unreachable(str(exc) or "the device did not answer") from exc
        except (DeviceError, SafetyError) as exc:          # parked, obstructed, over a limit, unsafe ...
            raise Refused(str(exc)) from exc
    return run


def register_device_operations(registry: Registry, access: DeviceAccess, holds: HoldManager | None = None) -> None:
    def available(category: str, label: str) -> Callable[[str], str | None]:
        def check(pier: str) -> str | None:
            c = access.controller(pier, category)
            if c is None:
                return f"this Pier has no {label}"
            if hasattr(c, "is_connected") and not c.is_connected:
                return f"the {label} is not connected"
            return None
        return check

    def ctrl(ctx: OperationContext, category: str) -> Any:
        return access.controller(ctx.pier, category)

    def add(name: str, category: str, label: str, handler: Callable[..., Any], args: tuple[Arg, ...] = (), *,
            cls: str = "operate", lease: bool = True, long_running: bool = False, description: str = "") -> None:
        registry.register(
            OperationSpec(name, cls, args, needs_lease=lease and cls not in ("read", "emergency"),
                          long_running=long_running, available=available(category, label), description=description),
            _device(handler))

    # -- mount (CSURF-110) ---------------------------------------------------------------------------
    add("mount.status", "mount", "mount", lambda c, a: ctrl(c, "mount").get_status(), cls="read",
        description="Position, tracking, slewing and pier side")
    add("mount.slew", "mount", "mount",
        lambda c, a: ctrl(c, "mount").slew_to_coordinates(a["ra_deg"], a["dec_deg"]),
        (Arg("ra_deg", "float", minimum=0, maximum=360, unit="deg"),
         Arg("dec_deg", "float", minimum=-90, maximum=90, unit="deg")), long_running=True,
        description="Slew to coordinates, subject to the mount's limits and horizon")
    add("mount.sync", "mount", "mount", lambda c, a: ctrl(c, "mount").sync_to_coordinates(a["ra_deg"], a["dec_deg"]),
        (Arg("ra_deg", "float", minimum=0, maximum=360, unit="deg"),
         Arg("dec_deg", "float", minimum=-90, maximum=90, unit="deg")))
    add("mount.track", "mount", "mount", lambda c, a: ctrl(c, "mount").set_tracking(a["enabled"]),
        (Arg("enabled", "bool"),))
    add("mount.abort_slew", "mount", "mount", lambda c, a: ctrl(c, "mount").abort_slew())
    add("mount.park", "mount", "mount", lambda c, a: ctrl(c, "mount").park(), cls="confirm",
        description="Park the mount (asks for a second confirmation)")
    add("mount.unpark", "mount", "mount", lambda c, a: ctrl(c, "mount").unpark())

    # -- camera ----------------------------------------------------------------------------------------------
    add("camera.status", "camera", "camera",
        lambda c, a: {"temperature": ctrl(c, "camera").get_temperature(), "cooler_power": ctrl(c, "camera").get_cooler_power()},
        cls="read")
    add("camera.expose", "camera", "camera",
        lambda c, a: ctrl(c, "camera").start_exposure(a["seconds"], a["gain"], a["offset"], a["binning"], a["frame_type"]),
        (Arg("seconds", "float", minimum=0.001, maximum=3600, unit="s"),
         Arg("gain", "int", required=False, default=0, minimum=0, maximum=10000),
         Arg("offset", "int", required=False, default=0, minimum=0, maximum=10000),
         Arg("binning", "int", required=False, default=1, minimum=1, maximum=4),
         Arg("frame_type", "enum", required=False, default="Light", choices=("Light", "Dark", "Flat", "Bias"))),
        long_running=True)
    add("camera.abort", "camera", "camera", lambda c, a: ctrl(c, "camera").abort_exposure())
    add("camera.set_temperature", "camera", "camera", lambda c, a: ctrl(c, "camera").set_target_temperature(a["celsius"]),
        (Arg("celsius", "float", minimum=-60, maximum=40, unit="°C"),))

    # -- the rest of the train ------------------------------------------------------------------------------
    add("filter.names", "filter_wheel", "filter wheel", lambda c, a: ctrl(c, "filter_wheel").get_filter_names(), cls="read")
    add("filter.select", "filter_wheel", "filter wheel", lambda c, a: ctrl(c, "filter_wheel").move_to_filter(a["name"]),
        (Arg("name", "str"),))
    add("rotator.status", "rotator", "rotator", lambda c, a: ctrl(c, "rotator").get_status(), cls="read")
    add("rotator.move", "rotator", "rotator", lambda c, a: ctrl(c, "rotator").move_to_angle(a["angle"]),
        (Arg("angle", "float", minimum=0, maximum=360, unit="deg"),))
    add("dome.status", "dome", "dome", lambda c, a: ctrl(c, "dome").get_status(), cls="read")
    add("dome.open", "dome", "dome", lambda c, a: ctrl(c, "dome").open_shutter())
    add("dome.close", "dome", "dome", lambda c, a: ctrl(c, "dome").close_shutter())
    add("dome.slew", "dome", "dome", lambda c, a: ctrl(c, "dome").slew_to_azimuth(a["azimuth"]),
        (Arg("azimuth", "float", minimum=0, maximum=360, unit="deg"),))
    add("dome.abort", "dome", "dome", lambda c, a: ctrl(c, "dome").abort_slew())
    add("flatpanel.status", "flat_panel", "flat panel", lambda c, a: ctrl(c, "flat_panel").get_status(), cls="read")
    add("flatpanel.light", "flat_panel", "flat panel",
        lambda c, a: ctrl(c, "flat_panel").light_on() if a["on"] else ctrl(c, "flat_panel").light_off(), (Arg("on", "bool"),))
    add("flatpanel.brightness", "flat_panel", "flat panel", lambda c, a: ctrl(c, "flat_panel").set_brightness(a["level"]),
        (Arg("level", "int", minimum=0, maximum=65535),))
    add("weather.readings", "weather", "weather station", lambda c, a: ctrl(c, "weather").get_readings(), cls="read")

    # -- switches and the Imaging screen's own controls (EQP-SW-150) -----------------------------------------
    def switches(ctx: OperationContext) -> Any:
        from galileo.core.devices import SwitchController
        adapter = ctrl(ctx, "switch")
        return adapter if isinstance(adapter, SwitchController) else SwitchController(adapter)

    async def switch_panel(ctx: OperationContext, args: dict[str, Any]) -> Any:
        from galileo.imaging_switches import can_show, describe, shown_ids
        panel = await switches(ctx).get_panel()
        shown = set(shown_ids(ctx.pier))
        return {
            "groups": [{"name": g.name, "channels": [describe(c, c.id in shown if can_show(c) else None)
                                                     for c in g.channels]} for g in panel.groups],
            "sensors": [{"id": s.id, "label": s.label, "value": s.value, "unit": s.unit} for s in panel.sensors],
            "message": panel.message,
        }

    async def switch_set(ctx: OperationContext, args: dict[str, Any]) -> Any:
        from galileo.imaging_switches import can_show
        on, duty = args.get("on"), args.get("duty")
        if on is None and duty is None:
            raise Refused("give on (true/false), duty (0-100) or both")
        controller = switches(ctx)
        channel = (await controller.get_panel()).channel(args["channel"])
        if channel is None or not can_show(channel):
            raise Refused(f"this switch device has no on/off channel {args['channel']!r}")
        if not (channel.writable and channel.available):
            raise Refused(f"{channel.label} cannot be set right now")
        if duty is not None and channel.kind != "dew":
            raise Refused(f"{channel.label} has no percentage; only a dew heater does")
        await controller.set_channel(channel.id, on=on, duty=None if duty is None else float(duty))
        return {"channel": channel.id}

    async def imaging_controls(ctx: OperationContext, args: dict[str, Any]) -> Any:
        """What the Imaging screen offers besides the camera: the switch channels ticked Show on imaging on
        Equipment > Switches, and the flat panel, so a small screen can put both beside the exposure."""
        from galileo.imaging_switches import describe, shown_channels
        out: dict[str, Any] = {"switches": [], "flat_panel": None}
        if available("switch", "switch device")(ctx.pier) is None:
            try:
                out["switches"] = [describe(c, True) for c in shown_channels(await switches(ctx).get_panel(), ctx.pier)]
            except (DeviceConnectionError, DeviceTimeoutError):
                out["switches_error"] = "the switch device did not answer"
        if available("flat_panel", "flat panel")(ctx.pier) is None:
            out["flat_panel"] = ctrl(ctx, "flat_panel").get_status()
        return out

    registry.register(OperationSpec("switch.panel", "read", (), needs_lease=False, available=available("switch", "switch device"),
                                    description="Every channel of the switch device and its readings, with which are shown on Imaging"),
                      _device(switch_panel))
    registry.register(OperationSpec(
        "switch.set", "operate",
        (Arg("channel", "str"), Arg("on", "bool", required=False),
         Arg("duty", "float", required=False, minimum=0, maximum=100, unit="%")),
        needs_lease=True, available=available("switch", "switch device"),
        description="Switch a channel on or off and, for a dew heater, set its power in percent"), _device(switch_set))
    registry.register(OperationSpec("imaging.controls", "read", (), needs_lease=False,
                                    description="The switches ticked Show on imaging, and the flat panel's state, for the Imaging screen"),
                      _device(imaging_controls))

    # -- safety (CSURF-220): read-only; the safety service alone decides when it is safe again ---------------
    add("safety.status", "safety", "safety monitor",
        lambda c, a: {"safe": ctrl(c, "safety").is_safe, "explanation": ctrl(c, "safety").explanation,
                      "last_abort": getattr(ctrl(c, "safety"), "last_abort_trigger", "")}, cls="read")

    # -- focus (CSURF-150, FOC-120): the focus module's own ManualFocus, never a generic focuser move --------
    def focus_available(pier: str) -> str | None:
        return None if access.manual_focus(pier) is not None else "this Pier has no focuser"

    def mf(ctx: OperationContext) -> ManualFocus:
        found = access.manual_focus(ctx.pier)
        if found is None:
            raise Refused("this Pier has no focuser")
        return found

    def add_focus(name: str, handler: Callable[..., Any], args: tuple[Arg, ...] = (), cls: str = "operate",
                  lease: bool = True) -> None:
        registry.register(OperationSpec(name, cls, args, needs_lease=lease and cls != "read", available=focus_available),
                          _device(handler))

    add_focus("focus.status", lambda c, a: {"position": mf(c).position(), "temperature": mf(c).temperature()}, cls="read")
    add_focus("focus.move_to", lambda c, a: mf(c).move_to(a["position"]), (Arg("position", "int", minimum=0),))
    add_focus("focus.move_by", lambda c, a: mf(c).move_by(a["steps"]), (Arg("steps", "int", minimum=-100000, maximum=100000),))
    add_focus("focus.halt", lambda c, a: mf(c).halt())
    if holds is not None:
        add_focus("focus.hold_start", lambda c, a: mf(c).start_hold(holds, a["direction"], c.principal, origin="control_surface"),
                  (Arg("direction", "int", minimum=-1, maximum=1),))
        add_focus("focus.hold_beat", lambda c, a: holds.beat(a["hold_id"], c.principal), (Arg("hold_id", "str"),), lease=False)
        add_focus("focus.hold_stop", lambda c, a: holds.stop(a["hold_id"], c.principal, "stopped"),
                  (Arg("hold_id", "str"),), lease=False)

    # -- the three emergency operations (CSURF-300) --------------------------------------------------------------
    async def stop_everything(pier: str) -> None:
        for category, call in (("mount", "abort_slew"), ("camera", "abort_exposure"), ("dome", "abort_slew")):
            c = access.controller(pier, category)
            if c is not None:
                try:
                    await getattr(c, call)()
                except Exception:
                    logger.exception("Emergency stop: %s.%s failed", category, call)
        mf_ = access.manual_focus(pier)
        if mf_ is not None:
            try:
                await mf_.halt()
            except Exception:
                logger.exception("Emergency stop: focuser halt failed")
        result = access.stop_session(pier)
        if hasattr(result, "__await__"):
            await result

    async def park(pier: str) -> None:
        c = access.controller(pier, "mount")
        if c is None:
            raise Refused("this Pier has no mount")
        await c.park()

    async def close_dome(pier: str) -> None:
        c = access.controller(pier, "dome")
        if c is None:
            raise Refused("this Pier has no dome")
        await c.close_shutter()

    register_emergency(registry, stop_everything=stop_everything, park=park, close_dome=close_dome, holds=holds)


__all__ = ["DeviceAccess", "register_device_operations"]
