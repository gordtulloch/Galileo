# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""EXT — External Interface Requirements (TC-EXT-010 … TC-EXT-150).

EXT-100 (AAVSO Target Tool API) is retired from core: it covered a
VSTarget-plugin-only integration and now lives as VST-EXT-010 in
docs/plugins/vstarget/SRS.md, tested in tests/test_vst.py.
"""

from pathlib import Path

import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# TC-EXT-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-010")
@pytest.mark.priority("MVP")
def test_tc_ext_010_pyside6_gui_entry_point():
    """EXT-010: The system shall provide a graphical desktop UI as the sole primary interactive interface."""
    app_module = pytest.importorskip("galileo.app")
    assert hasattr(app_module, "main"), "galileo.app must expose a main() entry point"
    assert callable(app_module.main)


# ---------------------------------------------------------------------------
# TC-EXT-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-020")
@pytest.mark.priority("MVP")
def test_tc_ext_020_indi_and_alpaca_only():
    """EXT-020: Devices connected only via INDI TCP or Alpaca HTTP/REST — no direct driver binding."""
    devices = pytest.importorskip("galileo.core.devices")
    assert hasattr(devices, "DeviceBackend"), "DeviceBackend base class must exist"
    indi = pytest.importorskip("galileo.adapters.indi")
    alpaca = pytest.importorskip("galileo.adapters.alpaca")
    assert issubclass(indi.IndiAdapter, devices.DeviceBackend)
    assert issubclass(alpaca.AlpacaAdapter, devices.DeviceBackend)


# ---------------------------------------------------------------------------
# TC-EXT-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-030")
@pytest.mark.priority("MVP")
def test_tc_ext_030_remote_connection_host_port():
    """EXT-030: Connect to an INDI server or Alpaca device at a configurable host:port over LAN/WAN."""
    indi = pytest.importorskip("galileo.adapters.indi")
    adapter = indi.IndiAdapter(host="192.168.1.50", port=7624)
    assert adapter.host == "192.168.1.50"
    assert adapter.port == 7624

    alpaca = pytest.importorskip("galileo.adapters.alpaca")
    adapter_a = alpaca.AlpacaAdapter(host="192.168.1.50", port=11111)
    assert adapter_a.host == "192.168.1.50"
    assert adapter_a.port == 11111


@pytest.mark.requirement("TC-EXT-030")
@pytest.mark.priority("MVP")
async def test_tc_ext_030_unreachable_alpaca_device_raises_device_connection_error():
    """EXT-030: an unreachable Alpaca device (unresolvable .local name, or a
    refused connection) surfaces as a DeviceConnectionError, not a raw
    RuntimeError/httpx/socket error."""
    from galileo.adapters import alpaca
    from galileo.exceptions import DeviceConnectionError

    adapter = alpaca.AlpacaAdapter(host="seestar.local", port=32323)
    with patch.object(alpaca, "resolve_mdns_host_sync", side_effect=DeviceConnectionError("no mDNS")):
        with pytest.raises(DeviceConnectionError, match="no mDNS"):
            await adapter.connect()

    # Port 1 on loopback refuses immediately.
    adapter = alpaca.AlpacaAdapter(host="127.0.0.1", port=1)
    with pytest.raises(DeviceConnectionError, match="127.0.0.1:1 is not responding"):
        await adapter.connect()


@pytest.mark.requirement("TC-EXT-030")
@pytest.mark.priority("MVP")
def test_tc_ext_030_connectivity_failures_log_without_traceback():
    """EXT-030: an unreachable device is reported in the log as one readable
    line, while genuine (non-connectivity) errors keep their traceback."""
    import logging
    from galileo.diagnostics import _ConciseFormatter, _LOG_FORMAT
    from galileo.exceptions import DeviceConnectionError

    formatter = _ConciseFormatter(_LOG_FORMAT)

    def render(exc: BaseException) -> str:
        try:
            raise exc
        except type(exc):
            import sys
            record = logging.LogRecord(
                "galileo.ui.app_window", logging.ERROR, __file__, 1,
                "Could not connect %s", ("focuser",), sys.exc_info(),
            )
        first = formatter.format(record)
        assert formatter.format(record) == first  # formatting twice must not change it
        return first

    concise = render(DeviceConnectionError("device is off"))
    assert concise.endswith("Could not connect focuser — device is off")
    assert "Traceback" not in concise

    assert "Traceback" in render(KeyError("bug"))


# ---------------------------------------------------------------------------
# TC-EXT-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-040")
@pytest.mark.priority("MVP")
def test_tc_ext_040_plate_solver_external_cli_or_http():
    """EXT-040: Interoperate with external plate-solving engines via command-line or local HTTP."""
    platesolve = pytest.importorskip("galileo.platesolve")
    solver = platesolve.PlateSolver(backend="astap", executable="/usr/bin/astap")
    assert solver.backend == "astap"
    # Solver must expose an async solve() method
    assert callable(getattr(solver, "solve", None))


# ---------------------------------------------------------------------------
# TC-EXT-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-050")
@pytest.mark.priority("MVP")
def test_tc_ext_050_guider_phd2_compatible_interface():
    """EXT-050: Interoperate with external autoguiding applications via a PHD2-compatible JSON-RPC interface."""
    guiding = pytest.importorskip("galileo.guiding")
    service = guiding.GuidingService(host="localhost", port=4400)
    assert service.host == "localhost"
    assert service.port == 4400
    for method in ("connect", "start_guiding", "stop_guiding", "dither"):
        assert callable(getattr(service, method, None)), f"GuidingService must have {method}()"


# ---------------------------------------------------------------------------
# TC-EXT-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-060")
@pytest.mark.priority("MVP")
def test_tc_ext_060_fits_only_output(tmp_path):
    """EXT-060: Image files written in FITS format only to a user-configured filesystem location."""
    metadata = pytest.importorskip("galileo.metadata")
    np = pytest.importorskip("numpy")
    writer = metadata.FitsMetadataWriter(output_dir=tmp_path)
    data = np.zeros((100, 100), dtype=np.float32)
    out_path = writer.write(data, {"OBJECT": "M42", "EXPTIME": 300.0, "IMAGETYP": "Light Frame"})
    assert out_path.suffix.lower() == ".fits"
    assert out_path.exists()


# ---------------------------------------------------------------------------
# TC-EXT-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-070")
@pytest.mark.priority("P3")
def test_tc_ext_070_outbound_notification_endpoints():
    """EXT-070: Support outbound notification integrations (webhook, email, push) as configurable optional endpoints."""
    notify = pytest.importorskip("galileo.notify")
    service = notify.NotificationService()
    service.add_channel(notify.WebhookChannel(url="https://example.com/hook"))
    assert len(service.channels) == 1
    assert isinstance(service.channels[0], notify.WebhookChannel)


# ---------------------------------------------------------------------------
# TC-EXT-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-080")
@pytest.mark.priority("MVP")
def test_tc_ext_080_smb_ftp_smart_telescope_adapters():
    """EXT-080: Connect to smart-telescope network shares via SMB/CIFS and FTP/FTPS."""
    library = pytest.importorskip("galileo.library")
    assert hasattr(library, "SmartTelescopeSmbAdapter"), "SMB adapter must be present"
    assert hasattr(library, "SmartTelescopeFtpAdapter"), "FTP adapter must be present"


# ---------------------------------------------------------------------------
# TC-EXT-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-090")
@pytest.mark.priority("P2")
def test_tc_ext_090_google_cloud_storage_sync():
    """EXT-090: Synchronize repository contents with Google Cloud Storage via its documented API."""
    cloud = pytest.importorskip("galileo.library.services.cloud")
    assert callable(cloud.sync_with_google_cloud_repo), "the Google Cloud Storage sync must be present"
    assert callable(cloud.validate_google_cloud_config)


# ---------------------------------------------------------------------------
# TC-EXT-110
# ---------------------------------------------------------------------------
# Note: EXT-100 (AAVSO Target Tool API) is retired from core — it covered a
# VSTarget-plugin-only integration and now lives as TC-VST-EXT-010 in
# tests/test_vst.py, matching docs/plugins/vstarget/SRS.md.

@pytest.mark.requirement("TC-EXT-110")
@pytest.mark.priority("MVP")
def test_tc_ext_110_simbad_coordinate_lookup():
    """EXT-110: Query the Simbad astronomical database for target coordinate/magnitude lookup — genuinely shared infrastructure, also backing SKY-100's fallback lookup (not AAVSO-specific)."""
    import sys
    import types
    from astropy.table import Table

    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    queried: list[tuple[str, tuple[str, ...]]] = []

    class FakeSimbad:
        """Stands in for ``astroquery.simbad.Simbad``: answers the primary name/type/coordinate query
        and the follow-up V-magnitude query, so no network is touched."""
        def __init__(self):
            self.fields: tuple[str, ...] = ()

        def add_votable_fields(self, *fields):
            self.fields += fields

        def query_object(self, name, wildcard=False):
            queried.append((name, self.fields))
            if "V" in self.fields:
                return Table({"V": [3.44]})
            return Table({"main_id": ["M  31"], "ra": [10.6847], "dec": [41.2687], "otype": ["G"]})

    fake_module = types.ModuleType("astroquery.simbad")
    fake_module.Simbad = FakeSimbad
    with patch.dict(sys.modules, {"astroquery.simbad": fake_module}):
        results = sky_mod._search_simbad_sync("M31")

    assert len(results) == 1
    obj = results[0]
    assert obj.primary_name == "M31"
    assert (obj.ra_deg, obj.dec_deg) == pytest.approx((10.6847, 41.2687))   # coordinates
    assert obj.magnitude == pytest.approx(3.44)                              # magnitude, via the follow-up query
    assert [name for name, _ in queried] == ["M31", "M31"]


