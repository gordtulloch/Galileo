# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The protective stop (SAFE-130 … SAFE-180): one Qt-free service that judges an Observatory's safety and, when it
turns unsafe, stops every activity, parks every mount and closes the roof.

The desktop and the headless engine each give it a *snapshot* of what they hold (:class:`Site`) and register the
things that can move equipment with its :class:`ActivityRegistry`. Everything else happens here, on the supervisor's
own thread, so it does not depend on any screen being open.

State, one per Observatory::

    READY → STOPPING → SECURED | NOT_SECURED (retries) → AWAITING_ACK → READY
"""

from __future__ import annotations

import asyncio
import datetime
import inspect
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from enum import StrEnum
from typing import Any

from galileo.roof import park_roof_mounts, roof_left_open_message

logger = logging.getLogger(__name__)

SETTINGS_NAMESPACE = "safety"
TICK_S = 5.0
ACTIVITY_TIMEOUT_S = 30.0     # how long running work is given to end before parking goes ahead anyway
DEVICE_TIMEOUT_S = 30.0       # one device read or command
SHUTTER_TIMEOUT_S = 300.0     # a roll-off roof can take minutes
SHUTTER_POLL_S = 2.0


class Level(StrEnum):
    SAFE = "safe"
    WARNING = "warning"
    UNSAFE = "unsafe"
    UNMONITORED = "unmonitored"     # no saved safety device: not unsafe, but nothing is watching


class State(StrEnum):
    READY = "ready"
    STOPPING = "stopping"
    SECURED = "secured"
    NOT_SECURED = "not_secured"
    AWAITING_ACK = "awaiting_ack"


@dataclass
class SafetySettings:
    """Per-Observatory settings (SAFE-030, SAFE-040, SAFE-140, SAFE-160)."""

    enabled: bool = True              # carry out the protective stop
    close_roof: bool = True
    grace_s: float = 60.0             # a device unreadable this long is acted on
    stable_s: float = 900.0           # safe this long, continuously, before the stop can be cleared
    auto_restart: bool = False
    retry_s: float = 60.0
    realert_s: float = 600.0


MIN_STABLE_S = 300.0


def load_settings(scope: str = "") -> SafetySettings:
    from galileo.settings_store import get_namespace
    settings = SafetySettings()
    try:
        saved = get_namespace(SETTINGS_NAMESPACE, scope)
        for item in fields(SafetySettings):
            if item.name in saved:
                kind = type(getattr(settings, item.name))
                setattr(settings, item.name, kind(saved[item.name]))
    except Exception:
        logger.exception("Could not read the safety settings; using the defaults")
        return SafetySettings()
    settings.stable_s = max(MIN_STABLE_S, settings.stable_s)
    return settings


def save_settings(settings: SafetySettings, scope: str = "") -> None:
    from galileo.settings_store import set_namespace
    set_namespace(SETTINGS_NAMESPACE, {f.name: getattr(settings, f.name) for f in fields(SafetySettings)}, scope)


# ---------------------------------------------------------------------------
# What the host tells the supervisor about the site
# ---------------------------------------------------------------------------

@dataclass
class Source:
    """One saved safety device: ``adapter`` is ``None`` while it is not connected."""

    key: str
    name: str
    kind: str                         # "weather" or "safety_monitor"
    adapter: Any = None
    rules: list = field(default_factory=list)


@dataclass
class Roof:
    """One dome or roof, and the ``(pier name, mount or None)`` that sit under it."""

    name: str
    dome: Any
    mounts: list = field(default_factory=list)
    before_close: Callable[[], None] | None = None     # e.g. stop dome slaving


@dataclass
class Site:
    sources: list = field(default_factory=list)
    mounts: list = field(default_factory=list)         # (pier name, mount or None), every Pier
    guiders: list = field(default_factory=list)        # (pier name, guiding service)
    roofs: list = field(default_factory=list)


@dataclass
class Verdict:
    level: Level = Level.UNMONITORED
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    act: bool = False                 # grounds to carry out the protective stop (SAFE-140)

    @property
    def blocking(self) -> bool:
        return self.level == Level.UNSAFE


# ---------------------------------------------------------------------------
# Evaluation (SAFE-130, SAFE-140)
# ---------------------------------------------------------------------------

def _read(source: Source) -> dict:
    from galileo.weather_ops import read_device
    return read_device(source.adapter, source.kind)


class Evaluator:
    """Judges the sources, remembering which have been read and since when each has been lost."""

    def __init__(self, read: Callable[[Source], dict] | None = None) -> None:
        self._read = read
        self._seen: set[str] = set()
        self._lost_since: dict[str, float] = {}

    async def evaluate(self, sources: list, grace_s: float, now: float) -> Verdict:
        verdict = Verdict()
        if not sources:
            return verdict
        for source in sources:
            readings = await self._readings(source)
            if readings is None:
                reason = f"{source.name} is not connected or cannot be read"
                verdict.reasons.append(reason)
                # A device never read since start-up blocks starts but moves nothing; one that has dropped out
                # is acted on once the grace period is over.
                if source.key in self._seen:
                    since = self._lost_since.setdefault(source.key, now)
                    verdict.act = verdict.act or now - since >= grace_s
                continue
            self._seen.add(source.key)
            self._lost_since.pop(source.key, None)
            unsafe, warnings = self._judge(source, readings)
            verdict.warnings += warnings
            if unsafe:
                verdict.reasons += unsafe
                verdict.act = True
        if verdict.reasons:
            verdict.level = Level.UNSAFE
        else:
            verdict.level = Level.WARNING if verdict.warnings else Level.SAFE
        return verdict

    async def _readings(self, source: Source) -> dict | None:
        if source.adapter is None or getattr(source.adapter, "is_connected", True) is False:
            return None
        try:
            read = self._read or _read
            return await asyncio.wait_for(asyncio.to_thread(read, source), DEVICE_TIMEOUT_S)
        except Exception:
            logger.warning("Could not read %s", source.name, exc_info=True)
            return None

    @staticmethod
    def _judge(source: Source, readings: dict) -> tuple[list[str], list[str]]:
        if source.kind == "safety_monitor":
            if readings.get("is_safe"):
                return [], []
            why = str(getattr(source.adapter, "explanation", "") or "")
            return [f"{source.name} reports unsafe" + (f": {why}" if why else "")], []
        from galileo.safety import evaluate_weather_safety
        status = evaluate_weather_safety(readings, source.rules)
        return list(status.violations), list(status.warnings)


# ---------------------------------------------------------------------------
# Activities that can move or use equipment
# ---------------------------------------------------------------------------

class ActivityRegistry:
    """``stop`` callables for everything that can move or use equipment. Each must be safe to call when idle and,
    where it can, return (or await) only once the work has ended."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stoppers: dict[str, Callable[[], Any]] = {}

    def register(self, name: str, stop: Callable[[], Any]) -> None:
        with self._lock:
            self._stoppers[name] = stop

    def unregister(self, name: str) -> None:
        with self._lock:
            self._stoppers.pop(name, None)

    async def stop_all(self, timeout_s: float | None = None) -> list[str]:
        """Stop everything at once. Returns what could not be stopped; one failure never prevents the others."""
        timeout_s = ACTIVITY_TIMEOUT_S if timeout_s is None else timeout_s
        with self._lock:
            stoppers = dict(self._stoppers)

        async def one(name: str, stop: Callable[[], Any]) -> str | None:
            try:
                async def call() -> None:
                    result = stop() if inspect.iscoroutinefunction(stop) else await asyncio.to_thread(stop)
                    if inspect.isawaitable(result):
                        await result
                await asyncio.wait_for(call(), timeout_s)
            except TimeoutError:
                return f"{name} did not stop within {timeout_s:g} s"
            except Exception as exc:
                logger.exception("Could not stop %s", name)
                return f"{name} could not be stopped ({exc})"
            return None

        results = await asyncio.gather(*(one(n, s) for n, s in stoppers.items()))
        return [r for r in results if r]


