# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""HEAD — headless engine and the desktop as a client (TC-HEAD-010 ... TC-HEAD-180).

The engine (``galileo.engine``) is designed in SDD section 4.33 and not built yet, so each test is reserved
and skips while the module is missing. Once it exists, an unwritten test fails (``_pending``), so a
requirement cannot silently stay unverified.
"""

import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _pending(tc, module):
    """Skip while the module is missing; fail once it exists but the test is unwritten."""
    pytest.importorskip(module)
    pytest.fail(f"{tc}: {module} exists but this requirement has no test body yet")


@pytest.mark.requirement("TC-HEAD-010")
@pytest.mark.priority("MVP")
def test_tc_head_010_engine_main():
    """HEAD-010: the engine runs the domain core with no display and imports no module of PySide6."""
    code = (
        "import sys\n"
        "import galileo.engine, galileo.engine.main, galileo.engine.lock, galileo.engine.service\n"
        "bad = sorted(m for m in sys.modules if m == 'PySide6' or m.startswith('PySide6.') or m.startswith('galileo.ui'))\n"
        "print('BAD:' + ','.join(bad))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=REPO,  # noqa: S603 -- this interpreter on a fixed snippet
                         env={**os.environ, "PYTHONPATH": str(REPO)})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "BAD:", out.stdout


def test_tc_head_010_engine_starts_and_stops_in_order(tmp_path, monkeypatch):
    """HEAD-010: start opens the database and loads plugins; stop releases everything."""
    from galileo.engine import Engine, EngineLock
    calls = []
    monkeypatch.setattr("galileo.library.database.init_db", lambda *a, **k: calls.append("db"))
    monkeypatch.setattr("galileo.plugins.PluginManager.initialize_from_disk", lambda self: calls.append("plugins"))
    monkeypatch.setattr("galileo.crashreport.install_crash_handlers", lambda *a, **k: calls.append("crash"))
    monkeypatch.setattr(Engine, "_start_devices", lambda self: calls.append("devices"))    # HEAD-040 has its own test
    monkeypatch.setattr(Engine, "_stop_link", staticmethod(lambda: calls.append("link-stop")))
    monkeypatch.setattr(Engine, "_stop_workers", staticmethod(lambda: calls.append("workers-stop")))
    engine = Engine(EngineLock(tmp_path))
    engine.start()
    assert calls == ["crash", "db", "plugins", "devices"] and engine.lock.held
    engine.stop()
    assert calls[-2:] == ["link-stop", "workers-stop"] and not engine.lock.held


def test_tc_head_010_stop_survives_a_failing_step(tmp_path, monkeypatch):
    """HEAD-010: one failing stop step neither skips the rest nor keeps the lock."""
    from galileo.engine import Engine, EngineLock
    ran = []

    def boom():
        raise RuntimeError("link failed")

    monkeypatch.setattr(Engine, "_stop_link", staticmethod(boom))
    monkeypatch.setattr(Engine, "_stop_workers", staticmethod(lambda: ran.append("workers")))
    engine = Engine(EngineLock(tmp_path))
    engine.lock.acquire()
    engine.stop()
    assert ran == ["workers"] and not engine.lock.held


@pytest.mark.requirement("TC-HEAD-020")
@pytest.mark.priority("MVP")
def test_tc_head_020_engine_lock(tmp_path):
    """HEAD-020: at most one engine per machine and database; a second is refused and the holder is named."""
    from galileo.engine import EngineAlreadyRunning, EngineLock
    first, second = EngineLock(tmp_path), EngineLock(tmp_path)
    first.acquire(role="engine")
    with pytest.raises(EngineAlreadyRunning) as err:
        second.acquire()
    assert err.value.holder["pid"] == os.getpid() and str(os.getpid()) in str(err.value)
    assert not second.held
    first.release()
    second.acquire()
    assert second.held
    second.release()
    second.release()                      # idempotent


def test_tc_head_020_a_dead_engine_does_not_block_the_next(tmp_path):
    """HEAD-020: the lock belongs to the process, so a crashed engine leaves nothing to clean up."""
    from galileo.engine import EngineLock
    code = ("from galileo.engine import EngineLock\n"
            f"l = EngineLock({str(tmp_path)!r}); l.acquire(); print('held', flush=True)\n"
            "import os; os._exit(0)\n")      # exit without releasing
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=REPO,  # noqa: S603 -- this interpreter on a fixed snippet
                         env={**os.environ, "PYTHONPATH": str(REPO)})
    assert "held" in out.stdout, out.stderr
    lock = EngineLock(tmp_path)
    lock.acquire()
    assert lock.held
    lock.release()


def test_tc_head_020_main_refuses_a_second_engine(tmp_path, monkeypatch, capsys):
    """HEAD-020: ``Galileo --engine`` against a running engine exits with the already-running code and says why."""
    from galileo.engine import EXIT_ALREADY_RUNNING, EngineLock
    from galileo.engine import main as engine_main
    monkeypatch.setattr(sys.modules["galileo.engine.main"], "EngineLock", lambda: EngineLock(tmp_path))
    monkeypatch.setattr("galileo.diagnostics.DiagnosticsService", lambda *a, **k: None)
    holder = EngineLock(tmp_path)
    holder.acquire()
    try:
        assert engine_main() == EXIT_ALREADY_RUNNING
    finally:
        holder.release()
    assert "already running" in capsys.readouterr().err


@pytest.mark.requirement("TC-HEAD-030")
@pytest.mark.priority("MVP")
def test_tc_head_030_engine_service():
    """HEAD-030: foreground service run: start, ready, wait for SIGTERM/SIGINT, stop in order, exit code."""
    from galileo.engine import EXIT_FAILURE, EXIT_OK, StopSignal, run_until_stopped
    order = []
    stopper = StopSignal()
    threading.Timer(0.2, lambda: stopper.request("SIGTERM")).start()
    assert run_until_stopped(lambda: order.append("start"), lambda: order.append("stop"), stopper) == EXIT_OK
    assert order == ["start", "stop"] and stopper.signal_name == "SIGTERM"

    def broken():
        raise RuntimeError("no database")

    order.clear()
    assert run_until_stopped(broken, lambda: order.append("stop"), StopSignal()) == EXIT_FAILURE
    assert order == ["stop"], "a failed start still stops what it started"
    done = StopSignal()
    done.request("test")
    assert run_until_stopped(lambda: None, broken, done) == EXIT_FAILURE


@pytest.mark.skipif(sys.platform == "win32" or not hasattr(socket, "AF_UNIX"), reason="needs a Unix datagram socket")
def test_tc_head_030_sd_notify_reaches_systemd(tmp_path, monkeypatch):
    """HEAD-030: readiness is signalled to systemd through NOTIFY_SOCKET."""
    from galileo.engine import sd_notify
    path = str(tmp_path / "notify")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    srv.bind(path)
    srv.settimeout(2)
    monkeypatch.setenv("NOTIFY_SOCKET", path)
    assert sd_notify("READY=1") is True
    assert srv.recv(64) == b"READY=1"
    srv.close()


def test_tc_head_030_sd_notify_is_silent_outside_systemd(monkeypatch):
    """HEAD-030: outside systemd, sd_notify does nothing."""
    from galileo.engine import sd_notify
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert sd_notify("READY=1") is False


def test_tc_head_030_app_routes_engine_flag(monkeypatch):
    """HEAD-030: ``Galileo --engine`` reaches the engine before any Qt import."""
    import galileo.app as app
    seen = {}

    def fake(argv=None):
        seen["argv"] = argv
        return 7

    monkeypatch.setattr("galileo.engine.main", fake)
    monkeypatch.setattr(sys, "argv", ["Galileo", "--engine", "--x"])
    with pytest.raises(SystemExit) as ex:
        app.main()
    assert seen["argv"] == ["--x"] and ex.value.code == 7


@pytest.mark.requirement("TC-HEAD-040")
@pytest.mark.priority("MVP")
def test_tc_head_040_engine_devices(tmp_path):
    """HEAD-040: a screen-free device service connects each Pier's profile (auto-connect only where asked), holds
    controllers per Pier, publishes connection changes, isolates a failing device, and is the Control Surface's
    DeviceAccess."""
    import asyncio

    from galileo.bus import DeviceConnectedEvent, DeviceDisconnectedEvent, DeviceErrorEvent, EventBus
    from galileo.engine.devices import DeviceService
    from galileo.library.database import db, init_db
    from galileo.observatory import (
        create_observatory,
        create_pier,
        list_observatories,
        save_device_config,
        set_pier_connect_on_startup,
    )

    init_db(tmp_path / "head.db")
    try:
        obs = create_observatory("Home")
        auto, manual = create_pier(obs, "Auto"), create_pier(obs, "Manual")
        set_pier_connect_on_startup(manual, False)
        for p in (auto, manual):
            save_device_config(p, "mount", driver="INDI", server="h", port=7624, device_name="EQ6")
        save_device_config(auto, "focuser", driver="INDI", server="h", port=7624, device_name="Broken")
        assert list_observatories()

        class Fake:
            def __init__(self, name):
                self.name, self.is_connected = name, False
            async def connect(self):
                if self.name == "Broken":
                    raise ConnectionError("no such device")
                self.is_connected = True
            async def disconnect(self):
                self.is_connected = False
            async def push_context(self, **kw):
                self.context = kw

        bus = EventBus()
        seen = []
        for ev in (DeviceConnectedEvent, DeviceDisconnectedEvent, DeviceErrorEvent):
            bus.subscribe(ev, lambda e, ev=ev: seen.append((ev.__name__, e.payload["pier"])))
        svc = DeviceService(bus, factory=lambda cat, drv, srv, port, name: Fake(name))
        ids = svc.load_piers()
        assert len(ids) == 2
        results = asyncio.run(svc.connect_startup_piers())
        assert list(results) == [str(auto.id)]                          # the other Pier asked not to auto-connect
        a = str(auto.id)
        assert results[a]["mount/primary"] is True and results[a]["focuser/primary"] is False    # isolated
        assert svc.controller(a, "mount").is_connected and svc.controller(a, "focuser") is None
        assert svc.controller(str(manual.id), "mount") is None
        assert svc.connected(a) == ["mount/primary"] and hasattr(svc.controller(a, "mount"), "context")
        assert ("DeviceConnectedEvent", a) in seen and ("DeviceErrorEvent", a) in seen
        asyncio.run(svc.connect_pier(str(manual.id)))                    # an explicit connect still works
        assert svc.controller(str(manual.id), "mount").is_connected
        asyncio.run(svc.disconnect_all())
        assert svc.connected(a) == [] and ("DeviceDisconnectedEvent", a) in seen
        assert svc.manual_focus(a) is None and svc.stop_session(a) is None
    finally:
        if not db.is_closed():
            db.close()
        db.init(None)


@pytest.mark.requirement("TC-HEAD-050")
@pytest.mark.priority("MVP")
def test_tc_head_050_engine_runner():
    """HEAD-050: one asyncio runner runs sessions with no Qt, one per Pier and Piers concurrently, publishing start,
    progress and finish on the bus; the desktop's worker thread calls the same run_session."""
    import asyncio as aio
    import threading as th
    import time

    from galileo.bus import EventBus
    from galileo.engine.runner import (
        RunnerBusy,
        SessionFinishedEvent,
        SessionProgressEvent,
        SessionRunner,
        SessionStartedEvent,
        run_session,
    )

    class Result:
        state = "completed"
        frames_captured = 3

    class Exec:
        def __init__(self):
            self.cb, self.release, self.stopped = None, th.Event(), False

        def set_progress_callback(self, cb):
            self.cb = cb

        def stop(self):
            self.stopped = True
            self.release.set()

        pause = resume = lambda self: None

        async def run(self, blocks):
            self.cb("half")
            while not self.release.is_set():  # noqa: ASYNC110 - a fake that polls a threading.Event
                await aio.sleep(0.01)
            r = Result()
            r.state = "stopped" if self.stopped else "completed"
            return r

    bus, seen = EventBus(), []
    for ev in (SessionStartedEvent, SessionProgressEvent, SessionFinishedEvent):
        bus.subscribe(ev, lambda e, ev=ev: seen.append((ev.__name__, e.payload["pier"])))
    runner = SessionRunner(bus)
    a, b = Exec(), Exec()
    runner.start("1", "M31", a, [])
    runner.start("2", "M42", b, [])                          # another Pier runs at the same time
    with pytest.raises(RunnerBusy):
        runner.start("1", "again", Exec(), [])
    deadline = time.time() + 5
    while not (a.cb and b.cb) and time.time() < deadline:
        time.sleep(0.01)
    assert runner.is_running("1") and runner.is_running("2") and len(runner.snapshot()) == 2
    a.release.set()                                          # Pier 1 completes by itself
    while runner.is_running("1") and time.time() < deadline:
        time.sleep(0.01)
    assert not runner.is_running("1") and runner.is_running("2")
    assert runner.stop("2") and not runner.stop("9")
    runner.shutdown()
    names = [n for n, _p in seen]
    assert names.count("SessionStartedEvent") == 2 and names.count("SessionFinishedEvent") == 2
    assert ("SessionProgressEvent", "1") in seen and not runner.is_running()
    state, result = aio.run(run_session(_Quick(), []))
    assert state == "completed" and result.frames_captured == 3
    state, _ = aio.run(run_session(_Failing(), []))
    assert state == "error"


