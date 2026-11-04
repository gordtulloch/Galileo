# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""What a Weather Station / Safety Monitor tab does to its device, with no screen (EQP-WX).

* :func:`read_device` polls the adapter once and returns its readings.
* :func:`format_value` is how a reading is shown.
* :func:`banner_text` and :func:`violations` judge the readings against the safety rules.
* :func:`run_blocking` runs a coroutine to completion from any thread, including one with a running event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any


def run_blocking(make_coro: Callable[[], Any]) -> Any:
    """Run the coroutine ``make_coro()`` to completion and return its result, from any thread.

    ``asyncio.run`` refuses to run on a thread whose event loop is already running — the UI
    thread under qasync, which is where the scheduler's safety check and the dome ask for a
    fresh reading. There the coroutine runs on a short-lived helper thread instead (the caller
    blocks either way). The coroutine is only created where it will run, so a failure can't
    leave an un-awaited one behind."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coro())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(make_coro())).result()


def read_device(adapter: Any, device_type: str) -> dict:
    """Poll *adapter* once and return its readings; raises if the device can't be read. A safety monitor has the
    one reading ``is_safe`` (1.0 or 0.0), a weather station whatever its controller reports."""
    from galileo.core.devices import WeatherController
    if device_type == "safety_monitor":
        run_blocking(adapter.poll)
        return {"is_safe": 1.0 if adapter.is_safe else 0.0}
    controller = WeatherController(adapter)
    run_blocking(controller.poll)
    return controller.get_readings()


def format_value(value: Any, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "bool":
        return "Yes" if value else "No"
    try:
        return f"{float(value):.1f} {unit}".strip()
    except (TypeError, ValueError):
        return str(value)


def banner_text(readings: dict, rules: list, kind_label: str) -> str:
    """The SAFE / UNSAFE line shown above the readings."""
    from galileo.safety import evaluate_weather_safety
    if not readings:
        return "Not connected."
    status = evaluate_weather_safety(readings, rules)
    if status.is_safe:
        return f"{kind_label}: SAFE"
    return f"{kind_label}: UNSAFE — " + "; ".join(status.violations)


def violations(readings: dict, rules: list) -> list[str]:
    """What the safety-related rules say is wrong with *readings* (empty when it is safe)."""
    from galileo.safety import evaluate_weather_safety
    return list(evaluate_weather_safety(readings, [r for r in rules if r.safety_related]).violations)


__all__ = ["banner_text", "format_value", "read_device", "run_blocking", "violations"]
