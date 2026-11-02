# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""SKYSTR — sky data streaming (TC-SKYSTR-*). A synthetic catalog stands in for the bundled one, so the
tests need no network and are deterministic."""

import datetime as dt
import io

import numpy as np
import pytest
from PIL import Image

from galileo.planning.star_atlas import ConstellationLines
from galileo.skystream import (
    ArrayCatalog,
    SkyObject,
    SkyStreamError,
    SkyStreamService,
    decode_objects,
    derive_capability,
    encode_objects,
    render_static_image,
)


@pytest.fixture
def catalog():
    rng = np.random.default_rng(7)
    n = 20_000
    ra = rng.uniform(0, 360, n)
    dec = np.degrees(np.arcsin(rng.uniform(-1, 1, n)))
    mag = np.clip(rng.gamma(9.0, 0.9, n) - 1.0, -1.0, 16.0)           # many faint, few bright
    return ArrayCatalog(ra, dec, mag, (rng.uniform(size=n) < 0.1).astype(np.uint8))


class Clock:
    t = 1_800_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def svc(catalog):
    fast = iter([0.0, 0.001])                                       # benchmark: 1 ms for a page
    return SkyStreamService(catalog, clock=Clock(), timer=lambda: next(fast, 0.001))


async def _drain(svc, **kw):
    cursor, got, pages = "", [], 0
    while True:
        page = await svc.catalog(cursor=cursor, **kw)
        got += decode_objects(page["data"])
        pages += 1
        cursor = page["next"]
        if not cursor:
            return got, pages


@pytest.mark.requirement("TC-SKYSTR-010")
@pytest.mark.priority("MVP")
async def test_tc_skystr_010_a_region_arrives_brightest_first_in_pages(svc, catalog):
    """SKYSTR-010: objects of a region and limiting magnitude are served progressively — bright first, the
    fainter ones as later pages — and together they are exactly the region's objects."""
    first = await svc.catalog(100.0, 20.0, 30.0, 99.0, lod=4)
    objs = decode_objects(first["data"])
    assert first["count"] == len(objs) <= 500 and first["total"] > 500 and first["next"]
    sep = np.degrees(np.arccos(np.clip(
        np.sin(np.radians(catalog.dec)) * np.sin(np.radians(20.0)) + np.cos(np.radians(catalog.dec))
        * np.cos(np.radians(20.0)) * np.cos(np.radians(catalog.ra - 100.0)), -1, 1)))
    in_region = set(np.nonzero(sep <= 30.0)[0].tolist())
    got, pages = await _drain(svc, ra=100.0, dec=20.0, radius=30.0, limit_mag=99.0, lod=4)
    assert pages > 1 and {o.index for o in got} == in_region and len(got) == first["total"]
    mags = [catalog.mag[o.index] for o in got]
    assert max(mags[:300]) <= min(mags[-300:]) + 1e-6 or np.mean(mags[:300]) < np.mean(mags[-300:])
    assert max(o.mag for o in objs) < np.mean(mags[-300:])            # the first page is the bright end


@pytest.mark.requirement("TC-SKYSTR-010")
@pytest.mark.priority("MVP")
async def test_tc_skystr_010_limiting_magnitude_lod_and_resumable_cursor(svc, catalog):
    """SKYSTR-010: a magnitude limit and a level of detail narrow the result; a cursor resumes an
    interrupted stream where it stopped, and one that does not match the request is refused."""
    bright, _ = await _drain(svc, ra=100.0, dec=20.0, radius=40.0, limit_mag=6.0, lod=4)
    assert bright and all(catalog.mag[o.index] <= 6.0 + 1e-9 for o in bright)
    coarse, _ = await _drain(svc, ra=100.0, dec=20.0, radius=40.0, limit_mag=99.0, lod=0)
    fine, _ = await _drain(svc, ra=100.0, dec=20.0, radius=40.0, limit_mag=99.0, lod=4)
    assert 0 < len(coarse) < len(fine) and all(catalog.mag[o.index] <= 4.0 + 1e-9 for o in coarse)
    p1 = await svc.catalog(100.0, 20.0, 40.0, 99.0, 4)
    p2 = await svc.catalog(100.0, 20.0, 40.0, 99.0, 4, cursor=p1["next"])        # as if reconnected here
    seen = {o.index for o in decode_objects(p1["data"])}
    assert seen.isdisjoint(o.index for o in decode_objects(p2["data"]))
    for args in ((101.0, 20.0, 40.0), (100.0, 20.0, 41.0)):
        with pytest.raises(SkyStreamError, match="cursor"):
            await svc.catalog(*args, 99.0, 4, cursor=p1["next"])
    for bad in ("junk", "v2:abcd:3", "v1:abcd:-1"):
        with pytest.raises(SkyStreamError):
            await svc.catalog(100.0, 20.0, 40.0, 99.0, 4, cursor=bad)
    for region in ((361, 0, 5), (0, 91, 5), (0, 0, 0), (0, 0, 181)):
        with pytest.raises(SkyStreamError):
            await svc.catalog(*region)


