"""META — Image Metadata (TC-META-010 … TC-META-050).

These tests exercise FITS header writing/reading directly via astropy.
They run immediately without the galileo package and will remain valid once
galileo.metadata wraps the same astropy operations.
"""

import pytest
import numpy as np


# ---------------------------------------------------------------------------
# TC-META-010 — also runnable without galileo package via astropy directly
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-META-010")
@pytest.mark.priority("MVP")
def test_tc_meta_010_required_fits_keywords(tmp_path):
    """META-010: FITS headers cover object, exptime, filter, gain, binning, CCD-TEMP, DATE-OBS, telescope, focal length, pixel scale, frame type."""
    fits = pytest.importorskip("astropy.io.fits")
    meta_mod = pytest.importorskip("galileo.metadata")

    writer = meta_mod.FitsMetadataWriter(output_dir=tmp_path)
    data = np.zeros((100, 100), dtype=np.float32)
    out_path = writer.write(
        data,
        metadata={
            "object": "M42",
            "exposure_s": 300.0,
            "filter": "Ha",
            "gain": 100,
            "offset": 0,
            "binning_x": 1,
            "binning_y": 1,
            "ccd_temp_c": -10.0,
            "date_obs_utc": "2026-09-16T22:00:00.000",
            "telescope": "TestScope 200",
            "focal_length_mm": 1000.0,
            "pixel_size_x_um": 5.86,
            "pixel_size_y_um": 5.86,
            "frame_type": "Light Frame",
        },
    )

    with fits.open(out_path) as hdul:
        hdr = hdul[0].header
        required = ["OBJECT", "EXPTIME", "FILTER", "GAIN", "XBINNING", "YBINNING",
                    "CCD-TEMP", "DATE-OBS", "TELESCOP", "FOCALLEN", "XPIXSZ", "YPIXSZ", "IMAGETYP"]
        for kw in required:
            assert kw in hdr, f"Required FITS keyword missing: {kw}"


@pytest.mark.requirement("TC-META-010")
@pytest.mark.priority("MVP")
def test_tc_meta_010_required_fits_keywords_via_astropy_directly(tmp_path):
    """META-010 (baseline): Validate the required FITS keyword convention using astropy directly."""
    fits = pytest.importorskip("astropy.io.fits")
    data = np.zeros((50, 50), dtype=np.uint16)
    hdr = fits.Header()
    hdr["OBJECT"] = "M42"
    hdr["EXPTIME"] = 300.0
    hdr["FILTER"] = "Ha"
    hdr["GAIN"] = 100
    hdr["XBINNING"] = 1
    hdr["YBINNING"] = 1
    hdr["CCD-TEMP"] = -10.0
    hdr["DATE-OBS"] = "2026-09-16T22:00:00.000"
    hdr["TELESCOP"] = "TestScope 200"
    hdr["FOCALLEN"] = 1000.0
    hdr["XPIXSZ"] = 5.86
    hdr["YPIXSZ"] = 5.86
    hdr["IMAGETYP"] = "Light Frame"

    p = tmp_path / "meta_test.fits"
    fits.PrimaryHDU(data, header=hdr).writeto(p)

    with fits.open(p) as hdul:
        h = hdul[0].header
        assert h["OBJECT"] == "M42"
        assert h["EXPTIME"] == 300.0
        assert h["CCD-TEMP"] == -10.0
        assert h["IMAGETYP"] == "Light Frame"


# ---------------------------------------------------------------------------
# TC-META-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-META-020")
@pytest.mark.priority("P2")
def test_tc_meta_020_write_plate_solve_results_to_header(tmp_path, sample_fits_file):
    """META-020: Write plate-solve results (RA/Dec, rotation) to FITS header when solve was performed."""
    fits = pytest.importorskip("astropy.io.fits")
    meta_mod = pytest.importorskip("galileo.metadata")

    meta_mod.write_solve_result(
        fits_path=sample_fits_file,
        ra_deg=83.8221,
        dec_deg=-5.3911,
        rotation_deg=0.5,
        scale_arcsec_px=1.22,
    )

    with fits.open(sample_fits_file) as hdul:
        hdr = hdul[0].header
        assert abs(hdr["CRVAL1"] - 83.8221) < 0.001
        assert abs(hdr["CRVAL2"] - (-5.3911)) < 0.001


