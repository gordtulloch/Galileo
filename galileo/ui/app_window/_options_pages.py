# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Options > Equipment, Guiding and Science.

* Equipment: the crash/hang watchdog (SAFE-060) — whether it is armed and its timeout. Per-device
  settings (driver, server, port, poll interval) live on each Equipment device page, saved per Pier.
* Guiding: the dither and settle parameters sent to PHD2 (GUIDE-030). Saved as they change
  (``galileo.guiding_settings``); the PHD2 host/port are saved per Pier on the Guiding screen.
* Science: Galileo's core holds no science settings; plugin-provided science tools keep their own.
"""

from __future__ import annotations

from ._common import _new_form_layout, QWidget


class AppWindowOptionsPagesMixin:
    def _build_equipment_settings_page(self) -> QWidget:
        """Options > Equipment: the watchdog (SAFE-060). Applies the next time Galileo starts."""
        from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QLabel, QVBoxLayout
        from galileo.watchdog_settings import (
            MAX_TIMEOUT_S, MIN_TIMEOUT_S, load_watchdog_settings, save_watchdog_settings,
        )

        settings = load_watchdog_settings()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Equipment settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        intro = QLabel(
            "Each device's driver, server, port and poll interval are set on its own Equipment "
            "page and saved per Pier. What is here applies to the whole application."
        )
        intro.setObjectName("StatusHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = _new_form_layout()
        form.setSpacing(8)
        layout.addLayout(form)

        enabled = QCheckBox("Enable watchdog")
        enabled.setChecked(bool(settings["enabled"]))
        enabled.setToolTip(
            "Park the mount and close the dome if Galileo itself stops responding (a crash or "
            "hang) for the timeout below (SAFE-060)."
        )
        form.addRow(enabled)

        timeout = QDoubleSpinBox()
        timeout.setRange(MIN_TIMEOUT_S, MAX_TIMEOUT_S)
        timeout.setDecimals(0)
        timeout.setSuffix(" s")
        timeout.setValue(float(settings["timeout_s"]))
        timeout.setEnabled(enabled.isChecked())
        timeout.setToolTip("How long Galileo may go without answering before the watchdog acts.")
        form.addRow("Watchdog timeout", timeout)

        hint = QLabel("Watchdog changes take effect the next time Galileo starts.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        def changed(*_args) -> None:
            settings["enabled"] = enabled.isChecked()
            settings["timeout_s"] = timeout.value()
            timeout.setEnabled(enabled.isChecked())
            save_watchdog_settings(settings)

        enabled.toggled.connect(changed)
        timeout.valueChanged.connect(changed)
        return page

    def _build_guiding_settings_page(self) -> QWidget:
        """Options > Guiding: dither and settle parameters (GUIDE-030). Apply to the next command."""
        from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QLabel, QVBoxLayout
        from galileo.guiding_settings import RANGES, load_guiding_settings, save_guiding_settings

        settings = load_guiding_settings()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Guiding settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        intro = QLabel(
            "How far PHD2 dithers between exposures, and when it considers the guide star settled "
            "again. Used by the Guiding screen's Guide and Dither buttons and by dithers in a "
            "session. PHD2's host and port are set on the Guiding screen."
        )
        intro.setObjectName("StatusHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = _new_form_layout()
        form.setSpacing(8)
        layout.addLayout(form)

        def _spin(key: str, suffix: str, decimals: int, tip: str) -> QDoubleSpinBox:
            spin = QDoubleSpinBox()
            low, high = RANGES[key]
            spin.setRange(low, high)
            spin.setDecimals(decimals)
            spin.setSuffix(suffix)
            spin.setValue(float(settings[key]))
            spin.setToolTip(tip)
            spin.valueChanged.connect(lambda v, key=key: _store(key, float(v)))
            return spin

        def _store(key: str, value) -> None:
            settings[key] = value
            save_guiding_settings(settings)

        form.addRow("Dither amount", _spin(
            "dither_amount_px", " px", 1, "The maximum distance a dither moves the guide star."))
        ra_only = QCheckBox("Dither in RA only")
        ra_only.setChecked(bool(settings["dither_ra_only"]))
        ra_only.setToolTip("Dither along Right Ascension only, leaving Declination alone.")
        ra_only.toggled.connect(lambda v: _store("dither_ra_only", bool(v)))
        form.addRow(ra_only)
        form.addRow("Settle tolerance", _spin(
            "settle_pixels", " px", 1, "The guide error must fall below this to count as settled."))
        form.addRow("Settle time", _spin(
            "settle_time_s", " s", 0, "How long the error must stay within the tolerance."))
        form.addRow("Settle timeout", _spin(
            "settle_timeout_s", " s", 0, "Give up and report a failed settle after this long."))

        hint = QLabel("Applies to the next guide or dither command. Saved for the whole application.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_science_settings_page(self) -> QWidget:
        """Options > Science: Galileo's core has no science settings of its own."""
        from PySide6.QtWidgets import QLabel, QVBoxLayout

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)
        heading = QLabel("Science settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        note = QLabel(
            "Galileo itself has no science settings. Science tools such as Variable Stars are "
            "provided by plugins and keep their settings on their own panels under Science. "
            "Install, update or remove them under Options > Plugins."
        )
        note.setObjectName("StatusHint")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page
