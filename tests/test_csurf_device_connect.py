# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""CSURF-320: connecting and disconnecting a device through the Control Surface, over the real registry and the real
``DeviceService`` with fake adapters."""

import asyncio
from types import SimpleNamespace

import pytest

from galileo.bus import EventBus
from galileo.control_surface import Registry
from galileo.control_surface.catalogue import register_device_operations
from galileo.engine.devices import DeviceService

PIER = "1"


class FakeAdapter:
    def __init__(self, ok=True):
        self.ok, self.is_connected, self.disconnected = ok, False, 0

    async def connect(self):
        if not self.ok:
            raise RuntimeError("no route to host")
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False
        self.disconnected += 1


def make_service(configs, ok=True):
    svc = DeviceService(bus=EventBus(), factory=lambda cat, *a: FakeAdapter(ok))
    svc._piers = {PIER: SimpleNamespace(configs=configs)}   # each service's Pier carries its own saved profile
    return svc


def cfg(category, slot="primary"):
    return SimpleNamespace(category=category, slot=slot, driver="INDI", server="h", port=7624, device_name="X")


def invoke(registry, name, device):
    return asyncio.run(registry.invoke(name, {"device": device}, PIER, "tester"))


@pytest.fixture
def restore_observatory():
    """Make the saved profile of a Pier the ``configs`` its record carries, for the length of a test."""
    import galileo.observatory as obs
    saved = obs.list_device_configs
    obs.list_device_configs = lambda record: record.configs
    yield
    obs.list_device_configs = saved


@pytest.mark.requirement("TC-CSURF-320")
@pytest.mark.priority("P2")
def test_tc_csurf_320_connect_and_disconnect(restore_observatory):
    """CSURF-320: device.connect brings up the Pier's configured device of that kind and device.disconnect releases it."""
    svc = make_service([cfg("Mount"), cfg("Camera")])
    registry = Registry()
    register_device_operations(registry, svc)
    out = invoke(registry, "device.connect", "mount")
    assert out.status == "ok", out
    assert svc.controller(PIER, "mount").is_connected and svc.controller(PIER, "camera") is None
    adapter = svc.controller(PIER, "mount")
    out = invoke(registry, "device.disconnect", "mount")
    assert out.status == "ok" and adapter.disconnected == 1 and svc.controller(PIER, "mount") is None


@pytest.mark.requirement("TC-CSURF-320")
@pytest.mark.priority("P2")
def test_tc_csurf_320_refusals_and_failures(restore_observatory):
    """CSURF-320: no configured device is refused in words, a device that will not connect is unreachable, and a
    disconnect is refused while a session runs on the Pier."""
    svc = make_service([cfg("Mount")])
    registry = Registry()
    register_device_operations(registry, svc)
    out = invoke(registry, "device.connect", "dome")
    assert out.status == "refused" and "no Dome configured" in out.reason
    bad = make_service([cfg("Camera")], ok=False)
    reg2 = Registry()
    register_device_operations(reg2, bad)
    out = invoke(reg2, "device.connect", "camera")
    assert out.status == "unreachable"
    assert invoke(registry, "device.connect", "mount").status == "ok"
    svc.busy = lambda pier: True
    out = invoke(registry, "device.disconnect", "mount")
    assert out.status == "refused" and "session is running" in out.reason
    assert svc.controller(PIER, "mount").is_connected
    out = asyncio.run(registry.invoke("device.connect", {"device": "toaster"}, PIER, "tester"))
    assert out.status == "invalid"


@pytest.mark.requirement("TC-CSURF-320")
@pytest.mark.priority("P2")
def test_tc_csurf_320_catalogue_lists_both(restore_observatory):
    """CSURF-320: the catalogue offers both operations, class operate, lease required, with the device choices."""
    registry = Registry()
    register_device_operations(registry, make_service([]))
    entries = {e["name"]: e for e in registry.catalogue(PIER)["operations"]}
    for name in ("device.connect", "device.disconnect"):
        assert entries[name]["class"] == "operate" and entries[name]["needs_lease"]
        assert "filter_wheel" in entries[name]["args"][0]["choices"]


@pytest.mark.requirement("TC-CSURF-320")
@pytest.mark.priority("P2")
def test_tc_csurf_320_connect_all_brings_up_every_configured_device(restore_observatory):
    """CSURF-320: device.connect_all connects everything the Pier has configured, names what would not connect, and
    refuses a Pier with nothing configured."""
    svc = make_service([cfg("Mount"), cfg("Camera"), cfg("Camera", "guide")])
    registry = Registry()
    register_device_operations(registry, svc)
    out = asyncio.run(registry.invoke("device.connect_all", {}, PIER, "tester"))
    assert out.status == "ok", out
    assert out.value["connected"] == ["camera/guide", "camera/primary", "mount/primary"]
    assert svc.controller(PIER, "mount").is_connected
    empty = Registry()
    register_device_operations(empty, make_service([]))
    out = asyncio.run(empty.invoke("device.connect_all", {}, PIER, "tester"))
    assert out.status == "refused" and "no devices configured" in out.reason
    bad = Registry()
    register_device_operations(bad, make_service([cfg("Camera")], ok=False))
    out = asyncio.run(bad.invoke("device.connect_all", {}, PIER, "tester"))
    assert out.status == "unreachable" and "camera/primary" in out.reason


@pytest.mark.requirement("TC-CSURF-320")
@pytest.mark.priority("P2")
def test_tc_csurf_320_only_the_home_observatory_connects_at_start_up(restore_observatory):
    """HEAD-140: every Observatory's Piers are known, so a client can choose any, but only the home Observatory's
    connect by themselves at start-up; the others wait for a client (device.connect_all)."""
    svc = DeviceService(bus=EventBus(), factory=lambda cat, *a: FakeAdapter(True))
    obs = lambda name: SimpleNamespace(name=name)                      # noqa: E731
    svc._piers = {"1": SimpleNamespace(configs=[cfg("Mount")], observatory=obs("Home")),
                  "2": SimpleNamespace(configs=[cfg("Mount")], observatory=obs("Away"))}
    svc.home_observatory = "Home"
    assert svc.observatory_name("2") == "Away"
    asyncio.run(svc.connect_startup_piers())
    assert svc.controller("1", "mount") is not None and svc.controller("2", "mount") is None
    registry = Registry()
    register_device_operations(registry, svc)
    assert asyncio.run(registry.invoke("device.connect_all", {}, "2", "tester")).status == "ok"
    assert svc.controller("2", "mount").is_connected
