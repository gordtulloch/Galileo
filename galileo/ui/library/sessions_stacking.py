# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Sessions screen's calibrate and stack actions (sample stack, photometric stack)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging
import os
from datetime import UTC, datetime as dt
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QProgressDialog, QApplication, QMessageBox
from galileo.library.models import fitsFile as FitsFileModel, fitsSession as FitsSessionModel
from galileo.library.core.utils import session_light_frames

logger = logging.getLogger(__name__)


def _extract_image_hdu(hdul):
    """Return ``(hdu, 2D array)`` for the first HDU with 2D image data, or ``(None, None)``."""
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


def _read_fits_image(file_path: str):
    """Read a FITS image, handling data-in-extension FITS files.

    Returns (data, header). Header is taken from the image HDU when
    available; falls back to primary header.
    """
    from astropy.io import fits

    with fits.open(file_path) as hdul:
        primary_header = hdul[0].header.copy()
        hdu, data = _extract_image_hdu(hdul)
        if data is None:
            raise ValueError("No 2D image data found in any HDU")
        header = getattr(hdu, 'header', None)
        return data, (header.copy() if header is not None else primary_header)


def _load_master_arrays(masters: dict, progress) -> dict:
    """Load the master frames as float32 arrays keyed like *masters*; the flat is normalised to a mean of 1.

    When the session has a ``FlatDark`` master it is subtracted from the flat first (it removes the
    flat's thermal signal and bias pedestal), and is kept in the result only for reference.
    A flat with a non-positive mean maps to ``None`` (flat correction is skipped).
    """
    import numpy as np

    arrays: dict = {}
    for label in ("Bias", "Dark", "FlatDark", "Flat"):
        master = masters.get(label)
        if master is None:
            continue
        progress.setLabelText(f"Loading {label.lower()} master...")
        QApplication.processEvents()
        data, _header = _read_fits_image(master.master_path)
        data = data.astype(np.float32, copy=False)
        if label == "Flat":
            flat_dark = arrays.get("FlatDark")
            if flat_dark is not None:
                if flat_dark.shape == data.shape:
                    data = data - flat_dark
                else:
                    logger.warning(
                        f"Flat-dark master shape {flat_dark.shape} does not match flat shape {data.shape}; "
                        "skipping flat-dark subtraction"
                    )
                    masters.pop("FlatDark", None)
            flat_mean = np.mean(data)
            if flat_mean > 0:
                data = data / flat_mean
                logger.info(f"Loaded and normalized flat master: {os.path.basename(master.master_path)}")
            else:
                logger.warning("Flat frame has zero mean, skipping flat correction")
                data = None
        else:
            logger.info(f"Loaded {label.lower()} master: {os.path.basename(master.master_path)}")
        arrays[label] = data
    return arrays


