# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Control Surface registry (CSURF-010 to CSURF-050, CSURF-080).

Each domain service declares its operator-level operations here by calling
``registry.register(spec, handler)``. The registry validates a request against the declared schema,
calls the service's own handler — the same method the desktop uses — and turns whatever happens into
a typed :class:`Outcome`; an exception never reaches the caller. Registering costs nothing at run
time: no listener, thread or timer exists until something invokes an operation.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from galileo.bus import EventBus
from galileo.control_surface.events import OperationTracker
from galileo.control_surface.schema import Arg, InvalidArguments, validate_args

logger = logging.getLogger(__name__)

CLASSES = frozenset({"read", "operate", "confirm", "emergency"})
STATUSES = frozenset({"ok", "refused", "invalid", "unavailable", "busy", "unreachable"})
CATALOGUE_VERSION = 1
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}(\.[a-z][a-z0-9_]{0,39}){1,2}$")


class RegistrationError(ValueError):
    """An operation the registry refuses to hold (for example one of class *config*)."""


class Refused(Exception):
    """Raised by a handler when its service refuses (a safety interlock, a limit, a wrong state).
    The reason is returned to the client verbatim (CSURF-050)."""


class Busy(Exception):
    """The service is occupied; the client may retry."""


class Unreachable(Exception):
    """The node that owns the Pier cannot be reached."""


@dataclass(frozen=True)
class Outcome:
    status: str
    reason: str = ""
    value: Any = None
    correlation_id: str = ""
    path: str = ""                  # the offending argument, for ``invalid``
    confirm_token: str = ""         # set when a confirm-class operation needs its second step

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status, "reason": self.reason}
        for key in ("value", "correlation_id", "path", "confirm_token"):
            if getattr(self, key) not in (None, ""):
                d[key] = getattr(self, key)
        return d


@dataclass
class OperationContext:
    pier: str
    principal: str
    tracker: OperationTracker | None = None

    def progress(self, fraction: float | None = None, message: str = "") -> None:
        if self.tracker is not None:
            self.tracker.progress(fraction, message)


Handler = Callable[[OperationContext, dict[str, Any]], Any | Awaitable[Any]]


@dataclass(frozen=True)
class OperationSpec:
    name: str
    permission_class: str = "operate"
    args: tuple[Arg, ...] = ()
    needs_lease: bool = False
    long_running: bool = False
    # ``available(pier)`` returns None when the operation can run, else a readable reason.
    available: Callable[[str], str | None] = field(default=lambda pier: None, compare=False)
    description: str = ""
    result: str = ""                # a one-line description of the result, for the catalogue

    def describe(self, pier: str = "") -> dict[str, Any]:
        reason = self.available(pier) if pier else None
        return {
            "name": self.name, "class": self.permission_class, "needs_lease": self.needs_lease,
            "long_running": self.long_running, "description": self.description, "result": self.result,
            "args": [a.describe() for a in self.args],
            "available": reason is None, **({"reason": reason} if reason else {}),
        }


@dataclass(frozen=True)
class Prepared:
    spec: OperationSpec
    args: dict[str, Any]


