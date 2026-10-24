"""Pushing time, site and optics to an INDI device on connect (EQP INDI adapters)."""
import asyncio
from unittest.mock import MagicMock

import pytest

from galileo.adapters.indi import IndiCameraAdapter


@pytest.mark.requirement("TC-EQP-CAM-010")
@pytest.mark.priority("P2")
def test_tc_eqp_cam_010_push_context_sends_time_site_and_optics():
    """EQP-CAM-010: INDI camera is told UTC time, site and telescope on connect."""
    adapter = IndiCameraAdapter(device_name="Guide Simulator")
    adapter._client = MagicMock()
    adapter._has = lambda prop: prop in ("TIME_UTC", "GEOGRAPHIC_COORD", "SCOPE_INFO")
    asyncio.run(adapter.push_context(51.0, -114.0, 1000.0, 600.0, 80.0))
    adapter._client.send_text.assert_called_once()
    geo = adapter._client.send_number.call_args_list[0].args
    assert geo[1] == "GEOGRAPHIC_COORD" and geo[2]["LONG"] == 246.0
    assert adapter._client.send_number.call_args_list[1].args[2] == {"FOCAL_LENGTH": 600.0, "APERTURE": 80.0}


@pytest.mark.requirement("TC-EQP-CAM-010")
@pytest.mark.priority("P2")
def test_tc_eqp_cam_010_optics_reach_unmanaged_guide_camera(monkeypatch):
    """EQP-CAM-010: optics are written to every INDI device wanting them (a PHD2-owned guide camera)."""
    from galileo.adapters import indi_client as ic
    from galileo.adapters.indi._base import push_optics_to_server

    client = MagicMock()
    client.device_names.return_value = ["Telescope Simulator", "Guide Simulator", "Filter Simulator"]
    info = ic.IndiProperty.__new__(ic.IndiProperty)
    info.elements = {k: MagicMock() for k in
                     ("TELESCOPE_APERTURE", "TELESCOPE_FOCAL_LENGTH", "GUIDER_APERTURE", "GUIDER_FOCAL_LENGTH")}
    client.get_property.side_effect = lambda dev, name: info if (name == "TELESCOPE_INFO" and dev != "Filter Simulator") else None
    monkeypatch.setattr(ic, "acquire_client", lambda host, port: client)
    monkeypatch.setattr(ic, "release_client", lambda c: None)
    assert asyncio.run(push_optics_to_server("h", 7624, 600.0, 80.0)) == 2
    sent = {c.args[0]: c.args[2] for c in client.send_number.call_args_list}
    assert sent["Guide Simulator"]["GUIDER_FOCAL_LENGTH"] == 600.0 and sent["Guide Simulator"]["GUIDER_APERTURE"] == 80.0


@pytest.mark.requirement("TC-EQP-CAM-010")
@pytest.mark.priority("P2")
def test_tc_eqp_cam_010_guide_camera_gets_its_own_tubes_optics(monkeypatch):
    """EQP-CAM-010: a device behind a different optical tube gets that tube's optics, not the default pair."""
    from galileo.adapters import indi_client as ic
    from galileo.adapters.indi._base import push_optics_to_server

    client = MagicMock()
    client.device_names.return_value = ["Main Cam", "Guide Cam"]
    info = ic.IndiProperty.__new__(ic.IndiProperty)
    info.elements = {k: MagicMock() for k in ("TELESCOPE_APERTURE", "TELESCOPE_FOCAL_LENGTH")}
    client.get_property.side_effect = lambda dev, name: info if name == "TELESCOPE_INFO" else None
    monkeypatch.setattr(ic, "acquire_client", lambda host, port: client)
    monkeypatch.setattr(ic, "release_client", lambda c: None)
    asyncio.run(push_optics_to_server("h", 7624, 1000.0, 200.0, {"Guide Cam": (240.0, 50.0)}))
    sent = {c.args[0]: c.args[2] for c in client.send_number.call_args_list}
    assert sent["Main Cam"]["TELESCOPE_FOCAL_LENGTH"] == 1000.0
    assert sent["Guide Cam"] == {"TELESCOPE_FOCAL_LENGTH": 240.0, "TELESCOPE_APERTURE": 50.0}


@pytest.mark.requirement("TC-EQP-CAM-010")
@pytest.mark.priority("P2")
def test_tc_eqp_cam_010_repeated_driver_warning_is_throttled():
    """EQP-CAM-010: an identical INDI driver warning is logged once per window, not every exposure."""
    from galileo.adapters.indi_client import IndiClient
    client = IndiClient("localhost")
    line = "[Guide Simulator] [WARNING] No stars found in field"
    assert client._throttle_repeat(line) == line
    assert client._throttle_repeat(line) is None
    assert client._throttle_repeat(line) is None
    client._repeats[line] = (client._repeats[line][0] - 301.0, client._repeats[line][1])
    assert "repeated 2 more times" in client._throttle_repeat(line)