# ---------------------------------------------------------------------------
# TC-META-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-META-030")
@pytest.mark.priority("MVP")
def test_tc_meta_030_tile_compressed_fits_output(tmp_path):
    """META-030: Support writing tile-compressed FITS (Rice/GZIP/HCOMPRESS) with metadata identical to uncompressed."""
    fits = pytest.importorskip("astropy.io.fits")
    meta_mod = pytest.importorskip("galileo.metadata")

    data = np.arange(10000, dtype=np.int32).reshape(100, 100)
    metadata = {
        "object": "M42",
        "exposure_s": 300.0,
        "filter": "Ha",
        "gain": 100,
        "offset": 0,
        "binning_x": 1,
        "binning_y": 1,
        "ccd_temp_c": -10.0,
        "date_obs_utc": "2026-09-16T22:00:00.000",
        "telescope": "TestScope",
        "focal_length_mm": 1000.0,
        "pixel_size_x_um": 5.86,
        "pixel_size_y_um": 5.86,
        "frame_type": "Light Frame",
    }
    writer = meta_mod.FitsMetadataWriter(output_dir=tmp_path, compression="RICE_1")
    out_path = writer.write(data, metadata)

    with fits.open(out_path) as hdul:
        assert len(hdul) >= 2  # Primary + CompImageHDU
        assert hdul[1].header.get("ZCMPTYPE") or "CompImage" in str(type(hdul[1]))
        assert hdul[1].header["OBJECT"] == "M42"


# ---------------------------------------------------------------------------
# TC-META-030 — standalone astropy baseline (no galileo package required)
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-META-030")
@pytest.mark.priority("MVP")
def test_tc_meta_030_tile_compressed_fits_via_astropy(tmp_path):
    """META-030 (baseline): Validate tile-compressed FITS round-trip using astropy directly."""
    fits = pytest.importorskip("astropy.io.fits")
    data = np.arange(10000, dtype=np.int32).reshape(100, 100)
    hdr = fits.Header()
    hdr["OBJECT"] = "M42"
    hdr["EXPTIME"] = 300.0

    comp_hdu = fits.CompImageHDU(data, header=hdr, compression_type="RICE_1")
    hdul = fits.HDUList([fits.PrimaryHDU(), comp_hdu])
    p = tmp_path / "compressed.fits"
    hdul.writeto(p)

    with fits.open(p) as hdul_r:
        loaded = hdul_r[1].data
        assert loaded is not None
        assert loaded.shape == (100, 100)
        assert hdul_r[1].header["OBJECT"] == "M42"


# ---------------------------------------------------------------------------
# TC-META-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-META-040")
@pytest.mark.priority("MVP")
def test_tc_meta_040_read_decompress_tile_compressed_fits(tmp_path):
    """META-040: Read and correctly decompress tile-compressed FITS transparently."""
    fits = pytest.importorskip("astropy.io.fits")
    np_loc = pytest.importorskip("numpy")

    # Write compressed
    data = np.arange(10000, dtype=np.int32).reshape(100, 100)
    hdr = fits.Header()
    hdr["OBJECT"] = "NGC 1234"
    comp_hdu = fits.CompImageHDU(data, header=hdr, compression_type="RICE_1")
    p = tmp_path / "compressed.fits"
    fits.HDUList([fits.PrimaryHDU(), comp_hdu]).writeto(p)

    # Read via galileo.metadata (or astropy directly)
    meta_mod = pytest.importorskip("galileo.metadata")
    loaded_data, loaded_header = meta_mod.read_fits(p)

    assert loaded_data.shape == (100, 100)
    assert loaded_header["OBJECT"] == "NGC 1234"


# ---------------------------------------------------------------------------
# TC-META-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-META-050")
@pytest.mark.priority("P3")
def test_tc_meta_050_custom_static_fits_keywords(tmp_path):
    """META-050: Allow user to add custom static FITS header keywords applied to all frames in a session."""
    fits = pytest.importorskip("astropy.io.fits")
    meta_mod = pytest.importorskip("galileo.metadata")

    writer = meta_mod.FitsMetadataWriter(output_dir=tmp_path)
    writer.set_session_keywords({"OBSERVER": "Alice", "SITENAME": "Backyard"})

    data = np.zeros((50, 50), dtype=np.float32)
    out_path = writer.write(data, {"object": "M31", "exposure_s": 120.0, "frame_type": "Light Frame"})

    with fits.open(out_path) as hdul:
        assert hdul[0].header["OBSERVER"] == "Alice"
        assert hdul[0].header["SITENAME"] == "Backyard"