class Registry:
    def __init__(self, bus: EventBus | None = None) -> None:
        self._ops: dict[str, tuple[OperationSpec, Handler]] = {}
        self._bus = bus
        self._tasks: set[asyncio.Task[None]] = set()

    # -- declaration -------------------------------------------------------------------
    def register(self, spec: OperationSpec, handler: Handler, *, namespace: str = "") -> None:
        """Declare an operation. A plugin passes its ``namespace`` and may register only names under
        it (CSURF-250); class *config* and anything not in the four classes is refused (CSURF-020)."""
        if spec.permission_class not in CLASSES:
            raise RegistrationError(
                f"{spec.name}: class {spec.permission_class!r} is not allowed; the Control Surface never "
                "edits a stored definition of the observatory")
        if not _NAME.match(spec.name):
            raise RegistrationError(f"{spec.name!r} is not a valid operation name (area.operation)")
        if namespace and spec.name.split(".")[0] != namespace:
            raise RegistrationError(f"{spec.name}: a plugin may register only under {namespace}.")
        if spec.name in self._ops:
            raise RegistrationError(f"{spec.name} is already registered")
        if spec.permission_class == "emergency" and spec.needs_lease:
            raise RegistrationError(f"{spec.name}: an emergency operation needs no lease")
        self._ops[spec.name] = (spec, handler)

    def unregister_namespace(self, namespace: str) -> int:
        gone = [n for n in self._ops if n.split(".")[0] == namespace]
        for n in gone:
            del self._ops[n]
        return len(gone)

    def verify(self) -> None:
        """Re-check every entry (consumers call this at start-up, CSURF-020)."""
        for spec, _ in self._ops.values():
            if spec.permission_class not in CLASSES:
                raise RegistrationError(f"{spec.name}: class {spec.permission_class!r} is not allowed")

    # -- catalogue ---------------------------------------------------------------------
    def spec(self, name: str) -> OperationSpec | None:
        entry = self._ops.get(name)
        return entry[0] if entry else None

    def catalogue(self, pier: str = "") -> dict[str, Any]:
        """Every entry with its schema, class, lease requirement and — per Pier — availability (CSURF-030)."""
        return {"version": CATALOGUE_VERSION,
                "operations": [s.describe(pier) for s, _ in sorted(self._ops.values(), key=lambda e: e[0].name)]}

    def names(self) -> list[str]:
        return sorted(self._ops)

    # -- validation and invocation -----------------------------------------------------
    def prepare(self, name: str, args: dict[str, Any] | None, pier: str) -> Prepared | Outcome:
        """Look the operation up and validate; nothing in the catalogue is ``unavailable``-by-surprise."""
        entry = self._ops.get(name)
        if entry is None:
            return Outcome("unavailable", "no such operation")
        spec = entry[0]
        reason = spec.available(pier)
        if reason:
            return Outcome("unavailable", reason)
        try:
            return Prepared(spec, validate_args(spec.args, args))
        except InvalidArguments as exc:
            return Outcome("invalid", exc.reason, path=exc.path)

    async def invoke(self, name: str, args: dict[str, Any] | None, pier: str, principal: str) -> Outcome:
        prepared = self.prepare(name, args, pier)
        if isinstance(prepared, Outcome):
            return prepared
        return await self.run(prepared, pier, principal)

    async def run(self, prepared: Prepared, pier: str, principal: str) -> Outcome:
        spec, handler = prepared.spec, self._ops[prepared.spec.name][1]
        if not spec.long_running:
            return await self._call(handler, OperationContext(pier, principal), prepared.args)
        tracker = OperationTracker(spec.name, pier, principal, self._bus)
        tracker.start()
        task = asyncio.create_task(self._background(handler, OperationContext(pier, principal, tracker),
                                                    prepared.args, tracker))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return Outcome("ok", "started", correlation_id=tracker.correlation_id)

    async def _background(self, handler: Handler, ctx: OperationContext, args: dict[str, Any],
                          tracker: OperationTracker) -> None:
        try:
            outcome = await self._call(handler, ctx, args)
        except BaseException:                            # cancelled or died: still exactly one finished
            tracker.finish("unavailable", "the operation was interrupted")
            raise
        tracker.finish(outcome.status, outcome.reason)

    @staticmethod
    async def _call(handler: Handler, ctx: OperationContext, args: dict[str, Any]) -> Outcome:
        try:
            result = handler(ctx, args)
            if inspect.isawaitable(result):
                result = await result
        except Refused as exc:
            return Outcome("refused", str(exc))
        except Busy as exc:
            return Outcome("busy", str(exc) or "busy")
        except Unreachable as exc:
            return Outcome("unreachable", str(exc) or "unreachable")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Control Surface operation failed")
            return Outcome("unavailable", "the operation failed")
        return Outcome("ok", value=result)

    async def wait_idle(self) -> None:
        """Wait for background (long-running) operations to finish — used by tests and shutdown."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def cancel_background(self) -> None:
        for task in list(self._tasks):
            task.cancel()


__all__ = [
    "CATALOGUE_VERSION",
    "CLASSES",
    "STATUSES",
    "Busy",
    "Handler",
    "OperationContext",
    "OperationSpec",
    "Outcome",
    "Prepared",
    "Refused",
    "RegistrationError",
    "Registry",
    "Unreachable",
]