# ---------------------------------------------------------------------------
# The record of a stop (SAFE-170)
# ---------------------------------------------------------------------------

class MemoryStore:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def open(self, scope: str, reason: str) -> int:
        self.records.append({"id": len(self.records) + 1, "scope": scope, "reason": reason, "at": time.time(),
                             "outcome": "", "problems": "", "acknowledged_by": "", "acknowledged_at": None})
        return self.records[-1]["id"]

    def update(self, record_id: int, **values: Any) -> None:
        self.records[record_id - 1].update(values)

    def unacknowledged(self, scope: str) -> dict | None:
        return next((r for r in reversed(self.records) if r["scope"] == scope and not r["acknowledged_by"]), None)

    def history(self, scope: str) -> list[dict]:
        return [dict(r) for r in self.records if r["scope"] == scope][-50:]


class DatabaseStore:
    """The same, in the shared database, so an unacknowledged stop survives a restart."""

    def __init__(self) -> None:
        self._fallback = MemoryStore()

    @staticmethod
    def _model():
        from galileo.library.models.safety_event import SafetyEventRecord
        return SafetyEventRecord

    @staticmethod
    def _as_dict(row: Any) -> dict:
        return {"id": row.id, "scope": row.scope, "reason": row.reason, "at": row.at, "outcome": row.outcome,
                "problems": row.problems, "acknowledged_by": row.acknowledged_by, "acknowledged_at": row.acknowledged_at}

    def open(self, scope: str, reason: str) -> int:
        try:
            return self._model().create(scope=scope, reason=reason, at=time.time()).id
        except Exception:
            logger.exception("Could not save the safety stop")
            return -self._fallback.open(scope, reason)      # negative ids live in memory only

    def update(self, record_id: int, **values: Any) -> None:
        try:
            if record_id < 0:
                self._fallback.update(-record_id, **values)
            else:
                model = self._model()
                model.update(**values).where(model.id == record_id).execute()
        except Exception:
            logger.exception("Could not update the safety stop record")

    def unacknowledged(self, scope: str) -> dict | None:
        try:
            model = self._model()
            row = (model.select().where((model.scope == scope) & (model.acknowledged_by == ""))
                   .order_by(model.id.desc()).first())
            return self._as_dict(row) if row is not None else None
        except Exception:
            logger.debug("Could not read the safety stops", exc_info=True)
            return None

    def history(self, scope: str) -> list[dict]:
        try:
            model = self._model()
            rows = model.select().where(model.scope == scope).order_by(model.id.desc()).limit(50)
            return [self._as_dict(r) for r in reversed(list(rows))]
        except Exception:
            logger.debug("Could not read the safety stops", exc_info=True)
            return []


