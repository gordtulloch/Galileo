# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Planning page (formerly Sky Atlas): target search/criteria panel and result cards."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import _new_form_layout, QLabel, QWidget
from ._widgets import _ClickableThumbnail

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowPlanningPageMixin:
    def _build_sky_atlas_page(self: AppWindowState) -> QWidget:
        """Planning page — the catalog lookup formerly labelled Sky Atlas
        (SKY-010 … SKY-120): search criteria on the left, one result tile
        per row filling the rest of the page — no separate details panel,
        and no grid (each row's item widget always spans the full list
        width in Qt's default list mode, so the visible, white-bordered tile
        is narrowed to ``_TILE_WIDTH_FRACTION`` of that width and
        left-aligned within its row via ``_tile_row``, rather than switching
        the list itself to a wrapping icon/grid view). Each tile carries
        everything the removed details panel used to show — name/type,
        magnitude/size/constellation/RA/Dec, rise/transit/set, and a mini
        altitude-over-the-night chart with a labelled time axis — plus a
        thumbnail for the first few (``_MAX_AUTO_THUMBNAILS`` below) and,
        rightmost, per-tile action buttons (Select/Slew To/Add to Session —
        see ``_build_result_card``), matching what Obsy's target search was
        set up to show for a Simbad hit (its ``target_query`` view plus
        ``Target.save()``'s DSS-cutout fetch, ADR-005), extended past what
        Obsy had per SKY-020/030's own requirement text.

        The altitude chart/rise-transit-set for every tile is computed in one
        batch (``SkyAtlas.altitude_charts_batch``, a single vectorized astropy
        transform) rather than per tile — computing it individually for up to
        200 results measured at ~10s, genuinely UI-blocking; batched, the same
        200 results measure at ~1s. Thumbnails stay individually fetched and
        capped, unlike the chart/rise-set data — each is a real network
        request (hips2fits), not a local computation, so the same batching
        approach doesn't apply and the existing bound still holds."""
        from PySide6.QtWidgets import (
            QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QComboBox,
            QDoubleSpinBox, QPushButton, QListWidget, QListWidgetItem,
            QApplication, QCheckBox,
        )
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
        from galileo.ui.scheduler import _AltitudeChart

        # Auto-fetched result-card thumbnails (below) are capped at this many —
        # each one is a real network request (hips2fits), and a filtered search
        # can return up to 200 matches; fetching all of them up front would
        # freeze the UI for a long time and hammer the survey-image service for
        # results the user may never scroll to. The rest of a large result set
        # still gets a card with every other detail, just without an image.
        # The altitude chart/rise-transit-set data, unlike thumbnails, is a
        # local computation (batched — see the method docstring) cheap enough
        # to compute for every card, not just the first few.
        _MAX_AUTO_THUMBNAILS = 12
        _CARD_THUMB_PX = 44
        _CARD_CHART_SIZE = (130, 74)
        # Each result tile is sized to this fraction of the results list's own
        # width, with a floor so thumbnail+text+chart+buttons still fit at a
        # narrow window size — computed per search (`_tile_width()` below),
        # not once, since the list's width isn't final until the page is
        # actually shown. Raised from 340 alongside the action buttons
        # becoming content-sized (below) rather than a too-narrow fixed
        # width, which was clipping "Add to Session".
        _TILE_WIDTH_FRACTION = 0.50
        _TILE_MIN_WIDTH_PX = 420

        def _fmt_rise_set_time(iso: str | None) -> str:
            if iso is None:
                return "—"
            import datetime as _dt
            return _dt.datetime.fromisoformat(iso).strftime("%H:%M")

        def _build_result_card(obj, rise_set_text: str, chart: dict | None) -> tuple[QWidget, QLabel]:
            """One result's card: thumbnail slot, name/type/magnitude/size/
            constellation/RA/Dec/rise-transit-set, and (rightmost) a mini
            altitude chart — everything the removed details panel used to
            show, now per card. *rise_set_text* and *chart* (this object's
            pre-batched altitude data, or ``None`` with no Observatory
            location configured) are computed once by the caller, across all
            results together, not per card. The thumbnail starts blank; the
            caller fills it in later for the first ``_MAX_AUTO_THUMBNAILS``
            cards only."""
            card = QWidget()
            card.setObjectName("ResultTile")
            card.setStyleSheet("QWidget#ResultTile { border: 1px solid white; border-radius: 4px; }")
            row = QHBoxLayout(card)
            row.setContentsMargins(6, 4, 6, 4)
            row.setSpacing(8)

            # Left: thumbnail beside name/type on one line, then the rest of
            # the details full-width below — makes better use of a narrow
            # tile's width than a single thumb-then-text row would.
            left_col = QVBoxLayout()
            left_col.setSpacing(2)

            top_row = QHBoxLayout()
            top_row.setSpacing(6)
            thumb_label = _ClickableThumbnail()
            thumb_label.setFixedSize(_CARD_THUMB_PX, _CARD_THUMB_PX)
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_label.setObjectName("DeviceSlotPanel")
            thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
            thumb_label.setToolTip("Click for a full-size view.")
            thumb_label.clicked.connect(lambda o=obj: self._show_full_image(o))
            top_row.addWidget(thumb_label)
            name_label = QLabel(f"{obj.primary_name} · {obj.object_type.value}")
            name_label.setObjectName("PageSubtitle")
            name_label.setWordWrap(True)
            top_row.addWidget(name_label, 1)
            left_col.addLayout(top_row)

            try:
                from galileo.planning.sky_atlas import constellation_for
                constellation = constellation_for(obj.ra_deg, obj.dec_deg)
            except Exception:
                logger.debug("Could not compute constellation for %s", obj.primary_name, exc_info=True)
                constellation = "—"
            mag_text = f"mag {obj.magnitude:.1f}" if obj.magnitude < 90.0 else "mag unknown"
            size_text = f"  ·  {obj.size_arcmin:.1f}′" if obj.size_arcmin > 0 else ""
            subtitle_label = QLabel(
                f"{mag_text}{size_text}  ·  {constellation}  ·  RA {obj.ra_deg:.3f}°  Dec {obj.dec_deg:.3f}°"
            )
            subtitle_label.setObjectName("StatusHint")
            subtitle_label.setWordWrap(True)
            left_col.addWidget(subtitle_label)

            rise_set_label = QLabel(rise_set_text)
            rise_set_label.setObjectName("StatusHint")
            rise_set_label.setWordWrap(True)
            left_col.addWidget(rise_set_label)
            left_col.addStretch(1)
            row.addLayout(left_col, 1)

            chart_widget = _AltitudeChart()
            chart_widget.setFixedSize(*_CARD_CHART_SIZE)
            if chart is not None and chart.get("altitudes"):
                chart_widget.set_data(chart["times"], chart["altitudes"])
            row.addWidget(chart_widget)

            # Rightmost: this result's own action buttons — select it as the
            # Pier's current target, slew the mount straight to it, or spin
            # up a brand-new session pre-populated with a Target block for it.
            button_col = QVBoxLayout()
            button_col.setSpacing(4)
            select_btn = QPushButton("Select")
            select_btn.setToolTip("Make this the Pier's current object (IMG-140) — captured frames "
                                  "are named after it, and Solve's Slew to Target slews to it — and "
                                  "add it to the target list (SKY-080).")
            select_btn.clicked.connect(lambda _=None, o=obj: self._select_result(o))
            button_col.addWidget(select_btn)

            slew_btn = QPushButton("Slew To")
            slew_btn.setToolTip("Immediately slew the connected mount to this object.")
            slew_btn.clicked.connect(lambda _=None, o=obj: _slew_to_result(o))
            button_col.addWidget(slew_btn)

            session_btn = QPushButton("Add to Session")
            session_btn.setToolTip("Create a new session pre-populated with a Target block for this "
                                   "object (SES-160).")
            session_btn.clicked.connect(lambda _=None, o=obj: _add_result_to_new_session(o))
            button_col.addWidget(session_btn)
            button_col.addStretch(1)

            # Size every button to fit its own text (a hardcoded fixed width previously clipped
            # "Add to Session", the longest label) — all three made uniform to the widest one's
            # actual sizeHint, not a guessed constant, so this stays correct across fonts/platforms.
            button_width = max(b.sizeHint().width() for b in (select_btn, slew_btn, session_btn))
            for b in (select_btn, slew_btn, session_btn):
                b.setFixedWidth(button_width)

            row.addLayout(button_col)

            return card, thumb_label

        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        criteria, form = self._build_criteria_panel("Search Criteria")

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("e.g. M31")
        form.addRow("Object name", name_edit)

        type_combo = QComboBox()
        type_combo.addItem("Any")
        try:
            from galileo.planning.sky_atlas import ObjectType
            for t in ObjectType:
                type_combo.addItem(t.value)
        except ImportError:
            pass
        form.addRow("Object type", type_combo)

        catalog_checks: dict = {}
        catalog_row = QHBoxLayout()
        try:
            from galileo.planning.sky_atlas import DSO_CATALOGS
            for cat in DSO_CATALOGS:
                cb = QCheckBox(cat)
                catalog_checks[cat] = cb
                catalog_row.addWidget(cb)
        except ImportError:
            pass
        catalog_row_widget = QWidget()
        catalog_row_widget.setLayout(catalog_row)
        catalog_row_widget.setToolTip(
            "None checked = every catalog. Any checked = only objects belonging to at least one "
            "of them — the same Messier/Caldwell/NGC membership the Star Atlas's own catalog "
            "overlay toggles use."
        )
        form.addRow("Catalog", catalog_row_widget)

        max_mag = QDoubleSpinBox()
        max_mag.setRange(-5.0, 30.0)
        max_mag.setValue(99.0)
        form.addRow("Max magnitude", max_mag)

        min_size = QDoubleSpinBox()
        min_size.setRange(0.0, 500.0)
        min_size.setSuffix(" arcmin")
        form.addRow("Min size", min_size)

        max_size = QDoubleSpinBox()
        max_size.setRange(0.0, 500.0)
        max_size.setSuffix(" arcmin")
        max_size.setSpecialValueText("No max")
        form.addRow("Max size", max_size)

        visible_tonight_check = QCheckBox("Visible tonight")
        visible_tonight_check.setToolTip(
            "Needs the current Observatory's latitude/longitude set (top bar); ignored otherwise."
        )
        form.addRow(visible_tonight_check)

        min_altitude = QDoubleSpinBox()
        min_altitude.setRange(0.0, 90.0)
        min_altitude.setValue(20.0)
        min_altitude.setSuffix(" °")
        min_altitude.setToolTip("Only used when Visible tonight is checked (SKY-020).")
        form.addRow("Reach an altitude of", min_altitude)

        min_duration = QDoubleSpinBox()
        min_duration.setRange(0.0, 12.0)
        min_duration.setSuffix(" hr")
        min_duration.setSpecialValueText("Any moment")
        min_duration.setToolTip(
            "How long it must stay at/above that altitude, continuously — \"Any moment\" (0) just "
            "needs one moment tonight, matching the original Visible tonight check. Only used when "
            "Visible tonight is checked (SKY-020)."
        )
        form.addRow("...for at least", min_duration)

        min_moon_sep = QDoubleSpinBox()
        min_moon_sep.setRange(0.0, 180.0)
        min_moon_sep.setSuffix(" °")
        min_moon_sep.setSpecialValueText("No minimum")
        min_moon_sep.setToolTip(
            "Excludes anything closer to the Moon than this, at local midnight tonight (SKY-020) — "
            "needs the current Observatory's latitude/longitude set (top bar); ignored otherwise."
        )
        form.addRow("Min. Moon separation", min_moon_sep)

        search_btn = QPushButton("Search")
        search_btn.setObjectName("AccentButton")
        form.addRow(search_btn)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)

        heading = QLabel("Planning")
        heading.setObjectName("PageTitle")
        content_layout.addWidget(heading)

        results = QListWidget()
        results.setSpacing(4)
        results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content_layout.addWidget(results, 1)

        def _tile_row(card: QWidget) -> tuple[QWidget, object]:
            """Wrap *card* in a full-row container so results stay one
            per row (a plain vertical list, not a grid), while the visible
            tile itself is narrowed to ``_TILE_WIDTH_FRACTION`` of the
            results list's own width (floored at ``_TILE_MIN_WIDTH_PX`` so
            thumbnail/text/chart still fit at a narrow window) and left-
            aligned — a ``QListWidget`` row's item widget otherwise always
            stretches to the full viewport width regardless of the card's
            own size, so narrowing the card alone (without this wrapper)
            has no visible effect."""
            from PySide6.QtCore import QSize
            width = max(_TILE_MIN_WIDTH_PX, int(results.viewport().width() * _TILE_WIDTH_FRACTION))
            card.setFixedWidth(width)
            row_container = QWidget()
            row_layout = QHBoxLayout(row_container)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(card)
            row_layout.addStretch(1)
            return row_container, QSize(results.viewport().width(), card.sizeHint().height())

        def _current_location():
            """The active Observatory's location (top-bar selector), for
            visibility filtering and each card's altitude chart/rise-
            transit-set (SKY-020/SKY-030) — ``None`` when no Observatory is
            selected or it has no latitude/longitude configured yet."""
            obs = getattr(self, "_current_observatory", None)
            if obs is None or getattr(obs, "latitude", None) is None or getattr(obs, "longitude", None) is None:
                return None
            from galileo.planning.visibility import ObservingLocation
            return ObservingLocation(
                name=getattr(obs, "name", ""), latitude=obs.latitude, longitude=obs.longitude,
                timezone=getattr(obs, "timezone", None) or "UTC",
            )

        def _slew_to_result(obj) -> None:
            """"Slew To" (a result tile's own action button): immediately
            command the connected mount to this object, via the same
            ``_mount_to_object`` the Star Atlas/skymap's own slew-to-clicked-
            location uses (SKYMAP-060) — needs the current altitude (its
            below-horizon guard) computed fresh for *now*, the same
            precess-then-horizontal-transform technique
            ``galileo.ui.star_atlas``'s live renderer already uses."""
            location = _current_location()
            if location is None:
                self._window.statusBar().showMessage(
                    "Slew To needs the Observatory's latitude/longitude set (top bar).", 5000)
                return
            import datetime as _dt
            from galileo.planning import star_atlas as sa
            jd = sa.julian_date(_dt.datetime.now(_dt.UTC))
            lst = sa.local_sidereal_deg(jd, location.longitude)
            ra_of_date, dec_of_date = sa.precess_from_j2000(obj.ra_deg, obj.dec_deg, jd)
            alt, _az = sa.equatorial_to_horizontal(ra_of_date, dec_of_date, lst, location.latitude)
            target = obj.as_sequence_target()
            target["alt"] = float(alt)
            self._mount_to_object("goto", target)

        def _add_result_to_new_session(obj) -> None:
            """"Add to Session" (a result tile's own action button, SES-160) —
            goes through the shared :meth:`AppWindow._add_to_session`, the same
            entry point the Star Atlas's right-click context menu action uses,
            so the two never drift apart."""
            self._add_to_session(obj.primary_name, obj.ra_deg, obj.dec_deg)

        def run_search() -> None:
            import asyncio
            results.clear()
            self._window.statusBar().showMessage("Searching…")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            location = _current_location()
            try:
                from galileo.planning.sky_atlas import SkyAtlas, ObjectType
                atlas = SkyAtlas()
                name = name_edit.text().strip()
                if name:
                    matches = asyncio.run(atlas.search_online(name))
                else:
                    object_types = None
                    if type_combo.currentText() != "Any":
                        object_types = [ObjectType(type_combo.currentText())]
                    if (visible_tonight_check.isChecked() or min_moon_sep.value() > 0) and location is None:
                        self._window.statusBar().showMessage(
                            "Visible tonight/Moon separation need the Observatory's latitude/longitude "
                            "set (top bar) — showing all matches instead.", 6000)
                    selected_catalogs = {cat for cat, cb in catalog_checks.items() if cb.isChecked()} or None
                    matches = atlas.filter(
                        object_types=object_types,
                        max_magnitude=max_mag.value(),
                        min_size_arcmin=min_size.value(),
                        max_size_arcmin=max_size.value(),
                        location=location,
                        visible_tonight=visible_tonight_check.isChecked() and location is not None,
                        min_altitude_deg=min_altitude.value(),
                        min_duration_hours=min_duration.value(),
                        min_moon_separation_deg=min_moon_sep.value(),
                        catalogs=selected_catalogs,
                    )
            except Exception:
                logger.exception("Sky Atlas search failed")
                results.addItem("Search failed — see log for details.")
                self._window.statusBar().showMessage("Planning search failed — see log.", 6000)
                return
            finally:
                QApplication.restoreOverrideCursor()
            if not matches:
                results.addItem("No matching objects.")
                self._window.statusBar().showMessage("No matching objects.", 4000)
                return

            shown = matches[:200]

            # One batched astropy transform for every card's altitude chart,
            # not one per card (~1s for 200 vs. ~10s individually — see the
            # method docstring). rise/transit/set for each is then read off
            # its own already-computed chart, not recalculated.
            charts: list = [None] * len(shown)
            rise_set_texts = ["Set an Observatory location (top bar) for rise/transit/set."] * len(shown)
            if location is not None:
                self._window.statusBar().showMessage(f"Found {len(matches)} object(s) — computing altitude charts…")
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    charts = atlas.altitude_charts_batch(shown, location)
                    for i, (obj, chart) in enumerate(zip(shown, charts)):
                        if not chart.get("altitudes"):
                            rise_set_texts[i] = "Rise/transit/set unavailable."
                            continue
                        try:
                            rts = atlas.rise_transit_set(obj, location, chart=chart)
                            rise_set_texts[i] = (
                                f"Rise {_fmt_rise_set_time(rts['rise'])}  "
                                f"Transit {_fmt_rise_set_time(rts['transit'])}  "
                                f"Set {_fmt_rise_set_time(rts['set'])} UTC"
                            )
                        except Exception:
                            logger.debug("Could not compute rise/transit/set for %s", obj.primary_name, exc_info=True)
                            rise_set_texts[i] = "Rise/transit/set unavailable."
                except Exception:
                    logger.exception("Could not batch-compute altitude charts")
                    charts = [None] * len(shown)
                finally:
                    QApplication.restoreOverrideCursor()

            thumb_labels = []
            for obj, rise_set_text, chart in zip(shown, rise_set_texts, charts):
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, obj)
                card, thumb_label = _build_result_card(obj, rise_set_text, chart)
                row_container, size_hint = _tile_row(card)
                item.setSizeHint(size_hint)
                results.addItem(item)
                results.setItemWidget(item, row_container)
                thumb_labels.append(thumb_label)
            self._window.statusBar().showMessage(f"Found {len(matches)} object(s).", 4000)

            # Fill in the first few cards' thumbnails now (bounded — see
            # _MAX_AUTO_THUMBNAILS above, a real network request each); the
            # rest still show every other detail, just without an image.
            if thumb_labels:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    for obj, thumb_label in zip(shown[:_MAX_AUTO_THUMBNAILS], thumb_labels):
                        try:
                            data = asyncio.run(atlas._fetch_thumbnail(obj))
                        except Exception:
                            logger.debug("Could not fetch card thumbnail for %s", obj.primary_name, exc_info=True)
                            continue
                        pixmap = QPixmap()
                        if data and pixmap.loadFromData(data) and not pixmap.isNull():
                            thumb_label.setPixmap(pixmap.scaled(
                                _CARD_THUMB_PX, _CARD_THUMB_PX, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
                            ))
                finally:
                    QApplication.restoreOverrideCursor()

        search_btn.clicked.connect(run_search)
        name_edit.returnPressed.connect(run_search)

        layout.addWidget(criteria)
        layout.addWidget(content, 1)
        return page

    def _build_criteria_panel(self: AppWindowState, heading: str):
        """A fixed-width form panel holding search/input criteria, used
        instead of a secondary icon column (Planning, Star Atlas)."""
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

        panel = QWidget()
        panel.setObjectName("CriteriaPanel")
        panel.setFixedWidth(260)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(14, 16, 14, 16)
        outer.setSpacing(10)

        title = QLabel(heading)
        title.setObjectName("CriteriaHeading")
        outer.addWidget(title)

        form = _new_form_layout()
        form.setSpacing(8)
        outer.addLayout(form)
        outer.addStretch(1)
        return panel, form
