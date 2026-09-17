"""Shared fixtures and pytest configuration for the Galileo test suite."""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path


# ---------------------------------------------------------------------------
# Custom markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requirement(tc_id): RTM Test Case ID (e.g. TC-ARCH-010)",
    )
    config.addinivalue_line(
        "markers",
        "priority(level): requirement priority — MVP, P2, or P3",
    )
    config.addinivalue_line(
        "markers",
        "soak: requires extended runtime (hours); excluded from normal CI",
    )
    config.addinivalue_line(
        "markers",
        "hardware: requires physical INDI/Alpaca hardware on the LAN",
    )
    config.addinivalue_line(
        "markers",
        "integration: requires a running external service (INDI, PHD2, solver, etc.)",
    )


# ---------------------------------------------------------------------------
# Device mock fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_indi_camera():
    cam = MagicMock(name="SimCamera")
    cam.device_type = "Camera"
    cam.name = "SimCamera"
    cam.backend = "indi"
    cam.is_connected = True
    cam.capabilities = MagicMock(
        has_cooler=True,
        can_set_gain=True,
        can_set_offset=True,
        can_bin=True,
        max_bin_x=4,
        max_bin_y=4,
        has_shutter=True,
        sensor_width=4656,
        sensor_height=3520,
        pixel_size_x=5.86,
        pixel_size_y=5.86,
    )
    cam.start_exposure = AsyncMock()
    cam.abort_exposure = AsyncMock()
    cam.get_image_array = AsyncMock(return_value=None)
    cam.set_temperature = AsyncMock()
    cam.get_temperature = MagicMock(return_value=-10.0)
    cam.get_cooler_power = MagicMock(return_value=55.0)
    cam.warm_up = AsyncMock()
    cam.get_properties = MagicMock(return_value={})
    cam.set_property = AsyncMock()
    return cam


@pytest.fixture
def mock_indi_mount():
    mnt = MagicMock(name="SimMount")
    mnt.device_type = "Mount"
    mnt.name = "SimMount"
    mnt.backend = "indi"
    mnt.is_connected = True
    mnt.ra = 12.5
    mnt.dec = 45.0
    mnt.altitude = 60.0
    mnt.azimuth = 180.0
    mnt.pier_side = "East"
    mnt.is_tracking = True
    mnt.is_slewing = False
    mnt.slew_to_coordinates = AsyncMock()
    mnt.abort_slew = AsyncMock()
    mnt.park = AsyncMock()
    mnt.unpark = AsyncMock()
    mnt.set_tracking = AsyncMock()
    mnt.set_tracking_rate = AsyncMock()
    mnt.sync_to_coordinates = AsyncMock()
    return mnt


@pytest.fixture
def mock_filter_wheel():
    fw = MagicMock(name="SimFW")
    fw.device_type = "FilterWheel"
    fw.name = "SimFW"
    fw.is_connected = True
    fw.filter_names = ["Ha", "OIII", "SII", "L", "R", "G", "B"]
    fw.position = 0
    fw.is_moving = False
    fw.move_to = AsyncMock()
    return fw


@pytest.fixture
def mock_focuser():
    foc = MagicMock(name="SimFocuser")
    foc.device_type = "Focuser"
    foc.name = "SimFocuser"
    foc.is_connected = True
    foc.position = 5000
    foc.temperature = 15.0
    foc.is_moving = False
    foc.move_to = AsyncMock()
    foc.move_by = AsyncMock()
    return foc


@pytest.fixture
def mock_rotator():
    rot = MagicMock(name="SimRotator")
    rot.device_type = "Rotator"
    rot.name = "SimRotator"
    rot.is_connected = True
    rot.mechanical_angle = 0.0
    rot.sky_angle = 0.0
    rot.move_to_angle = AsyncMock()
    return rot


@pytest.fixture
def mock_flat_panel():
    fp = MagicMock(name="SimFlatPanel")
    fp.device_type = "FlatPanel"
    fp.name = "SimFlatPanel"
    fp.is_connected = True
    fp.cover_state = "Closed"
    fp.brightness = 0
    fp.open_cover = AsyncMock()
    fp.close_cover = AsyncMock()
    fp.set_brightness = AsyncMock()
    return fp


