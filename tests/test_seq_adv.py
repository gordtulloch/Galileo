# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SEQ-ADV — Advanced Sequencer (TC-SEQ-ADV-010 … TC-SEQ-ADV-100)."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def adv_seq():
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    return seq_mod.AdvancedSequencer()


# ---------------------------------------------------------------------------
# TC-SEQ-ADV-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-ADV-010")
@pytest.mark.priority("P2")
def test_tc_seq_adv_010_editor_instruction_condition_trigger_blocks():
    """SEQ-ADV-010: Advanced sequence editor composed of nested instruction, condition, and trigger blocks."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    root = seq_mod.InstructionGroup(name="Root")
    root.add_instruction(seq_mod.CaptureInstruction(filter="Ha", duration=300.0, count=5))
    root.add_condition(seq_mod.RepeatCountCondition(count=3))
    root.add_trigger(seq_mod.AutofocusTrigger(hfr_increase_threshold=0.2))

    assert len(root.instructions) == 1
    assert len(root.conditions) == 1
    assert len(root.triggers) == 1


# ---------------------------------------------------------------------------
# TC-SEQ-ADV-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-ADV-020")
@pytest.mark.priority("P2")
def test_tc_seq_adv_020_minimum_instruction_categories():
    """SEQ-ADV-020: Minimum required instruction categories: capture, mount, filter, focuser, rotator, guider, dome, switch, wait, script, message."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")

    expected_instructions = [
        "CaptureInstruction",
        "SlewInstruction",
        "FilterChangeInstruction",
        "AutofocusInstruction",
        "RotatorMoveInstruction",
        "StartGuidingInstruction",
        "DomeInstruction",
        "SwitchInstruction",
        "WaitInstruction",
        "ScriptInstruction",
        "MessageInstruction",
    ]
    for cls_name in expected_instructions:
        assert hasattr(seq_mod, cls_name), f"Missing instruction class: {cls_name}"


# ---------------------------------------------------------------------------
# TC-SEQ-ADV-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-ADV-030")
@pytest.mark.priority("P2")
def test_tc_seq_adv_030_minimum_loop_condition_types():
    """SEQ-ADV-030: Minimum loop-condition types: repeat-count, until-time, while-safe, while-above-horizon."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")

    for cls_name in (
        "RepeatCountCondition",
        "LoopUntilTimeCondition",
        "LoopWhileSafeCondition",
        "LoopWhileAboveHorizonCondition",
    ):
        assert hasattr(seq_mod, cls_name), f"Missing condition class: {cls_name}"


# ---------------------------------------------------------------------------
# TC-SEQ-ADV-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-ADV-040")
@pytest.mark.priority("P2")
def test_tc_seq_adv_040_minimum_trigger_types():
    """SEQ-ADV-040: Minimum trigger types: autofocus-HFR, autofocus-temperature, autofocus-interval, autofocus-filter-change, meridian-flip, safety-abort."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")

    for cls_name in (
        "AutofocusHfrTrigger",
        "AutofocusTemperatureTrigger",
        "AutofocusTimeTrigger",
        "AutofocusFilterChangeTrigger",
        "MeridianFlipTrigger",
        "SafetyAbortTrigger",
    ):
        assert hasattr(seq_mod, cls_name), f"Missing trigger class: {cls_name}"


# ---------------------------------------------------------------------------
# TC-SEQ-ADV-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-ADV-050")
@pytest.mark.priority("P2")
def test_tc_seq_adv_050_arbitrary_nesting_depth():
    """SEQ-ADV-050: Instructions/conditions/triggers nestable within instruction-group containers to arbitrary depth."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")

    outer = seq_mod.InstructionGroup(name="Outer")
    middle = seq_mod.InstructionGroup(name="Middle")
    inner = seq_mod.InstructionGroup(name="Inner")
    inner.add_instruction(seq_mod.CaptureInstruction(filter="L", duration=60.0, count=1))
    middle.add_group(inner)
    outer.add_group(middle)

    # Navigate 3 levels deep
    assert outer.groups[0].name == "Middle"
    assert outer.groups[0].groups[0].name == "Inner"
    assert outer.groups[0].groups[0].instructions[0].filter == "L"


# ---------------------------------------------------------------------------
# TC-SEQ-ADV-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-ADV-060")
@pytest.mark.priority("P2")
def test_tc_seq_adv_060_save_and_reuse_instruction_template(tmp_path):
    """SEQ-ADV-060: Save a configured instruction group as a template, reusable across sequences."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    grp = seq_mod.InstructionGroup(name="HaLRGB")
    grp.add_instruction(seq_mod.CaptureInstruction(filter="Ha", duration=300.0, count=10))
    grp.add_instruction(seq_mod.CaptureInstruction(filter="L", duration=120.0, count=20))

    tpl_file = tmp_path / "HaLRGB.gtpl"
    seq_mod.save_template(grp, tpl_file)
    assert tpl_file.exists()

    loaded_grp = seq_mod.load_template(tpl_file)
    assert loaded_grp.name == "HaLRGB"
    assert len(loaded_grp.instructions) == 2


