# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The process pool for CPU-bound work (SDD §2.3, NFR-PERF-020).

Some of Galileo's image work holds the GIL for seconds at a time — SEP star detection
(autofocus HFR, imaging-tab statistics) and astroalign registration (live stacking). Run in a
thread, that still freezes the Qt event loop, because the UI thread can't get the GIL back until
the C call returns. This module runs such work in a separate process instead.

Only send work here that holds the GIL. Pure-numpy work (stretching, debayering, histograms,
FFTs) releases it, so ``asyncio.to_thread`` already keeps the UI responsive. Sending it to a
worker would only add the cost of copying the frame there and back, about 1.5 ms per MB each way.
Work sent here must be a module-level function whose arguments and return value can be pickled,
and it should return something small (a stats dict, not a full-size float array) where it can.

The pool is created on first use and replaces a worker after ``_MAX_TASKS_PER_CHILD`` tasks, so a
leak in a C extension can't grow for a whole night (NFR-PERF-030). Setting the ``GALILEO_CPU_WORKERS``
environment variable to ``0`` turns the pool off: work then runs in a thread, as it did before.
That is useful for debugging, and the test suite uses it so monkeypatched functions still apply.
"""

from __future__ import annotations

import asyncio
import atexit
import functools
import logging
import multiprocessing
import os
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

WORKERS_ENV = "GALILEO_CPU_WORKERS"
_MAX_DEFAULT_WORKERS = 4          # a Raspberry Pi 5 has 4 cores; each worker holds its own numpy/SEP
_MAX_TASKS_PER_CHILD = 100        # respawn cost (~150 ms) is negligible against a night's work

_lock = threading.Lock()
_executor: ProcessPoolExecutor | None = None


def worker_count() -> int:
    """How many worker processes the pool uses: ``GALILEO_CPU_WORKERS`` if set, otherwise one
    fewer than the CPU count (leaving a core for the UI), capped at ``_MAX_DEFAULT_WORKERS``.
    Zero means the pool is off."""
    configured = os.environ.get(WORKERS_ENV, "").strip()
    if configured:
        try:
            return max(0, int(configured))
        except ValueError:
            logger.warning("Ignoring %s=%r: not a whole number.", WORKERS_ENV, configured)
    return max(1, min(_MAX_DEFAULT_WORKERS, (os.cpu_count() or 2) - 1))


def _start_method() -> str:
    """``forkserver`` where the platform has it (Linux), else ``spawn``. Plain ``fork`` is never
    used: forking a process that is running Qt and INDI reader threads can deadlock the child."""
    return "forkserver" if "forkserver" in multiprocessing.get_all_start_methods() else "spawn"


def cpu_executor() -> ProcessPoolExecutor | None:
    """The shared pool, created on first use, or ``None`` when ``GALILEO_CPU_WORKERS`` is 0."""
    global _executor
    workers = worker_count()
    if workers == 0:
        return None
    with _lock:
        if _executor is None:
            _executor = ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context(_start_method()),
                max_tasks_per_child=_MAX_TASKS_PER_CHILD,
            )
            logger.info("CPU worker pool started: %d %s worker(s).", workers, _start_method())
        return _executor


def _discard_broken(executor: ProcessPoolExecutor) -> None:
    """Drop *executor* after a worker died, so the next call starts a fresh pool rather than
    failing forever. The caller still gets the error for the task that was lost."""
    global _executor
    with _lock:
        if _executor is executor:
            _executor = None
    logger.error("A CPU worker process died; the pool will be restarted on next use.")
    executor.shutdown(wait=False, cancel_futures=True)


async def run_cpu(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Await ``fn(*args, **kwargs)`` run in the worker pool, or in a thread if the pool is off.

    Safe to call from any event loop, including the short-lived ``asyncio.run`` loops on the
    capture and autofocus ``QThread``s. The pool itself is shared by all of them."""
    executor = cpu_executor()
    if executor is None:
        return await asyncio.to_thread(fn, *args, **kwargs)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(executor, functools.partial(fn, *args, **kwargs))
    except BrokenProcessPool:
        _discard_broken(executor)
        raise


def run_cpu_sync(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Blocking form of :func:`run_cpu`, for code that already runs on a worker thread (e.g. a
    ``QThread``) and has no event loop of its own. With the pool off, it calls *fn* directly."""
    executor = cpu_executor()
    if executor is None:
        return fn(*args, **kwargs)
    try:
        return executor.submit(fn, *args, **kwargs).result()
    except BrokenProcessPool:
        _discard_broken(executor)
        raise


def imap_cpu(fn: Callable[..., T], arg_tuples: Iterable[tuple]) -> Iterator[T]:
    """Yield ``fn(*args)`` for each tuple in *arg_tuples*, in order, run in parallel across the
    pool. This is blocking, like :func:`run_cpu_sync`, for batch jobs on a worker thread.

    At most one task per worker is in flight at a time, so a long batch returning full-size
    frames never buffers more than a few of them in memory. With the pool off, it runs the
    calls one after another."""
    executor = cpu_executor()
    if executor is None:
        for args in arg_tuples:
            yield fn(*args)
        return
    in_flight = worker_count()
    pending: deque[Future] = deque()
    try:
        for args in arg_tuples:
            pending.append(executor.submit(fn, *args))
            if len(pending) >= in_flight:
                yield pending.popleft().result()
        while pending:
            yield pending.popleft().result()
    except BrokenProcessPool:
        _discard_broken(executor)
        raise
    finally:
        for future in pending:              # the caller stopped early, or a task failed
            future.cancel()


def shutdown_cpu_executor(wait: bool = True) -> None:
    """Stop the pool, cancelling queued work. Called when the app exits; it's safe to call again,
    and a later :func:`run_cpu` starts a new pool."""
    global _executor
    with _lock:
        executor, _executor = _executor, None
    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=True)


atexit.register(shutdown_cpu_executor, False)