@pytest.fixture
def mock_weather_station():
    wx = MagicMock(name="SimWeather")
    wx.device_type = "WeatherStation"
    wx.name = "SimWeather"
    wx.is_connected = True
    wx.cloud_cover = 0.1
    wx.wind_speed = 5.0
    wx.humidity = 60.0
    wx.temperature = 12.0
    wx.rain_rate = 0.0
    wx.is_safe = True
    wx.poll = AsyncMock()
    return wx


@pytest.fixture
def mock_safety_monitor():
    sm = MagicMock(name="SimSafetyMonitor")
    sm.device_type = "SafetyMonitor"
    sm.name = "SimSafetyMonitor"
    sm.is_connected = True
    sm.is_safe = True
    sm.explanation = "All sensors nominal"
    sm.poll = AsyncMock()
    return sm


@pytest.fixture
def mock_dome():
    dome = MagicMock(name="SimDome")
    dome.device_type = "Dome"
    dome.name = "SimDome"
    dome.is_connected = True
    dome.azimuth = 180.0
    dome.shutter_state = "Open"
    dome.is_at_park = False
    dome.slew_to_azimuth = AsyncMock()
    dome.open_shutter = AsyncMock()
    dome.close_shutter = AsyncMock()
    dome.park = AsyncMock()
    return dome


@pytest.fixture
def mock_guider():
    g = MagicMock(name="SimGuider")
    g.host = "localhost"
    g.port = 4400
    g.is_connected = True
    g.is_guiding = False
    g.rms_ra = 0.42
    g.rms_dec = 0.31
    g.connect = AsyncMock()
    g.start_guiding = AsyncMock()
    g.stop_guiding = AsyncMock()
    g.dither = AsyncMock()
    g.wait_for_settle = AsyncMock(return_value=True)
    return g


@pytest.fixture
def mock_switch_device():
    sw = MagicMock(name="SimSwitch")
    sw.device_type = "Switch"
    sw.name = "SimSwitch"
    sw.is_connected = True
    sw.switches = [
        MagicMock(name="Power-Cam", state=False, is_analog=False),
        MagicMock(name="Power-Mount", state=True, is_analog=False),
        MagicMock(name="Dew-Heater", state=0.0, is_analog=True),
    ]
    sw.set_switch = AsyncMock()
    return sw


# ---------------------------------------------------------------------------
# Sequence / scheduler fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_sequence():
    return {
        "name": "M42 Ha",
        "version": 1,
        "targets": [
            {
                "name": "M42",
                "ra_deg": 83.8221,
                "dec_deg": -5.3911,
                "steps": [
                    {
                        "filter": "Ha",
                        "exposure": 300.0,
                        "count": 20,
                        "binning": 1,
                        "frame_type": "Light",
                    }
                ],
            }
        ],
    }