# ---------------------------------------------------------------------------
# TC-SEQ-ADV-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-ADV-070")
@pytest.mark.priority("P2")
def test_tc_seq_adv_070_plugin_registers_instruction_type():
    """SEQ-ADV-070: A plugin can register a new instruction/condition/trigger type alongside built-ins."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    plugins = pytest.importorskip("galileo.plugins")

    class MyInstruction(seq_mod.BaseInstruction):
        label = "MyPluginInstruction"
        async def execute(self, context): pass

    ctx = plugins.PluginContext.__new__(plugins.PluginContext)
    ctx.register_instruction_type(MyInstruction)
    registry = seq_mod.InstructionRegistry.instance()
    assert MyInstruction in registry.available_instructions()


# ---------------------------------------------------------------------------
# TC-SEQ-ADV-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-ADV-080")
@pytest.mark.priority("P2")
async def test_tc_seq_adv_080_visual_current_instruction_indicator(adv_seq):
    """SEQ-ADV-080: Visually indicate the currently executing instruction during a running sequence."""
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    root = seq_mod.InstructionGroup(name="Root")
    instr = seq_mod.CaptureInstruction(filter="Ha", duration=0.01, count=1)
    root.add_instruction(instr)

    executing = []
    original_execute = instr.execute

    async def track_execute(ctx):
        executing.append(adv_seq.current_instruction)
        await original_execute(ctx)

    instr.execute = track_execute
    seq = seq_mod.AdvancedSequenceDef(name="Test", root=root)
    await adv_seq.run(seq)

    assert len(executing) > 0
    assert executing[0] is instr


# ---------------------------------------------------------------------------
# TC-SEQ-ADV-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-ADV-090")
@pytest.mark.priority("P3")
async def test_tc_seq_adv_090_edit_remaining_instructions_while_running(adv_seq):
    """SEQ-ADV-090: Allow editing not-yet-executed instructions while the sequence is running."""
    import asyncio
    seq_mod = pytest.importorskip("galileo.sequencer.advanced")
    root = seq_mod.InstructionGroup(name="Root")
    instr1 = seq_mod.WaitInstruction(duration_s=0.2)
    instr2 = seq_mod.CaptureInstruction(filter="L", duration=0.01, count=1)
    root.add_instruction(instr1)
    root.add_instruction(instr2)

    seq = seq_mod.AdvancedSequenceDef(name="Test", root=root)
    run_task = asyncio.create_task(adv_seq.run(seq))
    await asyncio.sleep(0.05)  # let instr1 start

    # Insert a new instruction before instr2 while instr1 is executing
    new_instr = seq_mod.MessageInstruction(message="Inserted at runtime")
    adv_seq.insert_instruction_before(instr2, new_instr)

    await run_task
    assert new_instr in adv_seq.executed_instructions or new_instr in root.instructions


# ---------------------------------------------------------------------------
# TC-SEQ-ADV-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-SEQ-ADV-100")
@pytest.mark.priority("P2")
def test_tc_seq_adv_100_convert_basic_to_advanced(minimal_sequence):
    """SEQ-ADV-100: Provide a documented migration path or converter from basic to advanced sequence."""
    seq_basic = pytest.importorskip("galileo.sequencer.basic")
    seq_adv = pytest.importorskip("galileo.sequencer.advanced")

    basic_seq = seq_basic.SequenceDef.from_dict(minimal_sequence)
    advanced_seq = seq_adv.from_basic_sequence(basic_seq)

    assert advanced_seq is not None
    assert advanced_seq.name == basic_seq.name
    # Root group must contain at least one capture instruction per basic step
    total_captures = sum(
        1 for i in advanced_seq.root.instructions
        if isinstance(i, seq_adv.CaptureInstruction)
    )
    assert total_captures >= 1
