# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""What's Up Tonight page (WUT-010 … WUT-100): a ranked recommendation layer
on top of the Targets page's catalog, not a second catalog or search screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from ._common import QWidget
from ._widgets import _ClickableThumbnail

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState

# Bounds the (cheap, magnitude/type-only) pre-filter passed into
# galileo.planning.recommend.compute_observability, which -- unlike
# SkyAtlas.filter's own magnitude/type/catalog checks -- calls
# astropy's altitude_chart per object; the same "bound before the
# expensive per-object computation" precedent _planning_page.py's own
# up-to-200-shown cap already sets, just applied earlier here since
# ranking (unlike a plain search) always touches every pre-filtered object.
_MAX_CANDIDATES = 300
_MAX_SHOWN = 50
# Same bound as the Targets page's own auto-thumbnail fill-in
# (_planning_page.py). Unlike a plain disk-cache read (applied to every shown
# tile, unbounded — see run_rank() below), a genuine network fetch is a real
# hips2fits request per uncached object, so only *that* part of the fill-in
# is capped, to keep a ranking run from firing up to _MAX_SHOWN (50) requests.
_MAX_AUTO_THUMBNAILS = 12


class AppWindowWhatsUpPageMixin:
    def _build_whats_up_page(self: AppWindowState) -> QWidget:
        """What's Up Tonight — one ranked tile per recommended object, reusing
        the Targets page's own tile/action-button pattern (``_build_sky_atlas_page``,
        Section 4.8) rather than a new one: a "why this ranking" line
        (``Recommendation.reasons``, WUT-020), a confidence badge shown only
        when inputs were incomplete (WUT-030), a prior-integration annotation
        when the Library has one (WUT-050, display only — never affects
        ordering), and the same Select / Slew To / Add to Session buttons
        (WUT-060). An observing-date picker (WUT-090, default today) and a
        weather/aurora/smoke advisory summary line (WUT-100, shown only for
        today — see ``_fetch_advisories`` below) sit in the criteria panel."""
        from PySide6.QtWidgets import (
            QApplication, QCheckBox, QDateEdit, QDoubleSpinBox, QHBoxLayout,
            QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
        )
        from PySide6.QtCore import Qt, QDate
        from galileo.ui.scheduler import _AltitudeChart

        _CARD_THUMB_PX = 44
        _CARD_CHART_SIZE = (130, 74)
        _TILE_WIDTH_FRACTION = 0.55
        _TILE_MIN_WIDTH_PX = 460

        def _current_location():
            """Same convention as the Targets page (``_planning_page.py``):
            the active Observatory's location, or ``None`` with none
            configured/no lat-long set yet."""
            obs = getattr(self, "_current_observatory", None)
            if obs is None or getattr(obs, "latitude", None) is None or getattr(obs, "longitude", None) is None:
                return None
            from galileo.planning.visibility import ObservingLocation
            loc = ObservingLocation(
                name=getattr(obs, "name", ""), latitude=obs.latitude, longitude=obs.longitude,
                timezone=getattr(obs, "timezone", None) or "UTC",
            )
            from galileo.observatory import list_horizon_points
            try:
                points = list_horizon_points(obs)
            except Exception:
                points = []
            if points:
                from galileo.planning.visibility import HorizonProfile
                loc.set_horizon(HorizonProfile(points=list(points)))
            return loc

        def _optical_train_for_fit():
            """The active optical tube (Equipment > Optics, PROF-100) plus
            its associated camera's sensor geometry (a ``DeviceConfigRecord``,
            PROF-120), bridged into the plain ``OpticalTrain`` shape
            ``galileo.planning.recommend`` expects (WUT-010) — keeps that
            domain-core module decoupled from the Optics/DeviceConfig
            persistence models, consistent with the ports-and-adapters rule
            (no persistence import in domain core)."""
            tube = self.active_optical_tube()
            if tube is None:
                return None
            from galileo.equipment.profiles import OpticalTrain
            camera_dict: dict = {}
            camera_slot = next(
                (key.split(":", 1)[1] for key in (getattr(tube, "associated", None) or [])
                 if key.startswith("camera:")),
                None,
            )
            if camera_slot and self._current_pier is not None:
                from galileo.observatory import get_device_config
                try:
                    cfg = get_device_config(self._current_pier, "camera", slot=camera_slot)
                except Exception:
                    cfg = None
                if cfg is not None:
                    camera_dict = {
                        "pixel_size_um": cfg.pixel_size_um or 0.0,
                        "sensor_width_px": cfg.sensor_width_px or 0,
                        "sensor_height_px": cfg.sensor_height_px or 0,
                    }
            return OpticalTrain(
                name=getattr(tube, "name", "") or "",
                focal_length_mm=getattr(tube, "focal_length_mm", 0.0) or 0.0,
                aperture_mm=getattr(tube, "aperture_mm", 0.0) or 0.0,
                camera=camera_dict,
            )

        def _imager_fov_arcmin(train) -> tuple[float, float] | None:
            """The active train's imaged field of view (width, height, arcmin)
            from the same plate-scale/sensor-geometry inputs
            ``recommend._fit_for_train`` already uses for its field-of-view
            fit check (WUT-010) — display only, not fed back into ranking.
            ``None`` with no train, or no camera pixel-size/sensor-geometry
            configured for it, so the caller can show a clear "not
            configured" message instead of a bogus 0′ × 0′."""
            if train is None:
                return None
            plate_scale = getattr(train, "plate_scale_arcsec_px", 0.0)
            camera = getattr(train, "camera", None) or {}
            width_px = camera.get("sensor_width_px", 0)
            height_px = camera.get("sensor_height_px", 0)
            if not (plate_scale and width_px and height_px):
                return None
            return (width_px * plate_scale / 60.0, height_px * plate_scale / 60.0)

        def _fetch_advisories(night_date: str) -> tuple[dict | None, float | None, float | None]:
            """Weather forecast / aurora Kp / smoke AQI for *night_date*
            (WUT-100), each ``None`` when unavailable. Only fetched for
            today: the Open-Meteo forecast client has no historical/future-
            date support (``forecast_days=1``), and there is no concrete
            aurora/smoke client wired in yet (``SAFE-090``/``SAFE-100`` are
            P3, not yet implemented) — so any other date, and every
            advisory, is simply "unavailable for this date," which is
            exactly WUT-030's existing missing-data degradation, not a
            special case. Reuses ``galileo.safety.SafetyMonitorService``
            (not a second weather/aurora/smoke path) so this starts
            returning real aurora/smoke data the moment those clients are
            wired up elsewhere, with no change needed here. Passes this
            page's own Observatory location into ``get_forecast_advisory``
            (fixed alongside this docstring — it previously called the
            client with no coordinates at all, silently fetching the
            Gulf-of-Guinea forecast, lat/lon 0,0, for every Observatory)."""
            import datetime as _dt
            if night_date != _dt.date.today().isoformat():
                return None, None, None
            location = _current_location()
            if location is None:
                return None, None, None
            import asyncio
            from galileo.safety import OpenMeteoClient, SafetyMonitorService
            service = SafetyMonitorService()
            service.set_forecast_client(OpenMeteoClient())
            try:
                forecast = asyncio.run(service.get_forecast_advisory(location.latitude, location.longitude))
            except Exception:
                logger.debug("Weather forecast advisory unavailable", exc_info=True)
                forecast = None
            try:
                aurora = asyncio.run(service.get_aurora_advisory())
            except Exception:
                logger.debug("Aurora advisory unavailable", exc_info=True)
                aurora = None
            try:
                smoke = asyncio.run(service.get_smoke_advisory())
            except Exception:
                logger.debug("Smoke advisory unavailable", exc_info=True)
                smoke = None
            return forecast, aurora, smoke

        def _weather_summary_text(forecast: dict | None) -> str:
            """A short cloud-cover/precipitation/wind summary from the raw
            Open-Meteo forecast blob (``OpenMeteoClient.get_forecast``'s
            hourly arrays over the ``forecast_days=1`` window), instead of
            just "available" — a planning aid only (`SAFE-050`), so this
            never affects ranking, only what the advisory line says. Degrades
            to "no data"/"no usable detail" on anything missing or malformed
            rather than raising, matching this whole advisory path's
            never-block-ranking contract."""
            if not forecast:
                return "Weather: no data for this date"
            try:
                hourly = forecast.get("hourly") or {}
                cloud = [v for v in (hourly.get("cloudcover") or []) if v is not None]
                precip = [v for v in (hourly.get("precipitation") or []) if v is not None]
                wind = [v for v in (hourly.get("windspeed_10m") or []) if v is not None]
            except Exception:
                logger.debug("Could not parse weather forecast for summary", exc_info=True)
                return "Weather: available (no usable detail)"
            if not (cloud or precip or wind):
                return "Weather: available (no usable detail)"
            bits = []
            if cloud:
                bits.append(f"cloud cover avg {sum(cloud) / len(cloud):.0f}% (peak {max(cloud):.0f}%)")
            if precip:
                bits.append(f"precip total {sum(precip):.1f}mm")
            if wind:
                bits.append(f"wind up to {max(wind):.0f} km/h")
            return "Weather: " + ", ".join(bits)

        def _aurora_summary_text(kp: float | None) -> str:
            """Kp index plus its standard activity-level band (0-9 scale:
            quiet below 3, unsettled/active 3-5, storm at/above 5) — a fixed
            reference table, not a Galileo-specific judgment call."""
            if kp is None:
                return "Aurora: no data for this date"
            if kp < 3.0:
                level = "quiet"
            elif kp < 5.0:
                level = "unsettled/active"
            else:
                level = "storm"
            return f"Aurora Kp {kp:.1f} ({level})"

        def _smoke_summary_text(aqi: float | None) -> str:
            """Smoke/transparency AQI plus its standard EPA category band."""
            if aqi is None:
                return "Smoke: no data for this date"
            if aqi <= 50:
                level = "good"
            elif aqi <= 100:
                level = "moderate"
            elif aqi <= 150:
                level = "unhealthy for sensitive groups"
            elif aqi <= 200:
                level = "unhealthy"
            elif aqi <= 300:
                level = "very unhealthy"
            else:
                level = "hazardous"
            return f"Smoke AQI {aqi:.0f} ({level})"

        def _confidence_tooltip(rec) -> str:
            o = rec.observability
            missing = []
            if not o.horizon_applied:
                missing.append("no horizon profile configured for this location")
            if not o.weather_available:
                missing.append("no weather forecast for this date")
            if not o.aurora_available:
                missing.append("no aurora estimate for this date")
            if not o.smoke_available:
                missing.append("no smoke/transparency estimate for this date")
            if o.moon_separation_deg is None:
                missing.append("Moon position unavailable")
            return "Reduced confidence — " + "; ".join(missing) if missing else "All inputs available."

        def _slew_to_result(obj) -> None:
            """Same technique as the Targets page's own Slew To (SKYMAP-060):
            a fresh below-horizon guard computed for *now*, not for the
            selected planning date — slewing always happens now, regardless
            of which night was being planned."""
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
            self._add_to_session(obj.primary_name, obj.ra_deg, obj.dec_deg)

        def _build_tile(rank: int, rec, chart: dict | None) -> tuple[QWidget, QLabel]:
            obj = rec.obj
            card = QWidget()
            card.setObjectName("ResultTile")
            card.setStyleSheet("QWidget#ResultTile { border: 1px solid white; border-radius: 4px; }")
            row = QHBoxLayout(card)
            row.setContentsMargins(6, 4, 6, 4)
            row.setSpacing(8)

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
            name_label = QLabel(f"#{rank}  {obj.primary_name} · {obj.object_type.value}")
            name_label.setObjectName("PageSubtitle")
            name_label.setWordWrap(True)
            top_row.addWidget(name_label, 1)
            if rec.confidence.value == "reduced":
                badge = QLabel("Reduced confidence")
                badge.setObjectName("StatusHint")
                badge.setToolTip(_confidence_tooltip(rec))
                top_row.addWidget(badge)
            left_col.addLayout(top_row)

            mag_text = f"mag {obj.magnitude:.1f}" if obj.magnitude < 90.0 else "mag unknown"
            size_text = f"  ·  {obj.size_arcmin:.1f}′" if obj.size_arcmin > 0 else ""
            subtitle = QLabel(f"{mag_text}{size_text}  ·  best {rec.observability.max_altitude_deg:.0f}° tonight")
            subtitle.setObjectName("StatusHint")
            subtitle.setWordWrap(True)
            left_col.addWidget(subtitle)

            reasons_label = QLabel("Why: " + "; ".join(rec.reasons))
            reasons_label.setObjectName("StatusHint")
            reasons_label.setWordWrap(True)
            left_col.addWidget(reasons_label)

            if rec.prior_integration_hours is not None:
                prior_label = QLabel(f"{rec.prior_integration_hours:.1f}h already integrated")
                prior_label.setObjectName("StatusHint")
                left_col.addWidget(prior_label)

            left_col.addStretch(1)
            row.addLayout(left_col, 1)

            chart_widget = _AltitudeChart()
            chart_widget.setFixedSize(*_CARD_CHART_SIZE)
            if chart is not None and chart.get("altitudes"):
                chart_widget.set_data(chart["times"], chart["altitudes"])
            row.addWidget(chart_widget)

            button_col = QVBoxLayout()
            button_col.setSpacing(4)
            select_btn = QPushButton("Select")
            select_btn.setToolTip("Make this the Pier's current object (IMG-140) and add it to the target list.")
            select_btn.clicked.connect(lambda _=None, o=obj: self._select_result(o))
            button_col.addWidget(select_btn)

            slew_btn = QPushButton("Slew To")
            slew_btn.setToolTip("Immediately slew the connected mount to this object.")
            slew_btn.clicked.connect(lambda _=None, o=obj: _slew_to_result(o))
            button_col.addWidget(slew_btn)

            session_btn = QPushButton("Add to Session")
            session_btn.setToolTip("Create a new session pre-populated with a Target block for this object (SES-160).")
            session_btn.clicked.connect(lambda _=None, o=obj: _add_result_to_new_session(o))
            button_col.addWidget(session_btn)
            button_col.addStretch(1)

            button_width = max(b.sizeHint().width() for b in (select_btn, slew_btn, session_btn))
            for b in (select_btn, slew_btn, session_btn):
                b.setFixedWidth(button_width)
            row.addLayout(button_col)

            return card, thumb_label

        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        criteria, form = self._build_criteria_panel("What's Up Tonight")

        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        date_edit.setDate(QDate.currentDate())
        date_edit.setToolTip(
            "Plan a night other than tonight (WUT-090) — sky state is recomputed for this date; "
            "weather/aurora/smoke advisories (WUT-100) are only available for today."
        )
        form.addRow("Observing date", date_edit)

        max_mag = QDoubleSpinBox()
        max_mag.setRange(-5.0, 30.0)
        max_mag.setValue(14.0)
        max_mag.setToolTip("Pre-filter before ranking, so a full 10,000+-object catalog isn't ranked every time.")
        form.addRow("Max candidate magnitude", max_mag)

        min_altitude = QDoubleSpinBox()
        min_altitude.setRange(0.0, 90.0)
        min_altitude.setValue(20.0)
        min_altitude.setSuffix(" °")
        form.addRow("Min. altitude", min_altitude)

        # Stacked, not side by side — see _planning_page.py's identical fix:
        # three checkboxes abreast don't fit this panel's fixed 260px width
        # once AllNonFixedFieldsGrow forces this field widget that narrow.
        catalog_checks: dict = {}
        catalog_row = QVBoxLayout()
        catalog_row.setSpacing(2)
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
        catalog_row_widget.setToolTip("None checked = every catalog.")
        form.addRow("Catalog", catalog_row_widget)

        rank_btn = QPushButton("Rank Tonight")
        rank_btn.setObjectName("AccentButton")
        form.addRow(rank_btn)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)

        heading = QLabel("What's Up Tonight")
        heading.setObjectName("PageTitle")
        content_layout.addWidget(heading)

        fov_label = QLabel("")
        fov_label.setObjectName("StatusHint")
        fov_label.setWordWrap(True)
        content_layout.addWidget(fov_label)

        advisory_label = QLabel("")
        advisory_label.setObjectName("StatusHint")
        advisory_label.setWordWrap(True)
        content_layout.addWidget(advisory_label)

        results = QListWidget()
        results.setSpacing(4)
        results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content_layout.addWidget(results, 1)

        def _tile_row(card: QWidget):
            from PySide6.QtCore import QSize
            width = max(_TILE_MIN_WIDTH_PX, int(results.viewport().width() * _TILE_WIDTH_FRACTION))
            card.setFixedWidth(width)
            row_container = QWidget()
            row_layout = QHBoxLayout(row_container)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(card)
            row_layout.addStretch(1)
            return row_container, QSize(results.viewport().width(), card.sizeHint().height())

        def run_rank() -> None:
            results.clear()
            fov_label.setText("")
            advisory_label.setText("")
            self._window.statusBar().showMessage("Ranking…")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                from galileo.planning.sky_atlas import SkyAtlas
                from galileo.planning.recommend import rank_tonight
                from galileo.library import prior_integration_hours

                location = _current_location()
                if location is None:
                    results.addItem("Set the active Observatory's latitude/longitude (top bar) first.")
                    self._window.statusBar().showMessage(
                        "What's Up Tonight needs an Observatory location.", 6000)
                    return

                night_date = date_edit.date().toString(Qt.DateFormat.ISODate)
                atlas = SkyAtlas()
                selected_catalogs = {cat for cat, cb in catalog_checks.items() if cb.isChecked()} or None
                candidates = atlas.filter(max_magnitude=max_mag.value(), catalogs=selected_catalogs)
                candidates = candidates[:_MAX_CANDIDATES]

                forecast, aurora, smoke = _fetch_advisories(night_date)
                if forecast or aurora is not None or smoke is not None:
                    parts = [
                        _weather_summary_text(forecast),
                        _aurora_summary_text(aurora),
                        _smoke_summary_text(smoke),
                    ]
                    advisory_label.setText("  ·  ".join(parts))
                else:
                    advisory_label.setText(
                        "Weather/aurora/smoke advisories are only available for today's date.")

                train = _optical_train_for_fit()
                fov = _imager_fov_arcmin(train)
                if fov is not None:
                    train_name = getattr(train, "name", "") or "active train"
                    fov_label.setText(f"Ranking for {train_name}'s field of view: {fov[0]:.1f}′ × {fov[1]:.1f}′")
                elif train is not None:
                    fov_label.setText(
                        f"{getattr(train, 'name', '') or 'Active train'}: no camera pixel size/sensor "
                        "geometry configured — field-of-view fit not evaluated.")
                else:
                    fov_label.setText("No active optical train — field-of-view fit not evaluated.")
                recommendations = rank_tonight(
                    location, train, candidates, forecast=forecast, night_date=night_date,
                    aurora_estimate=aurora, smoke_estimate=smoke,
                    library_lookup=lambda o: prior_integration_hours(o.primary_name),
                    min_altitude_deg=min_altitude.value(),
                )
            except Exception:
                logger.exception("What's Up Tonight ranking failed")
                results.addItem("Ranking failed — see log for details.")
                self._window.statusBar().showMessage("What's Up Tonight ranking failed — see log.", 6000)
                return
            finally:
                QApplication.restoreOverrideCursor()

            if not recommendations:
                results.addItem("Nothing observable tonight matches the current criteria.")
                self._window.statusBar().showMessage("No candidates found.", 4000)
                return

            shown = recommendations[:_MAX_SHOWN]
            self._window.statusBar().showMessage(
                f"Ranked {len(recommendations)} candidate(s) — showing the top {len(shown)}.", 4000)

            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            charts: list = [None] * len(shown)
            try:
                charts = atlas.altitude_charts_batch([r.obj for r in shown], location, night_date)
            except Exception:
                logger.debug("Could not batch-compute altitude charts for What's Up Tonight", exc_info=True)
            finally:
                QApplication.restoreOverrideCursor()

            thumb_labels = []
            for rank, (rec, chart) in enumerate(zip(shown, charts, strict=True), start=1):
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, rec.obj)
                card, thumb_label = _build_tile(rank, rec, chart)
                row_container, size_hint = _tile_row(card)
                item.setSizeHint(size_hint)
                results.addItem(item)
                results.setItemWidget(item, row_container)
                thumb_labels.append(thumb_label)

            # Fill in every cached thumbnail unconditionally (a plain disk
            # read, cheap regardless of how many tiles are shown) — an object
            # already thumbnailed via the Targets/Planning page shows its
            # cached image immediately, however far down the ranked list it
            # sits. Only a genuine network fetch (an object not yet cached
            # anywhere) is bounded, at _MAX_AUTO_THUMBNAILS, to keep a ranking
            # run from firing an unbounded number of hips2fits requests.
            import asyncio
            from galileo.planning.sky_atlas import _cached_thumbnail, _thumbnail_field_arcmin
            from PySide6.QtGui import QPixmap

            def _set_thumb(thumb_label, data: bytes) -> None:
                pixmap = QPixmap()
                if data and pixmap.loadFromData(data) and not pixmap.isNull():
                    thumb_label.setPixmap(pixmap.scaled(
                        _CARD_THUMB_PX, _CARD_THUMB_PX,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
                    ))

            uncached: list[tuple] = []
            for rec, thumb_label in zip(shown, thumb_labels):
                obj = rec.obj
                field_arcmin = _thumbnail_field_arcmin(obj.size_arcmin)
                data = _cached_thumbnail(obj.ra_deg, obj.dec_deg, field_arcmin, field_arcmin)
                if data:
                    _set_thumb(thumb_label, data)
                else:
                    uncached.append((obj, thumb_label))

            if uncached:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    for obj, thumb_label in uncached[:_MAX_AUTO_THUMBNAILS]:
                        try:
                            data = asyncio.run(atlas._fetch_thumbnail(obj))
                        except Exception:
                            logger.debug("Could not fetch card thumbnail for %s", obj.primary_name, exc_info=True)
                            continue
                        _set_thumb(thumb_label, data)
                finally:
                    QApplication.restoreOverrideCursor()

        rank_btn.clicked.connect(run_rank)

        layout.addWidget(criteria)
        layout.addWidget(content, 1)
        return page