class _Quick:
    async def run(self, blocks):
        class R:
            state = "completed"
            frames_captured = 3
        return R()


class _Failing:
    async def run(self, blocks):
        raise RuntimeError("device lost")


@pytest.mark.requirement("TC-HEAD-060")
@pytest.mark.priority("MVP")
def test_tc_head_060_engine_helpers():
    """HEAD-060: the engine polls mount pointing, waits out a slew then tracks, and records weather, publishing the
    results as Control Surface state that any client reads; an unreadable device is forgotten, not fatal."""
    import asyncio as aio

    from galileo.control_surface import ObservableState
    from galileo.engine.helpers import Helpers

    class Mount:
        is_connected = True
        def __init__(self):
            self.slewing, self.rate = True, None
        async def get_status(self):
            return {"right_ascension": 6.0, "declination": 10.0, "slewing": self.slewing, "equatorial_system": "J2000"}
        async def is_slewing(self):
            return self.slewing
        async def set_tracking_rate(self, rate):
            self.rate = rate
        async def set_tracking(self, on):
            self.tracking = on

    class Weather:
        is_connected = True
        temperature = 4.0
        async def poll(self):
            pass

    class Devices:
        def __init__(self):
            self.mount, self.weather = Mount(), Weather()
        def pier_ids(self):
            return ["1", "2"]
        def controller(self, pier, category):
            if pier == "1":
                return {"mount": self.mount}.get(category)
            return None

    devices, state = Devices(), ObservableState()
    h = Helpers(devices, state)
    aio.run(h.poll_pointing())
    pos = state.read("1", "mount.position")
    assert abs(pos["ra_deg"] - 90.0) < 1e-6 and pos["slewing"] and state.read("2", "mount.position") is None
    devices.mount.slewing = False
    aio.run(h.poll_pointing())
    assert state.read("1", "mount.position")["slewing"] is False

    class Broken(Mount):
        async def get_status(self):
            raise OSError("gone")
    devices.mount = Broken()
    aio.run(h.poll_pointing())
    assert state.read("1", "mount.position") is None                 # forgotten, not fatal

    devices.controller = lambda pier, cat: devices.weather if (pier == "1" and cat == "weather") else None
    aio.run(h.poll_weather())
    assert state.read("1", "weather.readings")["temperature"] == 4.0 and len(h.weather_history("1")) == 1
    h.start()
    try:
        assert h.slew_then_track("2") is None                         # no mount: nothing to wait for
    finally:
        h.stop()


