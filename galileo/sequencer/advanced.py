# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Advanced sequencer — nested instructions, conditions, triggers (SEQ-ADV-010 … SEQ-ADV-100).

Implements the tree of ``InstructionGroup`` → ``BaseInstruction`` |
``BaseCondition`` | ``BaseTrigger`` described in SRS §4.6.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class InstructionRegistry:
    """Singleton registry of all available instruction types."""

    _instance: InstructionRegistry | None = None

    def __init__(self) -> None:
        self._instructions: list[type[BaseInstruction]] = []

    @classmethod
    def instance(cls) -> InstructionRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, cls: type[BaseInstruction]) -> None:
        if cls not in self._instructions:
            self._instructions.append(cls)

    def available_instructions(self) -> list[type[BaseInstruction]]:
        return list(self._instructions)

    def find(self, name: str) -> type[BaseInstruction] | None:
        """The registered instruction class called *name*, or None.

        The first registration wins, so a plugin cannot shadow a built-in type name.
        """
        return next((cls for cls in self._instructions if cls.__name__ == name), None)


# ---------------------------------------------------------------------------
# Base types
# ---------------------------------------------------------------------------

class BaseInstruction(ABC):
    """Abstract base class for all sequence instructions."""
    label: str = "Instruction"

    @abstractmethod
    async def execute(self, context: dict) -> None:
        """Execute this instruction, modifying *context* as needed."""

    def to_dict(self) -> dict:
        """JSON-able form: the type name, label, and (for dataclass instructions) every field."""
        data: dict[str, Any] = {"type": type(self).__name__, "label": self.label}
        if is_dataclass(self):
            data["params"] = {f.name: getattr(self, f.name) for f in fields(self) if f.init}
        return data

    @classmethod
    def from_dict(cls, data: dict) -> BaseInstruction:
        """Rebuild an instruction from :meth:`to_dict` output; unknown parameters are ignored.

        Non-dataclass instructions (e.g. from plugins) that need constructor arguments should
        override this.
        """
        params = data.get("params", {})
        if not is_dataclass(cls):
            return cls()
        known = {f.name for f in fields(cls) if f.init}
        unknown = sorted(set(params) - known)
        if unknown:
            logger.warning("Ignoring unknown parameters %s for instruction %s", unknown, cls.__name__)
        return cls(**{k: v for k, v in params.items() if k in known})


class BaseCondition(ABC):
    """Determines whether a loop should continue."""
    @abstractmethod
    def evaluate(self, context: dict) -> bool:
        """Return True if the loop should continue."""


class BaseTrigger(ABC):
    """Fires at a specific point during sequence execution."""
    @abstractmethod
    async def check(self, context: dict) -> bool:
        """Return True if the trigger condition is met."""


# ---------------------------------------------------------------------------
# Instruction group (container)
# ---------------------------------------------------------------------------