@pytest.mark.requirement("TC-SKYSTR-020")
@pytest.mark.priority("MVP")
def test_tc_skystr_020_encoding_is_compact_quantised_delta_coded_and_versioned():
    """SKYSTR-020: a response is a versioned binary form that decodes to within its quantum and is far
    smaller than text; a client can name the version it understands, and one that is not offered is refused."""
    rng = np.random.default_rng(3)
    objs = [SkyObject(i * 7, float(rng.uniform(100, 101)), float(rng.uniform(20, 21)), float(rng.uniform(0, 12)),
                      int(i % 2)) for i in range(2000)]
    blob = encode_objects(objs)
    assert blob[:3] == b"GSK" and blob[3] == 1
    back = decode_objects(blob)
    assert len(back) == 2000 and len(blob) / 2000 < 9                          # bytes per object
    text = len(";".join(f"{o.index},{o.ra},{o.dec},{o.mag},{o.kind}" for o in objs).encode())
    assert len(blob) < text / 2
    by_index = {o.index: o for o in objs}
    for o in back:
        src = by_index[o.index]
        assert abs(o.ra - src.ra) <= 0.0005 + 1e-9 and abs(o.dec - src.dec) <= 0.0005 + 1e-9
        assert abs(o.mag - src.mag) <= 0.005 + 1e-9 and o.kind == src.kind
    assert decode_objects(encode_objects([])) == []
    with pytest.raises(SkyStreamError):
        encode_objects(objs, version=9)
    with pytest.raises(SkyStreamError):
        decode_objects(b"BAD" + blob[3:])
    far = [SkyObject(5, 0.0, -90.0, -1.5), SkyObject(6, 359.999, 90.0, 20.0)]
    assert [(o.index, o.dec) for o in decode_objects(encode_objects(far))] == [(5, -90.0), (6, 90.0)]


@pytest.mark.requirement("TC-SKYSTR-030")
@pytest.mark.priority("MVP")
async def test_tc_skystr_030_ephemeris_for_an_instant_and_a_range(catalog):
    """SKYSTR-030: positions of the Sun, Moon and planets for an instant, and a series over a range with
    a bounded number of steps."""
    seen = []

    def eph(when):
        seen.append(when)
        return [{"name": "Moon", "ra_deg": when.hour * 15.0, "dec_deg": 5.0}]

    svc = SkyStreamService(catalog, ephemeris=eph, clock=Clock())
    one = await svc.ephemeris(dt.datetime(2026, 11, 1, 3, 0))
    assert one["bodies"][0]["ra_deg"] == 45.0 and seen[0].tzinfo is dt.UTC
    rng = await svc.ephemeris(dt.datetime(2026, 11, 1, 0), dt.datetime(2026, 11, 1, 6), 3600)
    assert [s["bodies"][0]["ra_deg"] for s in rng["series"]] == [0, 15, 30, 45, 60, 75, 90]
    for args in ((dt.datetime(2026, 11, 1), dt.datetime(2026, 12, 30), 60),
                 (dt.datetime(2026, 11, 2), dt.datetime(2026, 11, 1), 60),
                 (dt.datetime(2026, 11, 1), dt.datetime(2026, 11, 2), 0)):
        with pytest.raises(SkyStreamError):
            await svc.ephemeris(*args)
    with pytest.raises(SkyStreamError):
        await SkyStreamService(catalog).ephemeris(dt.datetime(2026, 11, 1))


@pytest.mark.requirement("TC-SKYSTR-040")
@pytest.mark.priority("MVP")
def test_tc_skystr_040_050_site_horizon_pointing_and_the_masters_time(catalog):
    """SKYSTR-040 / SKYSTR-050: the site, horizon profile and live pointing are served, and every response
    carries the Master's as-of time."""
    clock = Clock()
    svc = SkyStreamService(catalog, clock=clock,
                           site=lambda: {"name": "Home", "lat": 45.0, "lon": -75.0, "horizon": [[0, 5], [90, 12]]},
                           pointing=lambda: {"ra_deg": 83.8, "dec_deg": -5.4, "fov": [1.2, 0.9]})
    s, p = svc.site(), svc.pointing()
    assert s["horizon"] == [[0, 5], [90, 12]] and s["name"] == "Home"
    assert p["mount"]["ra_deg"] == 83.8
    assert s["as_of"] == p["as_of"] == "2027-01-15T08:00:00+00:00"
    clock.t += 5
    assert svc.site()["as_of"].endswith("08:00:05+00:00")
    assert SkyStreamService(catalog, clock=clock).pointing()["mount"] is None


