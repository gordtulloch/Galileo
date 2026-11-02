# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""``galileo.engine`` — the headless engine (HEAD-*, SDD §4.33). Imports no Qt."""

from galileo.engine.lock import EngineAlreadyRunning, EngineLock
from galileo.engine.main import Engine, main
from galileo.engine.service import EXIT_ALREADY_RUNNING, EXIT_FAILURE, EXIT_OK, StopSignal, run_until_stopped, sd_notify

__all__ = ["EXIT_ALREADY_RUNNING", "EXIT_FAILURE", "EXIT_OK", "Engine", "EngineAlreadyRunning", "EngineLock",
           "StopSignal", "main", "run_until_stopped", "sd_notify"]
