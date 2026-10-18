# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Stacks calibration/light frames into masters: sigma-clip and simple-average stacking, the photometric mean light stack, headers and thumbnails."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging
import os
import datetime
from collections.abc import Callable
from galileo.core.compute import imap_cpu
from ..models import fitsSession, fitsFile

logger = logging.getLogger(__name__)


def _extract_image_hdu(hdul):
    """Return ``(hdu, data)`` for the first HDU with 2-D image data, or ``(None, None)``."""
    import numpy as np
    for hdu in hdul:
        data = getattr(hdu, 'data', None)
        if data is None:
            continue
        arr = np.asarray(data)
        # Some writers store a single plane as (1, H, W)
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.ndim != 2:
            continue
        return hdu, arr
    return None, None


def _read_fits_image(file_path: str, primary_only: bool = False):
    """``(data, header)`` for a FITS image. By default the first HDU holding 2-D data is used (for
    data-in-extension files), with its header, or the primary header if it has none;
    ``primary_only`` reads the primary HDU and nothing else."""
    from astropy.io import fits
    with fits.open(file_path) as hdul:
        if primary_only:
            return hdul[0].data, hdul[0].header.copy()
        primary_header = hdul[0].header.copy()
        hdu, data = _extract_image_hdu(hdul)
        if data is None:
            raise ValueError("No 2D image data found in any HDU")
        header = getattr(hdu, 'header', None)
        return data, (header.copy() if header is not None else primary_header)


def _is_astroalign_maxiter_error(exc: Exception) -> bool:
    try:
        import astroalign as aa  # type: ignore
        max_iter_error = getattr(aa, 'MaxIterError', None)
        if max_iter_error is not None and isinstance(exc, max_iter_error):
            return True
    except Exception:
        logger.debug("isinstance check against astroalign.MaxIterError failed", exc_info=True)
    return exc.__class__.__name__ == 'MaxIterError'


def _wcs_reproject(data, src_header, ref_full, ref_header):
    """*data* reprojected onto the reference by the two frames' WCS (bilinear), with pixels
    outside its footprint set to NaN, or ``None`` if either frame lacks a celestial WCS or
    ``reproject`` isn't installed."""
    import numpy as np
    if ref_header is None or ref_full is None or data.ndim != 2 or ref_full.ndim != 2:
        return None
    try:
        import warnings
        from astropy.wcs import WCS, FITSFixedWarning
        from reproject import reproject_interp  # type: ignore
        warnings.filterwarnings('ignore', category=FITSFixedWarning)
    except Exception:
        return None
    try:
        src_wcs = WCS(src_header)
        dst_wcs = WCS(ref_header)
        if not (getattr(src_wcs, 'has_celestial', False) and getattr(dst_wcs, 'has_celestial', False)):
            return None
        reproj, footprint = reproject_interp(
            (data.astype(np.float32, copy=False), src_wcs), dst_wcs,
            shape_out=ref_full.shape, order='bilinear',
        )
        aligned = np.asarray(reproj, dtype=np.float32)
        if footprint is not None:
            aligned = aligned.copy()
            aligned[np.asarray(footprint) <= 0] = np.nan
        return aligned
    except Exception:
        return None


