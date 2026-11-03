# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""``Galileo --engine --status`` (HEAD-170): what a supervisor can ask a running engine.

It reads the engine's info file for the channel address and token, asks the engine's read-only status route, and
prints. It takes no lease and changes nothing, so it can be run from a timer or a health check. Exit code 0 means
the engine is running and answered; 3 means none is running (the code ``systemctl status`` uses for "not
running"); 1 means a lock holder did not answer.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

EXIT_RUNNING = 0
EXIT_NOT_RUNNING = 3
EXIT_NO_ANSWER = 1


async def fetch_status(directory: Path | str | None = None) -> dict[str, Any]:
    """The engine's status plus ``running``; ``{"running": False}`` when no engine is running or it will not answer."""
    from galileo.engine.client import EngineClient, EngineUnreachable, find_engine
    from galileo.engine.lock import EngineLock

    lock = EngineLock(directory)
    holder = lock.holder()
    info = find_engine(lock.directory)
    if not holder or not info.get("address"):
        return {"running": False}
    client = EngineClient(info["address"], info["token"], "")
    try:
        status = await client.status()
    except EngineUnreachable as exc:
        return {"running": False, "stale": True, "holder": holder, "error": str(exc)}
    finally:
        await client.close()
    return {"running": True, "pid": holder.get("pid"), "since": holder.get("since"), **status}


def format_status(status: dict[str, Any]) -> str:
    if not status.get("running"):
        if status.get("stale"):
            return f"Galileo engine: not answering (pid {status['holder'].get('pid', '?')}): {status.get('error', '')}"
        return "Galileo engine: not running"
    lines = [f"Galileo engine: running (version {status.get('version', '?')}, pid {status.get('pid', '?')}, "
             f"since {status.get('since', '?')})"]
    if status.get("observatory"):
        lines.append(f"Observatory: {status['observatory']}")
    piers = status.get("piers") or []
    lines.append("Piers: " + ("none" if not piers else ""))
    for p in piers:
        devices = ", ".join(p["connected"]) if p.get("connected") else "no devices connected"
        lease = f", control held by {p['lease']}" if p.get("lease") else ""
        lines.append(f"  {p['name']} ({p['id']}): {devices}{lease}")
    for pid, failed in (status.get("problems") or {}).items():
        lines.append(f"  Problem: Pier {pid} could not connect {', '.join(failed)}")
    for pid, why in (status.get("unsafe") or {}).items():
        lines.append(f"  UNSAFE: Pier {pid}: {why}")
    lines.append(f"Watchdog: {status.get('watchdog', 'off')}")
    sessions = status.get("sessions") or []
    lines.append("Sessions: " + ("none running" if not sessions else ""))
    for s in sessions:
        lines.append(f"  Pier {s['pier']}: {s['name']} ({s['state']})")
    lines.append("Listening on: " + ", ".join(status.get("listeners") or ["nothing"]))
    return "\n".join(lines)


def status_main(json_output: bool = False, directory: Path | str | None = None) -> int:
    status = asyncio.run(fetch_status(directory))
    print(json.dumps(status, indent=2) if json_output else format_status(status))
    if status.get("running"):
        return EXIT_RUNNING
    return EXIT_NO_ANSWER if status.get("stale") else EXIT_NOT_RUNNING


__all__ = ["EXIT_NOT_RUNNING", "EXIT_NO_ANSWER", "EXIT_RUNNING", "fetch_status", "format_status", "status_main"]
