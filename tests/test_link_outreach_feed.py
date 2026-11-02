# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — the outreach event's live image and its tie to Connect Link (TC-LINK-100, TC-LINK-160)."""

import asyncio
import io

import numpy as np
import pytest
from PIL import Image

from galileo import settings_store
from galileo.bus import FrameCapturedEvent, get_bus
from galileo.connect_link.discovery import Discovery
from galileo.connect_link.outreach import NAMESPACE as OUTREACH_NS
from galileo.connect_link.outreach import OutreachError
from galileo.connect_link.secrets_store import MemorySecretStore
from galileo.connect_link.service import NAMESPACE, ConnectLinkService
from galileo.preview import assert_clean

GOOD = "192.168.50.20"


class FakeBackend:
    async def register(self, info):
        pass

    async def unregister(self, info):
        pass

    async def browse(self, listen_for):
        return []

    async def close(self):
        pass


class FakeImaging:
    def __init__(self, frame):
        self.current_frame = frame


@pytest.fixture
def svc(settings_db, tmp_path):
    from galileo.library.models.base import db
    db.execute_sql("INSERT INTO observatories (name) VALUES ('Home')")
    db.execute_sql("INSERT INTO piers (observatory_id, name, connect_on_startup) VALUES (1, 'Pier A', 0)")
    settings_store.set_namespace(NAMESPACE, {"enabled": True, "port": 0, "bind_host": "127.0.0.1"})
    settings_store.set_namespace(OUTREACH_NS, {
        "ssid": "Obs", "subnets": ["192.168.50.0/24"], "piers": ["1"], "surfaces": [], "guest_cap": 3,
        "default_duration_min": 30, "preview_size": 400, "preview_quality": 70})
    return ConnectLinkService(node_id="n", secrets=MemorySecretStore(), transfer_root=tmp_path / "x",
                              discovery=Discovery("n", "Home", "", FakeBackend()))


@pytest.mark.requirement("TC-LINK-160")
@pytest.mark.priority("MVP")
async def test_tc_link_160_a_finished_frame_reaches_a_guest_as_a_clean_capped_jpeg(svc):
    """LINK-160: a frame the imaging service finishes while an event is open is rendered in guest mode and
    pushed to a guest viewing that Pier; the Pier is shown by its Observatory and name."""
    await svc.acquire("webconnect")
    await svc.open_event("owner")
    assert svc.outreach.status()["piers"] == {"1": "Home / Pier A"}
    token = svc.outreach.enrol(svc.outreach._event.secret, GOOD).token
    got = []
    svc.outreach.add_sink(token, got.append)
    assert got == [{"type": "unavailable", "pier": "1"}]
    frame = np.random.default_rng(2).uniform(0, 5000, (900, 1200)).astype(np.float32)
    get_bus().publish(FrameCapturedEvent("imaging", pier=1, service=FakeImaging(frame)))
    for _ in range(100):
        await asyncio.sleep(0.02)
        if len(got) > 1:
            break
    jpeg = got[-1]["jpeg"]
    assert_clean(jpeg)
    assert max(Image.open(io.BytesIO(jpeg)).size) <= 400
    get_bus().publish(FrameCapturedEvent("imaging", pier=99, service=FakeImaging(frame)))     # not offered
    await asyncio.sleep(0.1)
    assert len(got) == 2
    await svc.close_event()
    assert not svc.outreach.is_open and svc.outreach_feed._frames == {}
    assert FrameCapturedEvent not in [t for t, hs in get_bus()._handlers.items() if svc.outreach_feed._on_frame in hs]
    await svc.shutdown()


@pytest.mark.requirement("TC-LINK-100")
@pytest.mark.priority("MVP")
async def test_tc_link_100_turning_connect_link_off_ends_the_event_and_a_closed_link_refuses_one(svc):
    """LINK-100: an event cannot open unless Connect Link is running, and disabling Connect Link ends an open
    event, tells its guests and leaves no timer."""
    with pytest.raises(OutreachError, match="not running"):
        await svc.open_event("owner")
    await svc.acquire("webconnect")
    await svc.open_event("owner", 10)
    token = svc.outreach.enrol(svc.outreach._event.secret, GOOD).token
    got = []
    svc.outreach.add_sink(token, got.append)
    await svc.set_enabled(False)
    assert not svc.outreach.is_open and {"type": "ended"} in got
    assert svc.outreach._ticker is None
    assert [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()] == []
    await svc.shutdown()