# ---------------------------------------------------------------------------
# TC-EXT-120
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-120")
@pytest.mark.priority("MVP")
def test_tc_ext_120_sftp_remote_telescope_retrieval():
    """EXT-120: Retrieve calibrated FITS images from a remote-telescope data server via SFTP, in addition to the FTP/FTPS access already required by EXT-080 — the adapter lives in core galileo.library.adapters, reused (not owned) by the VSTarget plugin."""
    adapters = pytest.importorskip("galileo.library.adapters")
    assert hasattr(adapters, "SftpImageRetriever"), "SftpImageRetriever must be present"
    retriever = adapters.SftpImageRetriever.__new__(adapters.SftpImageRetriever)
    assert hasattr(retriever, "download"), "SftpImageRetriever must expose download()"


def _fake_paramiko(files, *, connect_error=None, bad_files=()):
    """A stand-in ``paramiko`` module whose SFTP server holds *files*; records what the client did."""
    import types
    state = types.SimpleNamespace(policy=None, closed=False, sftp_closed=False, fetched=[])

    class Policy:
        pass

    class RejectPolicy(Policy):
        pass

    class MissingHostKeyPolicy:
        pass

    class Entry:
        def __init__(self, filename):
            self.filename = filename

    class Sftp:
        def listdir_attr(self, path):
            return [Entry(name) for name in files]

        def get(self, remote, local, callback=None):
            if remote.rsplit("/", 1)[-1] in bad_files:
                raise OSError("transfer failed")
            state.fetched.append(remote)

        def close(self):
            state.sftp_closed = True

    class SSHClient:
        def load_system_host_keys(self):
            pass

        def set_missing_host_key_policy(self, policy):
            state.policy = policy

        def connect(self, **kwargs):
            if connect_error:
                raise connect_error

        def open_sftp(self):
            return Sftp()

        def close(self):
            state.closed = True

    module = types.ModuleType("paramiko")
    module.SSHClient, module.RejectPolicy, module.MissingHostKeyPolicy = SSHClient, RejectPolicy, MissingHostKeyPolicy
    return module, state