class _FakeEngine:
    """Stands in for Engine: takes the real lock, publishes a channel like the real one, records stop."""

    def __init__(self, lock):
        self.lock, self.stopped = lock, False
        self.runner = type("R", (), {"running": False, "is_running": lambda s, pier=None: s.running})()

    def start(self):
        self.lock.acquire(role="engine")
        self.lock.update(channel={"address": "http://127.0.0.1:1", "token": "t", "protocol": "1"})

    def stop(self):
        self.stopped = True
        self.lock.release()


@pytest.mark.requirement("TC-HEAD-090")
@pytest.mark.priority("MVP")
def test_tc_head_090_engine_embedded(tmp_path):
    """HEAD-090: with no engine running the desktop hosts one, holding the lock; a second desktop on the machine
    attaches as a client instead of starting another."""
    from galileo.engine import EngineLock
    from galileo.engine.embedded import ATTACHED, HOSTING, attach_or_host

    first = attach_or_host("1.0", EngineLock(tmp_path), _FakeEngine)
    assert first.mode == HOSTING and first.hosting and first.engine.lock.held and first.client is None
    second = attach_or_host("1.0", EngineLock(tmp_path), _FakeEngine)
    assert second.mode == ATTACHED and second.engine is None
    assert second.client.address == "http://127.0.0.1:1" and second.client._token == "t"
    first.close()
    third = attach_or_host("1.0", EngineLock(tmp_path), _FakeEngine)               # the lock is free again
    assert third.hosting
    third.close()


