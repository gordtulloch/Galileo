# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The asyncio session runner (HEAD-050), shared by the engine and the desktop.

``run_session`` is the one code path that executes a Sessions-screen block list: a manual Run goes straight to
the executor and stays off the Schedule; a scheduled run goes through ``ObservatoryScheduler.run_job`` so a
session behaves the same however it was started. It is plain ``async`` code with no Qt in it.

``SessionRunner`` is the engine's owner of runs: one asyncio event loop on one thread, one run per Pier at a
time and Piers concurrently (OBS-020), with progress, start and finish published on the event bus. The
desktop's ``SessionRunController`` keeps its own Qt plumbing but calls ``run_session`` in its worker thread, so
both share one implementation of what a run does.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

from galileo.bus import Event, EventBus, get_bus

logger = logging.getLogger(__name__)


class SessionStartedEvent(Event):
    pass


class SessionProgressEvent(Event):
    pass


class SessionFinishedEvent(Event):
    pass


class RunnerBusy(Exception):
    """A session is already running on that Pier."""


async def run_session(executor: Any, blocks: list, *, scheduler: Any = None, job: Any = None,
                      manual: bool = True) -> tuple[str, Any]:
    """Run *blocks* on *executor*. Returns ``(state, result)`` where state is ``completed``, ``error`` or
    ``stopped`` (the scheduler's own verdict for a scheduled run)."""
    holder: dict[str, Any] = {}

    async def execute(j: Any = None) -> Any:
        holder["result"] = await executor.run(j.sequence.blocks if j is not None else blocks)
        return holder["result"]

    try:
        if manual or scheduler is None or job is None:
            result = await execute()
            value = getattr(result.state, "value", result.state)
            return (value if value in ("completed", "error") else "stopped"), result
        return await scheduler.run_job(job, execute), holder.get("result")
    except Exception:
        logger.exception("Session run failed")
        return "error", holder.get("result")


@dataclass
class _Run:
    name: str
    executor: Any
    future: Future | None = None
    progress: Any = None
    manual: bool = True
    state: str = "running"
    result: Any = None


@dataclass
class RunSnapshot:
    pier: str
    name: str
    state: str
    progress: Any = field(default=None)


class SessionRunner:
    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus or get_bus()
        self._runs: dict[str, _Run] = {}
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    # -- the loop -----------------------------------------------------------------------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                ready = threading.Event()

                def serve() -> None:
                    asyncio.set_event_loop(loop)
                    loop.call_soon(ready.set)
                    loop.run_forever()
                self._thread = threading.Thread(target=serve, name="engine-runner", daemon=True)
                self._thread.start()
                ready.wait(5)
                self._loop = loop
            return self._loop

    # -- starting and controlling -----------------------------------------------------------------
    def start(self, pier: str, name: str, executor: Any, blocks: list, *, scheduler: Any = None, job: Any = None,
              manual: bool = True) -> None:
        """Begin a run on *pier*; raises ``RunnerBusy`` if that Pier already has one."""
        with self._lock:
            if pier in self._runs:
                raise RunnerBusy(f"A session is already running on Pier {pier}.")
            run = _Run(name=name, executor=executor, manual=manual)
            self._runs[pier] = run
        executor.set_progress_callback(lambda p: self._on_progress(pier, run, p))
        self._bus.publish(SessionStartedEvent(source="runner", pier=pier, name=name, manual=manual))

        async def go() -> None:
            state, result = await run_session(executor, blocks, scheduler=scheduler, job=job, manual=manual)
            self._finished(pier, run, state, result)

        run.future = asyncio.run_coroutine_threadsafe(go(), self._ensure_loop())

    def _on_progress(self, pier: str, run: _Run, progress: Any) -> None:
        run.progress = progress
        self._bus.publish(SessionProgressEvent(source="runner", pier=pier, name=run.name, progress=progress))

    def _finished(self, pier: str, run: _Run, state: str, result: Any) -> None:
        run.state, run.result = state, result
        with self._lock:
            if self._runs.get(pier) is run:
                del self._runs[pier]
        self._bus.publish(SessionFinishedEvent(source="runner", pier=pier, name=run.name, state=state, result=result))

    def _run(self, pier: str) -> _Run | None:
        with self._lock:
            return self._runs.get(pier)

    def stop(self, pier: str) -> bool:
        run = self._run(pier)
        if run is None:
            return False
        run.executor.stop()
        return True

    def pause(self, pier: str) -> bool:
        run = self._run(pier)
        if run is None:
            return False
        run.executor.pause()
        return True

    def resume(self, pier: str) -> bool:
        run = self._run(pier)
        if run is None:
            return False
        run.executor.resume()
        return True

    def is_running(self, pier: str | None = None) -> bool:
        with self._lock:
            return (pier in self._runs) if pier is not None else bool(self._runs)

    def snapshot(self) -> list[RunSnapshot]:
        with self._lock:
            return [RunSnapshot(p, r.name, r.state, r.progress) for p, r in self._runs.items()]

    def stop_all(self, timeout: float = 30.0) -> None:
        """Ask every run to stop and wait for them to end."""
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            run.executor.stop()
        for run in runs:
            if run.future is not None:
                try:
                    run.future.result(timeout)
                except Exception:
                    logger.exception("A session did not end cleanly")

    def shutdown(self, timeout: float = 30.0) -> None:
        self.stop_all(timeout)
        with self._lock:
            loop, self._loop = self._loop, None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
            if self._thread is not None:
                self._thread.join(5)


__all__ = ["RunSnapshot", "RunnerBusy", "SessionFinishedEvent", "SessionProgressEvent", "SessionRunner",
           "SessionStartedEvent", "run_session"]