@pytest.fixture
def minimal_profile():
    return {
        "name": "TestSetup",
        "version": 1,
        "piers": [
            {
                "name": "Pier-1",
                "optical_trains": [
                    {
                        "name": "MainScope",
                        "focal_length_mm": 1000,
                        "aperture_mm": 200,
                        "camera": {
                            "name": "SimCamera",
                            "backend": "indi",
                            "host": "localhost",
                            "pixel_size_um": 5.86,
                            "sensor_width_px": 4656,
                            "sensor_height_px": 3520,
                        },
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# File / FITS fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_fits_file(tmp_path):
    """Writes a minimal, valid uncompressed FITS file and returns its Path."""
    np = pytest.importorskip("numpy")
    fits = pytest.importorskip("astropy.io.fits")
    data = np.zeros((100, 100), dtype=np.float32)
    hdr = fits.Header()
    hdr["OBJECT"] = "M42"
    hdr["EXPTIME"] = 300.0
    hdr["FILTER"] = "Ha"
    hdr["GAIN"] = 100
    hdr["OFFSET"] = 0
    hdr["XBINNING"] = 1
    hdr["YBINNING"] = 1
    hdr["CCD-TEMP"] = -10.0
    hdr["DATE-OBS"] = "2026-09-16T22:00:00.000"
    hdr["TELESCOP"] = "TestScope 200"
    hdr["FOCALLEN"] = 1000.0
    hdr["XPIXSZ"] = 5.86
    hdr["YPIXSZ"] = 5.86
    hdr["IMAGETYP"] = "Light Frame"
    hdr["INSTRUME"] = "SimCamera"
    p = tmp_path / "light_ha_001.fits"
    fits.PrimaryHDU(data, header=hdr).writeto(p)
    return p


@pytest.fixture
def sample_fits_repo(tmp_path, sample_fits_file):
    """Creates a small FITS repository tree with 3 UNIQUE light frames."""
    np = pytest.importorskip("numpy")
    fits = pytest.importorskip("astropy.io.fits")
    repo = tmp_path / "repo"
    session = repo / "M42" / "2026-09-16" / "Ha"
    session.mkdir(parents=True)
    # Create 3 files with different pixel data so their SHA-256 hashes differ
    for i in range(3):
        data = np.full((100, 100), i * 1000, dtype=np.float32)
        hdr = fits.Header()
        hdr["OBJECT"] = "M42"
        hdr["FILTER"] = "Ha"
        hdr["IMAGETYP"] = "Light Frame"
        hdr["EXPTIME"] = 300.0
        hdr["DATE-OBS"] = "2026-09-16T22:00:00"
        fits.PrimaryHDU(data, header=hdr).writeto(session / f"light_ha_{i + 1:03d}.fits")
    return repo


# ---------------------------------------------------------------------------
# Misc fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus():
    """Lightweight mock of the in-process publish/subscribe event bus."""
    bus = MagicMock(name="EventBus")
    bus.publish = MagicMock()
    bus.subscribe = MagicMock()
    bus.unsubscribe = MagicMock()
    return bus


# ---------------------------------------------------------------------------
# Sky atlas catalog bootstrap (session-scoped, autouse)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _bootstrap_sky_atlas_catalog(tmp_path_factory):
    """Pre-populate the sky atlas catalog cache with 10 K synthetic objects so
    offline tests (TC-SKY-010) pass without network access."""
    try:
        from galileo.platform import get_cache_dir
        from galileo.planning.sky_atlas import _CATALOG_FILENAME, ObjectType
        cache_dir = get_cache_dir()
        catalog_path = cache_dir / _CATALOG_FILENAME
        if catalog_path.exists() and catalog_path.stat().st_size > 10_000:
            return  # already populated

        # Include a few real Messier/NGC designations so catalog search tests pass
        key_objects = [
            {"n": "M42", "d": ["M42", "NGC 1976", "Orion Nebula"],
             "r": 83.8221, "c": -5.3911, "t": "Nebula", "m": 4.0, "s": 85.0},
            {"n": "M31", "d": ["M31", "NGC 224", "Andromeda Galaxy"],
             "r": 10.6847, "c": 41.2692, "t": "Galaxy", "m": 3.4, "s": 189.0},
            {"n": "M45", "d": ["M45", "Pleiades"],
             "r": 56.8750, "c": 24.1167, "t": "OpenCluster", "m": 1.6, "s": 110.0},
        ]
        objects = key_objects[:]
        types = [t.value for t in ObjectType]
        for i in range(10_500):
            objects.append({
                "n": f"NGC {i + 1}",
                "d": [f"NGC {i + 1}"],
                "r": (i * 360.0 / 10_500) % 360.0,
                "c": -90.0 + (i % 180),
                "t": types[i % len(types)],
                "m": 6.0 + (i % 8),
                "s": 1.0 + (i % 20),
            })
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(json.dumps(objects), encoding="utf-8")
    except Exception:
        pass  # non-fatal; tests that need the catalog will fail informatively