def test_tc_head_090_lock_held_without_channel_is_refused(tmp_path):
    """HEAD-090: a lock held by something that published no channel is refused, naming the holder."""
    from galileo.engine import EngineAlreadyRunning, EngineLock
    from galileo.engine.embedded import attach_or_host

    holder = EngineLock(tmp_path)
    holder.acquire(role="engine")
    try:
        with pytest.raises(EngineAlreadyRunning) as err:
            attach_or_host("1.0", EngineLock(tmp_path), _FakeEngine)
        assert "already running" in str(err.value)
    finally:
        holder.release()


@pytest.mark.requirement("TC-HEAD-100")
@pytest.mark.priority("P2")
def test_tc_head_100_engine_client(tmp_path):
    """HEAD-100: closing an attached desktop leaves the engine alone; closing a hosting one asks first while a
    session runs, then stops the engine."""
    from galileo.engine import EngineLock
    from galileo.engine.embedded import attach_or_host

    host = attach_or_host("1.0", EngineLock(tmp_path), _FakeEngine)
    guest = attach_or_host("1.0", EngineLock(tmp_path), _FakeEngine)
    assert guest.close() is True and not host.engine.stopped and host.engine.lock.held    # nothing of the engine's stops
    host.engine.runner.running = True
    assert host.needs_confirmation()
    assert host.close() is False and not host.engine.stopped                           # asks; does nothing yet
    assert host.close(confirmed=True) is True and host.engine.stopped
    idle = attach_or_host("1.0", EngineLock(tmp_path), _FakeEngine)
    assert not idle.needs_confirmation() and idle.close() is True and idle.engine.stopped   # no session: no question


@pytest.fixture
def fake_settings(monkeypatch):
    """The settings store as a dict, so the engine's configuration is read the way it is in production (via the
    store) without a database."""
    data = {}
    monkeypatch.setattr("galileo.settings_store.get_namespace",
                        lambda ns, scope="": {k: v for (n, k), v in data.items() if n == ns})
    monkeypatch.setattr("galileo.settings_store.get_setting", lambda ns, key, default=None, scope="": data.get((ns, key), default))
    monkeypatch.setattr("galileo.settings_store.set_setting", lambda ns, key, value, scope="": data.__setitem__((ns, key), value) or True)
    return data


@pytest.mark.requirement("TC-HEAD-130")
@pytest.mark.priority("MVP")
def test_tc_head_130_engine_config(fake_settings, monkeypatch):
    """HEAD-130: the engine reads its configuration from the settings store, reloads it on the settings-changed
    event, and a remote client cannot change configuration."""
    from galileo.control_surface import OperationSpec, Registry
    from galileo.control_surface.registry import RegistrationError
    from galileo.engine import Engine
    from galileo.engine.config import DEFAULT_RETRY_LIMIT, load_config

    assert load_config().retry_limit == DEFAULT_RETRY_LIMIT and load_config().observatory == ""
    fake_settings[("engine", "observatory")] = "Home"
    fake_settings[("engine", "retry_limit")] = 2
    fake_settings[("engine", "retry_interval_s")] = "bad"                        # unreadable falls back
    cfg = load_config()
    assert (cfg.observatory, cfg.retry_limit, cfg.retry_interval_s) == ("Home", 2, 30.0)

    engine = Engine.__new__(Engine)                                                # only the reload is under test
    engine.config = cfg
    fake_settings[("engine", "retry_limit")] = 9
    from galileo.replication import SettingsChanged
    engine._on_settings_changed(SettingsChanged("replication", tables=["settings"]))
    assert engine.config.retry_limit == 9                                          # an Options change reached the engine

    with pytest.raises(RegistrationError):
        Registry().register(OperationSpec("site.edit", "config"), lambda ctx, args: None)   # CSURF-020