def _calibrate_light_file(light_file, masters: dict, master_data: dict) -> str:
    """Write ``cal_<name>`` next to *light_file*, catalog it and soft-delete the source. Returns the new path."""
    import hashlib
    import uuid

    import numpy as np
    from astropy.io import fits

    from galileo.library.core.utils import normalize_file_path

    # Load light frame
    light_data0, light_header = _read_fits_image(light_file.fitsFileName)
    light_data = light_data0.astype(np.float32, copy=False)

    # Apply calibration: (Light - Bias - Dark) / Flat
    calibrated_data = light_data.copy()

    for label in ("Bias", "Dark", "Flat"):
        master_array = master_data.get(label)
        if master_array is not None and master_array.shape != calibrated_data.shape:
            logger.warning(
                f"{label} master shape {master_array.shape} does not match light shape {calibrated_data.shape}; skipping {label.lower()}"
            )
            master_array = None
        if master_array is None:
            continue

        if label == "Flat":
            mask = master_array > 0
            calibrated_data[mask] /= master_array[mask]
        else:
            calibrated_data -= master_array
        note = f'{label} corrected using {os.path.basename(masters[label].master_path)}'
        if label == "Flat" and masters.get("FlatDark") is not None:
            note += f' with flat-dark {os.path.basename(masters["FlatDark"].master_path)}'
        light_header['HISTORY'] = note

    # Update header
    light_header['CALIBRAT'] = True
    # NOTE: this file imports `datetime` module at top-level; use `dt` alias for datetime.datetime
    light_header['CALDATE'] = dt.now(UTC).replace(tzinfo=None).isoformat()
    light_header['HISTORY'] = 'Calibrated by Galileo'

    # Save calibrated frame in same directory with cal_ prefix
    source_dir = os.path.dirname(light_file.fitsFileName)
    base_filename = os.path.basename(light_file.fitsFileName)
    calibrated_filename = f"cal_{base_filename}"
    calibrated_path = os.path.join(source_dir, calibrated_filename)

    # Clip and convert
    calibrated_data = np.clip(calibrated_data, 0, 65535).astype(np.uint16)

    hdu = fits.PrimaryHDU(data=calibrated_data, header=light_header)
    hdu.writeto(calibrated_path, overwrite=True)

    # Add calibrated file to DB so it shows up in the session
    calibrated_hash = None
    try:
        with open(calibrated_path, 'rb') as f:
            calibrated_hash = hashlib.md5(f.read(), usedforsecurity=False).hexdigest()
    except Exception as e:
        logger.warning(f"Failed to hash calibrated file {calibrated_path}: {e}")

    FitsFileModel.create(
        fitsFileId=str(uuid.uuid4()),
        fitsFileName=normalize_file_path(calibrated_path),
        fitsFileDate=light_file.fitsFileDate,
        fitsFileCalibrated=1,
        fitsFileType=light_file.fitsFileType,
        fitsFileStacked=light_file.fitsFileStacked,
        fitsFileObject=light_file.fitsFileObject,
        fitsFileExpTime=light_file.fitsFileExpTime,
        fitsFileXBinning=light_file.fitsFileXBinning,
        fitsFileYBinning=light_file.fitsFileYBinning,
        fitsFileCCDTemp=light_file.fitsFileCCDTemp,
        fitsFileTelescop=light_file.fitsFileTelescop,
        fitsFileInstrument=light_file.fitsFileInstrument,
        fitsFileGain=light_file.fitsFileGain,
        fitsFileOffset=light_file.fitsFileOffset,
        fitsFileFilter=light_file.fitsFileFilter,
        fitsFileHash=calibrated_hash,
        fitsFileSession=light_file.fitsFileSession,
        fitsFileCloudURL=None,
        fitsFileSoftDelete=False,
        fitsFileCalibrationDate=dt.now(UTC).replace(tzinfo=None),
        fitsFileOriginalFile=normalize_file_path(light_file.fitsFileName),
        fitsFileOriginalCloudURL=light_file.fitsFileCloudURL
    )

    # Soft-delete the source record so the session shows calibrated outputs
    light_file.fitsFileSoftDelete = True
    light_file.save()

    logger.info(f"Calibrated: {calibrated_filename}")
    return calibrated_path

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as _MixinBase  # type checkers see a widget (it is mixed into one)
else:
    _MixinBase = object




