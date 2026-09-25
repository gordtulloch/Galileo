# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Star Atlas (planetarium) page."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _when_visible, _POINTING_POLL_MS, _SLEWING_POLL_MS, QWidget

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowStarAtlasPageMixin:
    def _build_star_atlas_page(self: AppWindowState) -> QWidget:
        """Star Atlas page: a basic planetarium (``galileo.ui.star_atlas``) with
        the time, site and display controls in the left panel and the sky view
        filling the rest. The site follows the selected Pier's Observatory."""
        import calendar
        import datetime as dt
        from PySide6.QtCore import QDateTime, Qt, QTimer
        from PySide6.QtWidgets import (
            QCheckBox, QDateTimeEdit, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout,
            QLabel, QLineEdit, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget,
        )
        from galileo.planning.sky_atlas import DSO_CATALOGS
        from galileo.ui.star_atlas import (
            StarAtlasView, format_dec, format_ra, load_display_prefs, save_display_prefs,
        )

        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        criteria, form = self._build_criteria_panel("Sky View")
        view = StarAtlasView()
        for attr, value in load_display_prefs().items():
            setattr(view, attr, set(value) if attr == "dso_catalogs" else value)

        find_edit = QLineEdit()
        find_edit.setPlaceholderText("e.g. Vega, Jupiter, M31")
        form.addRow("Find", find_edit)

        when_edit = QDateTimeEdit()
        when_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        when_edit.setTimeSpec(Qt.UTC)
        when_edit.setToolTip("Date and time shown, in UTC.")
        # The label sits on its own line so the field has the panel's full
        # width — beside the label it was too narrow to show the whole time.
        form.addRow(QLabel("Time (UTC)"))
        form.addRow(when_edit)

        step_row = QHBoxLayout()
        step_buttons = []
        for label, delta in (("−1d", dt.timedelta(days=-1)), ("−1h", dt.timedelta(hours=-1)),
                             ("+1h", dt.timedelta(hours=1)), ("+1d", dt.timedelta(days=1))):
            btn = QPushButton(label)
            btn.setToolTip(f"Step the time by {label.replace('−', '-')}")
            step_row.addWidget(btn)
            step_buttons.append((btn, delta))
        form.addRow(step_row)

        live_check = QCheckBox("Live (follow the clock)")
        live_check.setChecked(True)
        form.addRow(live_check)

        lat_spin = QDoubleSpinBox()
        lat_spin.setRange(-90.0, 90.0)
        lat_spin.setDecimals(4)
        lat_spin.setSuffix("° N")
        lon_spin = QDoubleSpinBox()
        lon_spin.setRange(-180.0, 180.0)
        lon_spin.setDecimals(4)
        lon_spin.setSuffix("° E")
        form.addRow("Latitude", lat_spin)
        form.addRow("Longitude", lon_spin)

        mag_spin = QDoubleSpinBox()
        mag_spin.setRange(0.0, 7.0)
        mag_spin.setDecimals(1)
        mag_spin.setSingleStep(0.5)
        mag_spin.setValue(view.mag_limit)
        form.addRow("Star magnitude limit", mag_spin)

        dso_mag_spin = QDoubleSpinBox()
        dso_mag_spin.setRange(0.0, 16.0)
        dso_mag_spin.setDecimals(1)
        dso_mag_spin.setValue(view.dso_mag_limit)
        form.addRow("Deep-sky magnitude limit", dso_mag_spin)

        toggles = (("Coordinate grid", "show_grid"), ("Constellation boundaries", "show_boundaries"),
                   ("Constellation outlines", "show_lines"),
                   ("Abbreviate constellation names", "abbreviate_constellations"),
                   ("Deep-sky objects", "show_dsos"),
                   ("Sun, Moon && planets", "show_bodies"), ("Labels", "show_labels"),
                   ("Ground", "show_ground"), ("Daylight sky", "daylight_sky"),
                   ("Horizon", "show_horizon"),
                   ("Telescope markers", "show_pier_markers"))
        for text, attr in toggles:
            box = QCheckBox(text)
            box.setChecked(getattr(view, attr))
            box.toggled.connect(lambda checked, a=attr: (view.set_option(a, checked), save_display_prefs(view)))
            form.addRow(box)

        status = QLabel("Loading catalogs…")
        status.setObjectName("StatusHint")
        status.setWordWrap(True)
        form.addRow(status)

        # Deep-sky catalogs: the "+" adds one to the map, each listed catalog has a "×" to remove it.
        catalogs_header = QHBoxLayout()
        catalogs_header.addWidget(QLabel("Catalogs"))
        catalogs_header.addStretch(1)
        add_catalog_btn = QToolButton()
        add_catalog_btn.setText("+")
        add_catalog_btn.setToolTip("Add a deep-sky catalog to the map")
        catalogs_header.addWidget(add_catalog_btn)
        form.addRow(catalogs_header)
        catalog_rows = QVBoxLayout()
        catalog_rows.setSpacing(2)
        form.addRow(catalog_rows)

        def refresh_catalog_rows() -> None:
            while catalog_rows.count():
                item = catalog_rows.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
            counts = view.dso_catalog_counts()
            for cat in DSO_CATALOGS:
                if cat not in view.dso_catalogs:
                    continue
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.addWidget(QLabel(f"{cat} ({counts[cat]:,})" if counts else cat))
                row_layout.addStretch(1)
                remove = QToolButton()
                remove.setText("×")
                remove.setToolTip(f"Remove {cat} from the map")
                remove.clicked.connect(lambda _=False, c=cat: set_catalogs(view.dso_catalogs - {c}))
                row_layout.addWidget(remove)
                catalog_rows.addWidget(row)
            add_catalog_btn.setEnabled(any(c not in view.dso_catalogs for c in DSO_CATALOGS))

        def set_catalogs(chosen) -> None:
            view.set_dso_catalogs(chosen)
            save_display_prefs(view)
            refresh_catalog_rows()

        def show_catalog_menu() -> None:
            menu = QMenu(add_catalog_btn)
            for cat in DSO_CATALOGS:
                if cat not in view.dso_catalogs:
                    menu.addAction(cat, lambda c=cat: set_catalogs(view.dso_catalogs | {c}))
            menu.exec(add_catalog_btn.mapToGlobal(add_catalog_btn.rect().bottomLeft()))

        add_catalog_btn.clicked.connect(show_catalog_menu)
        refresh_catalog_rows()

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)

        heading = QLabel("Star Atlas")
        heading.setObjectName("PageTitle")
        content_layout.addWidget(heading)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(view, 1)

        details = QFrame()
        details.setObjectName("DeviceSlotPanel")
        details.setFixedWidth(230)
        details_layout = QVBoxLayout(details)
        details_form = QFormLayout()
        detail_values = {}
        for key, label in (("name", "Name"), ("type", "Type"), ("mag", "Magnitude"), ("const", "Constellation"),
                           ("ra", "RA (J2000)"), ("dec", "Dec (J2000)"), ("alt", "Altitude"), ("az", "Azimuth")):
            value = QLabel("—")
            value.setWordWrap(True)
            detail_values[key] = value
            details_form.addRow(label, value)
        details_layout.addLayout(details_form)
        hint = QLabel("Click an object to identify it. Double-click to centre and track it. "
                      "Drag to pan, scroll to zoom. Right-click for Goto and Sync.")
        hint.setObjectName("StatusHint")
        hint.setWordWrap(True)
        details_layout.addWidget(hint)
        details_layout.addStretch(1)
        body.addWidget(details)
        content_layout.addLayout(body, 1)

        layout.addWidget(criteria)
        layout.addWidget(content, 1)

        # --- wiring -----------------------------------------------------------

        def show_object(obj: dict) -> None:
            from galileo.planning.sky_atlas import constellation_for
            detail_values["name"].setText(obj["name"] + (f" ({obj['designation']})" if obj.get("designation") else ""))
            detail_values["type"].setText(obj["type"])
            detail_values["mag"].setText(f"{obj['mag']:.1f}")
            try:
                detail_values["const"].setText(constellation_for(obj["ra_deg"], obj["dec_deg"]))
            except Exception:
                logger.exception("Could not compute constellation for %s", obj["name"])
                detail_values["const"].setText("—")
            detail_values["ra"].setText(format_ra(obj["ra_deg"]))
            detail_values["dec"].setText(format_dec(obj["dec_deg"]))
            refresh_altaz()

        def refresh_altaz() -> None:
            obj = view.selected
            if obj is None:
                return
            alt, az = view._altaz_of(obj)
            detail_values["alt"].setText(f"{alt:.1f}°" + ("  (below horizon)" if alt < 0 else ""))
            detail_values["az"].setText(f"{az:.1f}°")

        def find_object() -> None:
            query = find_edit.text().strip()
            if not query:
                return
            obj = view.find(query)
            if obj is None:
                self._window.statusBar().showMessage(f"Nothing called {query!r} in the loaded catalogs.", 6000)
                return
            view.select(obj)
            view.center_on(obj)
            if obj["alt"] < 0:
                self._window.statusBar().showMessage(f"{obj['name']} is below the horizon at this time and place.", 6000)

        def set_view_time() -> None:
            view.set_time(when_edit.dateTime().toUTC().toPython().replace(tzinfo=None))

        def on_time_edited() -> None:
            live_check.setChecked(False)
            set_view_time()

        def on_step(delta: dt.timedelta) -> None:
            live_check.setChecked(False)
            when_edit.setDateTime(when_edit.dateTime().addSecs(int(delta.total_seconds())))  # -> dateTimeChanged

        def on_live(live: bool) -> None:
            when_edit.setEnabled(not live)
            for btn, _ in step_buttons:
                btn.setEnabled(not live)
            view.set_live(live)

        def sync_time_field() -> None:
            when_edit.blockSignals(True)
            when_edit.setDateTime(QDateTime.fromSecsSinceEpoch(
                calendar.timegm(view.when.replace(second=0, microsecond=0).timetuple()), Qt.UTC))
            when_edit.blockSignals(False)

        def set_site() -> None:
            view.set_location(lat_spin.value(), lon_spin.value())
            if view.selected is not None:
                refresh_altaz()

        def refresh_site() -> None:
            """Take latitude/longitude from the selected Pier's Observatory."""
            pier = self._current_pier
            if pier is None:
                return
            try:
                observatory = pier.observatory
                lat = observatory.latitude if observatory.latitude is not None else lat_spin.value()
                lon = observatory.longitude if observatory.longitude is not None else lon_spin.value()
            except Exception:
                logger.exception("Could not read the Observatory's site coordinates")
                return
            for spin, value in ((lat_spin, lat), (lon_spin, lon)):
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
            view.set_location(lat, lon)
            if lat < 0:
                view.center_on_altaz(40.0, 0.0)   # look north from the southern hemisphere

        find_edit.returnPressed.connect(find_object)
        when_edit.dateTimeChanged.connect(lambda _dt: on_time_edited())
        for btn, delta in step_buttons:
            btn.clicked.connect(lambda _checked=False, d=delta: on_step(d))
        live_check.toggled.connect(on_live)
        lat_spin.editingFinished.connect(set_site)
        lon_spin.editingFinished.connect(set_site)
        mag_spin.valueChanged.connect(lambda v: view.set_option("mag_limit", v))
        dso_mag_spin.valueChanged.connect(lambda v: view.set_option("dso_mag_limit", v))
        view.objectSelected.connect(show_object)
        view.objectSelected.connect(self._set_current_object)

        def show_context_menu(obj, global_pos) -> None:
            menu = QMenu(view)
            goto = menu.addAction("Goto")
            goto.setToolTip("Slew the current Pier's mount to this object")
            sync = menu.addAction("Sync")
            sync.setToolTip("Tell the current Pier's mount it is pointing at this object")
            menu.addSeparator()
            add_to_session = menu.addAction("Add to Session")
            add_to_session.setToolTip(
                "Create a new session pre-populated with a Target block for this object (SES-160). "
                "A plain click only selects it — this is the explicit way to build a session from it."
            )
            goto.setEnabled(obj is not None)
            sync.setEnabled(obj is not None)
            add_to_session.setEnabled(obj is not None)
            goto.triggered.connect(lambda: self._mount_to_object("goto", obj))
            sync.triggered.connect(lambda: self._mount_to_object("sync", obj))
            add_to_session.triggered.connect(
                lambda: self._add_to_session(obj["name"], obj["ra_deg"], obj["dec_deg"])
            )
            menu.exec(global_pos)

        view.contextMenuRequested.connect(show_context_menu)
        view.viewChanged.connect(lambda: (sync_time_field() if live_check.isChecked() else None, refresh_altaz()))
        def show_catalog_status(stars: int, dsos: int) -> None:
            text = f"{stars:,} stars · {dsos:,} deep-sky objects"
            offline = stars < 200 or dsos == 0 or len(view._bounds) == 0 or len(view._lines) == 0
            if offline:
                text += (" (offline — connect to the internet once to load the full star and"
                         " deep-sky catalogs, constellation boundaries and outlines)")
            status.setText(text)
            refresh_catalog_rows()

        view.catalogsLoaded.connect(show_catalog_status)

        # Telescope reticles (SKYMAP-090). The mount is polled only while this page is on
        # screen, and more often while a slew is running so the reticle keeps up with it.
        def refresh_markers() -> None:
            view.set_pier_markers(self.pier_markers())

        def poll_markers() -> None:
            self._poll_pier_pointing(on_done=refresh_markers)
            slewing = any(m.get("slewing") for m in view.pier_markers)
            marker_timer.setInterval(_SLEWING_POLL_MS if slewing else _POINTING_POLL_MS)

        marker_timer = QTimer(page)
        marker_timer.timeout.connect(_when_visible(page, poll_markers))
        marker_timer.start(_POINTING_POLL_MS)

        self._star_atlas_refresh_site = refresh_site
        self._star_atlas_set_horizon = view.set_horizon
        self._star_atlas_refresh_markers = refresh_markers
        refresh_markers()
        refresh_site()
        sync_time_field()
        on_live(True)
        view.load_catalogs()
        return page
