# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""The Star Atlas/Library 'current object' selection shared across screens (the Targets page's click-to-select and click-to-enlarge behavior)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _FULL_IMAGE_SIZE_PX

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowCurrentObjectMixin:
    def current_object(self: AppWindowState):
        """The selected Pier's current object (IMG-140), or ``None``."""
        from galileo.current_object import get_current_objects
        return get_current_objects().get(self._current_pier)

    def _set_current_object(self: AppWindowState, atlas_obj: dict) -> None:
        """A Star Atlas item was selected (any click — left, double, or right):
        it becomes the selected Pier's current object (IMG-140). Does *not*
        create a session — clicking a star only identifies/selects it
        (SKYMAP-010); a session is a deliberate, separate action the user
        takes via "Add to Session" (the Star Atlas's right-click context
        menu, or the Targets page's own button), both going through
        :meth:`_add_to_session`. This used to also auto-create a session on
        every click, which was surprising — reported as "incorrect" since a
        plain click looked identical to actually building a session."""
        from galileo.current_object import CurrentObject, get_current_objects
        if self._current_pier is None:
            self._window.statusBar().showMessage("Create a Pier to keep a current object.", 4000)
            return
        get_current_objects().set(self._current_pier, CurrentObject.from_atlas(atlas_obj))
        self._refresh_current_object()

    def _add_to_session(self: AppWindowState, name: str, ra_deg: float, dec_deg: float) -> None:
        """Create a new session pre-populated with a Target block for
        (*name*, *ra_deg*, *dec_deg*) (SES-160) — the one shared entry point
        for every explicit "Add to Session" action (the Star Atlas's
        right-click context menu, the Targets page's own button), so the two
        never drift apart. Needs the Sessions screen (Planning > Sessions) to
        have been opened at least once this run; shows a status-bar message
        rather than silently doing nothing otherwise."""
        create_session = (self._device_pages.get("sessions") or {}).get("create_session_for_target")
        if create_session is None:
            self._window.statusBar().showMessage("Add to Session needs Planning > Sessions opened first.", 6000)
            return
        create_session(str(name), float(ra_deg), float(dec_deg))
        self._window.statusBar().showMessage(f"New session created for {name}.", 4000)

    def _shared_sky_atlas(self: AppWindowState) -> SkyAtlas:
        """A single persistent ``SkyAtlas`` instance, reused across calls that
        need its *state* to actually persist — `add_to_target_list`'s own
        target-list accumulation (SKY-080) needs this, unlike the throwaway
        per-call instances the Targets-page search/filter code elsewhere in
        this file constructs, which are fine since the catalog itself is
        read-only and nothing those calls do needs to be remembered between
        one another."""
        if self._sky_atlas is None:
            from galileo.planning.sky_atlas import SkyAtlas
            self._sky_atlas = SkyAtlas()
        return self._sky_atlas

    def _select_result(self: AppWindowState, obj: DeepSkyObject) -> None:
        """"Select" (a Targets-page result tile's own action button, SKY-050):
        makes *obj* the Pier's current target (IMG-140) and also adds it to
        `SkyAtlas`'s own target list (SKY-080) — reconciling two mechanisms
        this codebase previously carried in parallel with neither calling the
        other (`TODO.md`'s former "Planning (SKY-080)" gap note). A thumbnail-
        caching failure here is never fatal to Select itself, matching every
        other place in this app where a thumbnail fetch can fail silently."""
        self._set_current_object(obj.as_sequence_target())
        import asyncio
        try:
            asyncio.run(self._shared_sky_atlas().add_to_target_list(obj))
        except Exception:
            logger.debug("Could not add %s to the target list", obj.primary_name, exc_info=True)

    def _show_full_image(self: AppWindowState, obj: DeepSkyObject) -> None:
        """Clicking a Targets-page result tile's thumbnail (SKY-080) opens a
        larger view of the same survey-image field — fetched at
        `_FULL_IMAGE_SIZE_PX`, a separate cache entry from the small 150px
        tile thumbnail (`SkyAtlas._fetch_thumbnail`'s `size_px`), not an
        upscaled copy of it, which would just look blurry this large. Shows
        the dialog immediately with a "Loading…" placeholder — the fetch
        itself is a blocking call, same as every other single-object
        thumbnail fetch in this app, but a dialog with nothing in it while
        that runs would look broken rather than just slow."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

        dialog = QDialog(self._window)
        dialog.setWindowTitle(obj.primary_name)
        layout = QVBoxLayout(dialog)
        image_label = QLabel("Loading…")
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setMinimumSize(_FULL_IMAGE_SIZE_PX, _FULL_IMAGE_SIZE_PX)
        layout.addWidget(image_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.show()
        QApplication.processEvents()

        import asyncio
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            data = asyncio.run(self._shared_sky_atlas()._fetch_thumbnail(obj, size_px=_FULL_IMAGE_SIZE_PX))
        except Exception:
            logger.exception("Could not fetch full-size image for %s", obj.primary_name)
            data = b""
        finally:
            QApplication.restoreOverrideCursor()

        pixmap = QPixmap()
        if data and pixmap.loadFromData(data) and not pixmap.isNull():
            image_label.setPixmap(pixmap)
            image_label.setText("")
        else:
            image_label.setText("No image available.")
        dialog.exec()

    def _refresh_current_object(self: AppWindowState) -> None:
        """Show the current object at the top right, and tell the Solve page what it now targets."""
        obj = self.current_object()
        self._current_object_label.setText(f"Current object: {obj.name}" if obj is not None else "Current object: none")
        solve = self._device_pages.get("solve") or {}
        if "refresh_target" in solve:
            solve["refresh_target"]()
        refresh_markers = getattr(self, "_star_atlas_refresh_markers", None)
        if refresh_markers is not None:
            refresh_markers()
