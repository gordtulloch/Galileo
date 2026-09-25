"""
FITS File Compression Module

This module provides lossless compression for FITS images.
FITS tile-compressed files are written in-place (filename unchanged) when
`replace_original=True` (the default for auto-import). The resulting FITS file
stores the image using the FITS tile compression convention (GZIP_2, with
quantization disabled so floating-point images are preserved bit for bit).

The compression system supports:
- Lossless FITS tile compression (GZIP_2) and external gzip/lzma/bzip2 streams
- Transparent reading of tile-compressed files (astropy does this itself)
- Configuration-driven compression behavior
- Integration with file registration and download processes

Safety rule: the original file is never touched until the compressed copy has
been written **and verified** against it. A failed compression leaves the
original exactly as it was and cleans up its temporary file.

Configuration:
Set 'compress_fits=true' in library.ini (Options > Library) to enable automatic compression
for new files during download and repository loading.
"""

from __future__ import annotations

import bz2
import gzip
import hashlib
import logging
import lzma
import os
import shutil
import threading
from collections import Counter
from collections.abc import Callable
from typing import Any

import numpy as np
from astropy.io import fits

from galileo.library.config import load_config as load_library_config

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024 * 1024
_FITS_EXTENSIONS = ('.fits', '.fit', '.fts')
_EXTERNAL_EXTENSIONS = ('.gz', '.xz', '.bz2', '.fz')
_STREAM_OPENERS: dict[str, Callable[..., Any]] = {'gzip': gzip.open, 'lzma': lzma.open, 'bzip2': bz2.open}
# The project convention for FITS tile compression; every ``fits_*`` setting maps to it.
_TILE_COMPRESSION = 'GZIP_2'

_STRUCTURAL_KEYWORDS = {'SIMPLE', 'BITPIX', 'NAXIS', 'EXTEND', 'PCOUNT', 'GCOUNT', 'CHECKSUM', 'DATASUM'}
# Keywords a CompImageHDU (a BINTABLE extension) must not inherit from the source image header.
_PRIMARY_SKIP = _STRUCTURAL_KEYWORDS | {f'NAXIS{i}' for i in range(1, 10)}
_COMP_SKIP = _STRUCTURAL_KEYWORDS | {
    'BSCALE', 'BZERO', 'XTENSION', 'TFIELDS', 'ZIMAGE', 'ZCMPTYPE', 'ZBITPIX', 'ZNAXIS',
} | {
    f'{prefix}{i}'
    for i in range(1, 100)
    for prefix in ('NAXIS', 'ZNAXIS', 'TTYPE', 'TFORM', 'TUNIT', 'TDIM')
}


def _compression_ratio(original_size: int, compressed_size: int) -> float:
    """Percentage reduction; 0 for an empty original rather than a ZeroDivisionError."""
    return (1 - compressed_size / original_size) * 100 if original_size else 0.0