@pytest.mark.requirement("TC-EXT-120")
@pytest.mark.priority("MVP")
async def test_tc_ext_120_sftp_downloads_only_fits_and_skips_a_failed_file(tmp_path):
    """EXT-120: only FITS files are fetched, one failed transfer is skipped without abandoning the rest, and the connection is always closed."""
    import sys
    from galileo.library.adapters import SftpImageRetriever
    module, state = _fake_paramiko(["a.fits", "notes.txt", "b.FIT", "c.fits"], bad_files={"b.FIT"})
    with patch.dict(sys.modules, {"paramiko": module}):
        got = await SftpImageRetriever("host", "user").download(path="/data/", dest=tmp_path)
    assert [Path(g).name for g in got] == ["a.fits", "c.fits"]
    assert state.fetched == ["/data/a.fits", "/data/c.fits"]
    assert state.closed and state.sftp_closed


@pytest.mark.requirement("TC-EXT-120")
@pytest.mark.priority("MVP")
async def test_tc_ext_120_sftp_failure_is_logged_and_the_client_is_closed(tmp_path, caplog):
    """EXT-120: an unreachable server is reported at WARNING with its traceback (not buried at debug) and the client is still closed."""
    import sys
    from galileo.library.adapters import SftpImageRetriever
    module, state = _fake_paramiko([], connect_error=OSError("no route to host"))
    with patch.dict(sys.modules, {"paramiko": module}), caplog.at_level("WARNING", logger="galileo.library.adapters.sftp"):
        got = await SftpImageRetriever("203.0.113.9", "user").download(dest=tmp_path)
    assert got == []
    assert any(r.levelname == "WARNING" and r.exc_info and "203.0.113.9" in r.getMessage() for r in caplog.records)
    assert state.closed


