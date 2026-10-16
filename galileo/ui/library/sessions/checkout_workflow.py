from __future__ import annotations

import logging
import os
from typing import Any
from datetime import datetime as dt

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QProgressDialog, QMessageBox, QWidget

from galileo.library.models import fitsFile as FitsFileModel, fitsSession as FitsSessionModel

from .checkout_files import get_decompressed_dest_path, materialize_file
from .checkout_options_dialog import prompt_checkout_options
from .masters_resolver import find_matching_masters_for_light_session
from galileo.exceptions import LibraryError

logger = logging.getLogger(__name__)


def _format_method_desc(*, decompress: bool, copy_files: bool, masters_only: bool) -> str:
    method_bits: list[str] = []
    if decompress:
        method_bits.append("decompressed")
    method_bits.append("copied" if copy_files else "linked")
    if masters_only:
        method_bits.append("masters-only")
    return "+".join(method_bits)


def _show_checkout_complete(parent: QWidget, *, created_items: int, method_desc: str, out_dir: str, extra: str = "") -> None:
    message = f"Created {created_items} files ({method_desc}).\n\nFiles created in:\n{out_dir}"
    if extra:
        message = extra + "\n\n" + message
    QMessageBox.information(parent, "Checkout Complete", message)
    QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))


def _show_checkout_failed(parent: QWidget, *, message: str) -> None:
    QMessageBox.warning(parent, "Checkout Failed", message)


_CALIBRATION_OBJECTS = ('Bias', 'Dark', 'Flat', 'FlatDark')   # sessions that are themselves calibration frames


def _find_flat_files(session, light_files, *, log_counts: bool = False) -> list:
    """Flats from the sessions that match the lights' telescope/imager/binning, one lookup per filter used."""
    flat_files: list = []
    filters = {lf.fitsFileFilter for lf in light_files if lf.fitsFileFilter}
    if log_counts:
        logger.info(f"Filters used in light frames: {filters}")

    for filter_name in filters:
        flat_sessions = FitsSessionModel.select().where(
            (FitsSessionModel.fitsSessionObjectName == 'Flat')
            & (FitsSessionModel.fitsSessionTelescope == session.fitsSessionTelescope)
            & (FitsSessionModel.fitsSessionImager == session.fitsSessionImager)
            & (FitsSessionModel.fitsSessionBinningX == session.fitsSessionBinningX)
            & (FitsSessionModel.fitsSessionBinningY == session.fitsSessionBinningY)
            & (FitsSessionModel.fitsSessionFilter == filter_name)
        )
        for flat_session in flat_sessions:
            these_flats = FitsFileModel.select().where(FitsFileModel.fitsFileSession == flat_session.fitsSessionId)
            flat_files.extend(list(these_flats))
            if log_counts:
                logger.info(f"Found {these_flats.count()} flat files for filter {filter_name}")
    return flat_files


def _calibration_frames(session, light_files, *, log_counts: bool = False):
    """``(dark_files, bias_files, flat_files)`` for a light session (empty where the session has none)."""
    dark_files: Any = []  # a list until the session has darks/bias, then a Peewee query
    bias_files: Any = []
    if session.fitsBiasSession:
        bias_files = FitsFileModel.select().where(FitsFileModel.fitsFileSession == session.fitsBiasSession)
        if log_counts:
            logger.info(f"Found {bias_files.count()} bias files")
    if session.fitsDarkSession:
        dark_files = FitsFileModel.select().where(FitsFileModel.fitsFileSession == session.fitsDarkSession)
        if log_counts:
            logger.info(f"Found {dark_files.count()} dark files")
    return dark_files, bias_files, _find_flat_files(session, light_files, log_counts=log_counts)


def _destination_folder(file_type: str, dirs: dict[str, str | None]) -> tuple[bool, str | None]:
    """``(known_type, folder)`` for a frame type; the folder is ``None`` when that kind is not being checked out."""
    file_type = file_type.upper()
    for kind in ("light", "dark", "flat", "bias"):
        if kind.upper() in file_type:
            return True, dirs.get(kind)
    return False, None


def _materialize_into(src_path: str, dest_folder: str, *, copy_files: bool, decompress: bool) -> bool:
    """Link/copy/decompress *src_path* into *dest_folder*. False if it is already there; raises if it fails."""
    dest_path = os.path.join(dest_folder, os.path.basename(src_path))
    if os.path.exists(dest_path) or os.path.exists(get_decompressed_dest_path(dest_path)):
        return False
    ok = materialize_file(src_path=src_path, dest_path=dest_path, copy_files=copy_files, decompress=decompress)
    if not ok:
        raise LibraryError("Failed to create output")
    logger.info(f"Created checkout file for {src_path} -> {dest_path}")
    return True