def _remove_quietly(path: str) -> None:
    """Delete a temporary file, logging (not raising) if the OS refuses."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Could not remove temporary file %s: %s", path, exc)


def _has_comp_image(path: str) -> bool:
    """True if the FITS file at *path* holds a tile-compressed image HDU."""
    try:
        with fits.open(path) as hdul:
            return any(isinstance(hdu, fits.CompImageHDU) for hdu in hdul)
    except Exception:  # an unreadable file is simply "not compressed"
        logger.debug("Could not inspect %s for tile compression", path, exc_info=True)
        return False


def _is_readable_fits(path: str) -> bool:
    try:
        with fits.open(path, mode='readonly'):
            return True
    except Exception:
        return False


def _find_image_hdu_index(hdul: fits.HDUList) -> int | None:
    """Index of the first uncompressed image HDU that holds data (tables and CompImageHDUs don't count)."""
    for idx, hdu in enumerate(hdul):
        if isinstance(hdu, fits.CompImageHDU) or not isinstance(hdu, (fits.PrimaryHDU, fits.ImageHDU)):
            continue
        try:
            if hdu.data is not None:
                return idx
        except Exception:  # an HDU whose data can't be read is not a candidate
            logger.debug("HDU %d has unreadable data", idx, exc_info=True)
    return None


def _copy_header_cards(dst: fits.Header, src: fits.Header, skip: set[str]) -> list[str]:
    """Copy every non-structural card from *src* to *dst*; return the keywords that could not be copied."""
    failed: list[str] = []
    for card in src.cards:
        key = card.keyword
        if not key or key in skip:
            continue
        try:
            if key == 'COMMENT':
                dst.add_comment(card.value)
            elif key == 'HISTORY':
                dst.add_history(card.value)
            else:
                dst[key] = (card.value, card.comment)
        except Exception:
            failed.append(key)
    return failed


def _tile_compress_hdu(src_hdu: fits.PrimaryHDU | fits.ImageHDU) -> fits.CompImageHDU:
    """Build a tile-compressed copy of an image HDU, keeping its non-structural header cards."""
    # quantize_level=0 disables quantization: astropy's default (16) makes floating-point
    # images lossy, which would silently corrupt the photometry.
    compressed_hdu = fits.CompImageHDU(
        data=src_hdu.data, compression_type=_TILE_COMPRESSION, quantize_level=0,
    )
    failed = _copy_header_cards(compressed_hdu.header, src_hdu.header, _COMP_SKIP)
    if failed:
        raise ValueError(f"header cards could not be copied to the compressed HDU: {sorted(set(failed))}")

    # Preserve EXTNAME when present
    if 'EXTNAME' in src_hdu.header and 'EXTNAME' not in compressed_hdu.header:
        compressed_hdu.header['EXTNAME'] = src_hdu.header['EXTNAME']

    # Older astropy exposes the raw table header, already holding the tile-compression (Z*)
    # keywords, and needs them to match the original image. Newer astropy derives them itself
    # and would write our copies as stray reserved keywords (a VerifyWarning on every read).
    if 'ZCMPTYPE' in compressed_hdu.header:
        naxis = int(src_hdu.header.get('NAXIS', src_hdu.data.ndim))
        compressed_hdu.header['ZIMAGE'] = (True, 'Tile-compressed image')
        compressed_hdu.header['ZCMPTYPE'] = (_TILE_COMPRESSION, 'Compression algorithm')
        compressed_hdu.header['ZNAXIS'] = (naxis, 'Number of uncompressed axes')
        compressed_hdu.header['ZBITPIX'] = (int(src_hdu.header.get('BITPIX', -32)), 'Uncompressed data type')
        for axis in range(1, naxis + 1):
            n_key = f'NAXIS{axis}'
            length = int(src_hdu.header[n_key]) if n_key in src_hdu.header else int(src_hdu.data.shape[-axis])
            compressed_hdu.header[f'ZNAXIS{axis}'] = (length, f'Axis {axis} length (uncompressed)')
    return compressed_hdu


def _rebuild_with_compressed_image(hdul: fits.HDUList, target_idx: int) -> list[fits.hdu.base._BaseHDU]:
    """The HDU list for the compressed file: *hdul* with its image at *target_idx* tile-compressed.

    Raises if any extension or header card can't be carried over — a compressed copy that
    silently lacks part of the original must never replace it.
    """
    if target_idx == 0:
        # The image is in the PrimaryHDU; rewrite as an empty PrimaryHDU with the global
        # metadata followed by a CompImageHDU holding the image.
        primary = fits.PrimaryHDU()
        failed = _copy_header_cards(primary.header, hdul[0].header, _PRIMARY_SKIP)
        if failed:
            raise ValueError(f"header cards could not be copied to the primary HDU: {sorted(set(failed))}")
        return [primary, _tile_compress_hdu(hdul[0]), *(ext.copy() for ext in hdul[1:])]

    return [
        _tile_compress_hdu(hdu) if idx == target_idx else hdu.copy()
        for idx, hdu in enumerate(hdul)
    ]


def _data_hdus(hdul: fits.HDUList) -> list[fits.hdu.base._BaseHDU]:
    return [hdu for hdu in hdul if hdu.data is not None]


def _data_equal(a: np.ndarray, b: np.ndarray) -> bool:
    """Exact equality (NaN == NaN); handles table (record) arrays column by column."""
    if a.shape != b.shape:
        return False
    names = a.dtype.names
    if names or b.dtype.names:
        if names is None or names != b.dtype.names:
            return False
        return all(_data_equal(np.asarray(a[name]), np.asarray(b[name])) for name in names)
    both_float = a.dtype.kind in 'fc' and b.dtype.kind in 'fc'
    return bool(np.array_equal(a, b, equal_nan=both_float))


def _commentary_counts(hdul: fits.HDUList) -> Counter:
    return Counter(
        card.keyword for hdu in hdul for card in hdu.header.cards if card.keyword in ('COMMENT', 'HISTORY')
    )


class FitsCompressor:
    """
    Handles FITS file compression and decompression using lossless algorithms.
    """

    def __init__(self, config_path: str | None = None):
        """
        Initialize the FITS compressor.

        Args:
            config_path: Path to configuration file
        """
        self.config = load_library_config(config_path)

        # Get compression settings
        self.compression_enabled = self.config.getboolean('DEFAULT', 'compress_fits', fallback=False)
        self.compression_algorithm = self.config.get('DEFAULT', 'compression_algorithm', fallback='gzip')
        self.compression_level = self.config.getint('DEFAULT', 'compression_level', fallback=6)
        self.verify_compression = self.config.getboolean('DEFAULT', 'verify_compression', fallback=True)

        # Algorithm-specific settings. Every ``fits_*`` entry produces GZIP_2 tile compression
        # (the project convention, and the only one offered in Options > Library).
        self.algorithms: dict[str, dict[str, Any]] = {
            'gzip': {'extension': '.gz', 'module': gzip, 'levels': (1, 9)},
            'lzma': {'extension': '.xz', 'module': lzma, 'levels': (0, 9)},
            'bzip2': {'extension': '.bz2', 'module': bz2, 'levels': (1, 9)},
            'fits_rice': {'extension': '.fits', 'module': None, 'levels': (1, 9)},
            'fits_gzip1': {'extension': '.fits', 'module': None, 'levels': (1, 9)},
            'fits_gzip2': {'extension': '.fits', 'module': None, 'levels': (1, 9)},
            'auto': {'extension': '.fits', 'module': None, 'levels': (1, 9)},
        }

        logger.info("FITS compression initialized: enabled=%s, algorithm=%s, level=%s",
                    self.compression_enabled, self.compression_algorithm, self.compression_level)

    def get_algorithm_info(self, algorithm: str | None = None):
        """Get information about compression algorithm."""
        algo = algorithm or self.compression_algorithm
        return self.algorithms.get(algo, self.algorithms['gzip'])

    def is_compressed(self, file_path: str) -> bool:
        """
        Check if a file is already compressed (external or internal FITS compression).

        Args:
            file_path: Path to the file to check

        Returns:
            True if file appears to be compressed, False otherwise
        """
        lower = file_path.lower()
        # - .gz/.xz/.bz2 are external stream compression
        # - .fz is the conventional suffix for FITS tile-compression outputs (fpack)
        if lower.endswith(_EXTERNAL_EXTENSIONS):
            return True

        # A plain .fits name may still hold tile-compressed data (we compress in place)
        return lower.endswith(_FITS_EXTENSIONS) and _has_comp_image(file_path)

    def is_fits_file(self, file_path: str) -> bool:
        """
        Check if a file is a FITS file (compressed or uncompressed).

        Args:
            file_path: Path to the file to check

        Returns:
            True if file is a FITS file, False otherwise
        """
        lower = file_path.lower()
        if lower.endswith(_FITS_EXTENSIONS):
            return True

        # Externally compressed FITS files: the name without the compression suffix is FITS
        return any(
            lower.endswith(ext) and lower[:-len(ext)].endswith(_FITS_EXTENSIONS)
            for ext in _EXTERNAL_EXTENSIONS
        )

    def get_compressed_path(self, original_path: str, algorithm: str | None = None) -> str:
        """
        Get the compressed version path for an original file.

        Args:
            original_path: Path to the original file
            algorithm: Compression algorithm to use

        Returns:
            Path where the compressed file should be stored
        """
        algo_info = self.get_algorithm_info(algorithm)
        return f"{original_path}{algo_info['extension']}"

    def get_uncompressed_path(self, compressed_path: str) -> str:
        """
        Get the original file path from a compressed file path.

        Args:
            compressed_path: Path to the compressed file

        Returns:
            Path to the original uncompressed file
        """
        lower = compressed_path.lower()
        for ext in _EXTERNAL_EXTENSIONS:
            if lower.endswith(ext):
                return compressed_path[:-len(ext)]
        return compressed_path

    def calculate_file_hash(self, file_path: str) -> str:
        """
        Calculate SHA-256 hash of a file for verification.

        Args:
            file_path: Path to the file

        Returns:
            Hexadecimal hash string
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def compress_fits_file(self, input_path: str, replace_original: bool = True,
                           algorithm: str | None = None) -> str | None:
        """
        Compress a FITS file using lossless compression.

        Args:
            input_path: Path to the input FITS file
            replace_original: If True, replace the original file with compressed version
            algorithm: Compression algorithm ('gzip', 'lzma', 'bzip2', 'auto')

        Returns:
            Path to the compressed file if successful, None if failed
        """
        try:
            if not os.path.exists(input_path):
                logger.error("Input file does not exist: %s", input_path)
                return None

            if self.is_compressed(input_path):
                logger.debug("File already compressed: %s", input_path)
                return input_path

            # Verify it's a valid FITS file before compressing
            if not _is_readable_fits(input_path):
                logger.error("Invalid FITS file, cannot compress: %s", input_path)
                return None

            selected_algorithm = algorithm or self.compression_algorithm

            # For auto-import, "auto" means FITS tile compression (GZIP_2).
            if selected_algorithm == 'auto':
                selected_algorithm = 'fits_gzip2'

            if selected_algorithm not in self.algorithms:
                logger.error("Unsupported compression algorithm: %s", selected_algorithm)
                return None

            return self._compress_with_algorithm(input_path, replace_original, selected_algorithm)

        except Exception:  # never let compression break the import that called it
            logger.exception("Error compressing FITS file %s", input_path)
            return None

    def _compress_stream(self, input_path: str, output_path: str, algorithm: str) -> None:
        """Write a gzip/lzma/bzip2 copy of *input_path* to *output_path*."""
        low, high = self.algorithms[algorithm]['levels']
        level = min(max(self.compression_level, low), high)
        level_kwarg = 'preset' if algorithm == 'lzma' else 'compresslevel'
        with open(input_path, 'rb') as f_in, \
                _STREAM_OPENERS[algorithm](output_path, 'wb', **{level_kwarg: level}) as f_out:
            shutil.copyfileobj(f_in, f_out, _CHUNK_SIZE)

    def _compress_with_algorithm(self, input_path: str, replace_original: bool,
                                 algorithm: str) -> str | None:
        """
        Compress with a specific algorithm.

        Args:
            input_path: Path to input file
            replace_original: Whether to replace original
            algorithm: Specific algorithm to use

        Returns:
            Path to compressed file
        """
        if algorithm.startswith('fits_'):
            return self._compress_fits_internal(input_path, replace_original, algorithm)
        if algorithm not in _STREAM_OPENERS:
            logger.error("Unsupported compression algorithm: %s", algorithm)
            return None

        output_path = self.get_compressed_path(input_path, algorithm)
        part_path = f"{output_path}.part"
        try:
            original_size = os.path.getsize(input_path)
            logger.info("Compressing FITS file with %s: %s", algorithm, input_path)
            self._compress_stream(input_path, part_path, algorithm)

            compressed_size = os.path.getsize(part_path)
            logger.info("%s compression complete: %s bytes -> %s bytes (%.1f%% reduction)",
                        algorithm, f"{original_size:,}", f"{compressed_size:,}",
                        _compression_ratio(original_size, compressed_size))

            if self.verify_compression:
                if not self._verify_compression(part_path, input_path, algorithm):
                    logger.error("%s compression verification failed for %s", algorithm, input_path)
                    return None
                logger.debug("%s compression verification successful for %s", algorithm, input_path)

            os.replace(part_path, output_path)
        except Exception:  # reported and turned into a None result
            logger.exception("Error compressing with %s: %s", algorithm, input_path)
            return None
        finally:
            if os.path.exists(part_path):
                _remove_quietly(part_path)

        if replace_original:
            try:
                os.remove(input_path)
                logger.debug("Removed original file: %s", input_path)
            except OSError as exc:
                logger.warning("Could not remove original file %s: %s", input_path, exc)

        return output_path

    def decompress_fits_file(self, compressed_path: str, output_path: str | None = None,
                             replace_compressed: bool = False) -> str | None:
        """
        Decompress a compressed FITS file (gzip, lzma or bzip2 streams).

        Tile-compressed FITS (``.fz``, or a ``.fits`` compressed in place) is not handled here:
        astropy reads it transparently, so there is nothing to decompress.

        Args:
            compressed_path: Path to the compressed file
            output_path: Path for the decompressed file (auto-generated if None)
            replace_compressed: If True, remove the compressed file after decompression

        Returns:
            Path to the decompressed file if successful, None if failed
        """
        try:
            if not os.path.exists(compressed_path):
                logger.error("Compressed file does not exist: %s", compressed_path)
                return None

            if not self.is_compressed(compressed_path):
                logger.debug("File is not compressed: %s", compressed_path)
                return compressed_path

            if output_path is None:
                output_path = self.get_uncompressed_path(compressed_path)

            # Never write over the file we are reading from
            if os.path.abspath(output_path) == os.path.abspath(compressed_path):
                logger.error("Refusing to decompress %s onto itself", compressed_path)
                return None

            algorithm = self._detect_compression_algorithm(compressed_path)
            if algorithm == 'fits_internal':
                logger.error("Tile-compressed FITS is read directly by astropy and has no stream "
                             "decompression: %s", compressed_path)
                return None
            if algorithm is None:
                logger.error("Unsupported compression format: %s", compressed_path)
                return None

            logger.info("Decompressing FITS file with %s: %s", algorithm, compressed_path)
            compressed_size = os.path.getsize(compressed_path)

            # Decompress beside the target and only move it into place once it is valid FITS,
            # so a failure never leaves (or deletes) a half-written output.
            part_path = f"{output_path}.part"
            try:
                with _STREAM_OPENERS[algorithm](compressed_path, 'rb') as f_in, open(part_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out, _CHUNK_SIZE)

                if not _is_readable_fits(part_path):
                    logger.error("Decompressed file is not valid FITS: %s", compressed_path)
                    return None

                logger.info("%s decompression complete: %s bytes -> %s bytes", algorithm,
                            f"{compressed_size:,}", f"{os.path.getsize(part_path):,}")
                os.replace(part_path, output_path)
            finally:
                if os.path.exists(part_path):
                    _remove_quietly(part_path)

            if replace_compressed:
                try:
                    os.remove(compressed_path)
                    logger.debug("Removed compressed file: %s", compressed_path)
                except OSError as exc:
                    logger.warning("Could not remove compressed file %s: %s", compressed_path, exc)

            return output_path

        except Exception:  # reported and turned into a None result
            logger.exception("Error decompressing FITS file %s", compressed_path)
            return None

    def _detect_compression_algorithm(self, file_path: str) -> str | None:
        """
        Detect the compression format of a file.

        Args:
            file_path: Path to compressed file

        Returns:
            'gzip', 'lzma', 'bzip2', 'fits_internal' (tile-compressed FITS), or None if unrecognised
        """
        lower = file_path.lower()
        for extension, algorithm in (('.gz', 'gzip'), ('.xz', 'lzma'), ('.bz2', 'bzip2'), ('.fz', 'fits_internal')):
            if lower.endswith(extension):
                return algorithm

        # No telling extension: a FITS file compressed in place shows in its structure
        return 'fits_internal' if _has_comp_image(file_path) else None

    def _verify_compression(self, compressed_path: str, original_path: str, algorithm: str) -> bool:
        """
        Verify a stream-compressed file by decompressing it and comparing SHA-256 with the original.

        Args:
            compressed_path: Path to compressed file
            original_path: Path to original file
            algorithm: Compression algorithm used

        Returns:
            True if the decompressed bytes match the original exactly
        """
        opener = _STREAM_OPENERS.get(algorithm)
        if opener is None:
            return False
        try:
            digest = hashlib.sha256()
            with opener(compressed_path, 'rb') as stream:
                for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
                    digest.update(chunk)
            return digest.hexdigest() == self.calculate_file_hash(original_path)
        except (OSError, EOFError, lzma.LZMAError):
            logger.exception("Error verifying compressed file %s", compressed_path)
            return False

    def _compress_fits_internal(self, input_path: str, replace_original: bool, algorithm: str) -> str | None:
        """
        Compress FITS file using internal FITS compression (tile compression).

        The compressed copy is written to a temporary file, verified against the untouched
        original, and only then moved into place, so the original survives any failure.

        Args:
            input_path: Path to input FITS file
            replace_original: Whether to replace the original file (keeping its name)
            algorithm: The ``fits_*`` setting; all of them produce GZIP_2 (the project convention)

        Returns:
            Path to compressed FITS file
        """
        # When replacing the original (auto-import), keep the filename unchanged.
        output_path = input_path if replace_original else f"{input_path}.fz"
        temp_path = f"{output_path}.tmp"
        try:
            original_size = os.path.getsize(input_path)

            with fits.open(input_path, memmap=False) as hdul:
                target_idx = _find_image_hdu_index(hdul)
                if target_idx is None:
                    logger.debug("No image data found to compress: %s", input_path)
                    return input_path
                fits.HDUList(_rebuild_with_compressed_image(hdul, target_idx)).writeto(temp_path, overwrite=True)

            if self.verify_compression and not self._verify_fits_internal_compression(temp_path, input_path):
                logger.error("FITS %s compression verification failed for %s; original left untouched",
                             algorithm, input_path)
                return None

            os.replace(temp_path, output_path)

            compressed_size = os.path.getsize(output_path)
            logger.info("%s FITS compression complete: %s bytes -> %s bytes (%.1f%% reduction)",
                        algorithm, f"{original_size:,}", f"{compressed_size:,}",
                        _compression_ratio(original_size, compressed_size))
            return output_path

        except Exception:  # reported and turned into a None result; original is untouched
            logger.exception("Error in FITS internal compression %s: %s", algorithm, input_path)
            return None
        finally:
            if os.path.exists(temp_path):
                _remove_quietly(temp_path)

    def _verify_fits_internal_compression(self, compressed_path: str, original_path: str) -> bool:
        """
        Verify FITS internal compression: every data HDU must decompress to exactly the
        original values (NaN == NaN) and no HISTORY/COMMENT card may be lost.

        Args:
            compressed_path: Path to compressed FITS file
            original_path: Path to original FITS file

        Returns:
            True if verification successful
        """
        try:
            with fits.open(original_path, memmap=False) as orig_hdul, \
                    fits.open(compressed_path, memmap=False) as comp_hdul:
                orig_hdus = _data_hdus(orig_hdul)
                comp_hdus = _data_hdus(comp_hdul)
                if len(orig_hdus) != len(comp_hdus):
                    logger.error("HDU count mismatch: original has %d data HDUs, compressed has %d",
                                 len(orig_hdus), len(comp_hdus))
                    return False

                for number, (orig, comp) in enumerate(zip(orig_hdus, comp_hdus, strict=True)):
                    if not _data_equal(np.asarray(orig.data), np.asarray(comp.data)):
                        logger.error("Data mismatch in data HDU %d after compression", number)
                        return False

                lost = _commentary_counts(orig_hdul) - _commentary_counts(comp_hdul)
                if lost:
                    logger.error("Header cards lost in compression: %s", dict(lost))
                    return False
            return True

        except Exception:  # any failure to verify counts as "not verified"
            logger.exception("Error verifying FITS internal compression")
            return False

    def should_compress_file(self, file_path: str) -> bool:
        """
        Determine if a file should be compressed based on configuration and file properties.

        Args:
            file_path: Path to the file to check

        Returns:
            True if file should be compressed, False otherwise
        """
        if not self.compression_enabled:
            return False

        if self.is_compressed(file_path):
            return False

        # Only compress FITS files
        if not file_path.lower().endswith(_FITS_EXTENSIONS):
            return False

        # Check if file exists and is readable
        if not os.path.exists(file_path) or not os.access(file_path, os.R_OK):
            return False

        # Check minimum file size (don't compress very small files)
        min_size = self.config.getint('DEFAULT', 'min_compression_size', fallback=1024)  # 1KB default
        return os.path.getsize(file_path) >= min_size

    def process_file_for_compression(self, file_path: str) -> str | None:
        """
        Process a file for compression if appropriate.

        This is the main entry point for automatic compression during file processing.

        Args:
            file_path: Path to the file to process

        Returns:
            Path to the final file (compressed or original) if successful, None if failed
        """
        try:
            if not self.should_compress_file(file_path):
                logger.debug("Skipping compression for: %s", file_path)
                return file_path

            compressed_path = self.compress_fits_file(file_path, replace_original=True)

            if compressed_path:
                logger.info("Successfully compressed: %s -> %s", file_path, compressed_path)
                return compressed_path

            logger.warning("Compression failed for: %s", file_path)
            return file_path

        except Exception:  # the file is still usable uncompressed
            logger.exception("Error processing file for compression %s", file_path)
            return file_path


# One compressor per config path (None = the default library.ini). Settings are read when a
# compressor is created, so call reset_fits_compressor() after the configuration changes.
_compressors: dict[str | None, FitsCompressor] = {}
_compressors_lock = threading.Lock()


def get_fits_compressor(config_path: str | None = None) -> FitsCompressor:
    """
    Get the shared FitsCompressor for a configuration file.

    Args:
        config_path: Path to configuration file (None for the default library.ini)

    Returns:
        FitsCompressor instance
    """
    with _compressors_lock:
        compressor = _compressors.get(config_path)
        if compressor is None:
            compressor = _compressors[config_path] = FitsCompressor(config_path)
        return compressor


def reset_fits_compressor() -> None:
    """Drop the shared compressors so the next get_fits_compressor() re-reads the configuration."""
    with _compressors_lock:
        _compressors.clear()


def compress_fits_file(file_path: str) -> str | None:
    """
    Convenience function to compress a FITS file.

    Args:
        file_path: Path to the FITS file to compress

    Returns:
        Path to compressed file if successful, original path if compression not enabled/failed
    """
    compressor = get_fits_compressor()
    result = compressor.process_file_for_compression(file_path)
    return result or file_path


def is_compression_enabled() -> bool:
    """
    Check if FITS compression is enabled in configuration.

    Returns:
        True if compression is enabled, False otherwise
    """
    compressor = get_fits_compressor()
    return compressor.compression_enabled
