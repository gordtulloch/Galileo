# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Generic power-device support: the switch panel model, the INDI and Alpaca mappers, and profiles.

Covers ``EQP-SW-020`` … ``EQP-SW-140`` (the Switches *page* is in ``test_switch_page.py`` and the plugin
registration, ``PLUG-210``, in ``test_plug.py``). Pure mapping logic is tested against hand-built property
snapshots; writes and discovery run end to end over the real INDI wire protocol against the loopback fake
server in ``tests/indi_fake_server.py``; the Alpaca adapter runs against a fake ISwitchV2.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from galileo.adapters import alpaca, indi, indi_client
from galileo.adapters.indi import switch_map
from galileo.adapters.indi_client import INTERFACE_POWER, IndiElement, IndiProperty
from galileo.core.devices import DeviceCategory, SwitchController
from galileo.core.switches import (
    ProfileChannel,
    ProfileSensor,
    SwitchPanel,
    SwitchProfile,
    SwitchProfileRegistry,
    flat_switches,
    resolve_profile,
)
from galileo.exceptions import DevicePropertyError

from tests.indi_fake_server import (
    FakeIndiServer,
    blob_vec,
    delete_property,
    num_vec,
    sw_vec,
    text_vec,
)

BOX = "Power Sim"


@pytest.fixture(autouse=True)
def _clean_registry():
    SwitchProfileRegistry.clear()
    yield
    SwitchProfileRegistry.clear()


# --- hand-built snapshots -----------------------------------------------------

def sw(name, elements, rule="AnyOfMany", perm="rw", group="Main"):
    return IndiProperty("Dev", name, "switch", group=group, perm=perm, rule=rule,
                        elements={k: IndiElement(k, k, v) for k, v in elements.items()})


def num(name, elements, perm="rw", step=1.0, group="Main"):
    """elements: name -> (value, min, max)."""
    return IndiProperty("Dev", name, "number", group=group, perm=perm,
                        elements={k: IndiElement(k, k, v, lo, hi, step) for k, (v, lo, hi) in elements.items()})


def txt(name, elements, perm="rw", group="Main"):
    return IndiProperty("Dev", name, "text", group=group, perm=perm,
                        elements={k: IndiElement(k, k, v) for k, v in elements.items()})


def snap(*props):
    return {p.name: p for p in props}


def ppba_like():
    """A Pegasus-PPBA-shaped property set: 1 DC group, 2 dew heaters, auto dew, LEDs, one vendor extra."""
    return snap(
        sw("POWER_CHANNELS", {"POWER_CHANNEL_1": True}),
        txt("POWER_LABELS", {"POWER_CHANNEL_1": "Quad ports"}),
        num("POWER_CURRENTS", {"POWER_CHANNEL_1": (1.5, 0, 999)}, perm="ro"),
        sw("DEW_CHANNELS", {"DEW_CHANNEL_1": True, "DEW_CHANNEL_2": False}),
        num("DEW_DUTY_CYCLES", {"DEW_CHANNEL_1": (50, 0, 100), "DEW_CHANNEL_2": (0, 0, 100)}, step=10),
        txt("DEW_LABELS", {"DEW_CHANNEL_1": "Dew A", "DEW_CHANNEL_2": "Dew B"}),
        sw("AUTO_DEW_CONTROL", {"DEW_CHANNEL_1": False}),
        num("POWER_SENSORS", {"SENSOR_VOLTAGE": (12.1, 0, 999), "SENSOR_CURRENT": (2.3, 0, 999),
                              "SENSOR_POWER": (27.8, 0, 999)}, perm="ro"),
        sw("LED_CONTROL", {"INDI_ENABLED": True, "INDI_DISABLED": False}, rule="OneOfMany"),
        sw("ADJOUT_VOLTAGE", {"OFF": True, "V12": False}, rule="OneOfMany"),
        txt("DRIVER_INFO", {"DRIVER_NAME": "Pegasus PPBA"}, perm="ro"),
        sw("CONNECTION", {"CONNECT": True, "DISCONNECT": False}, rule="OneOfMany"),
    )


# --- EQP-SW-030: the standard mapper ------------------------------------------

@pytest.mark.requirement("TC-EQP-SW-030")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_030_standard_power_interface_becomes_one_group_per_port_type():
    """EQP-SW-030: INDI's power-interface properties map to one group per port type and one labelled
    channel per element, with a group present only if the driver defines it."""
    mapped = switch_map.build_panel("Pegasus PPBA", ppba_like())
    panel = mapped.panel
    assert panel.recognised
    assert [g.name for g in panel.groups] == ["DC", "Dew heaters", "Auto dew", "Device"]   # no USB, no Variable

    dc = panel.groups[0].channels[0]
    assert (dc.id, dc.label, dc.on, dc.current_a) == ("dc1", "Quad ports", True, 1.5)   # label from POWER_LABELS

    dew = {c.id: c for c in panel.groups[1].channels}
    assert dew["dew1"].label == "Dew A" and dew["dew1"].kind == "dew" and dew["dew1"].on is True
    assert dew["dew2"].on is False and dew["dew2"].duty == 0
    assert panel.groups[2].channels[0].id == "autodew1" and panel.groups[2].channels[0].on is False