def _make_session_dirs(session_dir: str, *, lights_only: bool, include_calibration_frames: bool):
    """Create a single-session checkout tree. Returns ``(dirs, masters_dir)``; ``dirs`` maps kind -> folder."""
    light_dir = os.path.join(session_dir, "lights")
    os.makedirs(light_dir, exist_ok=True)
    dirs: dict[str, str | None] = {"light": light_dir, "dark": None, "flat": None, "bias": None}
    masters_dir = None

    if lights_only:
        logger.info(f"Created session directory structure (lights only) at {session_dir}")
        return dirs, masters_dir

    masters_dir = os.path.join(session_dir, "masters")
    os.makedirs(masters_dir, exist_ok=True)
    if include_calibration_frames:
        for kind, folder in (("dark", "darks"), ("flat", "flats"), ("bias", "bias")):
            dirs[kind] = os.path.join(session_dir, folder)
            os.makedirs(dirs[kind], exist_ok=True)
        logger.info(f"Created session directory structure with calibration folders at {session_dir}")
    else:
        logger.info(f"Created session directory structure (lights + masters only) at {session_dir}")
    return dirs, masters_dir


def _progress_label(*, decompress: bool, copy_files: bool) -> str:
    if decompress and copy_files:
        return "Creating files (decompress/copy)..."
    if decompress:
        return "Creating files (decompress/link)..."
    if copy_files:
        return "Copying files..."
    return "Creating symbolic links..."


def _create_session_files(progress, all_files, master_files, dirs, masters_dir, *, copy_files: bool, decompress: bool) -> int:
    """Create the checkout files and masters of one session, driving *progress*. Returns how many were created."""
    created_items = 0
    total_items = len(all_files) + len(master_files)
    current_item = 0

    for file in all_files:
        progress.setValue(int(current_item * 100 / total_items) if total_items > 0 else 0)
        current_item += 1
        if progress.wasCanceled():
            break

        known_type, dest_folder = _destination_folder(file.fitsFileType, dirs)
        if not known_type:
            logger.warning(f"Unknown file type for {file.fitsFileName}, skipping")
            continue
        if dest_folder is None:
            logger.debug(f"Skipping calibration file {file.fitsFileName} (lights already calibrated)")
            continue
        if not file.fitsFileName or not os.path.exists(file.fitsFileName):
            continue

        try:
            if _materialize_into(file.fitsFileName, dest_folder, copy_files=copy_files, decompress=decompress):
                created_items += 1
        except Exception as e:
            logger.exception(f"Error creating link for {file.fitsFileName}: {e}")

    for _master_type, master_path in master_files:
        progress.setValue(int(current_item * 100 / total_items) if total_items > 0 else 0)
        current_item += 1
        if progress.wasCanceled():
            break

        try:
            if _materialize_into(master_path, masters_dir, copy_files=copy_files, decompress=decompress):
                created_items += 1
        except Exception as e:
            logger.exception(f"Error creating link for master {master_path}: {e}")

    return created_items