@pytest.mark.requirement("TC-HEAD-140")
@pytest.mark.priority("MVP")
def test_tc_head_140_engine_config(fake_settings, monkeypatch):
    """HEAD-140: the engine runs the configured Observatory, else the last one the desktop used, else the first;
    it reports a Pier that will not connect and keeps retrying within its limit."""
    import asyncio as aio

    from galileo.engine.config import EngineConfig, remember_observatory, resolve_observatory
    from galileo.engine.devices import DeviceService

    names = ["Home", "Remote"]
    assert resolve_observatory(EngineConfig(), names) == "Home"                    # nothing stored: the first
    remember_observatory("Remote")
    assert resolve_observatory(EngineConfig(), names) == "Remote"                  # the desktop's last choice
    assert resolve_observatory(EngineConfig(observatory="Home"), names) == "Home"  # the stored setting wins
    assert resolve_observatory(EngineConfig(observatory="Gone"), names) == "Remote"
    assert resolve_observatory(EngineConfig(), []) is None

    class Obs:
        def __init__(self, name):
            self.name = name

    class PierRec:
        def __init__(self, id_, name):
            self.id, self.name, self.connect_on_startup = id_, name, True

    monkeypatch.setattr("galileo.observatory.list_observatories", lambda: [Obs("Home"), Obs("Remote")])
    monkeypatch.setattr("galileo.observatory.list_piers",
                        lambda o: [PierRec(1 if o.name == "Home" else 2, o.name + " pier")])
    svc = DeviceService(bus=None, factory=None)
    assert svc.load_piers("Remote") == ["2"] and svc.load_piers() == ["1", "2"]
    svc.load_piers("Home")

    tries = []

    async def flaky(pier):
        tries.append(pier)
        return {"mount/primary": len(tries) >= 3}                                  # fails twice, then connects
    monkeypatch.setattr(svc, "connect_pier", flaky)
    aio.run(svc.connect_startup_piers(retry_limit=0))
    assert svc.problems == {"1": ["mount/primary"]} and len(tries) == 1            # reported, not retried
    tries.clear()
    aio.run(svc.connect_startup_piers(retry_limit=5, retry_interval_s=0.01))
    assert len(tries) == 3 and svc.problems == {}                                  # retried until it connected
    tries.clear()
    monkeypatch.setattr(svc, "connect_pier", lambda pier: flaky_never(tries))
    aio.run(svc.connect_startup_piers(retry_limit=2, retry_interval_s=0.01))
    assert len(tries) == 3 and svc.problems == {"1": ["mount/primary"]}            # gives up at the limit, still reported


async def flaky_never(tries):
    tries.append(1)
    return {"mount/primary": False}


@pytest.mark.requirement("TC-HEAD-150")
@pytest.mark.priority("P2")
def test_tc_head_150_engine_service():
    """HEAD-150: the Astroberry package's unit runs the engine as the imaging user, after the INDI services, with
    back-off and a start limit, notifying readiness. Reads the unit from the sibling galileo-astroberry repo."""
    unit = REPO.parent / "galileo-astroberry" / "packaging" / "systemd" / "galileo-engine.service"
    if not unit.exists():
        pytest.skip("the galileo-astroberry repository is not alongside this one")
    text = unit.read_text(encoding="utf-8")
    keys: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            keys[k.strip()] = v.strip()
    assert keys["ExecStart"].endswith("galileo --engine") and keys["User"]
    assert keys["Type"] == "notify" and keys["Restart"] == "on-failure"
    assert "indi" in keys["After"] and "network-online.target" in keys["After"]
    assert int(keys["RestartSec"]) >= 5 and int(keys["StartLimitBurst"]) <= 10 and int(keys["StartLimitIntervalSec"]) >= 60
    from galileo.engine.service import EXIT_ALREADY_RUNNING
    assert keys["RestartPreventExitStatus"] == str(EXIT_ALREADY_RUNNING)            # no point restarting a refused engine
    assert keys["WantedBy"] == "multi-user.target"


class _Mount:
    is_connected = True

    def __init__(self):
        self.parked = 0

    async def park(self):
        self.parked += 1


class _Monitor:
    is_connected = True

    def __init__(self):
        self.is_safe, self.explanation, self.fail = True, "", False

    async def poll(self):
        if self.fail:
            raise OSError("no answer")


def _guard_world():
    from galileo.engine.guard import Guard

    mount, monitor, stopped, events = _Mount(), _Monitor(), [], []

    class Devices:
        def pier_ids(self):
            return ["1"]

        def controller(self, pier, category, slot="primary"):
            return {"mount": mount, "safety": monitor}.get(category)

    class Runner:
        def stop(self, pier):
            stopped.append(pier)
            return True

    class Bus:
        def publish(self, event):
            events.append(event)
    return Guard(Devices(), Runner(), bus=Bus()), mount, monitor, stopped, events


@pytest.mark.requirement("TC-HEAD-160")
@pytest.mark.priority("MVP")
def test_tc_head_160_engine_main():
    """HEAD-160: with no desktop or client attached, an unsafe monitor stops the Pier's session, parks its mount
    and raises the unsafe event once per episode; the watchdog trips on a missing heartbeat and parks every mount."""
    import asyncio as aio
    import time

    guard, mount, monitor, stopped, events = _guard_world()
    aio.run(guard.check_once())
    assert not guard.unsafe and not stopped and mount.parked == 0                   # safe: nothing happens
    monitor.is_safe, monitor.explanation = False, "rain"
    aio.run(guard.check_once())
    aio.run(guard.check_once())
    assert guard.unsafe == {"1": "rain"} and stopped == ["1"] and mount.parked == 1  # acted once, not every poll
    assert len(events) == 1 and events[0].explanation == "rain"
    monitor.is_safe = True
    aio.run(guard.check_once())
    assert not guard.unsafe                                                         # the episode ends; no auto-resume
    monitor.is_safe = False
    aio.run(guard.check_once())
    assert mount.parked == 2                                                        # a new episode acts again
    monitor.is_safe = True
    aio.run(guard.check_once())
    monitor.fail = True                                                             # an unreadable monitor is unsafe
    aio.run(guard.check_once())
    assert "could not be read" in guard.unsafe["1"] and mount.parked == 3

    # the watchdog is the engine's own, armed with no client attached, and parks every Pier's mount when it trips
    import galileo.watchdog_settings as ws
    from galileo.engine.guard import build_watchdog
    mount2 = _Mount()

    class Devices2:
        def pier_ids(self):
            return ["1"]

        def controller(self, pier, category, slot="primary"):
            return mount2 if category == "mount" else None
    orig = ws.load_watchdog_settings
    ws.load_watchdog_settings = lambda: {"enabled": True, "timeout_s": 60.0}
    try:
        wd = build_watchdog(Devices2())
        ws.load_watchdog_settings = lambda: {"enabled": False, "timeout_s": 60.0}
        assert build_watchdog(Devices2()) is None                                   # switched off in the settings
    finally:
        ws.load_watchdog_settings = orig
    wd.timeout_s = 0.2
    wd.start()
    try:
        for _ in range(100):
            if wd.tripped and mount2.parked:                                        # `tripped` is set just before the park
                break
            time.sleep(0.05)
        assert wd.tripped and mount2.parked == 1
    finally:
        wd.stop_sync()
    g2, *_ = _guard_world()
    g2.watchdog = type("W", (), {"tripped": False, "status": "armed", "beats": 0, "start": lambda s: None,
                                 "stop_sync": lambda s: None,
                                 "heartbeat": lambda s: setattr(s, "beats", s.beats + 1)})()
    g2.start()
    time.sleep(0.3)
    g2.stop()
    assert g2.watchdog.beats >= 1 and g2.status()["watchdog"] == "armed"            # the guard's loop beats it


