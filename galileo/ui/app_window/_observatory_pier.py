# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Top bar Observatory/Pier selection (load/create/switch) and the per-Pier pointing/tracking polling that follows a Pier switch."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _NEW_OBSERVATORY_LABEL, _NEW_PIER_LABEL
from ._threads import _MountPositionThread, _ResumeTrackingThread

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowObservatoryPierMixin:
    def _load_observatories(self: AppWindowState) -> None:
        """Populate the Observatory combo from persisted records (settings
        survive restarts — see galileo.observatory.list_observatories)."""
        from galileo.observatory import list_observatories

        combo = self._observatory_combo
        try:
            records = list_observatories()
        except Exception:
            logger.exception("Could not load saved Observatories")
            records = []

        combo.blockSignals(True)
        for record in records:
            self._observatories[record.name] = record
            combo.insertItem(combo.count() - 1, record.name)
        combo.blockSignals(False)

        if records:
            combo.setCurrentIndex(0)
            self._select_observatory(records[0])
        else:
            self._refresh_pier_combo()

    def _prompt_new_name(self: AppWindowState, title: str, label_text: str) -> str | None:
        """Modal Name / OK / Cancel dialog used for New Pier."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QDialogButtonBox

        dialog = QDialog(self._window)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(label_text))
        name_edit = QLineEdit()
        layout.addWidget(name_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        name_edit.setFocus()

        if dialog.exec() == QDialog.Accepted:
            name = name_edit.text().strip()
            return name or None
        return None

    def _prompt_new_observatory(self: AppWindowState) -> dict | None:
        """Modal Name/Lat/Long/Timezone/Physical Address/Owner dialog for New Observatory."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox, QDialogButtonBox,
        )

        dialog = QDialog(self._window)
        dialog.setWindowTitle("New Observatory")
        outer = QVBoxLayout(dialog)
        form = QFormLayout()
        outer.addLayout(form)

        name_edit = QLineEdit()
        form.addRow("Name", name_edit)

        lat_edit = QDoubleSpinBox()
        lat_edit.setRange(-90.0, 90.0)
        lat_edit.setDecimals(6)
        form.addRow("Latitude", lat_edit)

        long_edit = QDoubleSpinBox()
        long_edit.setRange(-180.0, 180.0)
        long_edit.setDecimals(6)
        form.addRow("Longitude", long_edit)

        tz_edit = QLineEdit()
        tz_edit.setPlaceholderText("e.g. America/Toronto")
        form.addRow("Timezone", tz_edit)

        address_edit = QLineEdit()
        form.addRow("Physical Address", address_edit)

        owner_edit = QLineEdit()
        form.addRow("Owner", owner_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        outer.addWidget(buttons)
        name_edit.setFocus()

        if dialog.exec() != QDialog.Accepted:
            return None
        name = name_edit.text().strip()
        if not name:
            return None
        return {
            "name": name,
            "latitude": lat_edit.value(),
            "longitude": long_edit.value(),
            "timezone": tz_edit.text().strip() or None,
            "physical_address": address_edit.text().strip() or None,
            "owner": owner_edit.text().strip() or None,
        }

    def _on_observatory_activated(self: AppWindowState, index: int) -> None:
        from galileo.observatory import create_observatory

        combo = self._observatory_combo
        if combo.itemText(index) == _NEW_OBSERVATORY_LABEL:
            fields = self._prompt_new_observatory()
            if fields and fields["name"] not in self._observatories:
                try:
                    observatory = create_observatory(**fields)
                except Exception:
                    logger.exception("Could not save new Observatory %r", fields["name"])
                    combo.setCurrentIndex(self._index_of_current_observatory(combo))
                    return
                self._observatories[observatory.name] = observatory
                combo.insertItem(combo.count() - 1, observatory.name)
                combo.setCurrentIndex(combo.count() - 2)
                self._select_observatory(observatory)
            else:
                combo.setCurrentIndex(self._index_of_current_observatory(combo))
        else:
            self._select_observatory(self._observatories[combo.itemText(index)])

    def _index_of_current_observatory(self: AppWindowState, combo) -> int:
        if self._current_observatory is None:
            return combo.count() - 1
        idx = combo.findText(self._current_observatory.name)
        return idx if idx >= 0 else combo.count() - 1

    def _select_observatory(self: AppWindowState, observatory) -> None:
        self._current_observatory = observatory
        self._current_pier = None
        self._refresh_pier_combo()

    def _refresh_pier_combo(self: AppWindowState) -> None:
        from galileo.observatory import list_piers

        combo = self._pier_combo
        combo.blockSignals(True)
        combo.clear()
        if self._current_observatory is not None:
            try:
                piers = list_piers(self._current_observatory)
            except Exception:
                logger.exception("Could not load saved Piers for Observatory %r", self._current_observatory.name)
                piers = []
            for pier in piers:
                combo.addItem(pier.name)
            combo.addItem(_NEW_PIER_LABEL)
            combo.setEnabled(True)
            if piers:
                combo.setCurrentIndex(0)
                self._current_pier = piers[0]
        else:
            combo.setEnabled(False)
        combo.blockSignals(False)
        self._on_pier_changed()

    def _on_pier_activated(self: AppWindowState, index: int) -> None:
        from galileo.observatory import create_pier, list_piers

        combo = self._pier_combo
        if combo.itemText(index) == _NEW_PIER_LABEL:
            name = self._prompt_new_name("New Pier", "Pier name:")
            existing = {p.name for p in list_piers(self._current_observatory)}
            if name and name not in existing:
                try:
                    pier = create_pier(self._current_observatory, name)
                except Exception:
                    logger.exception("Could not save new Pier %r", name)
                    combo.setCurrentIndex(self._index_of_current_pier(combo))
                    return
                combo.insertItem(combo.count() - 1, name)
                combo.setCurrentIndex(combo.count() - 2)
                self._current_pier = pier
            else:
                combo.setCurrentIndex(self._index_of_current_pier(combo))
                return
        else:
            self._current_pier = next(
                p for p in list_piers(self._current_observatory) if p.name == combo.itemText(index)
            )
        self._on_pier_changed()

    def _index_of_current_pier(self: AppWindowState, combo) -> int:
        if self._current_pier is None:
            return combo.count() - 1
        idx = combo.findText(self._current_pier.name)
        return idx if idx >= 0 else combo.count() - 1

    def _on_pier_changed(self: AppWindowState) -> None:
        """Reload every built Equipment page's fields for the newly selected
        Pier, then re-attempt each page's auto-connect (currently the Camera
        and Focuser pages') for it. Reload happens for all pages first so a
        page that auto-connects never does so against another page's stale
        fields.

        Every step is timed and the total logged, slowest steps first, since
        a Pier switch blocks the UI until the last device has connected."""
        import time

        timings: list[tuple[str, float]] = []

        def timed(label: str, fn) -> None:
            start = time.perf_counter()
            try:
                fn()
            finally:
                timings.append((label, time.perf_counter() - start))

        switch_start = time.perf_counter()
        for page_id, state in self._device_pages.items():
            timed(f"{page_id} reload", state["reload"])
        for page_id, state in self._device_pages.items():
            autoconnect = state.get("autoconnect")
            if autoconnect is not None:
                timed(f"{page_id} autoconnect", autoconnect)
        timed("optics combo", self._refresh_optics_combo)
        timed("camera combo", self._refresh_camera_combo)
        timed("imaging filters", self._refresh_imaging_filters)
        timed("current object", self._refresh_current_object)
        refresh_star_atlas_site = getattr(self, "_star_atlas_refresh_site", None)
        if refresh_star_atlas_site is not None:
            timed("star atlas site", refresh_star_atlas_site)
        timed("horizon", self._apply_horizon)
        for refresh_name in ("_focus_settings_refresh", "_solve_settings_refresh"):
            refresh = getattr(self, refresh_name, None)
            if refresh is not None:
                timed(refresh_name.strip("_").replace("_", " "), refresh)
        self._log_pier_switch_timings(time.perf_counter() - switch_start, timings)

    def _log_pier_switch_timings(self: AppWindowState, total: float, timings: list[tuple[str, float]]) -> None:
        """Log how long a Pier switch took, with its steps slowest first (steps
        under 10 ms are left out of the INFO line and only logged at DEBUG)."""
        pier_name = self._current_pier.name if self._current_pier is not None else None
        ranked = sorted(timings, key=lambda t: t[1], reverse=True)
        notable = ", ".join(f"{label} {secs:.2f}s" for label, secs in ranked if secs >= 0.01)
        logger.info("Pier switch to %r took %.2fs: %s", pier_name, total, notable or "no step over 10 ms")
        for label, secs in ranked:
            logger.debug("Pier switch step %s: %.4fs", label, secs)

    def _apply_horizon(self: AppWindowState) -> None:
        """Load the current Observatory's horizon obstruction table and hand it to
        everything that uses it: the Star Atlas shading, the Options > Star Atlas
        table, and the slew guard the mount adapters consult (together with the
        site, and the Options > Planning switch)."""
        from galileo.core.slew_guard import get_slew_guard
        from galileo.observatory import list_horizon_points
        from galileo.planning.settings import load_planning_settings
        from galileo.planning.visibility import HorizonProfile

        observatory = getattr(self, "_current_observatory", None)
        points: list = []
        if observatory is not None:
            try:
                points = list_horizon_points(observatory)
            except Exception:
                logger.exception("Could not load the horizon obstructions for Observatory %r", observatory.name)
        horizon = HorizonProfile(points) if points else None

        guard = get_slew_guard()
        guard.enabled = bool(load_planning_settings()["block_obstructed_slews"])
        guard.horizon = horizon
        guard.latitude = getattr(observatory, "latitude", None)
        guard.longitude = getattr(observatory, "longitude", None)

        set_atlas_horizon = getattr(self, "_star_atlas_set_horizon", None)
        if set_atlas_horizon is not None:
            set_atlas_horizon(horizon)
        refresh_table = getattr(self, "_horizon_table_refresh", None)
        if refresh_table is not None:
            refresh_table(points)

    def pier_markers(self: AppWindowState) -> list:
        """A telescope reticle for each Pier in the current Observatory (SKYMAP-090).

        A Pier whose mount Galileo has read reports where it is actually pointing, so its reticle
        moves across the sky as it slews; its current object is shown as the target it is heading
        for. A Pier with no reading falls back to its current object's position, labelled as the
        target rather than the telescope. Only the selected Pier's mount is connected at a time
        (the Equipment pages reconnect on every Pier change), so the other Piers normally show
        their target alone."""
        from galileo.current_object import get_current_objects, pier_key
        from galileo.observatory import list_piers

        if self._current_observatory is None:
            return []
        try:
            piers = list_piers(self._current_observatory)
        except Exception:
            logger.exception("Could not load the Piers for the Star Atlas markers")
            return []

        objects = get_current_objects()
        markers = []
        for pier in piers:
            target = objects.get(pier)
            target_point = {"ra_deg": target.ra_deg, "dec_deg": target.dec_deg} if target is not None else None
            pointing = self._pier_pointing.get(pier_key(pier))
            if pointing is not None:
                label = f"{pier.name} → {target.name}" if target is not None else pier.name
                if pointing.get("slewing"):
                    label += " (slewing)"
                markers.append({"ra_deg": pointing["ra_deg"], "dec_deg": pointing["dec_deg"],
                                "label": label, "slewing": bool(pointing.get("slewing")),
                                "target": target_point})
            elif target_point is not None:
                markers.append({**target_point, "label": f"{pier.name} → {target.name}", "slewing": False})
        return markers

    def _poll_pier_pointing(self: AppWindowState, on_done=None) -> None:
        """Read the connected mount's position off the Qt UI thread and remember it for the Star
        Atlas reticles (SKYMAP-090). One poll at a time; a mount that can't be read is forgotten,
        so its reticle falls back to the Pier's target rather than freezing where it last was."""
        from galileo.current_object import pier_key

        mount = (self._device_pages.get("mount") or {}).get("adapter")
        key = pier_key(self._current_pier)
        if mount is None or key is None:
            if self._pier_pointing.pop(key, None) is not None and on_done is not None:
                on_done()
            return
        if self._pier_poll_thread is not None:
            return

        def done(status) -> None:
            self._pier_poll_thread = None
            pointing = None
            if status:
                ra_hours, dec = status.get("right_ascension"), status.get("declination")
                if ra_hours is not None and dec is not None:
                    from galileo.platesolve import mount_frame_to_j2000
                    ra_deg, dec_deg = mount_frame_to_j2000(ra_hours * 15.0, dec, status.get("equatorial_system"))
                    pointing = {"ra_deg": ra_deg, "dec_deg": dec_deg, "slewing": bool(status.get("slewing"))}
            if pointing is None:
                self._pier_pointing.pop(key, None)
            else:
                self._pier_pointing[key] = pointing
            if on_done is not None:
                on_done()

        thread = _MountPositionThread(mount, self._window)
        thread.position.connect(done)
        self._pier_poll_thread = thread
        thread.start()

    def _track_when_slew_finishes(self: AppWindowState, mount, target=None) -> None:
        """Once the slew that was just started finishes, track at the rate the target needs
        (EQP-MNT-050) — solar for the Sun, lunar for the Moon, sidereal for everything else.

        Waiting for a slew can take minutes, so it happens on a worker thread. With no *target*
        given (the Mount page's own coordinate slews, which name nothing) the Pier's current
        object stands in, since that is what the user last said they were working on."""
        if mount is None:
            return
        if self._tracking_thread is not None:
            return          # a slew already has one waiting; the later one wins by finishing later
        target = target if target is not None else self.current_object()

        def done(rate: str) -> None:
            self._tracking_thread = None
            if rate:
                self._window.statusBar().showMessage(f"Slew finished — tracking at the {rate} rate.", 5000)

        def failed(message: str) -> None:
            self._tracking_thread = None
            logger.error("Could not start tracking after the slew: %s", message)
            self._window.statusBar().showMessage("Slew finished, but tracking could not be started — see log.", 8000)

        thread = _ResumeTrackingThread(mount, target, self._window)
        thread.done.connect(done)
        thread.failed.connect(failed)
        self._tracking_thread = thread
        thread.start()