@pytest.mark.requirement("TC-EQP-SW-030")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_030_a_larger_box_adds_usb_and_variable_groups_with_no_extra_code():
    """EQP-SW-030: the same mapper serves a UPB3-shaped device (DC, USB, dew, two regulated outputs)."""
    props = snap(
        sw("POWER_CHANNELS", {f"POWER_CHANNEL_{i}": i % 2 == 1 for i in range(1, 7)}),
        sw("USB_PORTS", {f"USB_PORT_{i}": True for i in range(1, 9)}),
        txt("USB_LABELS", {"USB_PORT_3": "Camera hub"}),
        sw("VARIABLE_CHANNELS", {"VAR_CHANNEL_1": True, "VAR_CHANNEL_2": False}),
        num("VARIABLE_VOLTAGES", {"VAR_CHANNEL_1": (9, 3, 12), "VAR_CHANNEL_2": (5, 3, 12)}, step=0.1),
    )
    panel = switch_map.build_panel("Pegasus UPB3", props).panel
    assert [g.name for g in panel.groups] == ["DC", "USB", "Adjustable outputs"]
    assert len(panel.groups[0].channels) == 6 and len(panel.groups[1].channels) == 8
    assert {c.id: c.label for c in panel.groups[1].channels}["usb3"] == "Camera hub"
    var = panel.groups[2].channels[0]
    assert (var.kind, var.on, var.volts, var.min, var.max) == ("variable", True, 9.0, 3.0, 12.0)


# --- EQP-SW-040: readings and global controls ---------------------------------

@pytest.mark.requirement("TC-EQP-SW-040")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_040_readings_and_global_controls():
    """EQP-SW-040: voltage/current/power readings and the device-wide controls the driver defines."""
    props = ppba_like()
    props.update(snap(
        sw("POWER_CYCLE", {"POWER_CYCLE_Toggle": False}, rule="AtMostOne"),
        sw("POWER_OFF_DISCONNECT", {"INDI_ENABLED": False, "INDI_DISABLED": True}, rule="OneOfMany"),
        num("OVER_VOLTAGE_PROTECTION", {"OVERVOLTAGE": (13.8, 0, 999)}),
    ))
    panel = switch_map.build_panel("Pegasus PPBA", props).panel
    assert [(s.label, s.value, s.unit) for s in panel.sensors] == [
        ("Voltage", 12.1, "V"), ("Current", 2.3, "A"), ("Power", 27.8, "W")]
    device = {c.id: c for g in panel.groups if g.name == "Device" for c in g.channels}
    assert set(device) == {"led", "power_off_on_disconnect", "power_cycle", "over_voltage"}
    assert device["led"].on is True and device["power_off_on_disconnect"].on is False
    assert device["power_cycle"].kind == "action" and device["over_voltage"].value == 13.8


# --- EQP-SW-060: scale and clamping -------------------------------------------

@pytest.mark.requirement("TC-EQP-SW-060")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_060_dew_duty_is_always_zero_to_one_hundred():
    """EQP-SW-060: a driver on a 0-255 duty scale is presented as 0-100 %, whatever its native range."""
    props = snap(
        sw("DEW_CHANNELS", {"DEW_CHANNEL_1": True}),
        num("DEW_DUTY_CYCLES", {"DEW_CHANNEL_1": (255, 0, 255)}, step=5),
    )
    full = switch_map.build_panel("Dev", props).panel.channel("dew1")
    assert full.duty == 100.0 and (full.min, full.max) == (0.0, 100.0)
    assert full.step == pytest.approx(5 / 255 * 100)

    props["DEW_DUTY_CYCLES"].elements["DEW_CHANNEL_1"].value = 127.5
    assert switch_map.build_panel("Dev", props).panel.channel("dew1").duty == pytest.approx(50.0)


# --- EQP-SW-070: unclaimed properties -----------------------------------------

@pytest.mark.requirement("TC-EQP-SW-070")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_070_unclaimed_properties_stay_reachable_in_other():
    """EQP-SW-070: every property the mapping does not claim is listed under Other, BLOBs excepted."""
    props = ppba_like()
    props["IMAGE"] = IndiProperty("Dev", "IMAGE", "blob", elements={"IMAGE": IndiElement("IMAGE", "Image")})
    other = switch_map.build_panel("Pegasus PPBA", props).panel.other
    names = {p.name for g in other for p in g.properties}
    assert {"ADJOUT_VOLTAGE", "DRIVER_INFO", "CONNECTION"} <= names      # vendor extras are never hidden
    assert "IMAGE" not in names                                           # a BLOB is not a control
    assert not names & {"POWER_CHANNELS", "DEW_CHANNELS", "POWER_SENSORS", "LED_CONTROL"}   # claimed ones are not repeated