@pytest.mark.requirement("TC-EXT-120")
@pytest.mark.priority("MVP")
async def test_tc_ext_120_sftp_host_key_policy_logs_by_default_and_rejects_when_strict(tmp_path, caplog):
    """EXT-120: an unknown host key is accepted but logged with its fingerprint by default; strict_host_keys refuses it outright."""
    import sys
    from galileo.library.adapters import SftpImageRetriever
    module, state = _fake_paramiko([])
    key = type("Key", (), {"get_name": lambda self: "ssh-ed25519", "get_fingerprint": lambda self: bytes([0xAB, 0xCD])})()
    with patch.dict(sys.modules, {"paramiko": module}), caplog.at_level("WARNING", logger="galileo.library.adapters.sftp"):
        await SftpImageRetriever("h", "u").download(dest=tmp_path)
        state.policy.missing_host_key(None, "h", key)
        assert any("unknown host key" in r.getMessage() and "abcd" in r.getMessage() for r in caplog.records)
        await SftpImageRetriever("h", "u", strict_host_keys=True).download(dest=tmp_path)
    assert isinstance(state.policy, module.RejectPolicy)


# ---------------------------------------------------------------------------
# TC-EXT-130
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-130")
@pytest.mark.priority("P2")
def test_tc_ext_130_open_meteo_geocoding():
    """EXT-130: Query the Open-Meteo API for location geocoding and weather-forecast data."""
    safety = pytest.importorskip("galileo.safety")
    assert hasattr(safety, "OpenMeteoClient"), "OpenMeteoClient must be present"
    client = safety.OpenMeteoClient.__new__(safety.OpenMeteoClient)
    assert hasattr(client, "geocode")
    assert hasattr(client, "get_forecast")


# ---------------------------------------------------------------------------
# TC-EXT-140
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-140")
@pytest.mark.priority("P2")
def test_tc_ext_140_cli_batch_commands():
    """EXT-140: Standalone CLI programs for repo ingest, calibration, and cloud sync, runnable without GUI."""
    pytest.importorskip("galileo.commands.load_repo")
    pytest.importorskip("galileo.commands.auto_calibration")
    pytest.importorskip("galileo.commands.cloud_sync")


# ---------------------------------------------------------------------------
# TC-EXT-150
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-150")
@pytest.mark.priority("P2")
async def test_tc_ext_150_telescopius_optional_and_never_a_dependency():
    """EXT-150: Optionally query the Telescopius API for object search/target-suggestion data and observing-list import (traces to SKY-110/SKY-120), authenticated exclusively via a user-supplied Telescopius API key — its absence or unavailability shall not degrade SKY-010/SKY-070/SKY-100's offline-first behavior."""
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    atlas = sky_mod.SkyAtlas()

    # No API key configured -> Telescopius is simply not queried, no error raised.
    atlas.set_telescopius_api_key(None)
    with patch.object(sky_mod, "_search_telescopius_sync") as mock_telescopius:
        results = await atlas.search_online("M42")
        assert any("M42" in obj.designations for obj in results), "offline-first path still works"
        mock_telescopius.assert_not_called()

    # API key configured but the service is unreachable -> degrades gracefully, no exception.
    atlas.set_telescopius_api_key("user-supplied-key")
    with patch.object(sky_mod, "_search_telescopius_sync", side_effect=OSError("unreachable")):
        results = await atlas.search_online("M42")
        assert any("M42" in obj.designations for obj in results), "offline-first path unaffected"


@pytest.mark.requirement("TC-EXT-070")
@pytest.mark.priority("P3")
async def test_tc_ext_070_webhook_refuses_non_http_urls(caplog):
    """EXT-070: a webhook endpoint is an HTTP(S) POST — a file:// or ftp:// URL is refused and logged, never opened."""
    from galileo import notify
    channel = notify.WebhookChannel(url="file:///etc/passwd")
    note = notify._Notification(notify.NotificationEvent.SEQUENCE_COMPLETE, "done")
    with patch("urllib.request.urlopen") as opened, caplog.at_level("ERROR", logger="galileo.notify"):
        await channel.send(note)
    opened.assert_not_called()
    assert any("non-HTTP" in r.getMessage() for r in caplog.records)
