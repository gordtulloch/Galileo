# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Node health and power (``galileo.node_health``, ``galileo.control_surface.node``, ``galileo.engine.node``,
the Dashboard's ``NodeHealthBar``): CSURF-310."""

from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest

from galileo import node_health
from galileo.bus import EventBus
from galileo.control_surface import ObservableState, Registry
from galileo.control_surface.node import register_node_operations
from galileo.engine.node import EngineNode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

READING = {"cpu_percent": 12.0, "cpu_cores": 4, "load": 0.5, "memory_percent": 40.0, "disk_free_gb": 120.0,
           "disk_used_percent": 50.0, "temperature_c": 51.0, "uptime_s": 90061, "status": "ok"}


@pytest.mark.requirement("TC-CSURF-310")
@pytest.mark.priority("MVP")
def test_tc_csurf_310_sample_has_every_figure_and_bands_the_worst():
    """CSURF-310: a reading carries CPU, memory, free disk, temperature and uptime, and its status is the worst band."""
    reading = node_health.sample()
    assert set(reading) == set(READING)
    assert reading["status"] in ("ok", "warning", "critical")
    assert reading["disk_free_gb"] is not None and reading["disk_free_gb"] > 0
    assert node_health._level(97.0, 85, 95) == "critical"
    assert node_health._level(1.0, 10, 2, low_is_bad=True) == "critical"
    assert node_health._level(None, 85, 95) == "ok"
    assert node_health.summary(READING) == "CPU 12%  ·  Memory 40%  ·  Disk free 120 GB  ·  Temp 51°C  ·  Up 1d 1h"
    assert "not available" in node_health.summary({})


@pytest.mark.requirement("TC-CSURF-310")
@pytest.mark.priority("MVP")
def test_tc_csurf_310_power_commands_and_failures():
    """CSURF-310: restart and shutdown run the platform command; a refusal or a missing command is a PowerError."""
    from galileo.platform import power_command
    with pytest.raises(ValueError):
        power_command("hibernate")
    assert power_command("restart") != power_command("shutdown")
    seen = []
    node_health.request_power("restart", run=lambda cmd, **kw: seen.append(cmd) or SimpleNamespace(returncode=0, stderr=""))
    assert seen == [power_command("restart")]
    with pytest.raises(node_health.PowerError, match="would not power off: Access denied"):
        node_health.request_power("shutdown", run=lambda cmd, **kw: SimpleNamespace(returncode=1, stderr="Access denied\n"))
    with pytest.raises(node_health.PowerError, match=r"no .* command"):
        node_health.request_power("shutdown", run=lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(node_health.PowerError, match="did not finish"):
        node_health.request_power("shutdown", run=lambda cmd, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd, 30)))


def _node(running=False, power=None):
    state = ObservableState()
    runner = SimpleNamespace(is_running=lambda pier: running)
    return state, EngineNode(state, lambda: ["p1", "p2"], runner, sampler=lambda: dict(READING),
                             power=power or (lambda action: None))


@pytest.mark.requirement("TC-CSURF-310")
@pytest.mark.priority("MVP")
async def test_tc_csurf_310_health_is_published_to_every_pier_and_readable():
    """CSURF-310: the reading is the observable state node.health of every Pier and the result of node.health."""
    state, node = _node()
    registry = Registry(EventBus())
    register_node_operations(registry, node)
    node.sample_once()
    assert state.read("p1", "node.health") == READING and state.read("p2", "node.health") == READING
    out = await registry.invoke("node.health", {}, "p1", "web")
    assert out.ok and out.value["cpu_percent"] == 12.0
    cat = {o["name"]: o for o in registry.catalogue("p1")["operations"] if o["name"].startswith("node.")}
    assert set(cat) == {"node.health", "node.restart", "node.shutdown"}
    assert cat["node.health"]["class"] == "read"
    assert cat["node.restart"]["class"] == cat["node.shutdown"]["class"] == "confirm"


@pytest.mark.requirement("TC-CSURF-310")
@pytest.mark.priority("MVP")
async def test_tc_csurf_310_power_runs_and_is_refused_while_a_session_runs():
    """CSURF-310: restart/shutdown call the computer's power command; a running session or an OS refusal is refused
    with the reason."""
    calls = []
    _, node = _node(power=calls.append)
    registry = Registry(EventBus())
    register_node_operations(registry, node)
    assert (await registry.invoke("node.restart", {}, "p1", "web")).value == {"requested": "restart"}
    assert (await registry.invoke("node.shutdown", {}, "p1", "web")).ok
    assert calls == ["restart", "shutdown"]

    def refuse(action):
        raise node_health.PowerError("the computer would not restart: permission was refused")
    _, denied = _node(power=refuse)
    registry2 = Registry(EventBus())
    register_node_operations(registry2, denied)
    out = await registry2.invoke("node.restart", {}, "p1", "web")
    assert out.status == "refused" and "permission" in out.reason

    calls.clear()
    _, busy = _node(running=True, power=calls.append)
    registry3 = Registry(EventBus())
    register_node_operations(registry3, busy)
    out = await registry3.invoke("node.shutdown", {}, "p1", "web")
    assert out.status in ("refused", "unavailable") and "session is running" in out.reason and calls == []


@pytest.mark.requirement("TC-CSURF-310")
@pytest.mark.priority("MVP")
def test_tc_csurf_310_dashboard_line_shows_health_and_confirms_power(monkeypatch):
    """CSURF-310: the Dashboard's bottom line shows the figures; Restart/Shut down ask first and refuse during a session."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from galileo.ui import dashboard
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(node_health, "sample", lambda: dict(READING))
    issued = []
    monkeypatch.setattr(node_health, "request_power", issued.append)
    running = [False]
    bar = dashboard.NodeHealthBar(lambda: running[0])
    assert "CPU 12%" in bar._label.text() and "Disk free 120 GB" in bar._label.text()
    assert (bar.restart_button.text(), bar.shutdown_button.text()) == ("Restart", "Shut down")

    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: answers.pop(0))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    assert bar.request_power("restart") is False and issued == []          # declined
    assert bar.request_power("restart") is True and issued == ["restart"]  # confirmed
    running[0] = True
    assert bar.request_power("shutdown") is False and issued == ["restart"] and "session is running" in warned[-1]
    running[0] = False
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    def fail(action):
        raise node_health.PowerError("nope")
    monkeypatch.setattr(node_health, "request_power", fail)
    assert bar.request_power("shutdown") is False and warned[-1] == "nope"