@pytest.mark.requirement("TC-EQP-SW-070")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_070_a_device_nothing_recognises_still_lists_everything():
    """EQP-SW-070/080: a device with no power interface and no matching profile is reported as not
    recognised, with all its properties under Other instead of an empty panel."""
    props = snap(num("SOMETHING", {"X": (1, 0, 9)}), sw("OTHER", {"A": True}))
    panel = switch_map.build_panel("Mystery", props).panel
    assert not panel.recognised and "not recognised" in panel.message
    assert panel.groups == []
    assert {p.name for g in panel.other for p in g.properties} == {"SOMETHING", "OTHER"}


# --- EQP-SW-080: profiles -----------------------------------------------------

def make_profile(name="Test Box", device="Wander Sim", signature=None, channels=None, sensors=None):
    return SwitchProfile(
        name=name, device_names=(device,),
        signature=frozenset(signature if signature is not None else {("USBX", "switch"), ("MON", "number")}),
        channels=channels if channels is not None else (
            ProfileChannel(id="usb", label="USB hub", group="USB", switch=("USBX", "INDI_ENABLED")),
            ProfileChannel(id="heater", label="Heater", group="Dew", kind="dew", number=("PWMX", "DC1"),
                           native_max=255, on_via_duty=True, optional=True),
            ProfileChannel(id="always", label="12 V always on", group="DC", display_only=True, always_on=True),
        ),
        sensors=sensors if sensors is not None else (
            ProfileSensor(id="probe", label="Probe", unit="°C", ref=("MON", "Probe1"), no_reading=(-127.0,)),
            ProfileSensor(id="volts", label="Input", unit="V", ref=("MON", "VOLTAGE")),
        ),
    )


def wander_like(heater=True):
    props = [
        sw("USBX", {"INDI_ENABLED": True, "INDI_DISABLED": False}, rule="OneOfMany"),
        num("MON", {"Probe1": (-127, -200, 999), "VOLTAGE": (12.5, 0, 999)}, perm="ro"),
        num("CALIB", {"X": (0, 0, 1)}),
    ]
    if heater:
        props.append(num("PWMX", {"DC1": (128, 0, 255)}, step=5))
    return snap(*props)


@pytest.mark.requirement("TC-EQP-SW-080")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_080_profile_maps_channels_sensors_and_display_only_ports():
    """EQP-SW-080: a profile maps custom properties to channels and readings, scales a native duty,
    treats a declared sentinel as "no reading", and emits a display-only channel for a port with no property."""
    SwitchProfileRegistry.register(make_profile())
    panel = switch_map.build_panel("Wander Sim", wander_like()).panel
    assert panel.recognised and panel.profile == "Test Box"
    groups = {g.name: {c.id: c for c in g.channels} for g in panel.groups}
    assert groups["USB"]["usb"].on is True and groups["USB"]["usb"].switchable
    heater = groups["Dew"]["heater"]
    assert heater.duty == pytest.approx(128 / 255 * 100) and heater.on is True      # on = duty above zero
    always = groups["DC"]["always"]
    assert always.switchable is False and always.on is True and not always.writable
    readings = {s.id: s.value for s in panel.sensors}
    assert readings == {"probe": None, "volts": 12.5}                               # -127 is "no probe"
    assert {p.name for g in panel.other for p in g.properties} == {"CALIB"}          # claimed properties not repeated


@pytest.mark.requirement("TC-EQP-SW-080")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_080_signature_decides_never_the_device_name():
    """EQP-SW-080: two models sharing one INDI device name are told apart by their property signature, and
    a property's *kind* is part of it (a switch named DC2 is not a number named DC2)."""
    plus = make_profile("Plus", "Shared Name", {("USB", "switch"), ("DC2", "switch")})
    pro = make_profile("Pro", "Shared Name", {("USB3", "switch"), ("DC2", "switch"), ("DC34", "number")})
    dew = make_profile("Dew", "Other Name", {("DC2", "number"), ("DC1_DIFF", "switch")})
    for p in (plus, pro, dew):
        SwitchProfileRegistry.register(p)

    plus_props = {("USB", "switch"), ("DC2", "switch"), ("CONNECTION", "switch")}
    pro_props = {("USB3", "switch"), ("DC2", "switch"), ("DC34", "number")}
    assert resolve_profile("Shared Name", plus_props).profile is plus
    assert resolve_profile("Shared Name", pro_props).profile is pro            # the larger satisfied signature wins
    assert resolve_profile("Other Name", {("DC2", "number"), ("DC1_DIFF", "switch")}).profile is dew
    # Same names, wrong kind: not mistaken for the Plus.
    assert resolve_profile("Shared Name", {("USB", "switch"), ("DC2", "number")}).profile is None
    # A profile never applies under a name it does not claim.
    assert resolve_profile("Unclaimed", plus_props).profile is None


@pytest.mark.requirement("TC-EQP-SW-080")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_080_a_tie_is_reported_not_guessed():
    """EQP-SW-080: where two profiles are satisfied equally, the ambiguity is reported."""
    SwitchProfileRegistry.register(make_profile("A", "Twin", {("P", "switch")}))
    SwitchProfileRegistry.register(make_profile("B", "Twin", {("Q", "switch")}))
    res = resolve_profile("Twin", {("P", "switch"), ("Q", "switch")})
    assert res.profile is None and sorted(res.ambiguous) == ["A", "B"]

    panel = switch_map.build_panel("Twin", snap(sw("P", {"E": True}), sw("Q", {"E": True}))).panel
    assert not panel.recognised and "more than one switch profile" in panel.message