@pytest.mark.requirement("TC-HEAD-170")
@pytest.mark.priority("P2")
def test_tc_head_170_engine_main(tmp_path, capsys):
    """HEAD-170: `--engine --status` reports running or not, version, Piers and their devices, sessions and
    listeners, read-only, with an exit code a supervisor can use."""
    import asyncio as aio

    from galileo.engine import EngineLock
    from galileo.engine.status import EXIT_NOT_RUNNING, fetch_status, format_status, status_main

    assert status_main(directory=tmp_path) == EXIT_NOT_RUNNING
    assert "not running" in capsys.readouterr().out
    channel, leases, *_ = _channel_world(tmp_path)
    channel._status_extra = lambda: {"sessions": [{"pier": "1", "name": "M31", "state": "running"}]}
    lock = EngineLock(tmp_path)
    lock.acquire(role="engine")

    async def go():
        info = await channel.start()
        try:
            lock.update(channel=info)
            leases.acquire("1", "desktop")
            return await fetch_status(tmp_path)
        finally:
            await channel.stop()
    status = aio.run(go())
    lock.release()
    assert status["running"] and status["version"] == "9.9.9" and status["pid"] == os.getpid()
    assert status["piers"][0]["lease"] == "desktop" and status["sessions"][0]["name"] == "M31"
    text = format_status(status)
    assert "running (version 9.9.9" in text and "mount/primary" in text and "M31" in text and "Listening on:" in text
    assert leases.holder("1") == "desktop"                                              # reading changed nothing


# --- the local channel and the attached client (HEAD-070, 080, 110, 120, 180) -------------------------------------

def _channel_world(tmp_path):
    """A real EngineChannel over a registry with one operation, plus the pieces a test inspects."""
    from galileo.bus import EventBus
    from galileo.connect_link.audit import AuditLog
    from galileo.connect_link.gateway import Gateway
    from galileo.control_surface import LeaseBroker, ObservableState, OperationSpec, Registry
    from galileo.engine.channel import EngineChannel

    class Devices:
        def pier_name(self, pier):
            return "North"

        def pier_ids(self):
            return ["1"]

        def connected(self, pier):
            return ["mount/primary"]

    calls = []
    registry = Registry()
    registry.register(OperationSpec("test.move", "operate", needs_lease=True),
                      lambda ctx, args: calls.append(ctx.pier) or "moved")
    registry.register(OperationSpec("test.look", "read"), lambda ctx, args: "seen")
    bus, state = EventBus(), ObservableState()
    leases = LeaseBroker(bus=bus)

    class Audit(AuditLog):
        def __init__(self):
            super().__init__()
            self.rows = []

        def write(self, actor, plugin, route, outcome, reason="", **kw):
            self.rows.append((actor, route, outcome))
            return True
    audit = Audit()
    channel = EngineChannel(registry=registry, leases=leases, gateway=Gateway(registry, leases, audit), state=state,
                            devices=Devices(), bus=bus, version="9.9.9", directory=tmp_path / "ch")
    return channel, leases, state, audit, calls, bus


@pytest.mark.requirement("TC-HEAD-080")
@pytest.mark.priority("MVP")
def test_tc_head_080_engine_channel(tmp_path):
    """HEAD-080: operations arrive over the local channel, need the engine's token, pass the same Gateway (lease,
    audit as desktop), and the channel is owner-only."""
    import asyncio as aio

    from galileo.engine.client import EngineClient, EngineUnreachable

    channel, _leases, _state, audit, calls, _bus = _channel_world(tmp_path)

    async def go():
        info = await channel.start()
        try:
            client = EngineClient(info["address"], info["token"], "9.9.9")
            await client.attach()
            assert (await client.invoke("test.look", "1"))["status"] == "ok"
            refused = await client.invoke("test.move", "1")
            assert refused["status"] == "refused" and "control of this Pier" in refused["reason"]     # the Gateway's own rule
            assert (await client.acquire_lease("1"))["granted"]
            assert (await client.invoke("test.move", "1"))["status"] == "ok" and calls == ["1"]
            assert ("desktop", "op test.move", "ok") in audit.rows                       # audited as desktop
            await client.close()
            stranger = EngineClient(info["address"], "not-the-token", "9.9.9")
            with pytest.raises(EngineUnreachable):
                await stranger.piers()
            await stranger.close()
        finally:
            await channel.stop()
    aio.run(go())
    if sys.platform != "win32":
        assert (tmp_path / "ch").stat().st_mode & 0o077 == 0


