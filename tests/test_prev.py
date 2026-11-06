# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""PREV — the preview service (TC-PREV-*): stretch, binning, size and quality; tiles; the byte-budgeted
cache; degradation under a running session; and the metadata-free guest mode."""

import io

import numpy as np
import pytest
from PIL import Image

from galileo.preview import (
    GUEST_MAX_SIZE,
    GUEST_QUALITY,
    PreviewCache,
    PreviewError,
    PreviewParams,
    PreviewService,
    assert_clean,
)


def _frame(h=600, w=800, stars=12, seed=1):
    rng = np.random.default_rng(seed)
    f = rng.normal(1000, 20, (h, w)).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    for _ in range(stars):
        cy, cx = rng.integers(40, h - 40), rng.integers(40, w - 40)
        f += 8000 * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 2.0 ** 2))
    return f


@pytest.fixture
def versions():
    return {"v": "1"}


@pytest.fixture
def svc(versions):
    frames = {"current": _frame(), "library:abc": _frame(seed=2)}
    loads = []

    def source(ref):
        loads.append(ref)
        data = frames.get(ref.split(":")[0] if ref == "current" else ref)
        return None if data is None else (versions["v"], data)

    service = PreviewService({"current": source, "library": source})
    service.loads = loads
    return service


def _decode(preview):
    return Image.open(io.BytesIO(preview.data))


@pytest.mark.requirement("TC-PREV-010")
@pytest.mark.priority("MVP")
async def test_tc_prev_010_render_applies_stretch_binning_size_and_quality(svc):
    """PREV-010: a preview of the current exposure or a Library frame honours the requested stretch,
    binning, size and JPEG quality, and carries the histogram and statistics where asked."""
    p = await svc.render("current", PreviewParams(max_size=400, bin=1))
    img = _decode(p)
    assert img.format == "JPEG" and max(img.size) == 400 and (p.width, p.height) == img.size
    assert p.histogram is None and p.stats is None
    binned = await svc.render("current", PreviewParams(max_size=4096, bin=2))
    assert (binned.width, binned.height) == (400, 300)
    small = await svc.render("current", PreviewParams(max_size=800, quality=20))
    big = await svc.render("current", PreviewParams(max_size=800, quality=95))
    assert len(small.data) < len(big.data)
    flat = await svc.render("current", PreviewParams(stretch=0, max_size=800))
    hard = await svc.render("current", PreviewParams(stretch=100, max_size=800))
    assert np.asarray(_decode(hard)).mean() > np.asarray(_decode(flat)).mean()      # more clipping, brighter
    withh = await svc.render("library:abc", PreviewParams(histogram=True, max_size=300))
    assert len(withh.histogram["counts"]) == 256 and sum(withh.histogram["counts"]) == 600 * 800
    with pytest.raises(PreviewError):
        await svc.render("library:missing")
    with pytest.raises(PreviewError):
        await svc.render("nowhere:1")


@pytest.mark.requirement("TC-PREV-010")
@pytest.mark.priority("MVP")
async def test_tc_prev_010_statistics_report_stars_hfr_and_fwhm(svc):
    """PREV-010: the star count, HFR and FWHM come from SEP on the frame, not from the preview."""
    p = await svc.render("current", PreviewParams(stats=True, max_size=200))
    assert p.stats["star_count"] >= 8 and 0.5 < p.stats["hfr"] < 6
    assert p.stats["fwhm"] == pytest.approx(p.stats["hfr"] * 2.355 / 1.253)


@pytest.mark.requirement("TC-PREV-010")
@pytest.mark.priority("MVP")
async def test_tc_prev_010_colour_and_channel_first_frames(versions):
    """PREV-010: a colour frame, in either channel order, renders in colour."""
    rgb = np.random.default_rng(0).uniform(0, 5000, (60, 80, 3)).astype(np.float32)
    svc = PreviewService({"current": lambda ref: (versions["v"], rgb), "stack": lambda ref: ("1", np.moveaxis(rgb, -1, 0))})
    assert _decode(await svc.render("current")).mode == "RGB"
    assert _decode(await svc.render("stack")).size == (80, 60)


@pytest.mark.requirement("TC-PREV-020")
@pytest.mark.priority("MVP")
async def test_tc_prev_020_tiles_form_a_pyramid_with_a_fixed_stretch(svc):
    """PREV-020: tiles are 256 px at each level (the edge tile smaller), each level halves the image, and
    the stretch comes from the whole frame so two frames with the same parameters compare tile for tile."""
    across, down = svc.tile_grid((600, 800), 0)
    assert (across, down) == (4, 3)
    t = Image.open(io.BytesIO(await svc.tile("current", 0, 0, 0)))
    edge = Image.open(io.BytesIO(await svc.tile("current", 0, 3, 2)))
    assert t.size == (256, 256) and edge.size == (800 - 768, 600 - 512)
    assert svc.tile_grid((600, 800), 2) == (1, 1)
    top = Image.open(io.BytesIO(await svc.tile("current", 2, 0, 0)))
    assert top.size == (200, 150)
    other = Image.open(io.BytesIO(await svc.tile("library:abc", 0, 0, 0)))
    assert other.size == t.size
    for bad in ((0, 4, 0), (0, 0, 3), (13, 0, 0), (0, -1, 0)):
        with pytest.raises(PreviewError):
            await svc.tile("current", *bad)


@pytest.mark.requirement("TC-PREV-030")
@pytest.mark.priority("MVP")
async def test_tc_prev_030_repeats_are_cached_and_a_new_exposure_is_not_stale(svc, versions):
    """PREV-030: a repeated request is served from the cache without re-rendering; a new frame behind the
    same reference is a different cache entry."""
    a = await svc.render("current", PreviewParams(max_size=300))
    renders = []
    original = svc._render
    svc._render = lambda *args: (renders.append(1), original(*args))[1]
    assert await svc.render("current", PreviewParams(max_size=300)) is a and renders == []
    await svc.render("current", PreviewParams(max_size=301))
    versions["v"] = "2"
    await svc.render("current", PreviewParams(max_size=300))
    assert len(renders) == 2


@pytest.mark.requirement("TC-PREV-030")
@pytest.mark.priority("MVP")
def test_tc_prev_030_cache_is_bounded_by_bytes_and_evicts_least_recently_used():
    """PREV-030: the cache never exceeds its byte budget and drops the least recently used entry first;
    an item larger than the whole budget is not kept."""
    cache = PreviewCache(budget=100)
    cache.put(("a",), "A", 40)
    cache.put(("b",), "B", 40)
    assert cache.get(("a",)) == "A"                    # a is now the more recent
    cache.put(("c",), "C", 40)
    assert cache.get(("b",)) is None and cache.get(("a",)) == "A" and cache.get(("c",)) == "C"
    assert cache.used == 80
    cache.put(("huge",), "H", 500)
    assert cache.get(("huge",)) is None and cache.used == 80
    cache.put(("a",), "A2", 10)
    assert cache.used == 50 and len(cache) == 2


@pytest.mark.requirement("TC-PREV-040")
@pytest.mark.priority("MVP")
async def test_tc_prev_040_a_running_session_shrinks_previews_instead_of_delaying_them(versions):
    """PREV-040: under a running session the service renders a smaller, lighter preview at once and says
    so; the work itself runs off the calling thread."""
    import threading
    busy = [False]
    seen_threads = []

    def source(ref):
        seen_threads.append(threading.current_thread())
        return versions["v"], _frame()

    svc = PreviewService({"current": source}, busy=lambda: busy[0])
    normal = await svc.render("current", PreviewParams(max_size=1024, quality=90))
    assert normal.width == 800 and not normal.degraded
    busy[0] = True
    shrunk = await svc.render("current", PreviewParams(max_size=1024, quality=90))
    assert shrunk.degraded and max(shrunk.width, shrunk.height) == 512 and len(shrunk.data) < len(normal.data)
    assert all(t is not threading.main_thread() for t in seen_threads)
    already_small = await svc.render("current", PreviewParams(max_size=256, quality=50))
    assert not already_small.degraded


@pytest.mark.requirement("TC-PREV-050")
@pytest.mark.priority("MVP")
async def test_tc_prev_050_guest_previews_carry_no_metadata_and_are_never_cached(svc):
    """PREV-050: a guest preview is encoded from pixels, limited in size and quality, verified clean, not
    cached, and offers neither histogram nor statistics nor tiles."""
    p = await svc.render("current", PreviewParams(guest=True, max_size=4000, quality=95, histogram=True, stats=True))
    assert max(p.width, p.height) <= GUEST_MAX_SIZE and p.histogram is None and p.stats is None
    assert_clean(p.data)
    assert len(svc.cache) == 0
    jpeg = Image.open(io.BytesIO(p.data))
    assert not jpeg.info.get("exif") and not jpeg.info.get("icc_profile") and "comment" not in jpeg.info
    full = await svc.render("current", PreviewParams(max_size=800, quality=95))
    assert len(p.data) < len(full.data) and GUEST_QUALITY < 95
    with pytest.raises(PreviewError):
        await svc.tile("current", 0, 0, 0, PreviewParams(guest=True))


@pytest.mark.requirement("TC-PREV-050")
@pytest.mark.priority("MVP")
def test_tc_prev_050_assert_clean_rejects_exif_comments_and_trailing_data():
    """PREV-050: assert_clean accepts a bare JPEG and refuses one with EXIF (location, camera), a comment
    segment, anything after the end of the image, or something that is not a JPEG."""
    buf = io.BytesIO()
    Image.fromarray(np.zeros((8, 8), np.uint8)).save(buf, "JPEG")
    clean = buf.getvalue()
    assert_clean(clean)
    exif = Image.Exif()
    exif[0x010F] = "SECRET CAMERA MAKER"
    exif[0x8825] = {1: "N", 2: (45.0, 0.0, 0.0)}                     # GPS
    buf = io.BytesIO()
    Image.fromarray(np.zeros((8, 8), np.uint8)).save(buf, "JPEG", exif=exif)
    with pytest.raises(PreviewError, match="metadata segment"):
        assert_clean(buf.getvalue())
    comment = clean[:2] + b"\xff\xfe\x00\x0bhello fits" + clean[2:]
    with pytest.raises(PreviewError, match="metadata segment"):
        assert_clean(comment)
    with pytest.raises(PreviewError):
        assert_clean(clean + b"SIMPLE  = T")
    for junk in (b"", b"not a jpeg", b"\xff\xd8"):
        with pytest.raises(PreviewError):
            assert_clean(junk)


@pytest.mark.requirement("TC-PREV-060")
@pytest.mark.priority("P2")
async def test_tc_prev_060_a_client_can_ask_for_less_within_the_option_limits(versions):
    """PREV-060: a client may request a lower size or quality to suit its link, bounded by the options
    preview.max_size and preview.quality."""
    svc = PreviewService({"current": lambda ref: (versions["v"], _frame())}, max_size_limit=600, quality_limit=80)
    over = await svc.render("current", PreviewParams(max_size=5000, quality=100))
    assert max(over.width, over.height) == 600
    under = await svc.render("current", PreviewParams(max_size=200, quality=30))
    assert max(under.width, under.height) == 200 and len(under.data) < len(over.data)
    clamped = PreviewParams(max_size=1, quality=1, bin=9, stretch=500).clamped(600, 80)
    assert (clamped.max_size, clamped.quality, clamped.bin, clamped.stretch) == (16, 10, 4, 100)


# -- PREV-070: the frames a front end can look at ---------------------------------------------------------------
class _Service:
    def __init__(self, frame):
        self.current_frame = frame


@pytest.fixture
def frame_sources():
    from galileo.bus import EventBus
    from galileo.control_surface.frames import FrameSources
    bus = EventBus()
    loaded = []

    def loader(frame_id):
        loaded.append(frame_id)
        return None if frame_id == "missing" else ("v1", _frame(300, 400, seed=5))

    sources = FrameSources(bus, loader=loader)
    sources.bus, sources.loaded = bus, loaded
    yield sources
    sources.close()


@pytest.mark.requirement("TC-PREV-070")
@pytest.mark.priority("MVP")
async def test_tc_prev_070_current_frame_follows_the_bus_per_pier(frame_sources):
    """PREV-070: the current exposure of each Pier is kept from the frames the engine announces, and a new frame is
    a new version, so a client knows to look again."""
    from galileo.bus import FrameCapturedEvent
    from galileo.control_surface.frames import FramePreviews
    previews = FramePreviews(frame_sources)
    assert frame_sources.current_version("7") == 0
    with pytest.raises(PreviewError):
        await previews.render("current:7", PreviewParams())
    frame_sources.bus.publish(FrameCapturedEvent("imaging", pier=7, service=_Service(_frame(200, 300))))
    first = frame_sources.current_version("7")
    assert first > 0 and frame_sources.current_version("8") == 0
    shot = await previews.render("current:7", PreviewParams(max_size=128))
    assert Image.open(io.BytesIO(shot.data)).size[0] <= 128
    frame_sources.bus.publish(FrameCapturedEvent("imaging", pier=7, service=_Service(_frame(200, 300, seed=9))))
    assert frame_sources.current_version("7") > first
    assert (await previews.info("current:7"))["width"] == 300


@pytest.mark.requirement("TC-PREV-070")
@pytest.mark.priority("MVP")
async def test_tc_prev_070_library_frames_render_tile_and_are_read_once(frame_sources):
    """PREV-070: a Library frame is rendered and tiled from its file, read once however many previews are asked for,
    and an unknown frame or a malformed reference is refused."""
    from galileo.control_surface.frames import FramePreviews
    previews = FramePreviews(frame_sources)
    await previews.render("library:abc", PreviewParams(max_size=200))
    await previews.render("library:abc", PreviewParams(max_size=200, stretch=80))
    tile = await previews.tile("library:abc", 0, 1, 0, PreviewParams())
    assert Image.open(io.BytesIO(tile)).size == (144, 256)                  # 400 wide: a full 256 tile, then 144
    assert frame_sources.loaded == ["abc"]
    info = await previews.info("library:abc")
    assert (info["width"], info["height"]) == (400, 300)
    for bad in ("library:missing", "library:../etc", "nothing", "current:" + "x" * 90, ""):
        with pytest.raises(PreviewError):
            await previews.render(bad, PreviewParams())


@pytest.mark.requirement("TC-PREV-070")
@pytest.mark.priority("MVP")
async def test_tc_prev_070_frame_list_offers_current_and_recent_library_frames(frame_sources):
    """PREV-070: a client is offered the Pier's current frame and the recent Library frames to choose from."""
    from galileo.bus import FrameCapturedEvent
    from galileo.control_surface.frames import FramePreviews
    previews = FramePreviews(frame_sources, recent=lambda n: [{"id": "abc", "name": "m42.fits"}][:n])
    assert (await previews.frames("7"))["current"] == {"ref": "current:7", "version": 0, "available": False}
    frame_sources.bus.publish(FrameCapturedEvent("imaging", pier=7, service=_Service(_frame(100, 100))))
    out = await previews.frames("7")
    assert out["current"]["available"] and out["frames"] == [{"id": "abc", "name": "m42.fits"}]