# ---------------------------------------------------------------------------
# The supervisor
# ---------------------------------------------------------------------------

class SafetySupervisor:
    """Judges one Observatory and carries out its protective stop. ``tick`` is the whole behaviour; ``start`` just
    calls it on a thread. ``is_safe``, ``status`` and ``acknowledge`` are safe from any thread."""

    def __init__(self, snapshot: Callable[[], Site], *, scope: str = "",
                 settings: Callable[[], SafetySettings] | None = None, notify: Callable[[str], Any] | None = None,
                 store: Any = None, bus: Any = None, activities: ActivityRegistry | None = None,
                 clock: Callable[[], float] = time.monotonic, read: Callable[[Source], dict] | None = None,
                 on_restart: Callable[[], None] | None = None) -> None:
        self.scope = scope
        self.activities = activities or ActivityRegistry()
        self.on_restart = on_restart
        self._snapshot, self._notify, self._bus, self._clock = snapshot, notify, bus, clock
        self._settings = settings or (lambda: load_settings(scope))
        self._store = store if store is not None else MemoryStore()
        self._evaluator = Evaluator(read)
        self._lock = threading.RLock()
        self.verdict = Verdict()
        self.problems: list[str] = []
        self._clean_since: float | None = None
        self._last_retry = self._last_alert = 0.0
        self._roof_pending = False
        self._tick_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.checked = False                 # False until the first evaluation
        pending = self._store.unacknowledged(scope)
        # A stop nobody acknowledged is still in force after a restart. Equipment may have moved since, so a new
        # unsafe report carries the stop out again.
        self._record_id: int | None = pending["id"] if pending else None
        self._restored = pending is not None
        self.state = State.SECURED if pending else State.READY
        self.reason = pending["reason"] if pending else ""

    # -- queries ---------------------------------------------------------------------------------

    def is_safe(self) -> bool:
        """May something be started? False while unsafe and until a protective stop is acknowledged."""
        with self._lock:
            return self.state == State.READY and not self.verdict.blocking

    def gate_reason(self) -> str:
        with self._lock:
            if self.state == State.READY:
                return "; ".join(self.verdict.reasons) if self.verdict.blocking else ""
            if self.state == State.AWAITING_ACK:
                return f"a safety stop must be acknowledged first ({self.reason})"
            return f"a safety stop is in force ({self.reason})"

    def seconds_until_stable(self) -> float:
        with self._lock:
            if self._clean_since is None:
                return self._settings().stable_s
            return max(0.0, self._settings().stable_s - (self._clock() - self._clean_since))

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"state": self.state.value, "level": self.verdict.level.value, "reason": self.reason,
                    "reasons": list(self.verdict.reasons), "warnings": list(self.verdict.warnings),
                    "problems": list(self.problems)}

    def history(self) -> list[dict]:
        return self._store.history(self.scope)

    # -- acknowledging (SAFE-040) ----------------------------------------------------------------

    def acknowledge(self, who: str) -> None:
        """Clear a protective stop. Raises ``ValueError`` (with the reason) unless conditions have been safe long
        enough; it restarts nothing."""
        with self._lock:
            if self.state == State.READY:
                raise ValueError("there is no safety stop to acknowledge")
            if self.verdict.blocking:
                raise ValueError("conditions are still unsafe: " + "; ".join(self.verdict.reasons))
            if self.state != State.AWAITING_ACK:
                minutes = max(1, round(self.seconds_until_stable() / 60))
                raise ValueError(f"conditions have not been safe for long enough yet (about {minutes} min to go)")
            self._clear(who)

    def _clear(self, who: str) -> None:
        if self._record_id is not None:
            self._store.update(self._record_id, acknowledged_by=who,
                               acknowledged_at=datetime.datetime.now(datetime.UTC).timestamp())
        self._record_id, self._restored, self._roof_pending = None, False, False
        self.state, self.reason, self.problems = State.READY, "", []

    # -- the loop --------------------------------------------------------------------------------

    async def tick(self) -> None:
        """One evaluation, and whatever it calls for."""
        if not self._tick_lock.acquire(blocking=False):
            return
        try:
            await self._tick()
        finally:
            self._tick_lock.release()

    async def _tick(self) -> None:
        settings = self._settings()
        site = self._snapshot()
        now = self._clock()
        verdict = await self._evaluator.evaluate(site.sources, settings.grace_s, now)
        with self._lock:
            self.verdict, self.checked = verdict, True
            self._clean_since = None if verdict.blocking else (self._clean_since if self._clean_since is not None else now)
            state, stable = self.state, self._clean_since is not None and now - self._clean_since >= settings.stable_s

        new_episode = verdict.act and settings.enabled and (
            state in (State.READY, State.AWAITING_ACK) or (state == State.SECURED and self._restored))
        if new_episode:
            await self._protective_stop(site, settings, "; ".join(verdict.reasons))
            return
        if state == State.NOT_SECURED and self._roof_pending and verdict.blocking:
            await self._retry(site, settings, now)
            return
        if state in (State.SECURED, State.NOT_SECURED) and stable:
            if settings.auto_restart and state == State.SECURED and not self._restored:
                with self._lock:
                    self._clear("automatic restart")
                await self._alert("Conditions have been safe long enough: restarting scheduled sessions.")
                if self.on_restart is not None:
                    self.on_restart()
                return
            with self._lock:
                self.state = State.AWAITING_ACK
            await self._alert("Conditions are safe again. Acknowledge the safety stop to start anything.")

    # -- the protective stop (SAFE-150) -----------------------------------------------------------

    async def _protective_stop(self, site: Site, settings: SafetySettings, reason: str) -> None:
        with self._lock:
            if self._record_id is not None:           # a new episode replaces the one waiting
                self._store.update(self._record_id, acknowledged_by="superseded")
            self.state, self.reason, self.problems, self._restored = State.STOPPING, reason, [], False
        self._record_id = self._store.open(self.scope, reason)
        logger.warning("Protective stop: %s", reason)
        self._publish(site, reason)
        await self._alert(f"Protective stop: {reason}. Stopping activity and parking.")

        problems = await self.activities.stop_all()
        for pier, guider in site.guiders:
            try:
                await asyncio.wait_for(guider.stop_guiding(), DEVICE_TIMEOUT_S)
            except Exception as exc:
                logger.exception("Pier %s: could not stop guiding", pier)
                problems.append(f"guiding on {pier} could not be stopped ({exc})")
        secure_problems, pending = await self._secure(site, settings)
        await self._finish(problems + secure_problems, pending)

    async def _secure(self, site: Site, settings: SafetySettings) -> tuple[list[str], bool]:
        """Park every mount, then close each roof whose mounts all confirm. Returns ``(problems, roof pending)``."""
        try:
            unparked = set(await park_roof_mounts(site.mounts))
        except Exception:
            logger.exception("Could not park the mounts")
            unparked = {name for name, _mount in site.mounts}
        problems = [f"the mount of {name} could not be confirmed parked" for name in sorted(unparked)]
        pending = bool(unparked)
        if not settings.close_roof:
            return problems, pending
        known = {name for name, _mount in site.mounts}
        for roof in site.roofs:
            blocking = [name for name, _m in roof.mounts if name in unparked or name not in known]
            if blocking:
                problems.append(roof_left_open_message(blocking))
                pending = True
                continue
            problem = await self._close(roof)
            if problem:
                problems.append(problem)
                pending = True
        return problems, pending

    @staticmethod
    async def _close(roof: Roof) -> str | None:
        try:
            if roof.before_close is not None:
                roof.before_close()
            await asyncio.wait_for(roof.dome.close_shutter(), SHUTTER_TIMEOUT_S)

            async def closed() -> None:
                while True:
                    status = roof.dome.get_status()
                    if inspect.isawaitable(status):
                        status = await status
                    if str(status.get("shutter_state", "")).lower() == "closed":
                        return
                    await asyncio.sleep(SHUTTER_POLL_S)

            await asyncio.wait_for(closed(), SHUTTER_TIMEOUT_S)
        except Exception as exc:
            logger.exception("Could not close %s", roof.name)
            return f"{roof.name} was not confirmed closed ({type(exc).__name__})"
        try:
            await asyncio.wait_for(roof.dome.park(), DEVICE_TIMEOUT_S)
        except Exception:
            logger.debug("%s: dome park failed or is not supported", roof.name, exc_info=True)
        return None

    async def _retry(self, site: Site, settings: SafetySettings, now: float) -> None:
        """SAFE-160: while the roof cannot be closed and it is still unsafe, keep trying and keep alerting."""
        if now - self._last_retry < settings.retry_s:
            return
        self._last_retry = now
        problems, pending = await self._secure(site, settings)
        if not pending:
            await self._finish(problems, False)
            return
        with self._lock:
            self.problems = problems
        if now - self._last_alert >= settings.realert_s:
            self._last_alert = now
            await self._alert("Still not secured: " + " ".join(problems))

    async def _finish(self, problems: list[str], pending: bool) -> None:
        now = self._clock()
        with self._lock:
            self.problems, self._roof_pending = problems, pending
            self.state = State.NOT_SECURED if problems else State.SECURED
            state = self.state
        self._last_retry = self._last_alert = now
        if self._record_id is not None:
            self._store.update(self._record_id, outcome=state.value, problems="\n".join(problems))
        if problems:
            await self._alert("Safety stop NOT complete: " + " ".join(problems))
        else:
            await self._alert("Safety stop complete: activity stopped and equipment secured.")

    # -- helpers ----------------------------------------------------------------------------------

    def _publish(self, site: Site, reason: str) -> None:
        try:
            from galileo.bus import SafetyUnsafeEvent, get_bus
            bus = self._bus or get_bus()
            for pier in [name for name, _mount in site.mounts] or [""]:
                bus.publish(SafetyUnsafeEvent(source=f"pier:{pier}", pier=pier, explanation=reason))
        except Exception:
            logger.exception("Could not publish the unsafe event")

    async def _alert(self, message: str) -> None:
        logger.warning("Safety: %s", message)
        if self._notify is None:
            return
        try:
            result = self._notify(message)
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, DEVICE_TIMEOUT_S)
        except Exception:
            logger.exception("Could not send a safety alert")

    # -- thread ------------------------------------------------------------------------------------

    def start(self, interval_s: float = TICK_S) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()

        def run() -> None:
            while not self._stop_event.is_set():
                try:
                    asyncio.run(self.tick())
                except Exception:
                    logger.exception("The safety check failed")
                self._wake.wait(interval_s)
                self._wake.clear()

        self._thread = threading.Thread(target=run, name="galileo-safety", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop_event.set()
        self._wake.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout_s)


__all__ = ["ActivityRegistry", "DatabaseStore", "Evaluator", "Level", "MemoryStore", "Roof", "SafetySettings",
           "SafetySupervisor", "Site", "Source", "State", "Verdict", "load_settings", "save_settings"]
