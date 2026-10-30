# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Press-and-hold N/S/E/W mount motion, shared by the Imaging page's nudge pad and the Mount page's jog pad.

Like KStars' mount motion widget, a button's ``pressed`` starts the axis moving and its ``released`` stops
it, so the mount moves for exactly as long as the button is held."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication

from galileo.mount_limits import jog_level_text
from galileo.ui.imaging import nudge_command

logger = logging.getLogger(__name__)


def driver_rates_shown(combo) -> bool:
    """True when *combo* lists the mount driver's own slew rates (item data = rate index) rather than
    Galileo's fixed deg/s levels (item data = deg/s)."""
    return bool(combo.property("driverRates"))


def combo_rate(combo) -> float:
    """The deg/s to send for *combo*'s choice. A driver rate is selected by index instead (see
    :func:`combo_rate_index`), so the speed is only a nonzero placeholder that gives the sign."""
    return 1.0 if driver_rates_shown(combo) else float(combo.currentData())


def combo_rate_index(combo) -> int | None:
    """The driver slew-rate index *combo* has chosen, or None when it shows the fixed levels."""
    return int(combo.currentData()) if driver_rates_shown(combo) and combo.currentIndex() >= 0 else None


def sync_rate_combo(combo, status: dict, fixed_items: list[tuple[str, float]], fixed_index: int) -> None:
    """Make *combo* mirror the mount: the driver's own labelled slew rates (``status["slew_rates"]``,
    the one it has selected is ``status["slew_rate_index"]``) as KStars' Mount module lists them, or
    *fixed_items* (``(text, deg/s)``) when the mount has none, e.g. an Alpaca mount or no mount."""
    rates = status.get("slew_rates") or None
    shown = driver_rates_shown(combo)
    combo.blockSignals(True)
    try:
        if rates:
            if not shown or [combo.itemText(i) for i in range(combo.count())] != rates:
                combo.clear()
                for index, label in enumerate(rates):
                    combo.addItem(label, index)
                combo.setProperty("driverRates", True)
                shown = False   # freshly built: take the driver's selection below
            selected = status.get("slew_rate_index")
            if selected is not None and (not shown or combo.currentIndex() != selected):
                combo.setCurrentIndex(selected)
        elif shown or combo.count() == 0:
            combo.clear()
            for text, rate in fixed_items:
                combo.addItem(text, rate)
            combo.setProperty("driverRates", False)
            combo.setCurrentIndex(fixed_index)
    finally:
        combo.blockSignals(False)


class HoldToMove(QObject):
    """Drives ``mount.move_axis`` from button press/release.

    Device calls run on one worker thread, in the order they were requested, so a release can never
    overtake its press and the Qt UI thread never blocks on the mount. A held button is also released
    if it is hidden or disabled or the application loses focus, so the mount is never left running."""

    failed = Signal(str)

    def __init__(self, get_mount: Callable[[], object], get_rate: Callable[[], float],
                 get_reversed: Callable[[], tuple], parent: QObject | None = None,
                 get_rate_index: Callable[[], int | None] | None = None) -> None:
        super().__init__(parent)
        self._get_mount = get_mount
        self._get_rate = get_rate
        self._get_rate_index = get_rate_index or (lambda: None)
        self._get_reversed = get_reversed
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mount-motion")
        self._active: dict[int, str] = {}   # axis -> direction currently being held
        self._mount: dict[int, object] = {}  # axis -> the mount that axis was started on
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._app_state_changed)

    def attach(self, button, direction: str) -> None:
        """Make *button* move the mount *direction* while it is held."""
        button.pressed.connect(lambda d=direction: self.start(d))
        button.released.connect(lambda d=direction: self.stop(d))
        button.installEventFilter(self)
        button.setProperty("holdDirection", direction)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Hide or (kind == QEvent.Type.EnabledChange and not watched.isEnabled()):
            direction = watched.property("holdDirection")
            if direction:
                self.stop(direction)
        return False

    def _app_state_changed(self, state) -> None:
        if state != Qt.ApplicationState.ApplicationActive:
            self.stop_all()

    def start(self, direction: str) -> bool:
        """Start moving *direction*; False (nothing sent) when no mount is connected."""
        mount = self._get_mount()
        if mount is None:
            return False
        rate = self._get_rate()
        index = self._get_rate_index()
        if index is not None:
            self._submit_rate(mount, index)   # the driver ignores it if already selected
        # A diagonal ("NE", "SW", ...) drives both axes at once.
        commands = [nudge_command(leg, rate, self._get_reversed()) for leg in direction]
        for axis, signed in commands:
            self._active[axis] = direction
            self._mount[axis] = mount
            self._submit(mount, axis, signed)
        logger.info("Mount: hold %s at %s", direction,
                    jog_level_text(rate) if index is None else f"driver slew rate {index}")
        return True

    def rate_combo_changed(self, combo) -> None:
        """Pass a change of *combo* on to the mount when it lists the driver's own slew rates."""
        index = combo_rate_index(combo)
        mount = self._get_mount()
        if index is not None and mount is not None:
            self._submit_rate(mount, index)

    def stop(self, direction: str) -> None:
        """Stop the axes *direction* started (a release of a stale press does nothing)."""
        for leg in direction:
            axis = 1 if leg.upper() in ("N", "S") else 0
            if self._active.get(axis) == direction:
                self._release(axis)

    def stop_all(self) -> None:
        """Stop both axes, whether or not a button is held."""
        mount = self._get_mount()
        for axis in (0, 1):
            self._active.pop(axis, None)
            target = self._mount.pop(axis, None) or mount
            if target is not None:
                self._submit(target, axis, 0.0)
        logger.info("Mount: motion stop requested")

    def _release(self, axis: int) -> None:
        direction = self._active.pop(axis)
        mount = self._mount.pop(axis, None) or self._get_mount()
        logger.info("Mount: release %s", direction)
        if mount is not None:
            self._submit(mount, axis, 0.0)

    def _submit(self, mount, axis: int, rate: float) -> None:
        self._executor.submit(self._run, mount, axis, rate)

    def _submit_rate(self, mount, index: int) -> None:
        self._executor.submit(self._run_rate, mount, index)

    def _run_rate(self, mount, index: int) -> None:
        import asyncio
        try:
            asyncio.run(mount.set_slew_rate(index))
        except Exception as exc:
            logger.exception("Mount set_slew_rate(%s) failed", index)
            self.failed.emit(str(exc))

    def _run(self, mount, axis: int, rate: float) -> None:
        import asyncio
        try:
            asyncio.run(mount.move_axis(axis, rate))
        except Exception as exc:
            logger.exception("Mount move_axis(axis=%s, rate=%s) failed", axis, rate)
            if rate:   # a failed stop has nothing further to tell the user
                self._active.pop(axis, None)
                self.failed.emit(str(exc))

    def flush(self, timeout: float = 5.0) -> None:
        """Wait for every queued command to be sent (tests, and shutdown)."""
        self._executor.submit(lambda: None).result(timeout)