@pytest.mark.requirement("TC-PREV-070")
@pytest.mark.priority("MVP")
def test_tc_prev_070_the_engine_publishes_previews_with_the_control_surface():
    """PREV-070: the published Control Surface carries the preview facade, and stopping the engine's channel
    withdraws it and stops following frames."""
    import inspect

    from galileo.control_surface.service import ControlSurfaceService
    from galileo.engine.main import Engine
    assert "previews" in ControlSurfaceService.__dataclass_fields__
    start, stop = inspect.getsource(Engine._start_channel), inspect.getsource(Engine._stop_channel)
    assert "previews=self.previews" in start and "FrameSources(bus)" in start
    assert "sources.close()" in stop


@pytest.mark.requirement("TC-PREV-070")
@pytest.mark.priority("MVP")
def test_tc_prev_070_library_listing_and_reading_use_the_catalogue_and_the_fits_file(settings_db, tmp_path):
    """PREV-070: the recent list comes from the Library catalogue (newest first, soft-deleted and held-elsewhere
    frames marked or left out) and a frame's pixels are read from its FITS file; an unknown id gives nothing."""
    from astropy.io import fits

    from galileo.control_surface.frames import _library_frame, recent_library_frames
    from galileo.library.models.fits_file import fitsFile

    path = tmp_path / "m42.fits"
    fits.PrimaryHDU(np.random.default_rng(3).normal(1000, 20, (40, 60)).astype(np.float32)).writeto(path)
    fitsFile.create(fitsFileId="new", fitsFileName=str(path), fitsFileDate="2026-11-04", fitsFileObject="M 42",
                    fitsFileType="Light", fitsFileFilter="L", fitsFileExpTime="120", fitsFileLocation="local")
    fitsFile.create(fitsFileId="old", fitsFileName=str(tmp_path / "old.fits"), fitsFileDate="2026-10-01")
    fitsFile.create(fitsFileId="gone", fitsFileName=str(tmp_path / "gone.fits"), fitsFileDate="2026-11-05",
                    fitsFileSoftDelete=True)
    fitsFile.create(fitsFileId="away", fitsFileName=str(tmp_path / "away.fits"), fitsFileDate="2026-11-03",
                    fitsFileLocation="on_master")
    listing = recent_library_frames(10)
    assert [f["id"] for f in listing] == ["new", "away", "old"]                    # newest first, no soft-deleted
    assert listing[0] | {} == {"id": "new", "name": "m42.fits", "object": "M 42", "type": "Light", "filter": "L",
                               "exposure": "120", "date": "2026-11-04", "session": "", "local": True}
    assert [f["local"] for f in listing] == [True, False, True]                    # a frame on a Master is marked
    assert len(recent_library_frames(1)) == 1
    version, data = _library_frame("new")
    assert data.shape == (40, 60) and version.isdigit()
    assert _library_frame("no-such-frame") is None