@pytest.mark.requirement("TC-HEAD-070")
@pytest.mark.priority("MVP")
def test_tc_head_070_engine_client(tmp_path):
    """HEAD-070: the attached desktop lists the engine's Piers, holds the lease as `desktop`, reads state and
    mirrors the engine's events."""
    import asyncio as aio

    from galileo.engine.client import EngineClient

    channel, leases, state, _audit, _calls, _bus = _channel_world(tmp_path)

    async def go():
        info = await channel.start()
        got = []
        client = EngineClient(info["address"], info["token"], "9.9.9", on_event=got.append)
        try:
            await client.attach()
            piers = await client.piers()
            assert piers == [{"id": "1", "name": "North", "connected": ["mount/primary"], "lease": ""}]
            assert any(o["name"] == "test.move" for o in (await client.catalogue("1"))["operations"])
            await client.start_events()
            await aio.sleep(0.2)
            state.publish("1", "mount.position", {"ra_deg": 1.0})
            assert (await client.acquire_lease("1"))["holder"] == "desktop" and leases.holder("1") == "desktop"
            for _ in range(100):
                if any(m.get("type") == "lease" for m in got):
                    break
                await aio.sleep(0.05)
            assert any(m.get("type") == "lease" and m["holder"] == "desktop" for m in got)
            assert (await client.state("1"))["values"]["mount.position"] == {"ra_deg": 1.0}
            assert (await client.release_lease("1"))["released"] and leases.holder("1") == ""
        finally:
            await client.close()
            await channel.stop()
    aio.run(go())


@pytest.mark.requirement("TC-HEAD-110")
@pytest.mark.priority("MVP")
def test_tc_head_110_engine_client(tmp_path):
    """HEAD-110: the engine owns the one lease per Pier; a remote holder shows to the attached desktop, which can
    take over only after confirming."""
    import asyncio as aio

    from galileo.engine.client import EngineClient

    channel, leases, _state, _audit, _calls, _bus = _channel_world(tmp_path)

    async def go():
        info = await channel.start()
        client = EngineClient(info["address"], info["token"], "9.9.9")
        try:
            leases.acquire("1", "webconnect:tablet")
            assert (await client.piers())[0]["lease"] == "webconnect:tablet"
            denied = await client.acquire_lease("1")
            assert not denied["granted"] and denied["holder"] == "webconnect:tablet" and denied["can_take_over"]
            assert not (await client.take_lease("1", confirmed=False))["granted"]
            taken = await client.take_lease("1", confirmed=True)
            assert taken["granted"] and leases.holder("1") == "desktop"
        finally:
            await client.close()
            await channel.stop()
    aio.run(go())


@pytest.mark.requirement("TC-HEAD-120")
@pytest.mark.priority("MVP")
def test_tc_head_120_engine_client(tmp_path):
    """HEAD-120: when the engine goes away the client says so, keeps its last values, marks them stale and can retry
    once the engine is back; it starts nothing itself."""
    import asyncio as aio

    from galileo.engine.client import EngineClient, EngineUnreachable

    channel, _leases, state, _audit, _calls, _bus = _channel_world(tmp_path)

    async def go():
        info = await channel.start()
        seen = []
        client = EngineClient(info["address"], info["token"], "9.9.9", on_event=seen.append)
        await client.attach()
        await client.start_events()
        state.publish("1", "weather.readings", {"temperature": 4.0})
        await client.state("1")
        assert not client.stale
        await channel.stop()                                           # the engine goes away
        with pytest.raises(EngineUnreachable):
            await client.piers()
        for _ in range(100):
            if client.stale:
                break
            await aio.sleep(0.05)
        assert client.stale and client.last_state["1"]["weather.readings"] == {"temperature": 4.0}
        assert {"type": "stale"} in seen
        info2 = await channel.start()                                  # ... and comes back (a new port/token)
        client.address, client._token = info2["address"], info2["token"]
        await client.retry()
        assert not client.stale
        await client.close()
        await channel.stop()
    aio.run(go())


@pytest.mark.requirement("TC-HEAD-180")
@pytest.mark.priority("MVP")
def test_tc_head_180_engine_channel(tmp_path):
    """HEAD-180: a version or protocol mismatch on attach is refused with a message naming both versions."""
    import asyncio as aio

    from galileo.engine.client import EngineClient, EngineMismatch

    channel, *_ = _channel_world(tmp_path)

    async def go():
        info = await channel.start()
        try:
            old = EngineClient(info["address"], info["token"], "1.0.0")
            with pytest.raises(EngineMismatch) as err:
                await old.attach()
            assert "9.9.9" in str(err.value) and "1.0.0" in str(err.value)
            await old.close()
        finally:
            await channel.stop()
    aio.run(go())


