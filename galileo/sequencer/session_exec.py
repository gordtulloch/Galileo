# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Session execution engine (SES-030, SES-040, SES-050, SES-080, SES-170, SES-350).

``SessionExecutor`` runs the ordered, indent-nested action blocks of a Sessions-screen
session (``galileo.ui.sessions``) against real devices. It is the one execution path for
both the session card's Run control and a session fired by the scheduler
(``ObservatoryScheduler.run_job``).

Domain core: no Qt, no direct adapter imports. Every device and service arrives through a
``SessionContext`` — the UI layer fills it from the connected Pier's adapters and supplies
factories for the services that need UI-side wiring (``ImagingService`` with its Library
registrar, the plate solver with its configured executable, ...). Blocks are dispatched by
class name rather than imported, since the block classes live in the UI module; a block
type with no handler here but an async ``execute(context)`` of its own (a plugin block,
``NotificationBlock``) is run through that.

Error policy (SES-080): a failure in a block that only affects *this* block's product (a
bad frame, a failed autofocus, a missing guider) is logged and the session carries on. A
failure in a block the rest of the session depends on (slew to target, plate solve, dome
open, park, meridian flip — see ``_FATAL_BLOCKS``) ends the run, since carrying on would
image the wrong sky or move equipment into an unsafe state.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RunState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


class SessionBlockError(Exception):
    """A block could not do its job. ``fatal`` ends the run; otherwise it is logged and skipped."""

    def __init__(self, message: str, fatal: bool = True) -> None:
        super().__init__(message)
        self.fatal = fatal


class SessionAbort(SessionBlockError):
    """A failure that ends the whole run; propagates untouched through enclosing loops."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fatal=True)


class _Stopped(Exception):
    """Raised inside the run when the user stopped it; never escapes ``run``."""


# Blocks whose failure ends the run (see module docstring).
_FATAL_BLOCKS = frozenset({
    "TargetBlock", "PlateSolveBlock", "MeridianFlipBlock", "ParkMountBlock", "UnparkMountBlock",
    "DomeOpenBlock", "ForObjectBlock",
})

# Blocks that still run when the safety monitor reports unsafe conditions — they put equipment
# into a safe state, so skipping them would be the dangerous choice.
_SHUTDOWN_BLOCKS = frozenset({
    "ParkMountBlock", "DomeCloseBlock", "GuideStopBlock", "WarmCameraBlock", "NotificationBlock",
})

_LOOP_BLOCKS = frozenset({"ForFilterBlock", "ForObjectBlock"})

# Device each block type needs connected, for the pre-flight check.
_BLOCK_NEEDS: dict[str, tuple[str, ...]] = {
    "TargetBlock": ("mount",),
    "ImageBlock": ("camera",),
    "FilterChangeBlock": ("filter_wheel",),
    "CoolCameraBlock": ("camera",),
    "WarmCameraBlock": ("camera",),
    "AutofocusBlock": ("camera", "focuser"),
    "PlateSolveBlock": ("camera", "mount"),
    "GuideStartBlock": ("guider",),
    "GuideStopBlock": ("guider",),
    "DitherBlock": ("guider",),
    "FlatCaptureBlock": ("camera",),
    "DarkCaptureBlock": ("camera",),
    "ParkMountBlock": ("mount",),
    "UnparkMountBlock": ("mount",),
    "MeridianFlipBlock": ("mount",),
    "DomeOpenBlock": ("dome",),
    "DomeCloseBlock": ("dome",),
    "DomeSyncBlock": ("dome", "mount"),
    "ForObjectBlock": ("mount",),
}

_DEVICE_LABELS = {
    "camera": "camera", "mount": "mount", "filter_wheel": "filter wheel", "focuser": "focuser",
    "guider": "PHD2 guider", "dome": "dome",
}

COOL_TOLERANCE_C = 1.5
COOL_TIMEOUT_S = 15 * 60.0
_POLL_S = 0.2
MAX_CONSECUTIVE_FRAME_FAILURES = 3


# ---------------------------------------------------------------------------
# Context, progress, result
# ---------------------------------------------------------------------------

@dataclass
class SessionContext:
    """Everything a running session can touch. Any device may be ``None`` (not connected);
    a block that needs one reports it rather than the run crashing."""
    pier_name: str = ""
    camera: Any = None
    mount: Any = None
    filter_wheel: Any = None
    focuser: Any = None
    rotator: Any = None
    dome: Any = None
    guider: Any = None
    flat_panel: Any = None
    notify_service: Any = None
    observatory: Any = None
    location: Any = None
    max_well_depth: int | None = None
    # True while conditions are safe; ``None`` means no safety monitor is configured.
    is_safe: Callable[[], bool] | None = None
    # Factories for services that need UI-side wiring. Each returns a ready-to-use service.
    make_imaging: Callable[[], Any] | None = None           # -> ImagingService
    make_autofocus: Callable[[], Any] | None = None          # -> AutofocusService
    make_solve_workflow: Callable[[], Any] | None = None     # -> SolveWorkflow
    make_calibration: Callable[[], Any] | None = None        # -> CalibrationService
    # Applies the saved focus offset between two filters (FOC-060), if the Pier has any.
    apply_filter_focus_offset: Callable[[str | None, str], Awaitable[None]] | None = None


@dataclass
class SessionProgress:
    """A snapshot for the UI (SES-050, SES-350)."""
    state: RunState = RunState.IDLE
    block: Any = None            # the block executing now, if any
    block_index: int = 0         # 1-based position of that block in the session
    block_total: int = 0
    frames_done: int = 0
    frames_total: int = 0
    message: str = ""


@dataclass
class SessionRunResult:
    state: RunState
    frames_captured: int = 0
    log: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_utc: str = ""
    ended_utc: str = ""

    @property
    def succeeded(self) -> bool:
        return self.state == RunState.COMPLETED


# ---------------------------------------------------------------------------
# Block tree (indent -> nesting)
# ---------------------------------------------------------------------------

@dataclass
class _Node:
    block: Any
    index: int                       # 1-based position in the flat session
    children: list[_Node] = field(default_factory=list)


def build_tree(blocks: list) -> list[_Node]:
    """Turn the flat, indent-annotated block list into a tree: a block indented deeper than
    the block above it is that block's child (the Sessions model only allows this under a loop)."""
    roots: list[_Node] = []
    stack: list[tuple[int, _Node]] = []
    for i, block in enumerate(blocks, start=1):
        node = _Node(block, i)
        indent = getattr(block, "indent", 0)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        (stack[-1][1].children if stack else roots).append(node)
        stack.append((indent, node))
    return roots