@pytest.mark.requirement("TC-EQP-SW-080")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_080_malformed_profiles_name_their_problem():
    """EQP-SW-080 / PLUG-210: validation rejects a profile with a reason rather than failing later."""
    bad = {
        "no signature": make_profile(signature=set()),
        "unknown kind": make_profile(signature={("A", "blob")}),
        "duplicate id": make_profile(channels=(
            ProfileChannel(id="x", label="X", group="G", switch=("A", "B")),
            ProfileChannel(id="x", label="Y", group="G", switch=("A", "C")))),
        "no property": make_profile(channels=(ProfileChannel(id="x", label="X", group="G"),)),
        "display-only naming a property": make_profile(channels=(
            ProfileChannel(id="x", label="X", group="G", display_only=True, switch=("A", "B")),)),
        "on-via-duty without number": make_profile(channels=(
            ProfileChannel(id="x", label="X", group="G", kind="dew", switch=("A", "B"), on_via_duty=True),)),
    }
    for why, profile in bad.items():
        with pytest.raises(ValueError):
            profile.validate()
        assert why
    make_profile().validate()       # a good one passes


# --- EQP-SW-120: dynamic properties -------------------------------------------

@pytest.mark.requirement("TC-EQP-SW-120")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_120_a_withdrawn_property_disables_only_its_control():
    """EQP-SW-120: when a driver withdraws a property (a dew channel's PWM in an automatic mode), that
    channel's control is disabled with an explanation; every other control is untouched."""
    SwitchProfileRegistry.register(make_profile())
    panel = switch_map.build_panel("Wander Sim", wander_like(heater=False)).panel
    groups = {g.name: {c.id: c for c in g.channels} for g in panel.groups}
    heater = groups["Dew"]["heater"]
    assert heater.available is False and "PWMX" in heater.note and "optional" in heater.note
    assert groups["USB"]["usb"].available is True and panel.recognised


# --- end to end over the INDI wire protocol -----------------------------------

def _device(name, iface, on_connect, extra_static=()):
    return {
        "static": [
            text_vec(name, "DRIVER_INFO", {"DRIVER_NAME": name, "DRIVER_EXEC": "indi_test", "DRIVER_VERSION": "1.0",
                                           "DRIVER_INTERFACE": str(iface)}),
            sw_vec(name, "CONNECTION", {"CONNECT": False, "DISCONNECT": True}),
            *extra_static,
        ],
        "on_connect": on_connect,
    }


def power_box(name=BOX, ro=False):
    perm = "ro" if ro else "rw"
    return _device(name, INTERFACE_POWER, [
        sw_vec(name, "POWER_CHANNELS", {"POWER_CHANNEL_1": True, "POWER_CHANNEL_2": False}, rule="AnyOfMany",
               group="Power", perm=perm),
        text_vec(name, "POWER_LABELS", {"POWER_CHANNEL_1": "Camera", "POWER_CHANNEL_2": "Mount"}, perm="rw", group="Power"),
        sw_vec(name, "DEW_CHANNELS", {"DEW_CHANNEL_1": False}, rule="AnyOfMany", group="Dew"),
        num_vec(name, "DEW_DUTY_CYCLES", {"DEW_CHANNEL_1": (0, 0, 255)}, group="Dew", step=5),
        sw_vec(name, "VARIABLE_CHANNELS", {"VAR_CHANNEL_1": False}, rule="AnyOfMany", group="Variable"),
        num_vec(name, "VARIABLE_VOLTAGES", {"VAR_CHANNEL_1": (5, 3, 12)}, group="Variable", step=0.1),
        num_vec(name, "POWER_SENSORS", {"SENSOR_VOLTAGE": (12.1, 0, 999), "SENSOR_CURRENT": (2.3, 0, 999)}, perm="ro"),
        sw_vec(name, "LED_CONTROL", {"INDI_ENABLED": True, "INDI_DISABLED": False}),
        sw_vec(name, "VENDOR_QUIRK", {"A": True, "B": False}),
        blob_vec(name, "SNAPSHOT"),
    ])


def wanderer_like_device(name="Wander Sim", iface=0):
    return _device(name, iface, [
        sw_vec(name, "USBX", {"INDI_ENABLED": True, "INDI_DISABLED": False}),
        num_vec(name, "PWMX", {"DC1": (0, 0, 255)}, step=5),
        num_vec(name, "MON", {"Probe1": (-127, -200, 999), "VOLTAGE": (12.5, 0, 999)}, perm="ro"),
    ])


@pytest.fixture
def server():
    srv = FakeIndiServer(extras={
        BOX: power_box(),
        "Locked Sim": power_box("Locked Sim", ro=True),
        "Wander Sim": wanderer_like_device(),
        "Plain Sim": _device("Plain Sim", 0, []),
    })
    yield srv
    srv.close()
    assert indi_client._registry == {}, "adapters leaked a shared INDI connection"