@pytest.mark.requirement("TC-HEAD-040")
@pytest.mark.priority("MVP")
def test_tc_head_040_desktop_holds_devices_in_the_service_when_enabled(fake_settings):
    """HEAD-040: with the setting on, a screen's Connect builds the device through the device service, which holds it
    per Pier and slot and announces it; a disconnect releases it; with the setting off (the default) the service is
    not used at all."""
    import asyncio
    from types import SimpleNamespace

    from galileo import desktop_devices
    from galileo.bus import DeviceConnectedEvent, DeviceDisconnectedEvent, EventBus
    from galileo.core.devices import DeviceCategory
    from galileo.device_ops import DeviceOps
    from galileo.engine.devices import DeviceService

    class Adapter:
        def __init__(self, *args):
            self.args = args
            self.is_connected = False
            self.configured = False
            self.disconnected = False

        async def connect(self):
            self.is_connected = True

        async def disconnect(self):
            self.disconnected = True

    class Broken(Adapter):
        async def connect(self):
            raise RuntimeError("no route")

    bus = EventBus()
    seen = []
    bus.subscribe(DeviceConnectedEvent, seen.append)
    bus.subscribe(DeviceDisconnectedEvent, seen.append)
    desktop_devices.reset()
    try:
        assert desktop_devices.enabled() is False                                      # off by default
        desktop_devices.forget(object())                                              # no service yet: harmless

        service = DeviceService(bus=bus, factory=lambda *a: Adapter(*a))
        desktop_devices._service = service
        pier = SimpleNamespace(id=7, name="East")

        assert desktop_devices.set_enabled(True) and desktop_devices.enabled() is True
        adapter = desktop_devices.connect(pier, DeviceCategory.FOCUSER, "focuser_2", "INDI", "pi", 7624, "Focuser",
                                          configure=lambda a: setattr(a, "configured", True))
        assert adapter.is_connected and adapter.configured
        assert adapter.args == (DeviceCategory.FOCUSER, "INDI", "pi", 7624, "Focuser")
        assert service.controller("7", "focuser", "focuser_2") is adapter              # found the way the engine finds it
        assert service.connected("7") == ["focuser/focuser_2"]
        assert [type(e).__name__ for e in seen] == ["DeviceConnectedEvent"]

        DeviceOps(lambda: adapter).disconnect("focuser")                               # the screens' own disconnect
        assert adapter.disconnected and service.controller("7", "focuser", "focuser_2") is None
        assert [type(e).__name__ for e in seen] == ["DeviceConnectedEvent", "DeviceDisconnectedEvent"]

        service._factory = lambda *a: Broken(*a)
        assert desktop_devices.connect(pier, DeviceCategory.MOUNT, "primary", "INDI", "pi", 7624, "EQ") is None
        assert service.controller("7", "mount") is None                                # a failed connect holds nothing
        assert asyncio.run(service.connect_device("7", "nonsense", "primary", "INDI", "pi", 1, "x")) is None
    finally:
        desktop_devices.reset()


@pytest.mark.requirement("TC-HEAD-040")
@pytest.mark.priority("MVP")
def test_tc_head_040_screens_read_adapters_from_the_service_first():
    """HEAD-040: a screen's per-Pier adapter store is a plain dictionary until a service holds a device for that Pier,
    then the service's device wins, so a replaced or released device is never read from a stale copy."""
    from galileo import desktop_devices
    from galileo.bus import EventBus
    from galileo.core.devices import DeviceCategory
    from galileo.engine.devices import DeviceService

    desktop_devices.reset()
    try:
        single = desktop_devices.PierAdapters(DeviceCategory.ROTATOR)
        multi = desktop_devices.PierAdapters(DeviceCategory.FOCUSER, nested=True)
        mine, theirs, slot2 = object(), object(), object()

        assert single.get(3) is None and single.get(3, "x") == "x" and multi.get(3) is None
        single[3] = mine
        multi.setdefault(3, {})["primary"] = mine
        assert single.get(3) is mine and multi.get(3) == {"primary": mine}            # no service: a dictionary

        service = DeviceService(bus=EventBus())
        desktop_devices._service = service
        assert single.get(3) is mine                                                   # a service holding nothing changes nothing
        service.adopt("3", "rotator", "primary", theirs)
        service.adopt("3", "focuser", "focuser_2", slot2)
        assert single.get(3) is theirs                                                 # the service's device wins
        assert multi.get(3) == {"primary": mine, "focuser_2": slot2}                   # slots merge, service over local
        assert single.get(4) is None

        service.release(theirs)
        assert single.get(3) is mine                                                   # released: back to the local one
        service.adopt("3", "rotator", "primary", theirs)
        assert single.pop(3) is theirs and single.get(3) is theirs                     # held by the service still
        service.release(theirs)
        assert single.get(3) is None and single.pop(3, "gone") == "gone"
        assert multi.pop(3) == {"primary": mine, "focuser_2": slot2} and multi.get(3) == {"focuser_2": slot2}
    finally:
        desktop_devices.reset()


@pytest.mark.requirement("TC-HEAD-090")
@pytest.mark.priority("MVP")
def test_tc_head_090_desktop_hosts_a_lean_engine_over_its_own_devices(tmp_path, fake_settings, monkeypatch):
    """HEAD-090: with the device-service setting on, the desktop hosts an embedded engine that takes the lock, serves the
    channel over the desktop's own device service, starts no guard, helpers or auto-connect, and leaves the devices
    connected when it stops; off, it does nothing; a second host finds the lock taken and keeps its own devices."""
    from galileo import desktop_devices

    monkeypatch.setattr("galileo.platform.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("galileo.observatory.list_observatories", list)
    desktop_devices.reset()
    try:
        assert desktop_devices.host_engine() is None                                   # setting off: nothing happens
        assert not (tmp_path / "engine").exists()

        fake_settings[("engine", "desktop_uses_device_service")] = True
        attachment = desktop_devices.host_engine()
        assert attachment is not None and attachment.hosting
        engine = attachment.engine
        assert engine.embedded and engine.devices is desktop_devices.service()        # the desktop's devices, not new ones
        assert engine.channel is not None and engine.lock.held
        assert engine.guard is None and engine.helpers is None and engine._connecting is None
        assert engine.plugin_manager is None                                           # the desktop loaded its own

        class Held:
            disconnected = False
            is_connected = True

            async def disconnect(self):
                Held.disconnected = True

        held = Held()
        engine.devices.adopt("1", "mount", "primary", held)

        assert desktop_devices.host_engine() is None                                   # a second host: lock taken
        assert engine.lock.held                                                        # and the first is undisturbed

        assert attachment.close(confirmed=True)
        assert not engine.lock.held
        assert Held.disconnected is False and engine.devices.controller("1", "mount") is held   # devices stay the desktop's
    finally:
        desktop_devices.reset()