def _loop_passes(block: Any) -> int:
    name = type(block).__name__
    if name == "ForFilterBlock":
        return max(1, len(block.filters))
    if name == "ForObjectBlock":
        return len(block.objects)
    return 1


def estimate_frames(nodes: list[_Node]) -> int:
    """How many exposures running *nodes* will take, for the progress display."""
    total = 0
    for node in nodes:
        block = node.block
        name = type(block).__name__
        if name == "ImageBlock":
            panes = len(block.mosaic.panels) if getattr(block, "has_mosaic", False) else 1
            total += max(1, int(block.count)) * panes
        elif name == "DarkCaptureBlock":
            total += len(block.exposures)
        total += estimate_frames(node.children) * _loop_passes(block) if name in _LOOP_BLOCKS else 0
    return total


def validate_blocks(blocks: list) -> list[str]:
    """Run-time ordering check (SES-170): problems that make the session invalid, as messages."""
    problems: list[str] = []
    seen_target = False
    for i, block in enumerate(blocks, start=1):
        name = type(block).__name__
        if name in ("TargetBlock", "ForObjectBlock"):
            seen_target = True
            if name == "TargetBlock" and getattr(block, "is_placeholder_target", False):
                problems.append(f"Block {i} (Target) is a template placeholder — choose a real target.")
        elif name == "PlateSolveBlock" and not seen_target:
            problems.append(f"Block {i} (Plate Solve) needs a Target block before it.")
        elif name == "ForFilterBlock" and not block.filters:
            problems.append(f"Block {i} (FOR Filter) has no filters listed.")
        elif name == "ForObjectBlock" and not block.objects:
            problems.append(f"Block {i} (FOR Object) has no objects listed.")
    return problems


