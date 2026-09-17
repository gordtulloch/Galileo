"""EXT — External Interface Requirements (TC-EXT-010 … TC-EXT-140)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# TC-EXT-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-010")
@pytest.mark.priority("MVP")
def test_tc_ext_010_pyside6_gui_entry_point():
    """EXT-010: The system shall provide a graphical desktop UI as the sole primary interactive interface."""
    app_module = pytest.importorskip("galileo.app")
    assert hasattr(app_module, "main"), "galileo.app must expose a main() entry point"
    import inspect
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
    library = pytest.importorskip("galileo.library")
    assert hasattr(library, "CloudSyncService"), "CloudSyncService must be present"
    sync = library.CloudSyncService.__new__(library.CloudSyncService)
    assert hasattr(sync, "sync")


# ---------------------------------------------------------------------------
# TC-EXT-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-100")
@pytest.mark.priority("MVP")
def test_tc_ext_100_aavso_target_tool_api():
    """EXT-100: Retrieve variable-star target data from the AAVSO Target Tool API."""
    vst = pytest.importorskip("galileo.vstarget.planning")
    client = vst.AavsoTargetToolClient.__new__(vst.AavsoTargetToolClient)
    assert hasattr(client, "fetch_targets"), "Must expose fetch_targets(section)"


# ---------------------------------------------------------------------------
# TC-EXT-110
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-110")
@pytest.mark.priority("MVP")
def test_tc_ext_110_simbad_coordinate_lookup():
    """EXT-110: Query the Simbad astronomical database for target coordinate/magnitude lookup."""
    vst = pytest.importorskip("galileo.vstarget.planning")
    assert hasattr(vst, "SimbadClient"), "SimbadClient must be present"
    client = vst.SimbadClient.__new__(vst.SimbadClient)
    assert hasattr(client, "lookup"), "SimbadClient must expose lookup(target_name)"


# ---------------------------------------------------------------------------
# TC-EXT-120
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-EXT-120")
@pytest.mark.priority("MVP")
def test_tc_ext_120_sftp_remote_telescope_retrieval():
    """EXT-120: Retrieve calibrated FITS images from a remote-telescope data server via SFTP."""
    analysis = pytest.importorskip("galileo.vstarget.analysis")
    assert hasattr(analysis, "SftpImageRetriever"), "SftpImageRetriever must be present"
    retriever = analysis.SftpImageRetriever.__new__(analysis.SftpImageRetriever)
    assert hasattr(retriever, "download"), "SftpImageRetriever must expose download()"


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
    pytest.importorskip("galileo.commands.calibrate")
    pytest.importorskip("galileo.commands.cloud_sync")