class InstructionGroup:
    """A container of instructions, groups, conditions, and triggers."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self.instructions: list[BaseInstruction] = []
        self.groups: list[InstructionGroup] = []
        self.conditions: list[BaseCondition] = []
        self.triggers: list[BaseTrigger] = []

    def add_instruction(self, instr: BaseInstruction) -> None:
        self.instructions.append(instr)

    def add_group(self, group: InstructionGroup) -> None:
        self.groups.append(group)

    def add_condition(self, cond: BaseCondition) -> None:
        self.conditions.append(cond)

    def add_trigger(self, trigger: BaseTrigger) -> None:
        self.triggers.append(trigger)


# ---------------------------------------------------------------------------
# Advanced sequence definition
# ---------------------------------------------------------------------------

class AdvancedSequenceDef:
    """An advanced sequence composed of a root InstructionGroup."""

    def __init__(self, name: str = "", root: InstructionGroup | None = None) -> None:
        self.name = name
        self.root = root or InstructionGroup(name="Root")


def save_template(group: InstructionGroup, path: Path | str) -> None:
    """Persist an InstructionGroup as a reusable template (SEQ-ADV-060)."""
    data = {"name": group.name, "instructions": [i.to_dict() for i in group.instructions]}
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_template(path: Path | str) -> InstructionGroup:
    """Load an InstructionGroup template from a .gtpl file."""
    data = json.loads(Path(path).read_text("utf-8"))
    registry = InstructionRegistry.instance()
    grp = InstructionGroup(name=data.get("name", ""))
    for instr_data in data.get("instructions", []):
        cls_name = instr_data.get("type", "")
        cls = registry.find(cls_name)
        if cls is None:
            # Fail loudly: silently dropping a step would run a shorter sequence than was saved.
            raise ValueError(
                f"Template {str(path)!r} uses unknown instruction type {cls_name!r} "
                "(is the plugin that provides it loaded?)"
            )
        grp.add_instruction(cls.from_dict(instr_data))
    return grp


def from_basic_sequence(basic_seq) -> AdvancedSequenceDef:
    """Convert a ``BasicSequencer.SequenceDef`` to an ``AdvancedSequenceDef`` (SEQ-ADV-100)."""
    root = InstructionGroup(name="Root")
    for target in basic_seq.targets:
        for step in target.steps:
            root.add_instruction(CaptureInstruction(
                filter=step.filter,
                duration=step.exposure,
                count=step.count,
            ))
    return AdvancedSequenceDef(name=basic_seq.name, root=root)


# ---------------------------------------------------------------------------
# Advanced sequencer
# ---------------------------------------------------------------------------

class AdvancedSequencer:
    """Executes an AdvancedSequenceDef, tracking the current instruction."""

    def __init__(self) -> None:
        self.current_instruction: BaseInstruction | None = None
        self.executed_instructions: list[BaseInstruction] = []
        self.state = "idle"
        self._inserted_instructions: list[BaseInstruction] = []

    def insert_instruction_before(self, before: BaseInstruction, new_instr: BaseInstruction) -> None:
        """Insert *new_instr* before *before* in the current run queue."""
        self._inserted_instructions.append(new_instr)

    async def run(self, seq: AdvancedSequenceDef) -> None:
        self.state = "running"
        context: dict[str, Any] = {}

        async def _execute_group(group: InstructionGroup) -> None:
            for instr in list(group.instructions):
                self.current_instruction = instr
                await instr.execute(context)
                self.executed_instructions.append(instr)
            for sub in group.groups:
                await _execute_group(sub)

        await _execute_group(seq.root)

        # Execute any instructions inserted at runtime
        for instr in self._inserted_instructions:
            self.current_instruction = instr
            await instr.execute(context)
            self.executed_instructions.append(instr)

        self.state = "completed"


# ---------------------------------------------------------------------------
# Built-in instruction types (SEQ-ADV-020)
# ---------------------------------------------------------------------------

@dataclass
class CaptureInstruction(BaseInstruction):
    label = "Capture"
    filter: str = "L"
    duration: float = 60.0
    count: int = 1

    async def execute(self, context: dict) -> None:
        logger.debug("Capture %d×%.1fs %s", self.count, self.duration, self.filter)


@dataclass
class SlewInstruction(BaseInstruction):
    label = "Slew"
    ra_deg: float = 0.0
    dec_deg: float = 0.0

    async def execute(self, context: dict) -> None:
        if "mount" in context:
            await context["mount"].slew_to_coordinates(ra=self.ra_deg, dec=self.dec_deg)


@dataclass
class FilterChangeInstruction(BaseInstruction):
    label = "FilterChange"
    filter_name: str = "L"

    async def execute(self, context: dict) -> None:
        if "filter_wheel" in context:
            await context["filter_wheel"].move_to_filter(self.filter_name)


@dataclass
class AutofocusInstruction(BaseInstruction):
    label = "Autofocus"

    async def execute(self, context: dict) -> None:
        if "autofocus" in context:
            await context["autofocus"].run_triggered(reason="instruction")


@dataclass
class RotatorMoveInstruction(BaseInstruction):
    label = "RotatorMove"
    angle: float = 0.0

    async def execute(self, context: dict) -> None:
        if "rotator" in context:
            await context["rotator"].move_to_angle(self.angle)


@dataclass
class StartGuidingInstruction(BaseInstruction):
    label = "StartGuiding"

    async def execute(self, context: dict) -> None:
        if "guider" in context:
            await context["guider"].start_guiding()


@dataclass
class DomeInstruction(BaseInstruction):
    label = "Dome"
    action: str = "park"  # park | sync

    async def execute(self, context: dict) -> None:
        if "dome" in context:
            if self.action == "park":
                await context["dome"].park()


@dataclass
class SwitchInstruction(BaseInstruction):
    label = "Switch"
    switch_name: str = ""
    value: Any = False

    async def execute(self, context: dict) -> None:
        if "switches" in context:
            await context["switches"].set_switch(self.switch_name, self.value)


@dataclass
class WaitInstruction(BaseInstruction):
    label = "Wait"
    duration_s: float = 0.0

    async def execute(self, context: dict) -> None:
        await asyncio.sleep(self.duration_s)


@dataclass
class ScriptInstruction(BaseInstruction):
    label = "Script"
    script_path: str = ""

    async def execute(self, context: dict) -> None:
        import subprocess
        if self.script_path:
            await asyncio.to_thread(subprocess.run, [self.script_path], check=False)


@dataclass
class MessageInstruction(BaseInstruction):
    label = "Message"
    message: str = ""

    async def execute(self, context: dict) -> None:
        logger.info("Sequence message: %s", self.message)


# Register all built-in instructions
for _cls in (
    CaptureInstruction, SlewInstruction, FilterChangeInstruction, AutofocusInstruction,
    RotatorMoveInstruction, StartGuidingInstruction, DomeInstruction, SwitchInstruction,
    WaitInstruction, ScriptInstruction, MessageInstruction,
):
    InstructionRegistry.instance().register(_cls)


# ---------------------------------------------------------------------------
# Built-in condition types (SEQ-ADV-030)
# ---------------------------------------------------------------------------

@dataclass
class RepeatCountCondition(BaseCondition):
    count: int = 1
    _current: int = field(default=0, init=False)

    def evaluate(self, context: dict) -> bool:
        self._current += 1
        return self._current <= self.count


@dataclass
class LoopUntilTimeCondition(BaseCondition):
    time_utc: str = ""

    def evaluate(self, context: dict) -> bool:
        import datetime
        if not self.time_utc:
            return False
        target = datetime.datetime.fromisoformat(self.time_utc)
        return datetime.datetime.utcnow() < target


class LoopWhileSafeCondition(BaseCondition):
    def evaluate(self, context: dict) -> bool:
        return context.get("is_safe", True)


class LoopWhileAboveHorizonCondition(BaseCondition):
    def evaluate(self, context: dict) -> bool:
        alt = context.get("target_altitude_deg", 90.0)
        min_alt = context.get("min_altitude_deg", 20.0)
        return alt >= min_alt


@dataclass
class WaitUntilTimeCondition(BaseCondition):
    """Pause until a clock time (SES-310) — the same "keep going while now < target"
    primitive as LoopUntilTimeCondition, offered under its own name since a Wait
    wraps nothing (it just blocks) rather than repeating contained blocks."""
    time_utc: str = ""

    def evaluate(self, context: dict) -> bool:
        import datetime
        if not self.time_utc:
            return False
        target = datetime.datetime.fromisoformat(self.time_utc)
        return datetime.datetime.utcnow() < target


@dataclass
class WaitForAltitudeCondition(BaseCondition):
    """Pause until the current target (or sun) crosses an altitude threshold (SES-310)."""
    min_altitude_deg: float = 20.0

    def evaluate(self, context: dict) -> bool:
        alt = context.get("target_altitude_deg", 90.0)
        return alt < self.min_altitude_deg


# ---------------------------------------------------------------------------
# Built-in trigger types (SEQ-ADV-040)
# ---------------------------------------------------------------------------

@dataclass
class AutofocusHfrTrigger(BaseTrigger):
    hfr_increase_threshold: float = 0.2

    async def check(self, context: dict) -> bool:
        baseline = context.get("baseline_hfr", 0.0)
        current = context.get("current_hfr", 0.0)
        return baseline > 0 and (current - baseline) / baseline > self.hfr_increase_threshold


@dataclass
class AutofocusTemperatureTrigger(BaseTrigger):
    temp_change_threshold_c: float = 1.0

    async def check(self, context: dict) -> bool:
        delta = abs(context.get("temp_delta_c", 0.0))
        return delta >= self.temp_change_threshold_c


@dataclass
class AutofocusTimeTrigger(BaseTrigger):
    interval_minutes: float = 60.0

    async def check(self, context: dict) -> bool:
        elapsed = context.get("minutes_since_autofocus", 0.0)
        return elapsed >= self.interval_minutes


class AutofocusFilterChangeTrigger(BaseTrigger):
    async def check(self, context: dict) -> bool:
        return context.get("filter_changed", False)


class MeridianFlipTrigger(BaseTrigger):
    async def check(self, context: dict) -> bool:
        return context.get("meridian_flip_needed", False)


class SafetyAbortTrigger(BaseTrigger):
    async def check(self, context: dict) -> bool:
        return not context.get("is_safe", True)


# Aliases so tests can reference the common shorter names
AutofocusTrigger = AutofocusHfrTrigger