def checkout_single_session(parent: QWidget, item) -> None:
    """Create symbolic links/copies/decompressed outputs for a single session."""
    try:
        session_date = item.text(2)
        object_name = item.parent().text(0)

        session = (
            FitsSessionModel.select()
            .where(
                (FitsSessionModel.fitsSessionObjectName == object_name)
                & (FitsSessionModel.fitsSessionDate == session_date)
            )
            .first()
        )

        if not session:
            QMessageBox.warning(parent, "Error", "Session not found in database")
            return
        logger.info(f"Found session: {object_name} on {session_date}")

        light_files = FitsFileModel.select().where(FitsFileModel.fitsFileSession == session.fitsSessionId)
        lights_calibrated = all(lf.fitsFileCalibrated for lf in light_files)
        is_calibration_session = object_name in _CALIBRATION_OBJECTS

        dark_files: Any = []
        bias_files: Any = []
        flat_files: list = []
        master_files: list[tuple[str, str]] = []

        if not is_calibration_session:
            if not lights_calibrated:
                dark_files, bias_files, flat_files = _calibration_frames(session, light_files, log_counts=True)

                master_files = find_matching_masters_for_light_session(session, light_files)
                for master_type, master_path in master_files:
                    label = 'flat master' if master_type == 'flat' else f"{master_type} master"
                    logger.info(f"Found matching {label}: {os.path.basename(master_path)}")
            else:
                logger.info("Light frames are already calibrated, skipping calibration files and masters")

        opts = prompt_checkout_options(parent, "Check out Session")
        if not opts:
            return
        dest_dir, copy_files, decompress, masters_only = (
            opts.dest_dir,
            opts.copy_files,
            opts.decompress,
            opts.masters_only,
        )

        include_calibration_frames = (not masters_only) and (not lights_calibrated) and (not is_calibration_session)

        all_files = list(light_files)
        if include_calibration_frames:
            all_files += list(dark_files) + list(bias_files) + list(flat_files)

        if not all_files:
            QMessageBox.information(parent, "Information", "No files found for this session")
            return

        logger.info(f"Found {len(all_files)} files for session {object_name} on {session_date}")

        session_dir = os.path.join(dest_dir, f"{object_name}_{session_date.replace(':', '-')}")
        dirs, masters_dir = _make_session_dirs(
            session_dir,
            lights_only=lights_calibrated or is_calibration_session,
            include_calibration_frames=include_calibration_frames,
        )

        progress = QProgressDialog(_progress_label(decompress=decompress, copy_files=copy_files), "Cancel", 0, 100, parent)
        progress.setWindowModality(Qt.WindowModality.WindowModal)

        created_items = _create_session_files(
            progress, all_files, master_files if masters_dir else [], dirs, masters_dir,
            copy_files=copy_files, decompress=decompress)

        progress.setValue(100)

        method_desc = _format_method_desc(
            decompress=decompress,
            copy_files=copy_files,
            masters_only=masters_only,
        )

        _show_checkout_complete(
            parent,
            created_items=created_items,
            method_desc=method_desc,
            out_dir=session_dir,
        )

    except Exception as e:
        QMessageBox.critical(parent, "Checkout Failed", f"Failed to create symbolic links: {e!s}")
        logger.exception(f"Error in checkout_session: {e!s}")


def _ensure_dir(checkout_dir: str, current: str | None, name: str) -> str:
    """*current* if the folder was already made, else create ``checkout_dir/name`` and return it."""
    if current is None:
        current = os.path.join(checkout_dir, name)
        os.makedirs(current, exist_ok=True)
    return current


def _checkout_one_of_many(session_item, checkout_dir: str, dirs: dict[str, str | None],
                          *, copy_files: bool, decompress: bool, masters_only: bool, progress) -> tuple[int, str, str]:
    """Check out one session of a multi-session checkout. Returns ``(items created, object name, date)``.

    *dirs* maps kind -> folder and is updated as calibration/masters folders are created lazily.
    """
    session_id = session_item.data(0, Qt.ItemDataRole.UserRole)
    if not session_id:
        raise _SkipSessionError("Session item missing ID", log="Session item has no session ID, skipping")

    session = FitsSessionModel.get_by_id(session_id)
    if not session:
        raise _SkipSessionError(f"Session ID {session_id}: Not found in database")

    parent_item = session_item.parent()
    object_name = parent_item.text(0) if parent_item else session.fitsSessionObjectName
    session_date = session.fitsSessionDate
    filter_label = session.fitsSessionFilter or "NoFilter"

    progress.setLabelText(f"Processing {object_name} - {session_date} ({filter_label})...")

    light_files = FitsFileModel.select().where(FitsFileModel.fitsFileSession == session.fitsSessionId)
    lights_calibrated = all(lf.fitsFileCalibrated for lf in light_files)
    dark_files, bias_files, flat_files = _calibration_frames(session, light_files)

    include_calibration_frames = (
        (not masters_only) and (not lights_calibrated) and (object_name not in _CALIBRATION_OBJECTS)
    )
    if include_calibration_frames:
        for kind, folder in (("dark", "darks"), ("flat", "flats"), ("bias", "bias")):
            dirs[kind] = _ensure_dir(checkout_dir, dirs[kind], folder)

    all_files = list(light_files)
    if include_calibration_frames:
        all_files += list(dark_files) + list(bias_files) + list(flat_files)

    # Calibration folders only count while this session is including calibration frames.
    active_dirs = dirs if include_calibration_frames else {**dirs, "dark": None, "flat": None, "bias": None}

    created = 0
    for file in all_files:
        _, dest_folder = _destination_folder(file.fitsFileType, active_dirs)
        if dest_folder is None or not file.fitsFileName or not os.path.exists(file.fitsFileName):
            continue
        try:
            if _materialize_into(file.fitsFileName, dest_folder, copy_files=copy_files, decompress=decompress):
                created += 1
        except Exception as e:
            logger.exception(f"Error creating link for {file.fitsFileName}: {e}")

    logger.info(f"Successfully processed session {object_name} - {session_date} with {created} links")

    if masters_only and (not lights_calibrated) and (object_name not in _CALIBRATION_OBJECTS):
        try:
            dirs["masters"] = _ensure_dir(checkout_dir, dirs["masters"], "masters")
            for _, master_path in find_matching_masters_for_light_session(session, light_files):
                if _materialize_into(master_path, dirs["masters"], copy_files=copy_files, decompress=decompress):
                    created += 1
        except Exception as e:
            logger.exception(f"Error creating master files for session {session_id}: {e}")

    return created, object_name, session_date