def register_light_frame(file_path: str, ref_path: str, primary_only: bool = False):
    """Read *file_path* and register it onto the frame at *ref_path* with astroalign, returning a
    float32 array with NaN where the frame doesn't cover the reference.

    The reference itself comes back unchanged. If astroalign can't find a match (``MaxIterError``),
    the frame is reprojected by WCS if both frames have one, or else returned unaligned, with a
    warning either way. Any other error is raised. Module-level so it can run in the CPU worker
    pool (``galileo.core.compute.imap_cpu``)."""
    import numpy as np
    import astroalign as aa  # type: ignore

    data, src_header = _read_fits_image(file_path, primary_only)
    data = np.asarray(data).astype(np.float32, copy=False)
    if os.path.abspath(file_path) == os.path.abspath(ref_path):
        return data
    ref_data, ref_header = _read_fits_image(ref_path, primary_only)
    ref_full = np.asarray(ref_data).astype(np.float32, copy=False)
    try:
        aligned, footprint = aa.register(data, ref_full, fill_value=np.nan)
    except Exception as e:
        if not _is_astroalign_maxiter_error(e):
            raise
        aligned_wcs = _wcs_reproject(data, src_header, ref_full, ref_header)
        if aligned_wcs is not None:
            logger.warning("Star registration failed for %s: %s. Used WCS reprojection fallback.",
                           os.path.basename(file_path), e)
            return aligned_wcs
        logger.warning("Star registration failed for %s: %s. Proceeding without alignment for this frame.",
                       os.path.basename(file_path), e)
        return data
    aligned = aligned.astype(np.float32, copy=False)
    if footprint is not None:
        aligned = aligned.copy()
        aligned[footprint] = np.nan
    return aligned


def _nanmedian_quiet(a, axis=None):
    """``np.nanmedian`` without the "All-NaN slice" warning: a pixel no frame covers is expected
    at a registered stack's edges, and simply comes back NaN."""
    import warnings
    import numpy as np
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(a, axis=axis)


def _register_or_error(file_path: str, ref_path: str, primary_only: bool = False):
    """``(registered, None)``, or ``(None, message)`` if :func:`register_light_frame` raised, so
    one bad frame in a batch run through :func:`imap_cpu` can be skipped without ending it. The
    error comes back as text because not every exception survives the trip out of a worker."""
    try:
        return register_light_frame(file_path, ref_path, primary_only), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


