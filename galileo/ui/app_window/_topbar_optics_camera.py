# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Top bar Optics/Camera selection: optical tube and imaging-filter combos, and the multi-camera selector shown for Piers with more than one camera."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _camera_slot_label, _camera_backend_key_for_slot, _optical_tube_label, _OPTICS_SECTIONS, _CAMERA_SECTIONS
from ._threads import _FilterMoveThread

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowTopbarOpticsCameraMixin:
    def _refresh_optics_combo(self: AppWindowState) -> None:
        """Repopulate the top-bar Optics selector from the current Pier's
        saved optical tubes, and show it only on the screens that work with
        one (``_OPTICS_SECTIONS``). With no tubes defined it stays visible
        but disabled, pointing the user at where to define one."""
        from galileo.observatory import list_optical_tubes

        combo = self._optics_combo
        tubes = []
        if self._current_pier is not None:
            try:
                tubes = list_optical_tubes(self._current_pier)
            except Exception:
                logger.exception("Could not load optical tubes for Pier %r", self._current_pier.name)

        combo.blockSignals(True)
        combo.clear()
        if tubes:
            for i, tube in enumerate(tubes):
                combo.addItem(_optical_tube_label(tube, i), i)
            if not 0 <= self._active_optics_position < len(tubes):
                self._active_optics_position = 0
            combo.setCurrentIndex(self._active_optics_position)
        else:
            combo.addItem("None defined — see Equipment > Optics")
            self._active_optics_position = 0
        combo.setEnabled(bool(tubes))
        combo.blockSignals(False)

        show = self._current_primary_section in _OPTICS_SECTIONS
        combo.setVisible(show)
        self._optics_label.setVisible(show)

    def _on_optics_activated(self: AppWindowState, index: int) -> None:
        position = self._optics_combo.itemData(index)
        if position is not None:
            self._active_optics_position = position
        self._refresh_imaging_filters()

    def _active_filter_wheel(self: AppWindowState):
        """The connected filter wheel that belongs to the active optical tube, or
        ``None``. A tube with a filter wheel associated on the Optics page owns
        it. If no tube on the Pier has one associated the wheel is unassigned, so
        it is offered to whichever tube is selected; if another tube owns it,
        this one has no wheel."""
        adapter = (self._device_pages.get("filter_wheel") or {}).get("adapter")
        if adapter is None or self._current_pier is None:
            return None
        from galileo.observatory import list_optical_tubes
        try:
            tubes = list_optical_tubes(self._current_pier)
        except Exception:
            logger.exception("Could not load optical tubes for Pier %r", self._current_pier.name)
            return adapter
        def has_wheel(tube) -> bool:
            return any(key.startswith("filter_wheel:") for key in (tube.associated or []))
        tube = self.active_optical_tube()
        if tube is not None and has_wheel(tube):
            return adapter
        return None if any(has_wheel(t) for t in tubes) else adapter

    def _refresh_imaging_filters(self: AppWindowState) -> None:
        """Fill the Imaging page's Filter selector from the filter wheel that
        belongs to the active optical tube (see ``_active_filter_wheel``). The
        list is the wheel's own filter names, led by a blank for "no filter";
        with no wheel it is just the blank, and the box stays editable. Reads
        the names the adapter already holds rather than querying the device."""
        combo = getattr(self, "_imaging_filter_combo", None)
        if combo is None:
            return
        wheel = self._active_filter_wheel()
        names = [str(n) for n in (getattr(wheel, "filter_names", None) or [])] if wheel is not None else []
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(["", *names])
        position = getattr(wheel, "position", None)
        if current in names:
            combo.setCurrentText(current)
        elif isinstance(position, int) and 0 <= position < len(names):
            combo.setCurrentText(names[position])     # start on what the wheel is showing now
        combo.blockSignals(False)

    def _on_imaging_filter_activated(self: AppWindowState, _index: int = -1) -> None:
        """The user picked (or typed and confirmed) a filter on the Imaging page:
        move the active tube's wheel to that slot. Text that isn't one of the
        wheel's filters, or no wheel, leaves the box as a plain frame label. Runs
        the move on a worker thread; ``_refresh_imaging_filters`` doesn't fire
        this, so re-populating the list never moves the wheel."""
        combo = getattr(self, "_imaging_filter_combo", None)
        wheel = self._active_filter_wheel()
        if combo is None or wheel is None:
            return
        names = [str(n) for n in (getattr(wheel, "filter_names", None) or [])]
        name = combo.currentText().strip()
        if name not in names or getattr(wheel, "position", None) == names.index(name):
            return
        if self._imaging_filter_thread is not None:
            self._window.statusBar().showMessage("The filter wheel is still moving.", 4000)
            return
        index = names.index(name)

        def done() -> None:
            self._imaging_filter_thread = None
            logger.info("Filter wheel: moved to %r (#%d)", name, index)
            self._window.statusBar().showMessage(f"Filter wheel at {name}.", 4000)

        def failed(message: str) -> None:
            self._imaging_filter_thread = None
            logger.error("Filter wheel move to %r (#%d) failed: %s", name, index, message)
            self._window.statusBar().showMessage("Filter change failed — see log.", 6000)

        thread = _FilterMoveThread(wheel, index, self._window)
        thread.finished_ok.connect(done)
        thread.failed.connect(failed)
        self._imaging_filter_thread = thread
        self._window.statusBar().showMessage(f"Moving filter wheel to {name}…")
        thread.start()

    def active_optical_tube(self: AppWindowState):
        """The optical tube currently chosen in the top-bar Optics selector,
        or ``None`` if the Pier has none defined."""
        if self._current_pier is None:
            return None
        from galileo.observatory import list_optical_tubes
        try:
            tubes = list_optical_tubes(self._current_pier)
        except Exception:
            logger.exception("Could not load optical tubes for Pier %r", self._current_pier.name)
            return None
        return tubes[self._active_optics_position] if 0 <= self._active_optics_position < len(tubes) else None

    def _refresh_camera_combo(self: AppWindowState) -> None:
        """Fill the top-bar Camera selector and show it on every screen that also chooses the
        optics (``_CAMERA_SECTIONS``). It is shown even when the Pier has only one camera: the
        screens that capture frames can do nothing without it, so which camera they will use — and
        whether it is connected — has to be visible rather than inferred. With none configured it
        stays visible but disabled, pointing at where to configure one."""
        from galileo.observatory import list_device_config_slots, get_device_config

        combo = self._camera_combo
        slots: list[str] = []
        if self._current_pier is not None:
            try:
                slots = list_device_config_slots(self._current_pier, "camera")
            except Exception:
                logger.exception("Could not load camera slots for Pier %r", self._current_pier.name)

        combo.blockSignals(True)
        combo.clear()
        for slot in slots:
            label = _camera_slot_label(slot)
            cfg = None
            if self._current_pier is not None:
                try:
                    cfg = get_device_config(self._current_pier, "camera", slot=slot)
                except Exception:
                    cfg = None
            if cfg is not None and cfg.device_name:
                label = f"{label} — {cfg.device_name}"
            if self._camera_backends.get(_camera_backend_key_for_slot(slot)) is None:
                # Without this the selector looks the same whether or not the camera answered,
                # and a screen refusing to capture looks like it has no reason to.
                label = f"{label} (not connected)"
            combo.addItem(label, slot)
        if not slots:
            combo.addItem("None configured — see Equipment > Camera")

        if self._active_camera_slot not in slots:
            self._active_camera_slot = slots[0] if slots else "primary"
        idx = slots.index(self._active_camera_slot) if self._active_camera_slot in slots else -1
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

        combo.setEnabled(bool(slots))
        show = self._current_primary_section in _CAMERA_SECTIONS
        combo.setVisible(show)
        self._camera_label.setVisible(show)

    def _on_camera_activated(self: AppWindowState, index: int) -> None:
        slot = self._camera_combo.itemData(index)
        if slot:
            self._active_camera_slot = slot
