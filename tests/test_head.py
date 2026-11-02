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
    monkeypatch.setattr(Engine, "_stop_link", staticmethod(lambda: calls.append("link-stop")))
    monkeypatch.setattr(Engine, "_stop_workers", staticmethod(lambda: calls.append("workers-stop")))
    engine = Engine(EngineLock(tmp_path))
    engine.start()
    assert calls == ["crash", "db", "plugins"] and engine.lock.held
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
def test_tc_head_040_engine_devices():
    """HEAD-040: The system shall provide a **device service**, free of any screen, that connects the devices of each Pier's profile (including auto-connect), holds th."""
    _pending("TC-HEAD-040", "galileo.engine.devices")


@pytest.mark.requirement("TC-HEAD-050")
@pytest.mark.priority("MVP")
def test_tc_head_050_engine_runner():
    """HEAD-050: Sessions, calibration runs and scheduler jobs shall be run by one **asyncio session runner** used by the engine and the desktop alike, with no depende."""
    _pending("TC-HEAD-050", "galileo.engine.runner")


@pytest.mark.requirement("TC-HEAD-060")
@pytest.mark.priority("MVP")
def test_tc_head_060_engine_helpers():
    """HEAD-060: The engine shall own the background helpers that today live on the desktop window — mount pointing polling, slew-then-track (`EQP-MNT-050`), weather h."""
    _pending("TC-HEAD-060", "galileo.engine.helpers")


@pytest.mark.requirement("TC-HEAD-070")
@pytest.mark.priority("MVP")
def test_tc_head_070_engine_client():
    """HEAD-070: When an engine is running on the machine, the desktop application shall be its **client**: it shall list the engine's Piers, hold the control lease as."""
    _pending("TC-HEAD-070", "galileo.engine.client")


@pytest.mark.requirement("TC-HEAD-080")
@pytest.mark.priority("MVP")
def test_tc_head_080_engine_channel():
    """HEAD-080: The desktop shall reach a local engine over a **local channel**: a Unix domain socket (a loopback-only socket on Windows) readable only by the operati."""
    _pending("TC-HEAD-080", "galileo.engine.channel")


@pytest.mark.requirement("TC-HEAD-090")
@pytest.mark.priority("MVP")
def test_tc_head_090_engine_embedded():
    """HEAD-090: When no engine is running, the desktop shall host the engine in its own process, using the same engine code and holding the lock (`HEAD-020`), so that."""
    _pending("TC-HEAD-090", "galileo.engine.embedded")


@pytest.mark.requirement("TC-HEAD-100")
@pytest.mark.priority("P2")
def test_tc_head_100_engine_client():
    """HEAD-100: Closing a desktop that is attached to a separate engine shall not stop any session, device connection or listener; closing a desktop that hosts the en."""
    _pending("TC-HEAD-100", "galileo.engine.client")


@pytest.mark.requirement("TC-HEAD-110")
@pytest.mark.priority("MVP")
def test_tc_head_110_engine_client():
    """HEAD-110: The control lease shall be owned by the engine (`LEASE-010`, `LEASE-070`)."""
    _pending("TC-HEAD-110", "galileo.engine.client")


@pytest.mark.requirement("TC-HEAD-120")
@pytest.mark.priority("MVP")
def test_tc_head_120_engine_client():
    """HEAD-120: If the engine becomes unreachable, the attached desktop shall say so, keep its last values marked stale, and offer to retry; it shall never start a se."""
    _pending("TC-HEAD-120", "galileo.engine.client")


@pytest.mark.requirement("TC-HEAD-130")
@pytest.mark.priority("MVP")
def test_tc_head_130_engine_config():
    """HEAD-130: The engine shall read its configuration from the database (never from a file of its own)."""
    _pending("TC-HEAD-130", "galileo.engine.config")


@pytest.mark.requirement("TC-HEAD-140")
@pytest.mark.priority("MVP")
def test_tc_head_140_engine_config():
    """HEAD-140: The engine shall run the Observatory named by its stored setting (default: the last one the desktop used) and shall start without any person choosing ."""
    _pending("TC-HEAD-140", "galileo.engine.config")


@pytest.mark.requirement("TC-HEAD-150")
@pytest.mark.priority("P2")
def test_tc_head_150_engine_service():
    """HEAD-150: The Astroberry package shall install the engine as a systemd service (`galileo-engine."""
    pytest.skip("not built yet: the Astroberry package installs the unit")


@pytest.mark.requirement("TC-HEAD-160")
@pytest.mark.priority("MVP")
def test_tc_head_160_engine_main():
    """HEAD-160: The safety monitor and the watchdog (`SAFE-060`) shall run in the engine whether or not any desktop or remote client is attached, and an unsafe event ."""
    pytest.skip("not built yet: later step of SDD 4.33")


@pytest.mark.requirement("TC-HEAD-170")
@pytest.mark.priority("P2")
def test_tc_head_170_engine_main():
    """HEAD-170: `Galileo --engine --status` shall print, without disturbing the engine, whether it is running, its version, its Piers and their connection state, any ."""
    pytest.skip("not built yet: later step of SDD 4.33")


@pytest.mark.requirement("TC-HEAD-180")
@pytest.mark.priority("MVP")
def test_tc_head_180_engine_channel():
    """HEAD-180: A desktop and an engine shall compare versions and protocol on attach and refuse a mismatch with a message naming both versions, as Connect Link's han."""
    _pending("TC-HEAD-180", "galileo.engine.channel")
