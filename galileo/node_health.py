# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Node health (NODE-010 to NODE-030): how hard the computer running Galileo is working, and restarting or powering it
off.

A *node* is one computer running Galileo. :func:`sample` reads CPU load, memory, free disk space (on the drive that
holds the Galileo database, where the images and catalogue go), CPU temperature where the OS reports one, and uptime;
the desktop's Dashboard shows it as one line and the engine publishes it as the observable state ``node.health`` for
the mobile app. ``psutil`` does the reading; without it the figures it alone can give are left out rather than guessed.

:func:`request_power` runs the OS command from :func:`galileo.platform.power_command`. It is the only place Galileo
restarts or powers off a computer, and callers confirm with a person before calling it.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

try:                                    # a missing psutil degrades the readout; it never stops the application
    import psutil
except ImportError:                     # pragma: no cover - psutil is a declared dependency
    psutil = None                       # type: ignore[assignment]
else:
    psutil.cpu_percent(interval=None)   # the first call has nothing to compare with and reads 0

# Bands for the one-word state shown beside the figures. The same words reach the mobile app.
WARN_PERCENT = 85.0
CRITICAL_PERCENT = 95.0
DISK_WARN_FREE_GB = 10.0
DISK_CRITICAL_FREE_GB = 2.0
TEMP_WARN_C = 75.0
TEMP_CRITICAL_C = 85.0


class PowerError(RuntimeError):
    """The computer would not restart or power off; the message says why, in words for the user."""


def _disk_path() -> str:
    try:
        from galileo.platform import get_data_dir
        return str(get_data_dir())
    except Exception:
        return os.path.expanduser("~")


def _cpu_temperature() -> float | None:
    sensors = getattr(psutil, "sensors_temperatures", None) if psutil else None
    if sensors is None:
        return None
    try:
        readings = [r.current for group in sensors().values() for r in group if r.current]
    except Exception:
        return None
    return round(max(readings), 1) if readings else None


def _level(value: float | None, warn: float, critical: float, *, low_is_bad: bool = False) -> str:
    if value is None:
        return "ok"
    if low_is_bad:
        return "critical" if value <= critical else "warning" if value <= warn else "ok"
    return "critical" if value >= critical else "warning" if value >= warn else "ok"


def sample() -> dict[str, Any]:
    """One reading. Keys are always present; a figure that cannot be read is ``None``. ``status`` is the worst of the
    per-figure bands (``ok``, ``warning`` or ``critical``)."""
    cpu = memory = uptime = None
    cores = os.cpu_count()
    if psutil is not None:
        try:
            cpu = round(float(psutil.cpu_percent(interval=None)), 1)
            memory = round(float(psutil.virtual_memory().percent), 1)
            uptime = max(0.0, time.time() - psutil.boot_time())
        except Exception:
            logger.debug("psutil could not be read", exc_info=True)
    try:
        usage = shutil.disk_usage(_disk_path())
        disk_free_gb: float | None = round(usage.free / 1e9, 1)
        disk_percent: float | None = round(100.0 * (usage.total - usage.free) / usage.total, 1) if usage.total else None
    except OSError:
        disk_free_gb = disk_percent = None
    try:
        load = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):       # Windows has no load average
        load = None
    temperature = _cpu_temperature()
    bands = (_level(cpu, WARN_PERCENT, CRITICAL_PERCENT), _level(memory, WARN_PERCENT, CRITICAL_PERCENT),
             _level(disk_free_gb, DISK_WARN_FREE_GB, DISK_CRITICAL_FREE_GB, low_is_bad=True),
             _level(temperature, TEMP_WARN_C, TEMP_CRITICAL_C))
    status = "critical" if "critical" in bands else "warning" if "warning" in bands else "ok"
    return {"cpu_percent": cpu, "cpu_cores": cores, "load": load, "memory_percent": memory,
            "disk_free_gb": disk_free_gb, "disk_used_percent": disk_percent, "temperature_c": temperature,
            "uptime_s": round(uptime) if uptime is not None else None, "status": status}


def summary(reading: dict[str, Any]) -> str:
    """The one-line text of a reading, as the Dashboard shows it."""
    parts = []
    if reading.get("cpu_percent") is not None:
        parts.append(f"CPU {reading['cpu_percent']:.0f}%")
    if reading.get("memory_percent") is not None:
        parts.append(f"Memory {reading['memory_percent']:.0f}%")
    if reading.get("disk_free_gb") is not None:
        parts.append(f"Disk free {reading['disk_free_gb']:.0f} GB")
    if reading.get("temperature_c") is not None:
        parts.append(f"Temp {reading['temperature_c']:.0f}°C")
    if reading.get("uptime_s") is not None:
        seconds = int(reading["uptime_s"])
        days, rest = divmod(seconds, 86400)
        parts.append(f"Up {days}d {rest // 3600}h" if days else f"Up {rest // 3600}h {rest % 3600 // 60}m")
    text = "  ·  ".join(parts) or "Node health is not available"
    mark = {"warning": "⚠ ", "critical": "⛔ "}.get(str(reading.get("status")), "")   # words and symbols, not colour: the red night theme has none
    return mark + text


def request_power(action: str, *, run: Callable[..., Any] = subprocess.run) -> None:
    """Restart (``"restart"``) or power off (``"shutdown"``) this computer. Raises :class:`PowerError` when the OS
    refuses or has no such command (for example a Linux service without permission to power off)."""
    from galileo.platform import power_command
    command = power_command(action)
    try:
        done = run(command, capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError as exc:
        raise PowerError(f"this computer has no {command[0]} command to {action} with") from exc
    except subprocess.SubprocessError as exc:
        raise PowerError(f"the {action} command did not finish: {exc}") from exc
    if getattr(done, "returncode", 0) != 0:
        detail = (getattr(done, "stderr", "") or "").strip().splitlines()
        verb = "restart" if action == "restart" else "power off"
        raise PowerError(f"the computer would not {verb}: {detail[-1] if detail else 'permission was refused'}")
    logger.warning("Node %s requested", action)


__all__ = ["PowerError", "request_power", "sample", "summary"]