class MasterStackingMixin:
    """Stacks calibration/light frames into masters: sigma-clip and simple-average stacking, the photometric mean light stack, headers and thumbnails."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def _write_light_session_thumbnail(self, stacked_fits_path: str, session_id: str, width_px: int = 150) -> str | None:
        """Write a PNG thumbnail for a stacked FITS file into the repository Thumbnails folder.

        The thumbnail will be width_px wide and preserve aspect ratio. File is named "<session_id>.png".
        """
        try:
            if not stacked_fits_path or not os.path.exists(stacked_fits_path):
                return None
            if not session_id:
                return None

            from astropy.io import fits
            import numpy as np
            from PIL import Image

            with fits.open(stacked_fits_path) as hdul:
                data = hdul[0].data
            if data is None:
                return None

            arr = np.asarray(data)

            # Normalize to 2D grayscale for thumbnailing.
            if arr.ndim == 3:
                # Common FITS conventions are (C,H,W) or (H,W,C)
                if arr.shape[0] in (3, 4) and arr.shape[1] > 1 and arr.shape[2] > 1:
                    # (C,H,W) -> luminance-ish mean
                    arr2 = np.nanmean(arr[:3, :, :].astype(np.float32, copy=False), axis=0)
                elif arr.shape[-1] in (3, 4) and arr.shape[0] > 1 and arr.shape[1] > 1:
                    arr2 = np.nanmean(arr[..., :3].astype(np.float32, copy=False), axis=-1)
                else:
                    # Fallback: flatten extra dims
                    arr2 = np.nanmean(arr.astype(np.float32, copy=False), axis=0)
            elif arr.ndim == 2:
                arr2 = arr.astype(np.float32, copy=False)
            else:
                # Unsupported dimensionality for a quick preview
                return None

            finite = np.isfinite(arr2)
            if not np.any(finite):
                return None

            # Robust thumbnail stretch:
            # Some stacks can look fine in FITS viewers (auto-stretched) but produce
            # washed-out/white thumbnails if our normalization chooses a vmax that's
            # too low. Prefer a high-percentile interval (stable across devices),
            # then apply a mild gamma (>1) to keep the background from blowing out.
            try:
                from astropy.visualization import AsymmetricPercentileInterval

                interval = AsymmetricPercentileInterval(0.5, 99.9)
                lo, hi = interval.get_limits(arr2[finite])

                if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
                    raise RuntimeError("Invalid stretch limits")

                scaled = (arr2 - float(lo)) / float(hi - lo)
                scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0).astype(np.float32, copy=False)
                scaled = np.clip(scaled, 0.0, 1.0)

                # Gamma correction (display gamma convention):
                # use scaled^(1/gamma) so gamma > 1 brightens midtones (common expectation).
                gamma = 0.3
                if gamma > 0:
                    scaled = np.power(scaled, 1.0 / float(gamma), dtype=np.float32)
            except Exception:
                lo, hi = np.nanpercentile(arr2[finite], [1.0, 99.0])
                if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
                    lo = float(np.nanmin(arr2[finite]))
                    hi = float(np.nanmax(arr2[finite]))
                    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
                        return None

                scaled = (arr2 - lo) / (hi - lo)
                scaled = np.clip(scaled, 0.0, 1.0)
                scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0).astype(np.float32, copy=False)

            img8 = (scaled * 255.0).astype(np.uint8)

            im = Image.fromarray(img8, mode='L')
            w, h = im.size
            if w <= 0 or h <= 0:
                return None
            new_w = int(width_px)
            new_h = max(1, round((new_w * h) / float(w)))
            im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)

            thumbs_dir = self._get_thumbnails_directory()
            out_path = os.path.join(thumbs_dir, f"{session_id}.png")
            im.save(out_path, format='PNG')
            return out_path

        except Exception as e:
            logger.warning(f"Failed to write thumbnail for session {session_id}: {e}")
            return None

    def _create_master_sigma_clip(
        self,
        file_paths: list[str],
        output_path: str,
        cal_type: str,
        progress_callback: Callable | None = None,
        reference_path: str | None = None,
        thumbnail_session_id: str | None = None,
    ) -> bool:
        """
        Create master frame using sigma-clipped averaging (internal implementation).

        Args:
            file_paths: List of input FITS file paths
            output_path: Output path for master frame
            cal_type: Type of calibration
            progress_callback: Progress reporting function

        Returns:
            True if successful, False otherwise
        """
        try:
            from astropy.io import fits
            import numpy as np
            try:
                import astroalign as aa  # type: ignore
            except Exception:
                aa = None

            if not file_paths:
                logger.error("No input files provided")
                return False

            logger.info(f"Creating {cal_type} master from {len(file_paths)} files using sigma-clipped stacking")

            if progress_callback:
                progress_callback(25, 100, f"Loading {len(file_paths)} {cal_type} frames...")

            first = self._first_readable_frame(file_paths)
            if first is None:
                logger.error("No valid input frames contained 2D image data")
                return False
            header, data_shape, first_data_file = first

            is_light_stack = str(cal_type).lower() == 'light'

            # Prepare reference for star registration (light stacking only)
            ref_path = None
            if is_light_stack:
                if aa is None:
                    raise RuntimeError(
                        "Light-frame stacking requires astroalign for star registration. "
                        "Install it (pip install astroalign) and try again."
                    )

                # The worker pool reads the reference itself (register_light_frame).
                ref_path = reference_path if (reference_path and os.path.exists(reference_path)) else first_data_file

            if progress_callback:
                progress_callback(30, 100, "Computing statistics (pass 1/2)...")

            # First pass: validate files and compute frame medians for flats
            valid_files, frame_medians = self._validate_stack_frames(file_paths, data_shape, cal_type, progress_callback)
            if not valid_files:
                logger.error("No valid frames loaded")
                return False

            n_frames = len(valid_files)
            logger.info(f"Processing {n_frames} valid frames")

            if progress_callback:
                progress_callback(40, 100, "Computing sigma clipping bounds...")

            # Process frames in chunks small enough to fit in memory (up to 20 at a time)
            max_chunk_size = min(20, len(file_paths))
            median, std = self._chunked_median_and_std(valid_files, data_shape, is_light_stack, ref_path,
                                                       max_chunk_size, progress_callback)

            # Sigma clipping parameters
            sigma_low = 3.0
            sigma_high = 3.0
            lower_bound = median - sigma_low * std
            upper_bound = median + sigma_high * std

            logger.info("Sigma clipping bounds computed")

            if progress_callback:
                progress_callback(60, 100, f"Combining {n_frames} frames with sigma clipping (pass 2/2)...")

            # Pass 2 - Accumulate with sigma clipping
            logger.info("Pass 2: Combining frames with sigma clipping...")
            accumulator, count, rejected_pixels, total_pixels = self._accumulate_clipped(
                valid_files, data_shape, cal_type, is_light_stack, ref_path, frame_medians,
                lower_bound, upper_bound, progress_callback)

            rejection_rate = (rejected_pixels / total_pixels) * 100 if total_pixels > 0 else 0
            logger.info(f"Sigma clipping: {rejected_pixels}/{total_pixels} pixels rejected ({rejection_rate:.3f}%)")

            if progress_callback:
                progress_callback(80, 100, "Computing final master frame...")

            master_data, n_uncovered = self._finalize_master_data(accumulator, count, median)

            if cal_type == 'flat':
                logger.info("Applied multiplicative normalization for flat frames")
            else:
                logger.info("Applied additive combination for bias/dark frames")

            if progress_callback:
                progress_callback(80, 100, "Saving master frame...")

            # Update header with metadata
            header['HISTORY'] = f'Master {cal_type} created from {n_frames} files'
            header['NFILES'] = n_frames
            header['CREATOR'] = 'Galileo Internal Stacking'
            header['METHOD'] = f'Sigma-clipped mean (sigma_low={sigma_low}, sigma_high={sigma_high})'
            header['REJECTED'] = f'{rejection_rate:.3f}%'
            header['NODATA'] = (n_uncovered, 'Pixels with no data in any frame, written as 0')
            header['DATE'] = datetime.datetime.now(datetime.UTC).replace(tzinfo=None).isoformat()

            # Convert to appropriate dtype (preserve as uint16 for most cases, float32 for flats)
            if cal_type == 'flat':
                output_data = master_data.astype(np.float32)
            else:
                # Clip to uint16 range and convert
                output_data = np.clip(master_data, 0, 65535).astype(np.uint16)

            # Save master frame
            hdu = fits.PrimaryHDU(data=output_data, header=header)
            hdu.writeto(output_path, overwrite=True)

            # If this is a light stack, emit/update a session thumbnail.
            if is_light_stack and thumbnail_session_id:
                self._write_light_session_thumbnail(output_path, str(thumbnail_session_id), width_px=150)

            logger.info(f"Internal stacking: Master {cal_type} created successfully: {output_path}")
            logger.info(f"  Output shape: {output_data.shape}, dtype: {output_data.dtype}")
            logger.info(f"  Data range: [{np.min(output_data):.1f}, {np.max(output_data):.1f}]")
            logger.info(f"  Mean: {np.mean(output_data):.1f}, Median: {np.median(output_data):.1f}")

            if progress_callback:
                progress_callback(100, 100, "Master frame created successfully")

            return True

        except Exception:
            logger.exception("Error in sigma-clipped master creation")
            return False

    @staticmethod
    def _first_readable_frame(file_paths: list[str]):
        """``(header, shape, path)`` of the first readable frame (it sets the stack's dimensions), or ``None``."""
        for candidate_path in file_paths:
            try:
                data0, header0 = _read_fits_image(candidate_path)
            except Exception as e:
                logger.warning(f"Skipping unreadable FITS frame {candidate_path}: {e}")
                continue
            logger.info(f"Frame dimensions: {data0.shape}, dtype: {data0.dtype}")
            return header0, data0.shape, candidate_path
        return None

    @staticmethod
    def _validate_stack_frames(file_paths: list[str], data_shape, cal_type: str, progress_callback):
        """Pass 1: keep the readable frames of the right shape; for flats also record each frame's median."""
        import numpy as np

        valid_files: list[str] = []
        frame_medians: list[float] = []
        logger.info("Pass 1: Validating files and computing frame medians...")
        for i, file_path in enumerate(file_paths):
            try:
                try:
                    data, _hdr = _read_fits_image(file_path)
                except Exception as e:
                    logger.warning(f"Skipping corrupted/unreadable file {file_path}: {e}")
                    continue

                if data.shape != data_shape:
                    logger.warning(f"Skipping file with different dimensions: {file_path}")
                    continue

                valid_files.append(file_path)
                if cal_type == 'flat':
                    frame_medians.append(float(np.median(data)))

                if (i + 1) % 10 == 0 and progress_callback:
                    progress = 30 + int((i + 1) / len(file_paths) * 10)
                    progress_callback(progress, 100, f"Validating: {i+1}/{len(file_paths)} files...")
            except Exception as e:
                logger.warning(f"Skipping corrupted file {file_path}: {e}")
                continue
        return valid_files, frame_medians

    @staticmethod
    def _chunked_median_and_std(valid_files: list[str], data_shape, is_light_stack: bool, ref_path,
                                max_chunk_size: int, progress_callback):
        """Per-pixel median and standard deviation of the stack, computed a chunk of frames at a time."""
        import numpy as np

        n_frames = len(valid_files)
        logger.info(f"Computing statistics in chunks of {max_chunk_size} frames...")
        median = None
        M2 = None  # For Welford's online variance algorithm
        # Registered light frames are NaN wherever they don't cover the reference, so their
        # statistics must skip NaNs per pixel: a plain median/sum turns a pixel NaN if *any*
        # frame misses it, which gave NaN clip bounds there and rejected every frame — losing
        # a band as wide as the drift. Calibration frames have no NaNs and keep the plain
        # (faster, identical-result) functions.
        stat_median = _nanmedian_quiet if is_light_stack else np.median
        stat_sum = np.nansum if is_light_stack else np.sum
        samples = np.zeros(data_shape, dtype=np.uint32)   # frames contributing to M2, per pixel

        for chunk_start in range(0, n_frames, max_chunk_size):
            chunk_end = min(chunk_start + max_chunk_size, n_frames)
            chunk_files = valid_files[chunk_start:chunk_end]

            # Load chunk into memory; light frames are registered in parallel in the worker pool.
            if is_light_stack:
                chunk_data = list(imap_cpu(register_light_frame, [(fp, ref_path) for fp in chunk_files]))
            else:
                chunk_data = [_read_fits_image(fp)[0].astype(np.float32, copy=False) for fp in chunk_files]

            chunk_array = np.array(chunk_data)
            samples += np.isfinite(chunk_array).sum(axis=0, dtype=np.uint32)

            # Update running statistics
            if median is None:
                median = stat_median(chunk_array, axis=0)
                M2 = stat_sum((chunk_array - median[np.newaxis, ...]) ** 2, axis=0)
            else:
                # Combine statistics from chunks
                chunk_median = stat_median(chunk_array, axis=0)
                if is_light_stack:
                    # A pixel no frame of one chunk covered takes the other chunk's median.
                    median = np.where(np.isnan(median), chunk_median,
                                      np.where(np.isnan(chunk_median), median, (median + chunk_median) / 2))
                else:
                    median = (median + chunk_median) / 2  # Approximate for speed
                M2 += stat_sum((chunk_array - median[np.newaxis, ...]) ** 2, axis=0)

            del chunk_data, chunk_array

            if progress_callback:
                progress = 40 + int((chunk_end / n_frames) * 20)
                progress_callback(progress, 100, f"Statistics: {chunk_end}/{n_frames} frames...")

        # Per-pixel sample count: equal to n_frames for calibration frames (so unchanged there),
        # smaller near a light stack's edges where only some frames reach.
        std = np.sqrt(M2 / np.maximum(samples, 1))
        return median, std

    @staticmethod
    def _accumulate_clipped(valid_files: list[str], data_shape, cal_type: str, is_light_stack: bool, ref_path,
                            frame_medians: list[float], lower_bound, upper_bound, progress_callback):
        """Pass 2: sum the pixels inside the clip bounds. Returns ``(accumulator, count, rejected, total)``."""
        import numpy as np

        n_frames = len(valid_files)
        accumulator = np.zeros(data_shape, dtype=np.float32)
        count = np.zeros(data_shape, dtype=np.uint16)
        rejected_pixels = 0
        total_pixels = 0

        def _pass2_frames():
            """``(data, error)`` per valid file, in order; light frames registered in the pool."""
            if is_light_stack:
                yield from imap_cpu(_register_or_error, ((fp, ref_path) for fp in valid_files))
                return
            for fp in valid_files:
                try:
                    yield _read_fits_image(fp)[0].astype(np.float32, copy=False), None
                except Exception as e:
                    yield None, f"{type(e).__name__}: {e}"

        for i, (file_path, (data, error)) in enumerate(zip(valid_files, _pass2_frames(), strict=True)):
            if error is not None:
                logger.warning(f"Error processing {file_path}: {error}")
                continue
            try:
                # Apply flat normalization if needed
                if cal_type == 'flat':
                    data = data / frame_medians[i]

                # Apply sigma clipping mask
                mask = np.isfinite(data) & (data >= lower_bound) & (data <= upper_bound)

                # Accumulate valid pixels
                accumulator += np.where(mask, data, 0)
                count += mask.astype(np.uint16)

                rejected_pixels += np.sum(~mask)
                total_pixels += data.size

                if (i + 1) % 5 == 0 and progress_callback:
                    progress = 60 + int((i + 1) / n_frames * 20)
                    progress_callback(progress, 100, f"Pass 2: {i+1}/{n_frames} frames...")

            except Exception as e:
                logger.warning(f"Error processing {file_path}: {e}")
                continue
        return accumulator, count, rejected_pixels, total_pixels

    @staticmethod
    def _finalize_master_data(accumulator, count, median):
        """Mean of the accepted pixels, with gaps filled from the median. Returns ``(master_data, n_uncovered)``."""
        import numpy as np

        # Compute final master without triggering divide-by-zero warnings.
        # Note: np.where would still evaluate (accumulator / count) for all pixels.
        master_data = np.empty_like(accumulator, dtype=np.float32)
        np.divide(accumulator, count, out=master_data, where=(count > 0))
        if median is not None:
            master_data[count == 0] = median[count == 0] if hasattr(median, 'shape') else median

        # Replace any remaining NaN/Inf (e.g. from pathological inputs) with median.
        if median is not None:
            master_data = np.where(np.isfinite(master_data), master_data, median)

        # Pixels that are still not finite had no data in any frame (for a light stack: outside
        # every registered frame). Write them as 0 — the usual fill for a registered stack's
        # uncovered edges — rather than letting the integer cast below turn NaN into arbitrary
        # values.
        uncovered = ~np.isfinite(master_data)
        n_uncovered = int(np.count_nonzero(uncovered))
        if n_uncovered:
            master_data = np.where(uncovered, 0.0, master_data).astype(np.float32, copy=False)
            logger.info(f"{n_uncovered} pixel(s) had no data in any frame; written as 0")
        return master_data, n_uncovered

    def _create_light_stack_photometric_mean(
        self,
        file_paths: list[str],
        output_path: str,
        progress_callback: Callable | None = None,
        reference_path: str | None = None,
        thumbnail_session_id: str | None = None,
    ) -> bool:
        """Create a photometry-safe light stack.

        This uses star registration (astroalign) and a NaN-aware mean combine.
        It intentionally performs no sigma clipping / outlier rejection and
        writes float32 output to preserve linearity for photometry.
        """
        try:
            from astropy.io import fits
            import numpy as np

            try:
                import astroalign as aa  # type: ignore
            except Exception:
                aa = None

            if not file_paths:
                logger.error("No input files provided")
                return False

            if aa is None:
                raise RuntimeError(
                    "Photometric stacking requires astroalign for star registration. "
                    "Install it (pip install astroalign) and try again."
                )

            logger.info(
                "Creating photometric light stack from %d files using registered mean (no clipping)",
                len(file_paths),
            )

            if progress_callback:
                progress_callback(0, 100, f"Loading {len(file_paths)} light frames...")

            with fits.open(file_paths[0]) as hdul:
                header = hdul[0].header.copy()
                data_shape = hdul[0].data.shape

            # Prepare reference
            # The worker pool reads the reference itself (register_light_frame).
            ref_path = reference_path if (reference_path and os.path.exists(reference_path)) else file_paths[0]

            # Validate and stream accumulate
            valid_files: list[str] = []
            for i, file_path in enumerate(file_paths):
                try:
                    with fits.open(file_path) as hdul:
                        if hdul[0].data.shape != data_shape:
                            logger.warning("Skipping file with different dimensions: %s", file_path)
                            continue
                    valid_files.append(file_path)
                except Exception as e:
                    logger.warning("Skipping corrupted file %s: %s", file_path, e)

                if progress_callback and (i + 1) % 10 == 0:
                    progress_callback(5, 100, f"Validated {i+1}/{len(file_paths)} frames...")

            if len(valid_files) < 2:
                logger.error("Not enough valid frames to stack (%d)", len(valid_files))
                return False

            accumulator = np.zeros(data_shape, dtype=np.float64)
            count = np.zeros(data_shape, dtype=np.uint16)

            # Frames are registered in parallel in the CPU worker pool, and come back in order.
            registered = imap_cpu(register_light_frame, ((fp, ref_path, True) for fp in valid_files))
            for i, data in enumerate(registered):
                mask = np.isfinite(data)
                accumulator += np.where(mask, data, 0.0).astype(np.float64, copy=False)
                count += mask.astype(np.uint16)

                if progress_callback and (i + 1) % 2 == 0:
                    progress = 10 + int(((i + 1) / len(valid_files)) * 80)
                    progress_callback(progress, 100, f"Stacking {i+1}/{len(valid_files)} frames...")

            mean = np.full(data_shape, np.nan, dtype=np.float32)
            valid = count > 0
            mean[valid] = (accumulator[valid] / count[valid]).astype(np.float32)

            header['HISTORY'] = f'Photometric light stack created from {len(valid_files)} files'
            header['NFILES'] = len(valid_files)
            header['CREATOR'] = 'Galileo Photometric Stacking'
            header['METHOD'] = 'Registered mean (no clipping)'
            header['REFPATH'] = os.path.basename(ref_path)
            header['DATE'] = datetime.datetime.now(datetime.UTC).replace(tzinfo=None).isoformat()

            if progress_callback:
                progress_callback(95, 100, "Saving stack...")

            hdu = fits.PrimaryHDU(data=mean.astype(np.float32, copy=False), header=header)
            hdu.writeto(output_path, overwrite=True)

            if progress_callback:
                progress_callback(100, 100, "Stack created")

            logger.info("Photometric stack created successfully: %s", output_path)

            if thumbnail_session_id:
                self._write_light_session_thumbnail(output_path, str(thumbnail_session_id), width_px=150)
            return True

        except Exception:
            logger.exception("Error creating photometric light stack")
            return False

    def _create_master_simple_average(self, file_paths: list[str], output_path: str) -> bool:
        """
        Fallback method to create master frame using simple averaging.

        Args:
            file_paths: List of input FITS files
            output_path: Output path for master frame

        Returns:
            True if successful, False otherwise
        """
        try:
            from astropy.io import fits
            import numpy as np

            if not file_paths:
                return False

            # Read first file to get dimensions and header
            with fits.open(file_paths[0]) as hdul:
                header = hdul[0].header.copy()
                data_shape = hdul[0].data.shape
                data_stack = np.zeros((len(file_paths), *data_shape), dtype=np.float32)
                data_stack[0] = hdul[0].data.astype(np.float32)

            # Read remaining files
            for i, file_path in enumerate(file_paths[1:], 1):
                try:
                    with fits.open(file_path) as hdul:
                        data_stack[i] = hdul[0].data.astype(np.float32)
                except Exception as e:
                    logger.warning(f"Skipping corrupted file {file_path}: {e}")
                    continue

            # Calculate average
            master_data = np.mean(data_stack, axis=0)

            # Update header
            header['HISTORY'] = f'Created master frame from {len(file_paths)} files'
            header['NFILES'] = len(file_paths)
            header['CREATOR'] = 'Galileo Master Frame Manager'
            header['DATE'] = datetime.datetime.now(datetime.UTC).replace(tzinfo=None).isoformat()

            # Save master frame
            hdu = fits.PrimaryHDU(data=master_data.astype(np.uint16), header=header)
            hdu.writeto(output_path, overwrite=True)

            logger.info(f"Created simple average master frame: {output_path}")
            return True

        except Exception:
            logger.exception("Error in simple average master creation")
            return False

    def _update_master_header(self, master_path: str, session: fitsSession,
                            files: list[fitsFile], cal_type: str):
        """
        Update master frame FITS header with comprehensive metadata.

        Args:
            master_path: Path to master frame file
            session: Source session
            files: List of input files
            cal_type: Type of calibration
        """
        try:
            from astropy.io import fits

            with fits.open(master_path, mode='update') as hdul:
                header = hdul[0].header

                # Basic master frame info
                header['IMAGETYP'] = f'Master {cal_type.title()}'
                header['MSTTYPE'] = cal_type.upper()
                header['NFILES'] = len(files)
                header['CREATOR'] = 'Galileo Advanced Master Manager'
                header['VERSION'] = '2.0.0'
                header['DATE'] = datetime.datetime.now(datetime.UTC).replace(tzinfo=None).isoformat()

                # Session information
                header['TELESCOP'] = session.fitsSessionTelescope
                header['INSTRUME'] = session.fitsSessionImager
                header['SESSID'] = str(session.fitsSessionId)

                # Equipment settings
                if session.fitsSessionExposure:
                    header['EXPTIME'] = session.fitsSessionExposure
                if session.fitsSessionFilter:
                    header['FILTER'] = session.fitsSessionFilter
                if session.fitsSessionBinningX:
                    header['XBINNING'] = session.fitsSessionBinningX
                if session.fitsSessionBinningY:
                    header['YBINNING'] = session.fitsSessionBinningY
                if session.fitsSessionCCDTemp:
                    header['CCD-TEMP'] = session.fitsSessionCCDTemp
                if session.fitsSessionGain:
                    header['GAIN'] = session.fitsSessionGain
                if session.fitsSessionOffset:
                    header['OFFSET'] = session.fitsSessionOffset

                # File statistics
                total_size = sum(os.path.getsize(f.fitsFileName) for f in files
                                 if f.fitsFileName and os.path.exists(f.fitsFileName))
                header['TOTSIZE'] = total_size

                # Add history
                header['HISTORY'] = f'Master {cal_type} created from {len(files)} frames'
                header['HISTORY'] = f'Source session: {session.fitsSessionId}'
                header['HISTORY'] = f'Processing date: {datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")}'

                # Add comment
                header['COMMENT'] = 'Created by Galileo Master Frame Manager v2.0'

        except Exception:
            logger.exception("Error updating master frame header")