class SessionsStackingMixin(_MixinBase):
    """The Sessions screen's calibrate and stack actions (sample stack, photometric stack)."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def calibrate_session(self, item, *, confirm: bool = True, show_results: bool = True):
        """Calibrate light frames in a session using available master frames"""
        try:
            from galileo.library.core.master_manager import get_master_manager

            # Get session ID from tree item
            session_id = item.data(0, Qt.ItemDataRole.UserRole)
            if not session_id:
                if show_results:
                    QMessageBox.warning(self, "Error", "Session ID not found")
                return {"error": "Session ID not found"}

            # Get the session from database
            session = FitsSessionModel.get_by_id(session_id)
            if not session:
                if show_results:
                    QMessageBox.warning(self, "Error", "Session not found in database")
                return {"error": "Session not found in database"}

            parent_item = item.parent()
            object_name = parent_item.text(0) if parent_item else session.fitsSessionObjectName
            session_date = session.fitsSessionDate

            logger.info(f"Starting calibration for session: {object_name} on {session_date}")

            # Check if this is a calibration session
            if object_name in ['Bias', 'Dark', 'Flat', 'FlatDark']:
                if show_results:
                    QMessageBox.information(
                        self,
                        "Not Applicable",
                        "Calibration is only applicable to light frame sessions.",
                    )
                return {"error": "Calibration not applicable to calibration sessions"}

            # Find matching master frames
            masters = self._find_session_masters(get_master_manager(), session)
            available_masters = [f"{label}: {os.path.basename(m.master_path)}" for label, m in masters.items()]

            if not masters:
                details = (
                    f"No matching master frames found for this session.\n\n"
                    f"Telescope: {session.fitsSessionTelescope}\n"
                    f"Instrument: {session.fitsSessionImager}\n"
                    f"Filter: {session.fitsSessionFilter}\n"
                    f"Binning: {session.fitsSessionBinningX}x{session.fitsSessionBinningY}\n\n"
                    f"Please create master frames first using Auto-Calibration."
                )
                if show_results:
                    QMessageBox.warning(self, "No Master Frames", details)
                return {"error": "No matching master frames found", "details": details}

            if confirm:
                # Confirm calibration
                reply = QMessageBox.question(self, "Calibrate Session",
                    f"Calibrate light frames in session {object_name} ({session_date})?\n\n"
                    f"Available master frames:\n" + "\n".join(available_masters) + "\n\n"
                    "Calibrated frames will be saved with 'cal_' prefix.\n"
                    "Source uncalibrated frames will be soft-deleted.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)

                if reply != QMessageBox.StandardButton.Yes:
                    return {"cancelled": True}

            # Get light frames from session
            light_files = list(FitsFileModel.select().where(
                (FitsFileModel.fitsFileSession == session.fitsSessionId) &
                (FitsFileModel.fitsFileSoftDelete == False) &
                (FitsFileModel.fitsFileType.in_(['LIGHT', 'LIGHT FRAME']))
            ))

            if not light_files:
                if show_results:
                    QMessageBox.information(self, "No Files", "No light frames found in this session.")
                return {"total": 0, "calibrated": 0, "skipped": 0, "errors": 0}

            # Progress dialog
            progress = QProgressDialog("Calibrating light frames...", "Cancel", 0, len(light_files), self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setWindowTitle("Calibrating Session")
            progress.setMinimumDuration(0)
            progress.setValue(0)
            progress.show()
            QApplication.processEvents()

            try:
                master_data = _load_master_arrays(masters, progress)
            except Exception as e:
                progress.close()
                if show_results:
                    QMessageBox.critical(self, "Error", f"Failed to load master frames: {e!s}")
                logger.exception("Error loading master frames")
                return {"error": f"Failed to load master frames: {e!s}"}

            # Calibrate each light frame
            calibrated_count = 0
            skipped_count = 0
            error_count = 0

            for i, light_file in enumerate(light_files):
                if progress.wasCanceled():
                    break

                try:
                    progress.setLabelText(f"Calibrating {i+1}/{len(light_files)}: {os.path.basename(light_file.fitsFileName)}")
                    progress.setValue(i)
                    QApplication.processEvents()

                    # Check if already calibrated
                    if light_file.fitsFileCalibrated:
                        logger.debug(f"File already calibrated, skipping: {os.path.basename(light_file.fitsFileName)}")
                        skipped_count += 1
                        continue

                    if not os.path.exists(light_file.fitsFileName):
                        logger.warning(f"File not found: {light_file.fitsFileName}")
                        error_count += 1
                        continue

                    _calibrate_light_file(light_file, masters, master_data)
                    calibrated_count += 1

                except Exception:
                    logger.exception(f"Error calibrating {light_file.fitsFileName}")
                    error_count += 1

            progress.setValue(len(light_files))
            progress.close()

            # Show results
            message = "Calibration complete!\n\n"
            message += f"Processed: {len(light_files)} files\n"
            message += f"Calibrated: {calibrated_count}\n"
            message += f"Skipped: {skipped_count}\n"
            message += f"Errors: {error_count}\n\n"
            message += "Calibrated frames saved with 'cal_' prefix.\n"
            message += "Source frames marked as soft-deleted."

            if show_results:
                if calibrated_count > 0:
                    QMessageBox.information(self, "Calibration Complete", message)
                else:
                    QMessageBox.warning(self, "Calibration Complete", message)

            logger.info(f"Session calibration complete: {calibrated_count} calibrated, {skipped_count} skipped, {error_count} errors")

            # Refresh sessions tree so new calibrated records appear
            try:
                self.load_sessions_data()
            except Exception as e:
                logger.warning(f"Failed to refresh sessions view after calibration: {e}")

            return {
                "total": len(light_files),
                "calibrated": calibrated_count,
                "skipped": skipped_count,
                "errors": error_count,
            }

        except Exception as e:
            if show_results:
                QMessageBox.critical(self, "Error", f"Failed to calibrate session: {e!s}")
            logger.exception("Error in calibrate_session")
            return {"error": str(e)}

    @staticmethod
    def _find_session_masters(master_manager, session) -> dict:
        """The bias/dark/flat (and the flat's flat-dark) masters, keyed ``Bias``/``Dark``/``Flat``/``FlatDark``,
        that match *session* and exist on disk."""
        session_data = {
            'telescope': session.fitsSessionTelescope,
            'instrument': session.fitsSessionImager,
            'exposure_time': session.fitsSessionExposure,
            'filter_name': session.fitsSessionFilter,
            'binning_x': session.fitsSessionBinningX,
            'binning_y': session.fitsSessionBinningY,
            'ccd_temp': session.fitsSessionCCDTemp,
            'gain': session.fitsSessionGain,
            'offset': session.fitsSessionOffset
        }
        masters = {}
        for label, cal_type in (("Bias", "bias"), ("Dark", "dark"), ("Flat", "flat")):
            master = master_manager.find_matching_master(session_data, cal_type)
            if master is not None and os.path.exists(master.master_path):
                masters[label] = master

        # The flat-dark belongs to the session's flat: flat session -> its linked flat-dark session
        flat_dark = SessionsStackingMixin._find_flat_dark_master(master_manager, session)
        if flat_dark is not None:
            masters["FlatDark"] = flat_dark
        return masters

    @staticmethod
    def _find_flat_dark_master(master_manager, session):
        """The flat-dark master for *session*'s flat, or ``None`` if there is none (or it is missing on disk)."""
        from galileo.library.core.utils import session_to_calibration_criteria

        try:
            if not session.fitsFlatSession:
                return None
            flat_session = FitsSessionModel.get_by_id(session.fitsFlatSession)
            if not flat_session.fitsDarkSession:
                return None
            flat_dark_session = FitsSessionModel.get_by_id(flat_session.fitsDarkSession)
            master = master_manager.find_matching_master(session_to_calibration_criteria(flat_dark_session), 'flatdark')
            if master is not None and os.path.exists(master.master_path):
                return master
        except Exception as e:
            logger.debug(f"Unable to resolve flat-dark master for session {getattr(session, 'fitsSessionId', None)}: {e}")
        return None

    def sample_stack_session(self, item):
        """Create a quick stack of calibrated frames for review and open it in external viewer."""
        try:
            from galileo.library.core.master_manager import get_master_manager
            from galileo.library.core.utils import sanitize_filesystem_name

            session_id = item.data(0, Qt.ItemDataRole.UserRole)
            if not session_id:
                QMessageBox.warning(self, "Error", "Session ID not found")
                return

            session = FitsSessionModel.get_by_id(session_id)
            if not session:
                QMessageBox.warning(self, "Error", "Session not found in database")
                return

            parent_item = item.parent()
            object_name = parent_item.text(0) if parent_item else (session.fitsSessionObjectName or "Unknown")
            if object_name in ['Bias', 'Dark', 'Flat', 'FlatDark']:
                QMessageBox.information(self, "Not Applicable", "Stack is only available for light sessions.")
                return

            # Check if this is a precalibrated telescope/instrument (iTelescope or SeeStar)
            telescope = session.fitsSessionTelescope or ""
            instrument = session.fitsSessionImager or ""
            is_precalibrated_session = (
                ('itelescope' in telescope.lower()) or
                ('seestar' in instrument.lower())
            )

            if is_precalibrated_session:
                # Precalibrated sessions should skip calibration entirely and stack the light frames as-is.
                stack_candidates = list(FitsFileModel.select().where(
                    (FitsFileModel.fitsFileSession == session.fitsSessionId) &
                    (FitsFileModel.fitsFileSoftDelete == False) &
                    (FitsFileModel.fitsFileType.in_(['LIGHT', 'LIGHT FRAME']))
                ))
            else:
                # Find calibrated light frames in this session
                stack_candidates = list(FitsFileModel.select().where(
                    (FitsFileModel.fitsFileSession == session.fitsSessionId) &
                    (FitsFileModel.fitsFileSoftDelete == False) &
                    (FitsFileModel.fitsFileCalibrated == 1) &
                    (FitsFileModel.fitsFileType.in_(['LIGHT', 'LIGHT FRAME']))
                ))

                # If not calibrated, run calibration first (no confirmation popups)
                if not stack_candidates:
                    logger.info(f"No calibrated frames found for session {session.fitsSessionId}; running calibration")
                    cal_result = self.calibrate_session(item, confirm=False, show_results=False)
                    if isinstance(cal_result, dict) and cal_result.get("cancelled"):
                        return
                    if isinstance(cal_result, dict) and cal_result.get("error"):
                        details = cal_result.get("details")
                        msg = cal_result.get("error")
                        if details:
                            msg = f"{msg}\n\n{details}"
                        QMessageBox.warning(self, "Calibration Failed", f"Calibration failed:\n{msg}")
                        return

                    stack_candidates = list(FitsFileModel.select().where(
                        (FitsFileModel.fitsFileSession == session.fitsSessionId) &
                        (FitsFileModel.fitsFileSoftDelete == False) &
                        (FitsFileModel.fitsFileCalibrated == 1) &
                        (FitsFileModel.fitsFileType.in_(['LIGHT', 'LIGHT FRAME']))
                    ))

            if not stack_candidates:
                QMessageBox.information(self, "No Frames", "No light frames were found to stack.")
                return

            file_paths = [f.fitsFileName for f in stack_candidates if f.fitsFileName and os.path.exists(f.fitsFileName)]
            if len(file_paths) < 2:
                QMessageBox.information(self, "Not Enough Frames", "Need at least 2 frames to create a stack.")
                return

            # Output path next to the calibrated frames
            out_dir = os.path.dirname(file_paths[0])
            date_str = str(session.fitsSessionDate) if session.fitsSessionDate else "unknown_date"
            safe_object = sanitize_filesystem_name(object_name)
            output_path = os.path.join(out_dir, f"stack_{safe_object}_{date_str}.fits")

            # Progress dialog for stacking
            progress = QProgressDialog("Stacking calibrated frames...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setWindowTitle("Stack")
            progress.setMinimumDuration(0)
            progress.setValue(0)
            progress.show()
            QApplication.processEvents()

            def _progress_callback(current, total, message):
                # Map arbitrary current/total to 0-100
                if progress.wasCanceled():
                    raise RuntimeError("Stack cancelled by user")
                try:
                    pct = int((float(current) / float(total)) * 100) if total else 0
                except Exception:
                    pct = 0
                pct = max(0, min(100, pct))
                progress.setValue(pct)
                if message:
                    progress.setLabelText(str(message))
                QApplication.processEvents()

            # Use existing internal sigma-clipped stacker (same engine used for masters)
            master_manager = get_master_manager()
            ok = master_manager._create_master_sigma_clip(
                file_paths=file_paths,
                output_path=output_path,
                cal_type='light',
                progress_callback=_progress_callback,
                thumbnail_session_id=str(session.fitsSessionId),
            )

            progress.setValue(100)
            progress.close()

            if not ok or not os.path.exists(output_path):
                QMessageBox.warning(self, "Stack Failed", "Failed to create stack.")
                return

            logger.info(f"Stack created: {output_path}")
            self._open_path_in_external_viewer(output_path)
            self.load_sessions_data()

        except RuntimeError as e:
            # Cancellation
            logger.info(f"Stack cancelled: {e}")
        except Exception as e:
            logger.exception("Error creating stack")
            QMessageBox.critical(self, "Error", f"Failed to create stack:\n{e!s}")

    def photometric_stack_session(self, item):
        """Create a photometry-safe stack of light frames and open it in the external viewer."""
        try:
            from galileo.library.core.master_manager import get_master_manager
            from galileo.library.core.utils import best_hfr_reference_path, sanitize_filesystem_name
            from galileo.library.models import fitsSession as FitsSessionModel

            session_id = item.data(0, Qt.ItemDataRole.UserRole)
            if not session_id:
                QMessageBox.warning(self, "Error", "Session ID not found")
                return

            session = FitsSessionModel.get_by_id(session_id)
            if not session:
                QMessageBox.warning(self, "Error", "Session not found in database")
                return

            parent_item = item.parent()
            object_name = parent_item.text(0) if parent_item else (session.fitsSessionObjectName or "Unknown")
            if object_name in ['Bias', 'Dark', 'Flat', 'FlatDark']:
                QMessageBox.information(self, "Not Applicable", "Photometric stack is only available for light sessions.")
                return

            stack_candidates = self._photometric_stack_candidates(item, session)
            if stack_candidates is None:        # calibration was cancelled or failed (the user has been told)
                return
            if not stack_candidates:
                QMessageBox.information(self, "No Frames", "No light frames were found to stack.")
                return

            file_paths = [f.fitsFileName for f in stack_candidates if f.fitsFileName and os.path.exists(f.fitsFileName)]
            if len(file_paths) < 2:
                QMessageBox.information(self, "Not Enough Frames", "Need at least 2 frames to create a stack.")
                return

            out_dir = os.path.dirname(file_paths[0])
            date_str = str(session.fitsSessionDate) if session.fitsSessionDate else "unknown_date"
            safe_object = sanitize_filesystem_name(object_name)
            output_path = os.path.join(out_dir, f"photometric_stack_{safe_object}_{date_str}.fits")

            ok = self._run_photometric_stack(
                get_master_manager(), file_paths, output_path,
                reference_path=best_hfr_reference_path(stack_candidates),  # prefer the best-HFR frame as reference
                session_id=str(session.fitsSessionId))

            if not ok or not os.path.exists(output_path):
                QMessageBox.warning(self, "Stack Failed", "Failed to create photometric stack.")
                return

            logger.info(f"Photometric stack created: {output_path}")
            self._open_path_in_external_viewer(output_path)
            self.load_sessions_data()

        except RuntimeError as e:
            logger.info(f"Photometric stack cancelled: {e}")
        except Exception as e:
            logger.exception("Error creating photometric stack")
            QMessageBox.critical(self, "Error", f"Failed to create photometric stack:\n{e!s}")

    def _photometric_stack_candidates(self, item, session) -> list | None:
        """The light frames to stack (calibrating the session first if it has none calibrated).

        Returns None when that calibration was cancelled or failed.
        """
        telescope = session.fitsSessionTelescope or ""
        instrument = session.fitsSessionImager or ""
        precalibrated = 'itelescope' in telescope.lower() or 'seestar' in instrument.lower()

        candidates = session_light_frames(session, calibrated_only=not precalibrated)
        if candidates or precalibrated:
            return candidates

        logger.info(f"No calibrated frames found for session {session.fitsSessionId}; running calibration")
        cal_result = self.calibrate_session(item, confirm=False, show_results=False)
        if isinstance(cal_result, dict) and cal_result.get("cancelled"):
            return None
        if isinstance(cal_result, dict) and cal_result.get("error"):
            details = cal_result.get("details")
            msg = cal_result.get("error")
            if details:
                msg = f"{msg}\n\n{details}"
            QMessageBox.warning(self, "Calibration Failed", f"Calibration failed:\n{msg}")
            return None
        return session_light_frames(session, calibrated_only=True)

    def _run_photometric_stack(self, master_manager, file_paths, output_path, *, reference_path, session_id) -> bool:
        """Stack *file_paths* into *output_path* behind a cancellable progress dialog; True on success."""
        progress = QProgressDialog("Creating photometric stack...", "Cancel", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setWindowTitle("Stack (photometric)")
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()

        def _progress_callback(current, total, message):
            if progress.wasCanceled():
                raise RuntimeError("Stack cancelled by user")
            try:
                pct = int((float(current) / float(total)) * 100) if total else 0
            except Exception:
                pct = 0
            progress.setValue(max(0, min(100, pct)))
            if message:
                progress.setLabelText(str(message))
            QApplication.processEvents()

        ok = master_manager._create_light_stack_photometric_mean(
            file_paths=file_paths,
            output_path=output_path,
            progress_callback=_progress_callback,
            reference_path=reference_path,
            thumbnail_session_id=session_id,
        )

        progress.setValue(100)
        progress.close()
        return ok