def preflight(blocks: list, context: SessionContext) -> list[str]:
    """Everything wrong with running *blocks* against *context*, as user-readable messages:
    ordering problems plus equipment that a block needs but isn't connected. Empty = good to go."""
    problems = validate_blocks(blocks)
    missing: dict[str, set[str]] = {}
    for block in blocks:
        name = type(block).__name__
        for device in _BLOCK_NEEDS.get(name, ()):
            if getattr(context, device, None) is None:
                missing.setdefault(device, set()).add(getattr(block, "label", name))
    for device, labels in missing.items():
        problems.append(f"No {_DEVICE_LABELS.get(device, device)} connected (needed by: {', '.join(sorted(labels))}).")
    return problems


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class SessionExecutor:
    """Runs one session's blocks. Control methods (``stop``, ``pause``, ``resume``) are safe to
    call from any thread; ``run`` is a coroutine on whichever loop the caller provides."""

    def __init__(
        self,
        context: SessionContext,
        on_progress: Callable[[SessionProgress], None] | None = None,
        name: str = "",
    ) -> None:
        self.context = context
        self.name = name
        self._on_progress = on_progress
        self.state = RunState.IDLE
        self.log: list[str] = []
        self.errors: list[str] = []
        self.frames_captured = 0
        self._frames_total = 0
        self._block_total = 0
        self._current_block: Any = None
        self._current_index = 0
        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._active_services: list[Any] = []   # whatever is mid-run and can be asked to stop
        # Run-scoped state the blocks share.
        self.target: tuple[str, float, float] | None = None   # (name, ra_deg, dec_deg), J2000
        self.current_filter: str | None = None
        self._unsafe_logged = False

    def set_progress_callback(self, callback: Callable[[SessionProgress], None] | None) -> None:
        """Where progress snapshots go; called on whichever thread is running the session."""
        self._on_progress = callback

    # --- Control ------------------------------------------------------------

    def stop(self) -> None:
        """End the run: ask whatever is in progress to stop, abort the camera and mount, and
        have ``run`` return a ``STOPPED`` result. Safe from any thread."""
        if self._stop.is_set():
            return
        self._stop.set()
        self._resume.set()
        for service in list(self._active_services):
            for method in ("request_stop", "cancel", "stop"):
                fn = getattr(service, method, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        logger.debug("Could not ask %r to stop", service, exc_info=True)
                    break
        loop = self._loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._abort_hardware(), loop)

    def pause(self) -> None:
        """Hold before the next block or frame (a frame already exposing finishes)."""
        if self.state == RunState.RUNNING:
            self._resume.clear()
            self._set_state(RunState.PAUSED, "Paused — will hold before the next block or frame.")

    def resume(self) -> None:
        if self.state == RunState.PAUSED:
            self._set_state(RunState.RUNNING, "Resumed.")
            self._resume.set()

    @property
    def is_stopping(self) -> bool:
        return self._stop.is_set()

    async def _abort_hardware(self) -> None:
        ctx = self.context
        for device, method in ((ctx.camera, "abort_exposure"), (ctx.mount, "abort_slew")):
            if device is None:
                continue
            try:
                await getattr(device, method)()
            except Exception:
                logger.debug("%s failed while stopping a session", method, exc_info=True)

    # --- Reporting ----------------------------------------------------------

    def _emit(self, message: str = "") -> None:
        if self._on_progress is None:
            return
        try:
            self._on_progress(SessionProgress(
                state=self.state, block=self._current_block, block_index=self._current_index,
                block_total=self._block_total, frames_done=self.frames_captured,
                frames_total=self._frames_total, message=message,
            ))
        except Exception:
            logger.exception("Session progress callback raised")

    def _set_state(self, state: RunState, message: str = "") -> None:
        self.state = state
        if message:
            self._record(message)
        self._emit(message)

    def _record(self, message: str, error: bool = False) -> None:
        stamp = datetime.datetime.now(datetime.UTC).strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        self.log.append(line)
        if error:
            self.errors.append(message)
            logger.warning("Session %r: %s", self.name, message)
        else:
            logger.info("Session %r: %s", self.name, message)

    # --- Run ----------------------------------------------------------------

    async def run(self, blocks: list) -> SessionRunResult:
        """Execute *blocks* start to finish and report how it ended. Never raises for a block
        failure — that is the result's ``state``/``errors``."""
        self._loop = asyncio.get_running_loop()
        blocks = list(blocks)
        tree = build_tree(blocks)
        self._block_total = len(blocks)
        self._frames_total = estimate_frames(tree)
        started = datetime.datetime.now(datetime.UTC).isoformat()
        self._set_state(RunState.RUNNING, f"Session {self.name!r} started ({len(blocks)} block(s)).")
        try:
            problems = validate_blocks(blocks)
            if problems:
                raise SessionBlockError("; ".join(problems))
            await self._run_nodes(tree)
            if self._stop.is_set():
                raise _Stopped
            self._current_block = None
            self._set_state(RunState.COMPLETED, f"Session {self.name!r} completed — {self.frames_captured} frame(s) captured.")
        except _Stopped:
            self._current_block = None
            self._set_state(RunState.STOPPED, "Session stopped by the user.")
        except SessionBlockError as exc:
            self._set_state(RunState.ERROR)
            self._record(f"Session ended: {exc}", error=True)
            self._emit(str(exc))
        except asyncio.CancelledError:
            self._set_state(RunState.STOPPED, "Session cancelled.")
            raise
        except Exception as exc:
            logger.exception("Session %r failed unexpectedly", self.name)
            self._set_state(RunState.ERROR)
            self._record(f"Unexpected error: {exc}", error=True)
            self._emit(str(exc))
        await self._notify_outcome()
        return SessionRunResult(
            state=self.state, frames_captured=self.frames_captured, log=list(self.log),
            errors=list(self.errors), started_utc=started,
            ended_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        )

    async def _notify_outcome(self) -> None:
        """NOTIF-010: tell the Observatory's channels how the session ended."""
        service = self.context.notify_service
        if service is None or self.state == RunState.STOPPED:
            return
        try:
            from galileo.notify import NotificationEvent
            if self.state == RunState.COMPLETED:
                await service.emit(NotificationEvent.SEQUENCE_COMPLETE, f"Session {self.name!r} completed.")
            else:
                detail = self.errors[-1] if self.errors else "unknown error"
                await service.emit(NotificationEvent.SEQUENCE_ERROR, f"Session {self.name!r} failed: {detail}")
        except Exception:
            logger.exception("Could not send the session outcome notification")

    async def _checkpoint(self) -> None:
        """Between blocks and frames: honour Stop and Pause."""
        while not self._resume.is_set():  # noqa: ASYNC110 - a threading.Event, set from the UI thread
            await asyncio.sleep(_POLL_S)
        if self._stop.is_set():
            raise _Stopped

    async def _run_nodes(self, nodes: list[_Node]) -> None:
        for node in nodes:
            await self._checkpoint()
            await self._run_node(node)

    def _unsafe(self) -> bool:
        check = self.context.is_safe
        if check is None:
            return False
        try:
            return not check()
        except Exception:
            logger.exception("Safety check failed; treating conditions as unsafe")
            return True

    async def _run_node(self, node: _Node) -> None:
        block = node.block
        name = type(block).__name__
        label = getattr(block, "display_text", name)
        self._current_block, self._current_index = block, node.index
        if self._unsafe() and name not in _SHUTDOWN_BLOCKS:
            if not self._unsafe_logged:
                self._unsafe_logged = True
                self._record("Conditions are unsafe — skipping everything except shutdown blocks.", error=True)
                await self._notify_unsafe()
            self._emit(f"Skipped (unsafe): {label}")
            return
        self._record(f"Block {node.index}/{self._block_total}: {label}")
        self._emit(label)
        try:
            if name in _LOOP_BLOCKS:
                await self._run_loop(node)
            else:
                await self._dispatch(block)
        except (_Stopped, SessionAbort, asyncio.CancelledError):
            raise
        except Exception as exc:
            if self._stop.is_set():
                raise _Stopped from exc
            if name in _FATAL_BLOCKS and getattr(exc, "fatal", True):
                raise SessionAbort(f"{label} failed: {exc}") from exc
            self._record(f"{label} failed: {exc} — continuing.", error=True)

    async def _notify_unsafe(self) -> None:
        service = self.context.notify_service
        if service is None:
            return
        try:
            from galileo.notify import NotificationEvent
            await service.emit(NotificationEvent.SAFETY_ABORT, f"Session {self.name!r}: unsafe conditions.")
        except Exception:
            logger.exception("Could not send the unsafe-conditions notification")

    async def _dispatch(self, block: Any) -> None:
        handler = getattr(self, f"_do_{type(block).__name__}", None)
        if handler is not None:
            await handler(block)
            return
        execute = getattr(block, "execute", None)
        if execute is None:
            raise SessionBlockError(f"{type(block).__name__} has no execution behavior", fatal=False)
        await execute(self.context)

    # --- Helpers ------------------------------------------------------------

    def _need(self, device: str) -> Any:
        obj = getattr(self.context, device, None)
        if obj is None:
            raise SessionBlockError(f"no {_DEVICE_LABELS.get(device, device)} connected")
        return obj

    def _make(self, factory_name: str, what: str) -> Any:
        factory = getattr(self.context, factory_name, None)
        if factory is None:
            raise SessionBlockError(f"{what} is not available in this environment", fatal=False)
        return factory()

    async def _run_tracked(self, service: Any, coro: Awaitable) -> Any:
        """Await *coro* while *service* is registered as stoppable."""
        self._active_services.append(service)
        try:
            return await coro
        finally:
            self._active_services.remove(service)

    async def _slew(self, name: str, ra_deg: float, dec_deg: float) -> None:
        """Slew to a J2000 position and start tracking it at the right rate."""
        from galileo.tracking import resume_tracking, wait_for_slew
        mount = self._need("mount")
        send_ra, send_dec = ra_deg, dec_deg
        status = await mount.get_status() or {}
        if status.get("equatorial_system") != "J2000":
            from galileo.planning.star_atlas import julian_date, precess_from_j2000
            jd = julian_date(datetime.datetime.now(datetime.UTC).replace(tzinfo=None))
            send_ra, send_dec = (float(v) for v in precess_from_j2000(ra_deg, dec_deg, jd))
        await mount.slew_to_coordinates(send_ra, send_dec)
        if not await wait_for_slew(mount):
            raise SessionBlockError(f"mount did not finish slewing to {name or 'the target'}")
        await resume_tracking(mount, name)
        self.target = (name, ra_deg, dec_deg)
        self._record(f"On target {name or '(unnamed)'} (RA {ra_deg / 15.0:.4f}h, Dec {dec_deg:+.4f}°).")

    async def _select_filter(self, name: str | None) -> None:
        """Move the wheel to *name* (no-op when empty, already there, or no wheel is fitted)."""
        if not name or name == self.current_filter:
            return
        wheel = self.context.filter_wheel
        if wheel is None:
            self._record(f"No filter wheel — taking frames as {name!r} without moving one.")
            self.current_filter = name
            return
        names = [str(n) for n in (getattr(wheel, "filter_names", None) or [])]
        lookup = {n.lower(): i for i, n in enumerate(names)}
        if name.lower() not in lookup:
            raise SessionBlockError(f"filter {name!r} is not on the wheel ({', '.join(names) or 'no filters known'})")
        position = getattr(wheel, "position", None)
        previous = names[position] if isinstance(position, int) and 0 <= position < len(names) else self.current_filter
        await wheel.move_to(lookup[name.lower()])
        self.current_filter = names[lookup[name.lower()]]
        offset = self.context.apply_filter_focus_offset
        if offset is not None:
            try:
                await offset(previous, self.current_filter)
            except Exception as exc:
                self._record(f"Could not apply the focus offset for {name!r}: {exc}", error=True)

    def _new_imaging(self) -> Any:
        svc = self._make("make_imaging", "Image capture")
        if self.target is not None:
            svc.object_name = self.target[0]
        return svc

    async def _expose(self, svc: Any, exposure: float, filter_name: str, frame_type: str,
                      gain: int | None = None, offset: int | None = None) -> bool:
        """One frame through *svc*; ``False`` if it failed (logged) rather than raising, so a bad
        frame never ends the session (SES-080)."""
        svc.gain, svc.offset = gain or 0, offset or 0
        try:
            await self._run_tracked(svc, svc.capture_series(1, exposure, filter_name, frame_type))
        except Exception as exc:
            if self._stop.is_set():
                raise _Stopped from exc
            self._record(f"Frame failed: {exc}", error=True)
            return False
        self.frames_captured += 1
        self._emit(f"Frame {self.frames_captured} of {self._frames_total}")
        return True

    # --- Block handlers -----------------------------------------------------

    async def _do_TargetBlock(self, block: Any) -> None:
        if getattr(block, "is_placeholder_target", False):
            raise SessionBlockError("target is a template placeholder")
        await self._slew(block.name, block.ra_deg, block.dec_deg)

    async def _do_FilterChangeBlock(self, block: Any) -> None:
        self._need("filter_wheel")
        await self._select_filter(block.filter)

    async def _do_CoolCameraBlock(self, block: Any) -> None:
        camera = self._need("camera")
        await camera.set_temperature(block.setpoint_c)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + COOL_TIMEOUT_S
        while loop.time() < deadline:
            await self._checkpoint()
            try:
                temp = float(camera.get_temperature())
            except Exception:
                self._record("Camera does not report its temperature; not waiting for it to cool.")
                return
            self._emit(f"Cooling: {temp:.1f}°C → {block.setpoint_c:g}°C")
            if abs(temp - block.setpoint_c) <= COOL_TOLERANCE_C:
                self._record(f"Camera at {temp:.1f}°C.")
                return
            await asyncio.sleep(2.0)
        raise SessionBlockError(f"camera did not reach {block.setpoint_c:g}°C within {COOL_TIMEOUT_S / 60:.0f} min", fatal=False)

    async def _do_WarmCameraBlock(self, block: Any) -> None:
        await self._need("camera").warm_up()

    async def _do_AutofocusBlock(self, block: Any) -> None:
        self._need("camera"), self._need("focuser")
        await self._select_filter(block.filter)
        service = self._make("make_autofocus", "Autofocus")
        result = await self._run_tracked(service, service.run())
        if self._stop.is_set():
            raise _Stopped
        if not result.success:
            raise SessionBlockError(f"autofocus failed: {result.failure_reason or 'no reason given'}", fatal=False)
        self._record(f"Autofocus complete — best position {result.best_position}.")

    async def _do_PlateSolveBlock(self, block: Any) -> None:
        if self.target is None:
            raise SessionBlockError("no target to solve against")
        from galileo.platesolve import SolveAction, SolveSettings
        workflow = self._make("make_solve_workflow", "Plate solving")
        workflow.set_target(self.target[1], self.target[2], self.target[0])
        settings = SolveSettings(action=SolveAction.SLEW_TO_TARGET)
        results = await self._run_tracked(workflow, workflow.capture_and_solve(settings))
        if self._stop.is_set():
            raise _Stopped
        if not results or not results[-1].success:
            reason = results[-1].failure_reason if results else "no solve attempted"
            raise SessionBlockError(f"plate solve failed: {reason}")
        self._record("Plate solved and centred on the target.")

    async def _do_GuideStartBlock(self, block: Any) -> None:
        guider = self._need("guider")
        if block.calibrate and hasattr(guider, "clear_calibration"):
            await asyncio.wrap_future(guider.clear_calibration())
        await guider.start_guiding()

    async def _do_GuideStopBlock(self, block: Any) -> None:
        await self._need("guider").stop_guiding()

    async def _do_DitherBlock(self, block: Any) -> None:
        await self._need("guider").dither()

    async def _do_ImageBlock(self, block: Any) -> None:
        self._need("camera")
        await self._select_filter(block.filter)
        filter_name = self.current_filter or ""
        svc = self._new_imaging()
        if block.has_mosaic:
            await self._capture_mosaic(svc, block, filter_name)
            return
        failures = 0
        for i in range(1, int(block.count) + 1):
            await self._checkpoint()
            ok = await self._expose(svc, block.exposure, filter_name, block.frame_type, block.gain, block.offset)
            failures = 0 if ok else failures + 1
            if failures >= MAX_CONSECUTIVE_FRAME_FAILURES:
                raise SessionBlockError(
                    f"giving up after {failures} failed frames in a row ({i - failures} of {block.count} captured)",
                    fatal=False)

    async def _capture_mosaic(self, svc: Any, block: Any, filter_name: str) -> None:
        """SES-230: a mosaic Image block follows the mosaic round-robin capture model."""
        svc.active_mosaic = block.mosaic
        svc._mount = self._need("mount")
        svc.gain, svc.offset = block.gain or 0, block.offset or 0
        before = svc.series_done
        try:
            await self._run_tracked(svc, svc.capture_mosaic(int(block.count), block.exposure, filter_name, block.frame_type))
        except Exception as exc:
            if self._stop.is_set():
                raise _Stopped from exc
            raise
        finally:
            self.frames_captured += max(0, svc.series_done - before)
            self._emit()
        if self._stop.is_set():
            raise _Stopped

    async def _do_DarkCaptureBlock(self, block: Any) -> None:
        self._need("camera")
        await self._select_filter(block.filter)
        svc = self._new_imaging()
        for exposure in block.exposures:
            await self._checkpoint()
            await self._expose(svc, exposure, block.filter or self.current_filter or "", "Dark")

    async def _do_FlatCaptureBlock(self, block: Any) -> None:
        self._need("camera")
        if block.method != "Sky Flats":
            raise SessionBlockError(f"{block.method} flats are not implemented yet — only Sky Flats runs a real capture", fatal=False)
        if not self.context.max_well_depth:
            raise SessionBlockError("Sky Flats needs the camera's Max Well Depth set on Equipment > Camera", fatal=False)
        service = self._make("make_calibration", "Flat capture")
        filters = None if block.filter == "All" else [block.filter]
        results = await self._run_tracked(service, service.run_sky_flats_all_filters(
            filters, block.count, self.context.max_well_depth, location=self.context.location,
            measure=block.adu_method, exposure_s=block.exposure or None,
            exposure_increment_s=block.exposure_increment,
        ))
        got = sum(r.frames_captured for r in results)
        self.frames_captured += got
        if self._stop.is_set():
            raise _Stopped
        self._record(f"Flats done — {got} frame(s).")

    async def _do_ParkMountBlock(self, block: Any) -> None:
        await self._need("mount").park()

    async def _do_UnparkMountBlock(self, block: Any) -> None:
        await self._need("mount").unpark()

    async def _do_MeridianFlipBlock(self, block: Any) -> None:
        from galileo.meridianflip import MeridianFlipConfig, MeridianFlipService
        from galileo.tracking import resume_tracking
        mount = self._need("mount")
        if self.target is None:
            status = await mount.get_status() or {}
            ra, dec = (status.get("right_ascension") or 0.0) * 15.0, status.get("declination") or 0.0
        else:
            _name, ra, dec = self.target
        service = MeridianFlipService(
            mount=mount, config=MeridianFlipConfig(post_flip_recenter=False, post_flip_restart_guiding=False))
        await service.execute_flip(target_ra=ra, target_dec=dec)
        await resume_tracking(mount, self.target[0] if self.target else None)
        guider = self.context.guider
        if guider is not None:
            try:
                await guider.start_guiding()
            except Exception as exc:
                self._record(f"Could not restart guiding after the flip: {exc}", error=True)

    async def _do_DomeOpenBlock(self, block: Any) -> None:
        await self._need("dome").open_shutter()

    async def _do_DomeCloseBlock(self, block: Any) -> None:
        await self._need("dome").close_shutter()

    async def _do_DomeSyncBlock(self, block: Any) -> None:
        dome, mount = self._need("dome"), self._need("mount")
        azimuth = (await mount.get_status() or {}).get("azimuth")
        if azimuth is None:
            raise SessionBlockError("the mount does not report its azimuth", fatal=False)
        await dome.slew_to_azimuth(float(azimuth))

    # --- Loops --------------------------------------------------------------

    async def _run_loop(self, node: _Node) -> None:
        block = node.block
        if type(block).__name__ == "ForFilterBlock":
            for filter_name in block.filters:
                await self._checkpoint()
                self._record(f"FOR Filter: {filter_name}")
                try:
                    await self._select_filter(filter_name)
                except SessionBlockError as exc:
                    self._record(f"Skipping filter {filter_name!r}: {exc}", error=True)
                    continue
                await self._run_nodes(node.children)
        else:
            for obj in block.objects:
                await self._checkpoint()
                self._record(f"FOR Object: {obj.get('name', '')}")
                await self._slew(obj.get("name", ""), float(obj["ra_deg"]), float(obj["dec_deg"]))
                await self._run_nodes(node.children)