class _SkipSessionError(Exception):
    """A session in a multi-session checkout that is recorded as failed without a traceback."""

    def __init__(self, message: str, *, log: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.log = log


def checkout_multiple_sessions(parent: QWidget, session_items) -> None:
    """Create symbolic links/copies/decompressed outputs for multiple sessions in a common directory structure."""
    try:
        opts = prompt_checkout_options(parent, "Check out Multiple Sessions")
        if not opts:
            return
        dest_dir, copy_files, decompress, masters_only = (
            opts.dest_dir,
            opts.copy_files,
            opts.decompress,
            opts.masters_only,
        )

        checkout_dir = os.path.join(dest_dir, f"Sessions_Checkout_{dt.now().astimezone().strftime('%Y%m%d_%H%M%S')}")
        light_dir = os.path.join(checkout_dir, "lights")
        process_dir = os.path.join(checkout_dir, "process")

        # Create only folders that are always needed up-front.
        # Calibration and masters folders are created lazily, only if any selected session needs them.
        os.makedirs(light_dir, exist_ok=True)
        os.makedirs(process_dir, exist_ok=True)
        dirs: dict[str, str | None] = {"light": light_dir, "dark": None, "flat": None, "bias": None, "masters": None}

        total_sessions = len(session_items)
        overall_progress = QProgressDialog("Processing sessions...", "Cancel", 0, total_sessions, parent)
        overall_progress.setWindowModality(Qt.WindowModality.WindowModal)
        overall_progress.setWindowTitle("Checking Out Multiple Sessions")

        successful_sessions = 0
        failed_sessions: list[str] = []
        total_created_items = 0

        for current_session, session_item in enumerate(session_items):
            if overall_progress.wasCanceled():
                break

            overall_progress.setValue(current_session)
            try:
                created, _object_name, _session_date = _checkout_one_of_many(
                    session_item, checkout_dir, dirs,
                    copy_files=copy_files, decompress=decompress, masters_only=masters_only,
                    progress=overall_progress,
                )
                successful_sessions += 1
                total_created_items += created
            except _SkipSessionError as skip:
                if skip.log:
                    logger.exception(skip.log)
                failed_sessions.append(skip.message)
            except Exception as e:
                error_msg = f"{_describe_session_item(session_item)}: {e!s}"
                failed_sessions.append(error_msg)
                logger.exception(f"Error processing session: {error_msg}")

            logger.info(f"Completed session {current_session + 1} of {total_sessions}")

        overall_progress.setValue(total_sessions)

        method_desc = _format_method_desc(
            decompress=decompress,
            copy_files=copy_files,
            masters_only=masters_only,
        )

        message = f"Successfully processed {successful_sessions} out of {total_sessions} sessions."
        if failed_sessions:
            message += "\n\nFailed sessions:\n" + "\n".join(failed_sessions)

        if successful_sessions > 0:
            _show_checkout_complete(
                parent,
                created_items=total_created_items,
                method_desc=method_desc,
                out_dir=checkout_dir,
                extra=message,
            )
        else:
            _show_checkout_failed(parent, message=message)

    except Exception as e:
        QMessageBox.critical(parent, "Checkout Failed", f"Failed to checkout multiple sessions: {e!s}")
        logger.exception(f"Error in checkout_multiple_sessions: {e!s}")


def _describe_session_item(session_item) -> str:
    """``<object> - <date>`` for a session tree item, or ``Unknown - Unknown`` if it cannot be read."""
    try:
        parent_item = session_item.parent()
        object_name = parent_item.text(0) if parent_item else None
        session_id = session_item.data(0, Qt.ItemDataRole.UserRole)
        session = FitsSessionModel.get_by_id(session_id) if session_id else None
        return f"{object_name or (session.fitsSessionObjectName if session else 'Unknown')} - " \
               f"{session.fitsSessionDate if session else 'Unknown'}"
    except Exception:
        return "Unknown - Unknown"
