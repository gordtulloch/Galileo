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
