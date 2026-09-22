# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

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


# ---------------------------------------------------------------------------
# Pixel format — what other astronomy software can actually open
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-META-010")
@pytest.mark.priority("MVP")
def test_tc_meta_010_written_frames_use_a_pixel_format_other_software_reads(tmp_path):
    """META-010: no frame Galileo writes uses a 64-bit sample format — legal FITS, and astropy reads it, but ASTAP and Tenmon reject it."""
    import json
    import numpy as np
    from astropy.io import fits
    from galileo.metadata import FitsMetadataWriter

    # An Alpaca camera's image arrives as JSON numbers, which numpy makes 64-bit integers.
    alpaca = np.asarray(json.loads(json.dumps([[100, 200], [300, 400]]))).swapaxes(0, 1)
    assert alpaca.dtype == np.int64, "the case this guards against"

    for name, data in (("alpaca", alpaca), ("float64", np.zeros((4, 4))),
                       ("uint16", np.zeros((4, 4), dtype=np.uint16)),
                       ("float32", np.zeros((4, 4), dtype=np.float32))):
        path = FitsMetadataWriter(output_dir=tmp_path).write(data, {"object": "M 31"}, filename=f"{name}.fits")
        bitpix = fits.getheader(path)["BITPIX"]
        assert bitpix in (8, 16, 32, -32), f"{name}: BITPIX {bitpix} is not one other tools read"


@pytest.mark.requirement("TC-META-010")
@pytest.mark.priority("MVP")
def test_tc_meta_010_normalising_pixels_keeps_the_image():
    """META-010: converting to a portable sample format preserves the pixel values and leaves an already-portable frame untouched."""
    import numpy as np
    from galileo.metadata import normalise_pixels

    counts = np.array([[0, 1000], [30000, 65535]], dtype=np.int64)
    converted = normalise_pixels(counts)
    assert converted.dtype == np.uint16 and np.array_equal(converted, counts)

    # Already portable: handed back as-is, not copied into something else.
    for dtype in (np.uint16, np.int16, np.int32, np.float32, np.uint8):
        original = np.zeros((2, 2), dtype=dtype)
        assert normalise_pixels(original) is original

    # Beyond 16 bits, and negatives, keep their values rather than wrapping round.
    wide = normalise_pixels(np.array([[-5, 200000]], dtype=np.int64))
    assert wide.dtype == np.int32 and wide.tolist() == [[-5, 200000]]
    stacked = normalise_pixels(np.array([[1.5, 2.5]], dtype=np.float64))
    assert stacked.dtype == np.float32 and stacked.tolist() == [[1.5, 2.5]]


@pytest.mark.requirement("TC-META-010")
@pytest.mark.priority("MVP")
def test_tc_meta_010_bscale_bzero_land_right_after_naxis_not_after_custom_keywords():
    """META-010: for unsigned pixel data, BSCALE/BZERO must come immediately after NAXIS2, ahead of every custom
    keyword — ASTAP's parser refuses a file where they land at the end, behind the rest of the header, even though
    it is otherwise entirely standard FITS that astropy (and Tenmon) read without complaint."""
    import numpy as np
    from galileo.metadata import build_primary_hdu

    # uint16 needs the unsigned-integer BZERO/BSCALE convention; uint8 does not (BZERO defaults to 0).
    for dtype, expect_bscale in ((np.uint16, True), (np.uint8, False)):
        data = np.zeros((10, 10), dtype=dtype)
        hdu = build_primary_hdu(data, {"object": "M 31", "telescope": "Newt 200", "instrument": "ASI294"})
        keys = list(hdu.header.keys())
        naxis2 = keys.index("NAXIS2")
        custom_positions = [keys.index(k) for k in ("OBJECT", "TELESCOP", "INSTRUME")]
        if expect_bscale:
            assert "BZERO" in keys and "BSCALE" in keys
            assert keys.index("BZERO") < min(custom_positions), f"{dtype}: BZERO must precede custom keywords"
            assert keys.index("BSCALE") < min(custom_positions), f"{dtype}: BSCALE must precede custom keywords"
            # Nothing but structural cards (e.g. EXTEND) sits between NAXIS2 and BZERO/BSCALE.
            assert keys.index("BZERO") - naxis2 <= 3, f"{dtype}: BZERO is not right after NAXIS2"
        else:
            assert "BZERO" not in keys, f"{dtype}: signed/8-bit data needs no BZERO"


@pytest.mark.requirement("TC-META-010")
@pytest.mark.priority("MVP")
def test_tc_meta_010_build_primary_hdu_round_trips_and_keeps_extra_cards():
    """META-010: build_primary_hdu's output is readable, its pixels survive, and extra_cards (session keywords, DATE) still land after the metadata cards."""
    import numpy as np
    from astropy.io import fits
    from galileo.metadata import build_primary_hdu

    data = np.arange(100, dtype=np.uint16).reshape(10, 10)
    hdu = build_primary_hdu(data, {"object": "M 31"}, extra_cards=[("SITEELEV", 250), ("DATE", "2026-01-01T00:00:00")])
    assert np.array_equal(hdu.data, data)
    keys = list(hdu.header.keys())
    assert keys.index("OBJECT") < keys.index("SITEELEV") < keys.index("DATE")
    assert hdu.header["SITEELEV"] == 250 and hdu.header["DATE"] == "2026-01-01T00:00:00"
