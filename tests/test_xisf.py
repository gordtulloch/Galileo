# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""XISF import (LIB-010, TC-LIB-010) — the converter, its type/data helpers and the Library's ingest handler.

XISF is accepted only on import and converted to FITS (FITS-only constraint, SDD §4.18). These tests build real
``.xisf`` files in a temporary folder, so every codec the converter claims to read is exercised end to end.
"""

import gzip
import struct
import zlib

import numpy as np
import pytest
from astropy.io import fits

from galileo.library.file_formats.xisfFile import (
    XISFConverter,
    XISFGeometry,
    XISFSampleFormat,
    prepare_fits_data,
    validate_data_integrity,
)

_NS = "http://www.pixinsight.com/xisf"


def build_xisf(
    path,
    pixels: np.ndarray | None = None,
    *,
    geometry: str | None = None,
    sample_format: str = "UInt16",
    codec: str = "",
    keywords: dict | None = None,
    image_attrs: str = "",
    extra_xml: str = "",
    payload: bytes | None = None,
    location: str | None = None,
    namespaced: bool = True,
):
    """Write a minimal XISF 1.0 monolithic file and return its path.

    *pixels* is stored little-endian under *codec* ("", "zlib", "zlib+sh", "gzip"); *payload* overrides the stored bytes
    and *location* the ``location`` attribute, for building deliberately broken files.
    """
    if pixels is not None:
        raw = pixels.astype(pixels.dtype.newbyteorder("<")).tobytes()
        if geometry is None:
            geometry = ":".join(str(n) for n in reversed(pixels.shape))
    else:
        raw = b""
    stored = payload
    compression = ""
    if stored is None:
        if codec == "zlib":
            stored = zlib.compress(raw)
        elif codec == "zlib+sh":
            item = pixels.dtype.itemsize
            shuffled = np.frombuffer(raw, dtype=np.uint8).reshape(-1, item).T.copy().tobytes()
            stored = zlib.compress(shuffled)
        elif codec == "gzip":
            stored = gzip.compress(raw)
        else:
            stored = raw
        if codec:
            compression = f' compression="{codec}:{len(raw)}"'

    keyword_xml = "".join(
        f'<FITSKeyword name="{name}" value="{value}" comment="{name.lower()} note"/>' for name, value in (keywords or {}).items()
    )

    def document(offset: int) -> bytes:
        loc = location if location is not None else f"attachment:{offset:08d}:{len(stored):08d}"
        ns = f' xmlns="{_NS}"' if namespaced else ""
        return (
            f'<?xml version="1.0" encoding="UTF-8"?><xisf version="1.0"{ns}>'
            f'<Image geometry="{geometry}" sampleFormat="{sample_format}" location="{loc}"{compression}{image_attrs}>'
            f"{keyword_xml}</Image>{extra_xml}</xisf>"
        ).encode("utf-8")

    xml = document(0)                    # the attachment offset is fixed-width, so the length is the same for any offset
    xml = document(16 + len(xml))
    path.write_bytes(b"XISF0100" + struct.pack("<I", len(xml)) + struct.pack("<I", 0) + xml + stored)
    return str(path)


@pytest.fixture
def frame():
    """A 6x4 16-bit image with distinct values, so byte order and reshaping errors show up."""
    return (np.arange(24, dtype=np.uint16).reshape(4, 6) * 257) + 3


# ---------------------------------------------------------------------------
# Sample formats and geometry
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("name,size,bitpix,dtype", [
    ("UInt8", 1, 8, "<u1"),
    ("UInt16", 2, 16, "<u2"),
    ("UInt32", 4, 32, "<u4"),
    ("UInt64", 8, 64, "<u8"),
    ("Int16", 2, 16, "<i2"),
    ("Int32", 4, 32, "<i4"),
    ("Float32", 4, -32, "<f4"),
    ("Float64", 8, -64, "<f8"),
    ("Complex32", 8, -32, "<c8"),
    ("Complex64", 16, -64, "<c16"),
])
def test_tc_lib_010_xisf_sample_format_maps_to_fits(name, size, bitpix, dtype):
    """LIB-010: every XISF sample format has the right byte size, FITS BITPIX and little-endian numpy dtype."""
    fmt = XISFSampleFormat(name)
    assert (fmt.size(), fmt.to_fits_bitpix(), fmt.to_numpy_dtype()) == (size, bitpix, dtype)
    assert XISFSampleFormat.from_string(name) is fmt
    assert fmt.is_unsigned() == name.startswith("UInt")
    assert fmt.is_complex() == name.startswith("Complex")
    assert fmt.is_floating_point() == (name.startswith(("Float", "Complex")))


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xisf_unknown_sample_format_is_rejected():
    """LIB-010: an unrecognised sample format is an error, not a silent default."""
    with pytest.raises(ValueError, match="Unknown sample format"):
        XISFSampleFormat.from_string("Float16")


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xisf_geometry_properties():
    """LIB-010: XISF geometry strings give width/height/channels, a pixel total and the FITS array shape."""
    mono = XISFGeometry("1024:768")
    assert (mono.width, mono.height, mono.channels, mono.total_pixels) == (1024, 768, 1, 1024 * 768)
    assert not mono.is_color and mono.to_fits_shape() == (768, 1024)

    rgb = XISFGeometry("100:50:3")
    assert (rgb.channels, rgb.total_pixels, rgb.channel_size()) == (3, 15000, 5000)
    assert rgb.is_color and rgb.is_multidimensional and rgb.to_fits_shape() == (3, 50, 100)

    for bad in ("100", "a:b", ""):
        with pytest.raises(ValueError):
            XISFGeometry(bad)


# ---------------------------------------------------------------------------
# Preparing pixel data for FITS
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("fmt,source,dtype,bitpix", [
    ("UInt8", np.array([0, 255], dtype=np.uint8), np.uint8, 8),
    ("UInt16", np.array([0, 65535], dtype=np.uint16), np.uint16, 16),
    ("Int16", np.array([-5, 7], dtype=np.int16), np.int16, 16),
    ("Int32", np.array([-5, 7], dtype=np.int32), np.int32, 32),
    ("Float32", np.array([0.5, 2.5], dtype=np.float32), np.float32, -32),
    ("Float64", np.array([0.5, 2.5], dtype=np.float64), np.float64, -64),
    ("UInt32", np.array([1, 2_000_000_000], dtype=np.uint32), np.int32, 32),
])
def test_tc_lib_010_prepare_fits_data_keeps_values(fmt, source, dtype, bitpix):
    """LIB-010: pixel data is handed to FITS in a type FITS supports, with the matching BITPIX and values intact."""
    data, got_bitpix = prepare_fits_data(source, fmt)
    assert (data.dtype, got_bitpix) == (np.dtype(dtype), bitpix)
    assert np.array_equal(data, source)


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_prepare_fits_data_widens_values_fits_cannot_hold():
    """LIB-010: UInt32 beyond the int32 range, UInt64 and complex data are widened/reduced rather than wrapped or crashed."""
    big, bitpix = prepare_fits_data(np.array([1, 4_000_000_000], dtype=np.uint32), XISFSampleFormat.UINT32)
    assert bitpix == -32 and big[1] == pytest.approx(4e9, rel=1e-6)

    wide, bitpix = prepare_fits_data(np.array([2**40], dtype=np.uint64), "UInt64")
    assert bitpix == -64 and wide[0] == float(2**40)

    magnitude, bitpix = prepare_fits_data(np.array([3 + 4j], dtype=np.complex64), "Complex32")
    assert bitpix == -32 and magnitude[0] == pytest.approx(5.0)


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_validate_data_integrity():
    """LIB-010: integrity checks accept a normal frame and reject empty, wrongly sized or non-array data."""
    good = np.arange(12, dtype=np.uint16).reshape(3, 4)
    assert validate_data_integrity(good, 12, "UInt16")
    assert not validate_data_integrity(good, 13)
    assert not validate_data_integrity(np.array([], dtype=np.uint16))
    assert not validate_data_integrity([1, 2, 3])
    assert validate_data_integrity(np.zeros((2, 2), dtype=np.uint16))          # all zeros: warned about, still usable


# ---------------------------------------------------------------------------
# Reading and converting files
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xisf_header_cards_and_image_info(tmp_path, frame):
    """LIB-010: FITS keywords, geometry and provenance come through from the XISF header, with typed values."""
    path = build_xisf(
        tmp_path / "m42.xisf", frame,
        keywords={"OBJECT": "M42", "EXPTIME": "120.5", "GAIN": "100", "FILTER": "'Ha'", "ROWORDER": "true"},
        extra_xml='<Metadata><CreationTime>2026-01-02T03:04:05Z</CreationTime></Metadata><Software name="PixInsight" version="1.9"/>',
    )
    converter = XISFConverter(path)
    cards = converter.get_header_cards()

    assert (cards["OBJECT"], cards["EXPTIME"], cards["GAIN"], cards["FILTER"], cards["ROWORDER"]) == ("M42", 120.5, 100, "Ha", True)
    assert (cards["SIMPLE"], cards["BITPIX"], cards["NAXIS"], cards["NAXIS1"], cards["NAXIS2"]) == (True, 16, 2, 6, 4)
    assert cards["XISFFILE"] == "m42.xisf" and cards["ORIGIN"] == "XISF to FITS Converter"
    assert cards["DATE"] == "2026-01-02T03:04:05Z" and cards["SOFTWARE"] == "PixInsight 1.9"
    assert cards["COMMENT_OBJECT"] == "object note"

    info = converter.get_image_info()
    assert info["geometry"]["width"] == 6 and info["geometry"]["height"] == 4
    assert info["geometry"]["sample_format"] == "UInt16" and info["location_method"] == "attachment"
    assert info["data_loaded"] is False                      # pixels are read lazily, at conversion
    assert converter.get_header_cards() is not converter.get_header_cards()   # callers get a copy


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xisf_standard_metadata_properties_are_read(tmp_path, frame):
    """LIB-010: the creation time and creator application PixInsight writes as standard ``XISF:`` properties become DATE and SOFTWARE."""
    path = build_xisf(
        tmp_path / "pi.xisf", frame,
        extra_xml='<Metadata><Property id="XISF:CreationTime" type="TimePoint" value="2026-03-04T05:06:07Z"/>'
                  '<Property id="XISF:CreatorApplication" type="String">PixInsight 1.8.9</Property></Metadata>',
    )
    cards = XISFConverter(path).get_header_cards()
    assert cards["DATE"] == "2026-03-04T05:06:07Z" and cards["SOFTWARE"] == "PixInsight 1.8.9"


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("codec", ["", "zlib", "zlib+sh", "gzip"])
def test_tc_lib_010_xisf_converts_to_fits_for_every_codec(tmp_path, frame, codec):
    """LIB-010: raw, zlib, byte-shuffled zlib and gzip pixel data all convert to a FITS file with identical pixels."""
    path = build_xisf(tmp_path / "frame.xisf", frame, codec=codec, keywords={"OBJECT": "M31"})
    out = XISFConverter(path).convert_to_fits()

    assert out == str(tmp_path / "frame.fits")
    with fits.open(out) as hdul:
        assert np.array_equal(hdul[0].data, frame)
        assert hdul[0].header["OBJECT"] == "M31"
        assert hdul[0].header["XISFCMPR"] == codec.split(":")[0]


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xisf_float_pixels_and_explicit_output_path(tmp_path):
    """LIB-010: 32-bit float data converts losslessly to a FITS file at the requested path."""
    pixels = np.linspace(0.0, 1.0, 12, dtype=np.float32).reshape(3, 4)
    path = build_xisf(tmp_path / "f.xisf", pixels, sample_format="Float32")
    target = tmp_path / "elsewhere" / "out.fits"
    target.parent.mkdir()

    assert XISFConverter(path).convert_to_fits(str(target)) == str(target)
    with fits.open(target) as hdul:
        assert hdul[0].header["BITPIX"] == -32
        assert np.allclose(hdul[0].data, pixels)


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xisf_multichannel_image_keeps_plane_order(tmp_path):
    """LIB-010: a 3-channel XISF becomes a (channels, height, width) FITS cube with each plane in place."""
    cube = np.stack([np.full((4, 5), value, dtype=np.uint16) for value in (10, 20, 30)])
    path = build_xisf(tmp_path / "rgb.xisf", cube, geometry="5:4:3", image_attrs=' colorSpace="RGB"')
    converter = XISFConverter(path)

    assert converter.get_header_cards()["NAXIS"] == 3 and converter.get_header_cards()["XISFCLRS"] == "RGB"
    with fits.open(converter.convert_to_fits()) as hdul:
        assert hdul[0].data.shape == (3, 4, 5)
        assert [int(plane[0, 0]) for plane in hdul[0].data] == [10, 20, 30]


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xisf_header_without_a_namespace_is_accepted(tmp_path, frame):
    """LIB-010: a header whose elements carry no XISF namespace is still read (some writers omit it)."""
    path = build_xisf(tmp_path / "plain.xisf", frame, namespaced=False, keywords={"OBJECT": "NGC7000"})
    assert XISFConverter(path).get_header_cards()["OBJECT"] == "NGC7000"


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xisf_data_following_the_header_without_an_attachment(tmp_path, frame):
    """LIB-010: with no ``attachment`` location the pixel data is taken from straight after the XML header."""
    path = build_xisf(tmp_path / "inline.xisf", frame, location="inline")
    with fits.open(XISFConverter(path).convert_to_fits()) as hdul:
        assert np.array_equal(hdul[0].data, frame)


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xisf_unshuffle_restores_byte_planes():
    """LIB-010: byte-unshuffling inverts the shuffle PixInsight applies before compressing."""
    values = np.array([0x0102, 0x0304, 0x0506], dtype="<u2")
    shuffled = np.frombuffer(values.tobytes(), dtype=np.uint8).reshape(-1, 2).T.copy().tobytes()
    converter = XISFConverter.__new__(XISFConverter)

    assert converter._unshuffle_bytes(shuffled, 2) == values.tobytes()
    assert converter._unshuffle_bytes(b"abc", 1) == b"abc"            # single-byte samples need nothing
    assert converter._unshuffle_bytes(b"abcde", 2) == b"abcde"        # a ragged length is left alone, not mangled


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_corrupt_compressed_data_does_not_pass_for_pixels(tmp_path, frame):
    """LIB-010: a zlib attachment that will not decompress yields an error, not garbage pixels."""
    path = build_xisf(tmp_path / "bad.xisf", frame, codec="zlib", payload=b"this is not zlib data at all, sorry")
    with pytest.raises(ValueError, match="Insufficient data|Error reading image data"):
        XISFConverter(path).convert_to_fits()


# ---------------------------------------------------------------------------
# Refusing files that are not valid XISF
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_missing_file_and_wrong_signature(tmp_path):
    """LIB-010: a missing file and a file that is not XISF at all are refused with clear errors."""
    with pytest.raises(FileNotFoundError):
        XISFConverter(str(tmp_path / "nope.xisf"))

    fake = tmp_path / "fake.xisf"
    fake.write_bytes(b"NOTXISF!" + b"\x00" * 64)
    with pytest.raises(ValueError, match="Invalid XISF signature"):
        XISFConverter(str(fake))


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("kwargs,message", [
    ({"geometry": "0:4"}, "Invalid image dimensions"),
    ({"geometry": "6"}, "Invalid geometry"),
    ({"sample_format": "Float16"}, "Unsupported sample format"),
    ({"location": "attachment:0:0"}, "Invalid attachment location"),
])
def test_tc_lib_010_malformed_image_element_is_rejected(tmp_path, frame, kwargs, message):
    """LIB-010: zero-sized or malformed geometry, an unsupported sample format and a bad attachment location are all refused."""
    path = build_xisf(tmp_path / "bad.xisf", frame, **kwargs)
    with pytest.raises(ValueError, match=message):
        XISFConverter(path)


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_header_without_an_image_is_rejected(tmp_path):
    """LIB-010: an XISF whose header holds no Image element is refused."""
    xml = f'<?xml version="1.0"?><xisf version="1.0" xmlns="{_NS}"><Metadata/></xisf>'.encode()
    path = tmp_path / "empty.xisf"
    path.write_bytes(b"XISF0100" + struct.pack("<I", len(xml)) + struct.pack("<I", 0) + xml)
    with pytest.raises(ValueError, match="No Image element"):
        XISFConverter(str(path))


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_truncated_pixel_data_is_rejected(tmp_path, frame):
    """LIB-010: pixel data shorter than the geometry says is an error rather than a short or padded image."""
    path = build_xisf(tmp_path / "short.xisf", frame, payload=frame.tobytes()[:10])
    with pytest.raises(ValueError, match="Insufficient data"):
        XISFConverter(path).convert_to_fits()


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_xml_that_is_not_well_formed_is_rejected(tmp_path):
    """LIB-010: a header that is not well-formed XML is refused with a clear error."""
    xml = b"<xisf><Image geometry='4:4'"
    path = tmp_path / "broken.xisf"
    path.write_bytes(b"XISF0100" + struct.pack("<I", len(xml)) + struct.pack("<I", 0) + xml)
    with pytest.raises(ValueError, match="Invalid XML"):
        XISFConverter(str(path))


# ---------------------------------------------------------------------------
# The Library's ingest handler
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_library_ingest_converts_xisf_through_the_format_processor(tmp_path, frame):
    """LIB-010: the Library's format processor picks the XISF handler for a .xisf file and returns a FITS file with the same pixels."""
    from galileo.library.core.file_formats import FileFormatProcessor

    path = build_xisf(tmp_path / "import_me.xisf", frame, keywords={"OBJECT": "M42"})
    processor = FileFormatProcessor()
    assert processor.can_process(path)

    converted = processor.process_file(path)
    assert str(converted).endswith(".fits")
    with fits.open(converted) as hdul:
        assert np.array_equal(hdul[0].data, frame)
        assert hdul[0].header["OBJECT"] == "M42"


@pytest.mark.requirement("TC-LIB-010")
@pytest.mark.priority("MVP")
def test_tc_lib_010_library_ingest_reports_a_corrupt_xisf_as_a_processing_error(tmp_path):
    """LIB-010: an unreadable XISF surfaces as the Library's FileProcessingError, not a bare converter exception."""
    from galileo.library.core.file_formats import FileFormatProcessor
    from galileo.library.exceptions import FileProcessingError

    bad = tmp_path / "corrupt.xisf"
    bad.write_bytes(b"XISF0100" + b"\x00" * 8)
    with pytest.raises(FileProcessingError):
        FileFormatProcessor().process_file(str(bad))