def make(server, device):
    return indi.IndiSwitchAdapter(host="127.0.0.1", port=server.port, device_name=device)


def commands(server, device, prop):
    return [v for _, d, n, v in server.received if d == device and n == prop]


async def eventually(check, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await check()
        if result:
            return result
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


async def server_saw(server, device, prop, expected):
    async def _check():
        cmds = commands(server, device, prop)
        return bool(cmds) and cmds[-1] == expected
    try:
        await eventually(_check)
    except AssertionError:
        raise AssertionError(f"{device}/{prop}: expected {expected!r}, server saw {commands(server, device, prop)!r}") from None


@pytest.mark.requirement("TC-EQP-SW-020")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_020_scan_lists_power_devices_and_profile_claimed_ones(server):
    """EQP-SW-020: the Switch scan lists devices reporting the power interface, plus any device whose name
    a registered profile claims even though its driver sets no interface bit — and nothing unrelated."""
    adapter = indi.get_adapter_class(DeviceCategory.SWITCH)(host="127.0.0.1", port=server.port)
    names = await adapter.list_available_devices(DeviceCategory.SWITCH)
    assert set(names) == {BOX, "Locked Sim"}                    # the Wander and Plain devices set no interface bit

    SwitchProfileRegistry.register(make_profile())
    names = await adapter.list_available_devices(DeviceCategory.SWITCH)
    assert set(names) == {BOX, "Locked Sim", "Wander Sim"}      # claimed by name; "Plain Sim" still not offered
    assert names.count("Wander Sim") == 1


@pytest.mark.requirement("TC-EQP-SW-020")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_020_a_disabled_plugins_profile_is_not_offered(server):
    """EQP-SW-020 / PLUG-060: a profile whose owning plugin is disabled is not offered in the scan."""
    active = {"on": True}
    SwitchProfileRegistry.register(make_profile(), owner="WandererBox", is_active=lambda: active["on"])
    adapter = indi.get_adapter_class(DeviceCategory.SWITCH)(host="127.0.0.1", port=server.port)
    assert "Wander Sim" in await adapter.list_available_devices(DeviceCategory.SWITCH)
    active["on"] = False
    assert "Wander Sim" not in await adapter.list_available_devices(DeviceCategory.SWITCH)


@pytest.mark.requirement("TC-EQP-SW-030")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_030_connected_device_builds_a_panel_from_the_live_cache(server):
    """EQP-SW-030/040/070: a connected power box yields groups, readings and an Other group over real INDI."""
    adapter = make(server, BOX)
    await adapter.connect()
    try:
        panel = await SwitchController(adapter).get_panel()
        assert [g.name for g in panel.groups] == ["DC", "Dew heaters", "Adjustable outputs", "Device"]
        assert {c.id: c.label for c in panel.groups[0].channels} == {"dc1": "Camera", "dc2": "Mount"}
        assert [(s.label, s.value) for s in panel.sensors] == [("Voltage", 12.1), ("Current", 2.3)]
        other = {p.name for g in panel.other for p in g.properties}
        assert "VENDOR_QUIRK" in other and "SNAPSHOT" not in other
    finally:
        await adapter.disconnect()


@pytest.mark.requirement("TC-EQP-SW-050")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_050_writes_reach_the_driver_and_state_is_read_back(server):
    """EQP-SW-050/060: a toggle, a dew duty and a regulator voltage land on the right property element
    (duty scaled from 0-100 to the driver's 0-255, voltage clamped), and the panel then shows the driver's state."""
    adapter = make(server, BOX)
    await adapter.connect()
    try:
        controller = SwitchController(adapter)

        await controller.set_channel("dc1", on=False)
        await server_saw(server, BOX, "POWER_CHANNELS", {"POWER_CHANNEL_1": "Off"})    # only that element is sent

        async def dc1_off():
            return (await controller.get_panel()).channel("dc1").on is False
        await eventually(dc1_off)

        await controller.set_channel("dew1", duty=50)
        await server_saw(server, BOX, "DEW_DUTY_CYCLES", {"DEW_CHANNEL_1": "127.5"})
        await controller.set_channel("dew1", on=True)
        await server_saw(server, BOX, "DEW_CHANNELS", {"DEW_CHANNEL_1": "On"})

        async def dew_half():
            dew = (await controller.get_panel()).channel("dew1")
            return dew.on is True and dew.duty == pytest.approx(50.0)
        await eventually(dew_half)

        await controller.set_channel("var1", volts=20)                                  # above the 12 V ceiling
        await server_saw(server, BOX, "VARIABLE_VOLTAGES", {"VAR_CHANNEL_1": "12"})
        await controller.set_channel("led", on=False)                                   # a two-way On/Off vector
        await server_saw(server, BOX, "LED_CONTROL", {"INDI_ENABLED": "Off", "INDI_DISABLED": "On"})
    finally:
        await adapter.disconnect()


@pytest.mark.requirement("TC-EQP-SW-050")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_050_displayed_state_is_the_drivers_not_the_last_command(server):
    """EQP-SW-050: when the driver refuses a command (reports the channel still On, in Alert), the panel
    shows that, not what was asked for."""
    adapter = make(server, BOX)
    await adapter.connect()
    try:
        controller = SwitchController(adapter)
        await controller.set_channel("dc1", on=False)
        await server_saw(server, BOX, "POWER_CHANNELS", {"POWER_CHANNEL_1": "Off"})
        await asyncio.sleep(0.2)
        server.push(
            f'<setSwitchVector device="{BOX}" name="POWER_CHANNELS" state="Alert">'
            '<oneSwitch name="POWER_CHANNEL_1">On</oneSwitch></setSwitchVector>'
        )

        async def refused():
            dc1 = (await controller.get_panel()).channel("dc1")
            return dc1.on is True and dc1.state == "Alert"
        await eventually(refused)
    finally:
        await adapter.disconnect()


@pytest.mark.requirement("TC-EQP-SW-050")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_050_bad_writes_raise_instead_of_silently_succeeding(server):
    """EQP-SW-050: an unknown channel, a read-only property and a withdrawn property each raise."""
    adapter = make(server, BOX)
    await adapter.connect()
    locked = make(server, "Locked Sim")
    await locked.connect()
    try:
        with pytest.raises(DevicePropertyError, match="no switch channel 'nope'"):
            await adapter.set_channel("nope", on=True)
        with pytest.raises(DevicePropertyError, match="read-only"):
            await locked.set_channel("dc1", on=False)
        with pytest.raises(DevicePropertyError, match=r"no on/off|duty"):
            await adapter.set_channel("dc1", duty=10)           # a plain toggle has no duty
        with pytest.raises(DevicePropertyError, match="Nothing to set"):
            await adapter.set_channel("dc1")

        server.push(delete_property(BOX, "DEW_DUTY_CYCLES"))

        async def withdrawn():
            return "DEW_DUTY_CYCLES" not in {p.name for p in adapter._c().device_properties(BOX)}
        await eventually(withdrawn)
        with pytest.raises(DevicePropertyError, match="duty"):
            await adapter.set_channel("dew1", duty=10)
        # EQP-SW-120: everything else carries on.
        await adapter.set_channel("dc2", on=True)
        await server_saw(server, BOX, "POWER_CHANNELS", {"POWER_CHANNEL_2": "On"})
    finally:
        await locked.disconnect()
        await adapter.disconnect()


@pytest.mark.requirement("TC-EQP-SW-080")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_080_profiled_device_is_mapped_after_connect(server):
    """EQP-SW-080/060: a driver with no power interface is mapped by its profile once connected (it defines
    its properties only then), its heater is scaled to 0-100 %, and a heater written as a plain switch goes 0/255."""
    SwitchProfileRegistry.register(make_profile())
    adapter = make(server, "Wander Sim")
    await adapter.connect()
    try:
        controller = SwitchController(adapter)
        panel = await controller.get_panel()
        assert panel.profile == "Test Box"

        await controller.set_channel("usb", on=False)
        await server_saw(server, "Wander Sim", "USBX", {"INDI_ENABLED": "Off", "INDI_DISABLED": "On"})
        await controller.set_channel("heater", on=True)                                  # no switch element: full duty
        await server_saw(server, "Wander Sim", "PWMX", {"DC1": "255"})
        await controller.set_channel("heater", duty=40)
        await server_saw(server, "Wander Sim", "PWMX", {"DC1": "102"})                   # 40 % of 255
        await controller.set_channel("heater", on=False)
        await server_saw(server, "Wander Sim", "PWMX", {"DC1": "0"})

        with pytest.raises(DevicePropertyError):
            await controller.set_channel("always", on=False)                             # display-only: no target
    finally:
        await adapter.disconnect()


@pytest.mark.requirement("TC-EQP-SW-080")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_080_unprofiled_device_is_reported_not_recognised(server):
    """EQP-SW-080: a device no profile matches is reported as not recognised, not guessed at."""
    SwitchProfileRegistry.register(make_profile(signature={("USBX", "switch"), ("NOT_THERE", "number")}))
    adapter = make(server, "Wander Sim")
    await adapter.connect()
    try:
        panel = await SwitchController(adapter).get_panel()
        assert not panel.recognised and panel.groups == []
        assert {"USBX", "PWMX", "MON"} <= {p.name for g in panel.other for p in g.properties}
    finally:
        await adapter.disconnect()


@pytest.mark.requirement("TC-EQP-SW-100")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_100_flat_contract_addresses_every_toggle_by_stable_id(server):
    """EQP-SW-100: list_switches/set_switch keep working — every switchable channel has a stable id, a bool
    switches it and a number sets its level — and display-only channels and readings are not switches."""
    SwitchProfileRegistry.register(make_profile())
    box, wander = make(server, BOX), make(server, "Wander Sim")
    await box.connect()
    await wander.connect()
    try:
        flat = SwitchController(box).list_switches()
        assert [s.name for s in flat] == ["dc1", "dc2", "dew1", "var1", "led"]
        assert all(s.is_analog is False for s in flat) and flat[0].state is True
        assert "always" not in [s.name for s in SwitchController(wander).list_switches()]   # display-only

        await SwitchController(box).set_switch("dc2", True)
        await server_saw(server, BOX, "POWER_CHANNELS", {"POWER_CHANNEL_2": "On"})
        await SwitchController(box).set_switch("dew1", 25.0)                # a level goes to the heater's duty
        await server_saw(server, BOX, "DEW_DUTY_CYCLES", {"DEW_CHANNEL_1": "63.75"})
        await SwitchController(box).set_switch("var1", 9.0)                 # ... or a regulated output's volts
        await server_saw(server, BOX, "VARIABLE_VOLTAGES", {"VAR_CHANNEL_1": "9"})
    finally:
        await wander.disconnect()
        await box.disconnect()


class FlatOnlyBackend:
    """What the Kasa, Relay and SwitchBot plugin adapters look like to the controller: a ``switches`` list and
    ``set_switch``, with no panel."""

    def __init__(self):
        self.switches = [SimpleNamespace(name="Power-Cam", state=False, is_analog=False),
                         SimpleNamespace(name="Power-Mount", state=True, is_analog=False),
                         SimpleNamespace(name="Dew-Heater", state=0.0, is_analog=True)]
        self.calls = []

    async def set_switch(self, name, value):
        self.calls.append((name, value))


@pytest.mark.requirement("TC-EQP-SW-100")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_100_a_plain_backend_still_gets_a_panel():
    """EQP-SW-100: a backend that only keeps the flat list (the Kasa/Relay/SwitchBot plugin adapters) still
    drives the Switches page: its list becomes a one-group panel, and a level is refused clearly."""
    backend = FlatOnlyBackend()
    controller = SwitchController(backend)
    assert [s.name for s in controller.list_switches()] == ["Power-Cam", "Power-Mount", "Dew-Heater"]   # unchanged
    panel = await controller.get_panel()
    assert [g.name for g in panel.groups] == ["Switches"]
    assert [c.id for c in panel.groups[0].channels] == ["Power-Cam", "Power-Mount", "Dew-Heater"]
    assert panel.channel("Power-Mount").on is True and panel.channel("Dew-Heater").on is None   # analog: no on/off
    await controller.set_channel("Power-Cam", on=True)
    assert backend.calls == [("Power-Cam", True)]
    with pytest.raises(DevicePropertyError, match="only switches on and off"):
        await controller.set_channel("Power-Cam", duty=10)


@pytest.mark.requirement("TC-EQP-SW-100")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_100_a_test_double_that_answers_everything_is_not_taken_for_a_panel_backend(mock_switch_device):
    """EQP-SW-100: the controller decides on the backend's *class*, so the existing MagicMock fixture (which
    has every attribute) keeps the old flat behaviour instead of failing on an un-awaitable get_panel."""
    controller = SwitchController(mock_switch_device)
    assert len(controller.list_switches()) == 3
    await controller.set_channel("Power-Cam", on=True)
    mock_switch_device.set_switch.assert_called_with("Power-Cam", True)


# --- Alpaca: EQP-SW-130, EQP-SW-140 -------------------------------------------

def fake_alpaca(channels):
    """An Alpaca switch adapter over a fake ISwitchV2. *channels*: list of dicts
    (name, desc, write, lo, hi, step, value)."""
    adapter = alpaca.AlpacaSwitchAdapter(host="127.0.0.1", port=11111)
    calls: list[str] = []

    async def fake_get(attribute, timeout=10.0, **extra):
        calls.append(attribute)
        if attribute == "maxswitch":
            return len(channels)
        ch = channels[extra["Id"]]
        return {
            "getswitchname": ch["name"], "getswitchdescription": ch.get("desc", ""), "canwrite": ch["write"],
            "minswitchvalue": ch["lo"], "maxswitchvalue": ch["hi"], "switchstep": ch["step"],
            "getswitch": ch["value"], "getswitchvalue": ch["value"],
        }[attribute]

    adapter._get = fake_get
    adapter._put = AsyncMock()
    adapter.calls = calls
    return adapter


CHANNELS = [
    {"name": "Camera", "desc": "Camera power relay", "write": True, "lo": 0.0, "hi": 1.0, "step": 1.0, "value": True},
    {"name": "Heater", "write": True, "lo": 0.0, "hi": 100.0, "step": 5.0, "value": 25.0},
    {"name": "Input", "write": False, "lo": 0.0, "hi": 20.0, "step": 0.1, "value": 12.4},
    {"name": "Door", "write": False, "lo": 0.0, "hi": 1.0, "step": 1.0, "value": False},
    {"name": "Camera", "write": True, "lo": 0.0, "hi": 1.0, "step": 1.0, "value": False},     # a duplicate name
]


@pytest.mark.requirement("TC-EQP-SW-130")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_130_alpaca_channels_become_one_group_of_toggles_values_and_readings():
    """EQP-SW-130: an Alpaca switch device becomes one group; 0..1 step-1 writable channels are toggles,
    other writable ones values, read-only ones readings (a read-only boolean a display-only channel)."""
    adapter = fake_alpaca(CHANNELS)
    panel = await adapter.get_panel()
    assert [g.name for g in panel.groups] == ["Switches"]
    by_id = {c.id: c for c in panel.groups[0].channels}
    assert list(by_id) == ["0:Camera", "1:Heater", "3:Door", "4:Camera"]
    assert by_id["0:Camera"].kind == "toggle" and by_id["0:Camera"].on is True and by_id["0:Camera"].note == "Camera power relay"
    assert by_id["3:Door"].switchable is False and by_id["3:Door"].on is False                  # read-only boolean
    assert [(s.label, s.value) for s in panel.sensors] == [("Input", 12.4)]                       # read-only analog


@pytest.mark.requirement("TC-EQP-SW-130")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_130_alpaca_writes_and_the_flat_contract():
    """EQP-SW-130/050/100: writes call setswitch/setswitchvalue by index; toggles are in the flat list under
    stable ids (two channels may share a name); a plain name works only when it is unambiguous."""
    adapter = fake_alpaca(CHANNELS)
    await adapter.get_panel()
    assert [s.name for s in adapter.switches] == ["0:Camera", "4:Camera"]       # writable toggles only

    await adapter.set_switch("0:Camera", False)
    adapter._put.assert_awaited_with("setswitch", Id=0, State=False)
    await adapter.set_switch("Heater", 40.0)                                    # unambiguous plain name
    adapter._put.assert_awaited_with("setswitchvalue", Id=1, Value=40.0)
    with pytest.raises(DevicePropertyError, match="more than one channel named 'Camera'"):
        await adapter.set_switch("Camera", True)
    with pytest.raises(DevicePropertyError, match="read-only"):
        await adapter.set_channel("2:Input", value=5.0)
    with pytest.raises(DevicePropertyError, match="not an on/off switch"):
        await adapter.set_channel("1:Heater", on=True)
    with pytest.raises(DevicePropertyError, match="no channel"):
        await adapter.set_channel("9:Nope", on=True)


@pytest.mark.requirement("TC-EQP-SW-100")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_100_alpaca_flat_list_is_ready_as_soon_as_it_connects():
    """EQP-SW-100: the flat switch list is filled by connect(), so a consumer can address a channel at once, and
    it is empty again after disconnect()."""
    adapter = fake_alpaca(CHANNELS)
    assert adapter.switches == []                                   # nothing known before connecting
    await adapter.connect()
    assert adapter.is_connected and [s.name for s in adapter.switches] == ["0:Camera", "4:Camera"]
    await adapter.disconnect()
    assert not adapter.is_connected and adapter.switches == []


@pytest.mark.requirement("TC-EQP-SW-130")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_130_alpaca_refresh_reads_only_values_after_the_first_time():
    """EQP-SW-130: channel metadata is read once per connection; a refresh re-reads only live values, so a
    large device is not asked for its names and ranges every couple of seconds."""
    adapter = fake_alpaca(CHANNELS)
    await adapter.get_panel()
    adapter.calls.clear()
    await adapter.get_panel()
    assert set(adapter.calls) <= {"getswitch", "getswitchvalue"}
    assert len(adapter.calls) == len(CHANNELS)


@pytest.mark.requirement("TC-EQP-SW-140")
@pytest.mark.priority("P2")
async def test_tc_eqp_sw_140_generic_value_carries_only_the_declared_range():
    """EQP-SW-140: an analog Alpaca channel is a generic value — the device's own min/max/step, no unit and
    no assumed scale — and a write is clamped to that range."""
    adapter = fake_alpaca(CHANNELS)
    panel = await adapter.get_panel()
    heater = panel.channel("1:Heater")
    assert heater.kind == "value" and (heater.value, heater.min, heater.max, heater.step) == (25.0, 0.0, 100.0, 5.0)
    assert heater.volts is None and heater.duty is None                          # no assumed meaning

    await adapter.set_channel("1:Heater", value=500.0)
    adapter._put.assert_awaited_with("setswitchvalue", Id=1, Value=100.0)       # clamped to the declared maximum
    await adapter.set_channel("1:Heater", value=-3.0)
    adapter._put.assert_awaited_with("setswitchvalue", Id=1, Value=0.0)


@pytest.mark.requirement("TC-EQP-SW-140")
@pytest.mark.priority("P2")
def test_tc_eqp_sw_140_values_are_not_switches_in_the_flat_list():
    """EQP-SW-140/100: a generic value or an action is not an on/off switch, so it is not in the flat list."""
    panel = SwitchPanel()
    from galileo.core.switches import SwitchChannel, SwitchGroup
    panel.groups.append(SwitchGroup("G", [
        SwitchChannel(id="a", label="A"), SwitchChannel(id="v", label="V", kind="value", value=1.0),
        SwitchChannel(id="x", label="X", kind="action"), SwitchChannel(id="d", label="D", switchable=False),
    ]))
    assert [s.name for s in flat_switches(panel)] == ["a"]