@pytest.mark.requirement("TC-SKYSTR-060")
@pytest.mark.priority("MVP")
def test_tc_skystr_060_capability_comes_from_a_measurement_not_a_platform_name(catalog):
    """SKYSTR-060: streaming limits derive from how long this machine takes; a fast one offers VR-class
    streaming, a slow one reports it unavailable with a reason a client can show and reduced limits."""
    fast, mid, slow = derive_capability(5), derive_capability(100), derive_capability(900)
    assert fast.vr_available and fast.max_clients > mid.max_clients > slow.max_clients
    assert not mid.vr_available and mid.reason and not slow.vr_available and "slow" in slow.reason
    assert fast.max_page > mid.max_page > slow.max_page and fast.rate_per_s > slow.rate_per_s
    ticks = iter([0.0, 0.4])                                        # a "400 ms" page
    svc = SkyStreamService(catalog, timer=lambda: next(ticks))
    cap = svc.benchmark()
    assert cap.available and not cap.vr_available and cap.max_clients == 1
    d = cap.as_dict()
    assert d["vr_available"] is False and d["reason"] and d["encodings"] == [1]


@pytest.mark.requirement("TC-SKYSTR-070")
@pytest.mark.priority("MVP")
async def test_tc_skystr_070_streaming_yields_to_a_session_and_is_capped_and_rate_limited(catalog):
    """SKYSTR-070: under a running session pages shrink and detail drops rather than anything waiting; the
    number of concurrent clients is capped by the capability; each client is rate-limited."""
    busy = [False]
    ticks = iter([0.0, 0.1])                                        # mid capability: 2 clients, 8/s
    clock = Clock()
    svc = SkyStreamService(catalog, busy=lambda: busy[0], clock=clock, timer=lambda: next(ticks, 0.1))
    normal = await svc.catalog(100.0, 20.0, 60.0, 99.0, 4)
    busy[0] = True
    shrunk = await svc.catalog(100.0, 20.0, 60.0, 99.0, 4)
    assert shrunk["degraded"] and shrunk["count"] < normal["count"] and shrunk["total"] < normal["total"]
    with svc.stream("a"), svc.stream("b"):
        with pytest.raises(SkyStreamError) as full, svc.stream("c"):
            pass
        assert full.value.status == 503
        with svc.stream("a"):                                        # a client already streaming is fine
            pass
    with svc.stream("c"):
        pass
    cap = svc.capability()
    allowed = 0
    with pytest.raises(SkyStreamError) as limited:
        for _ in range(100):
            with svc.stream("burst"):
                allowed += 1
    assert limited.value.status == 429 and allowed == int(cap.rate_per_s)
    clock.t += 5
    with svc.stream("burst"):
        pass


@pytest.mark.requirement("TC-SKYSTR-080")
@pytest.mark.priority("MVP")
def test_tc_skystr_080_static_sky_image_shows_stars_lines_mount_field_and_horizon(catalog):
    """SKYSTR-080: a PNG of a region at a time with stars to a limiting magnitude, constellation lines, the
    mount's position, the field of view and the horizon, rendered on the Master."""
    cat = ArrayCatalog(np.array([100.0, 101.0, 100.5]), np.array([20.0, 20.5, 19.5]), np.array([2.0, 5.0, 12.0]),
                       np.array([0, 0, 1], np.uint8))
    lines = ConstellationLines(np.array([99.5, 101.5]), np.array([19.5, 20.5]), [0, 2])
    base = Image.open(io.BytesIO(render_static_image(cat, 100.0, 20.0, 10.0, size=400, limit_mag=8.0)))
    assert base.format == "PNG" and base.size == (400, 400)
    full = Image.open(io.BytesIO(render_static_image(
        cat, 100.0, 20.0, 10.0, size=400, limit_mag=8.0, lines=lines, mount=(100.0, 20.0), field_deg=(2.0, 1.5),
        horizon=[(98.0, 18.0), (102.0, 18.5)])))
    arr = np.asarray(full.convert("RGB")).astype(int)
    red = (arr[..., 0] > 200) & (arr[..., 1] < 120) & (arr[..., 2] < 120)
    assert red.sum() > 40                                                      # crosshair and field rectangle
    assert np.abs(np.asarray(base.convert("RGB")).astype(int) - arr).sum() > 0
    assert (np.asarray(base.convert("L")) > 200).sum() > 0                    # the two bright stars are drawn
    faint = Image.open(io.BytesIO(render_static_image(cat, 100.0, 20.0, 10.0, size=400, limit_mag=1.0)))
    assert (np.asarray(faint.convert("L")) > 200).sum() < (np.asarray(base.convert("L")) > 200).sum()
