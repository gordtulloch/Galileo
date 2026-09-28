# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""WUT — What's Up Tonight (TC-WUT-010 … TC-WUT-100)."""

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def recommend_mod():
    return pytest.importorskip("galileo.planning.recommend")


@pytest.fixture
def observing_location():
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    return sky_mod.ObservingLocation(
        name="Backyard", latitude=51.5, longitude=-1.0, elevation_m=100, timezone="UTC",
    )


@pytest.fixture
def train():
    prof_mod = pytest.importorskip("galileo.equipment.profiles")
    return prof_mod.OpticalTrain(
        name="Main", focal_length_mm=600.0, aperture_mm=150.0,
        camera={"pixel_size_um": 3.76, "sensor_width_px": 4144, "sensor_height_px": 2822},
    )


def _obj(name: str, ra_deg: float, dec_deg: float, magnitude: float = 8.0, size_arcmin: float = 5.0):
    sky_mod = pytest.importorskip("galileo.planning.sky_atlas")
    return sky_mod.DeepSkyObject(
        primary_name=name, designations=[name], ra_deg=ra_deg, dec_deg=dec_deg,
        object_type=sky_mod.ObjectType.GALAXY, magnitude=magnitude, size_arcmin=size_arcmin,
    )


# Circumpolar at latitude 51.5N (dec > 90 - lat = 38.5): always above ~36.5° altitude,
# so it is deterministically "visible tonight" regardless of test date.
@pytest.fixture
def bright_circumpolar_object():
    return _obj("Bright", ra_deg=180.0, dec_deg=75.0, magnitude=8.0)


# Never rises at latitude 51.5N (dec < -(90 - lat) = -38.5): always below the horizon.
@pytest.fixture
def never_rises_object():
    return _obj("NeverRises", ra_deg=90.0, dec_deg=-75.0, magnitude=8.0)


# ---------------------------------------------------------------------------
# TC-WUT-010
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-WUT-010")
@pytest.mark.priority("MVP")
def test_tc_wut_010_ranked_list_combines_observability_and_equipment_fit(
    recommend_mod, observing_location, train, bright_circumpolar_object,
):
    """WUT-010: ranked list combines sky observability (SKY-020/030) with the active
    optical train's imaging capability (PROF-080) — a bright, well-placed object should
    outrank one that is equally well placed but too faint for the train's aperture."""
    too_faint = _obj("TooFaint", ra_deg=180.0, dec_deg=75.0, magnitude=25.0)
    catalog = [bright_circumpolar_object, too_faint]

    recs = recommend_mod.rank_tonight(observing_location, train, catalog, night_date="2026-06-15")

    assert [r.obj.primary_name for r in recs] == ["Bright", "TooFaint"]
    assert recs[0].score > recs[1].score
    assert recs[0].fit.value > 0.0
    assert recs[1].fit.value == 0.0
    # Scores are sorted descending.
    assert all(recs[i].score >= recs[i + 1].score for i in range(len(recs) - 1))


@pytest.mark.requirement("TC-WUT-010")
@pytest.mark.priority("MVP")
def test_tc_wut_010_fit_score_is_independent_per_optical_train(
    recommend_mod, observing_location, bright_circumpolar_object,
):
    """WUT-010: Fit Score is computed independently per optical train (PROF-080) — a
    multi-Pier Observatory can rank the same target differently for two different trains."""
    prof_mod = pytest.importorskip("galileo.equipment.profiles")
    small_train = prof_mod.OpticalTrain(name="Small", focal_length_mm=300.0, aperture_mm=60.0)
    large_train = prof_mod.OpticalTrain(name="Large", focal_length_mm=1200.0, aperture_mm=300.0)

    faint = _obj("Faint", ra_deg=180.0, dec_deg=75.0, magnitude=15.0)

    small_recs = recommend_mod.rank_tonight(observing_location, small_train, [faint], night_date="2026-06-15")
    large_recs = recommend_mod.rank_tonight(observing_location, large_train, [faint], night_date="2026-06-15")

    assert large_recs[0].fit.value > small_recs[0].fit.value
    assert large_recs[0].fit.limiting_magnitude > small_recs[0].fit.limiting_magnitude


# ---------------------------------------------------------------------------
# TC-WUT-020
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-WUT-020")
@pytest.mark.priority("MVP")
def test_tc_wut_020_every_entry_has_a_human_readable_reason(
    recommend_mod, observing_location, train, bright_circumpolar_object, never_rises_object,
):
    """WUT-020: every ranked entry shows at least one human-readable reason for its
    ranking or exclusion."""
    recs = recommend_mod.rank_tonight(
        observing_location, train, [bright_circumpolar_object, never_rises_object], night_date="2026-06-15",
    )
    assert len(recs) == 2
    for rec in recs:
        assert rec.reasons, f"{rec.obj.primary_name} has no reasons"
        assert all(isinstance(r, str) and r for r in rec.reasons)

    never_rises = next(r for r in recs if r.obj.primary_name == "NeverRises")
    assert any("reaches" in reason.lower() for reason in never_rises.reasons)


# ---------------------------------------------------------------------------
# TC-WUT-030
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-WUT-030")
@pytest.mark.priority("MVP")
def test_tc_wut_030_confidence_is_separate_from_score_and_degrades_on_missing_data(
    recommend_mod, observing_location, train, bright_circumpolar_object,
):
    """WUT-030: a data-completeness confidence indicator, separate from the score,
    degrades to REDUCED rather than omitting the entry when forecast/horizon data is
    unavailable — and is FULL when every input was available."""
    from galileo.planning.visibility import HorizonProfile

    # No horizon profile, no forecast/aurora/smoke: reduced confidence, entry still present.
    reduced = recommend_mod.rank_tonight(
        observing_location, train, [bright_circumpolar_object], night_date="2026-06-15",
    )
    assert len(reduced) == 1
    assert reduced[0].confidence == recommend_mod.Confidence.REDUCED
    assert isinstance(reduced[0].score, float)   # the score itself stays a plain float either way

    # Every input available: full confidence.
    observing_location.set_horizon(HorizonProfile(points=[(0.0, 0.0), (180.0, 0.0)]))
    full = recommend_mod.rank_tonight(
        observing_location, train, [bright_circumpolar_object], night_date="2026-06-15",
        forecast={"hourly": {"cloudcover": [10, 20, 15]}},
        aurora_estimate=1.0, smoke_estimate=5.0,
    )
    assert full[0].confidence == recommend_mod.Confidence.FULL


# ---------------------------------------------------------------------------
# TC-WUT-040
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-WUT-040")
@pytest.mark.priority("MVP")
def test_tc_wut_040_reranking_on_train_change_reuses_cached_observability(
    recommend_mod, observing_location, bright_circumpolar_object, monkeypatch,
):
    """WUT-040: re-ranking on a Pier/optical-train change reuses the already-computed
    sky-observability data rather than recomputing it — rank_for_train, called twice
    against the same compute_observability result, must not touch altitude/Moon
    computation again."""
    import galileo.planning.visibility as vis_mod
    prof_mod = pytest.importorskip("galileo.equipment.profiles")

    call_count = {"altitude_chart": 0}
    real_altitude_chart = vis_mod.altitude_chart

    def counting_altitude_chart(*args, **kwargs):
        call_count["altitude_chart"] += 1
        return real_altitude_chart(*args, **kwargs)

    monkeypatch.setattr(vis_mod, "altitude_chart", counting_altitude_chart)

    observability = recommend_mod.compute_observability(
        observing_location, [bright_circumpolar_object], night_date="2026-06-15",
    )
    assert call_count["altitude_chart"] == 1
    observability_score_before = observability[0].observability

    train_a = prof_mod.OpticalTrain(name="A", focal_length_mm=300.0, aperture_mm=60.0)
    train_b = prof_mod.OpticalTrain(name="B", focal_length_mm=1200.0, aperture_mm=300.0)

    recs_a = recommend_mod.rank_for_train(observability, train_a)
    recs_b = recommend_mod.rank_for_train(observability, train_b)

    # No new altitude computation happened for either re-rank.
    assert call_count["altitude_chart"] == 1
    # The same ObservabilityScore instance is reused (identity, not just equality).
    assert recs_a[0].observability is observability_score_before
    assert recs_b[0].observability is observability_score_before
    # Fit scores still differ per train (WUT-010's per-train independence).
    assert recs_a[0].fit.value != recs_b[0].fit.value or recs_a[0].fit.limiting_magnitude != recs_b[0].fit.limiting_magnitude


# ---------------------------------------------------------------------------
# TC-WUT-050
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-WUT-050")
@pytest.mark.priority("MVP")
def test_tc_wut_050_prior_integration_is_informational_only_never_scored(
    recommend_mod, observing_location, train, bright_circumpolar_object,
):
    """WUT-050: prior Library integration time is shown per entry as an informational
    annotation only — it must never adjust the entry's score or position."""
    def lookup_with_hours(obj):
        return 8.5

    def lookup_none(obj):
        return None

    def lookup_raises(obj):
        raise RuntimeError("catalog unavailable")

    with_hours = recommend_mod.rank_tonight(
        observing_location, train, [bright_circumpolar_object], night_date="2026-06-15",
        library_lookup=lookup_with_hours,
    )
    without_hours = recommend_mod.rank_tonight(
        observing_location, train, [bright_circumpolar_object], night_date="2026-06-15",
        library_lookup=lookup_none,
    )
    no_lookup_at_all = recommend_mod.rank_tonight(
        observing_location, train, [bright_circumpolar_object], night_date="2026-06-15",
    )

    assert with_hours[0].prior_integration_hours == 8.5
    assert without_hours[0].prior_integration_hours is None
    assert no_lookup_at_all[0].prior_integration_hours is None
    # The score is identical regardless of prior_integration_hours.
    assert with_hours[0].score == without_hours[0].score == no_lookup_at_all[0].score

    # A failing lookup degrades to None rather than raising or blocking the ranking.
    resilient = recommend_mod.rank_tonight(
        observing_location, train, [bright_circumpolar_object], night_date="2026-06-15",
        library_lookup=lookup_raises,
    )
    assert resilient[0].prior_integration_hours is None
    assert resilient[0].score == with_hours[0].score


@pytest.mark.requirement("TC-WUT-050")
@pytest.mark.priority("MVP")
def test_tc_wut_050_prior_integration_hours_lookup_sums_light_frames(tmp_path):
    """WUT-050: galileo.library.prior_integration_hours sums a catalogued object's
    light-frame exposure time (hours), excluding calibration frames and soft-deleted
    rows, and returns None when nothing is catalogued for it."""
    from galileo.library.database import db, init_db
    init_db(tmp_path / "wut_prior_integration.db")
    from galileo.library.models import fitsFile
    from galileo.library import prior_integration_hours

    try:
        fitsFile.create(fitsFileId="a", fitsFileName="M31_1.fits", fitsFileObject="M31",
                         fitsFileType="LIGHT FRAME", fitsFileExpTime="1800")
        fitsFile.create(fitsFileId="b", fitsFileName="M31_2.fits", fitsFileObject="M31",
                         fitsFileType="LIGHT FRAME", fitsFileExpTime="1800")
        fitsFile.create(fitsFileId="c", fitsFileName="M31_dark.fits", fitsFileObject="M31",
                         fitsFileType="DARK FRAME", fitsFileExpTime="1800")
        fitsFile.create(fitsFileId="d", fitsFileName="M31_deleted.fits", fitsFileObject="M31",
                         fitsFileType="LIGHT FRAME", fitsFileExpTime="9999", fitsFileSoftDelete=True)

        assert prior_integration_hours("M31") == pytest.approx(1.0)
        assert prior_integration_hours("M13") is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# TC-WUT-070
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-WUT-070")
@pytest.mark.priority("MVP")
def test_tc_wut_070_whats_up_tonight_is_first_in_planning_sidebar():
    """WUT-070: the What's Up Tonight screen shall be the first entry in the Planning
    sidebar section."""
    app_window_mod = pytest.importorskip("galileo.ui.app_window")
    assert app_window_mod.PLANNING_ITEMS[0][0] == "whats_up"
    assert app_window_mod.PLANNING_ITEMS[0][1] == "What's Up Tonight"
    assert hasattr(app_window_mod.AppWindow, "_build_whats_up_page")


# ---------------------------------------------------------------------------
# TC-WUT-060
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-WUT-060")
@pytest.mark.priority("MVP")
def test_tc_wut_060_select_reuses_the_same_entry_point_as_targets(tmp_path, monkeypatch):
    """WUT-060: a ranked entry's Select button reuses the same shared entry point the
    Targets screen's own Select button uses (AppWindow._select_result) — not a new
    selection mechanism."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("galileo.planning.sky_atlas")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from galileo.library.database import db, init_db
    init_db(tmp_path / "wut_select_test.db")
    from galileo.observatory import create_observatory, create_pier
    from galileo.ui.app_window import AppWindow

    win = AppWindow()
    try:
        win.app, win.QtWidgets = app, QtWidgets
        observatory = create_observatory("Test Obs", latitude=51.5, longitude=-1.0)
        win.pier = create_pier(observatory, "Pier A")
        win._current_pier = win.pier
        win._current_observatory = observatory

        # A date well away from "today" so the advisory fetch (WUT-100) — which would
        # otherwise make a real network call — is skipped, matching its own documented
        # "only fetched for today" behavior; this test only needs the ranked list itself.
        page = win._build_whats_up_page()
        date_edit = next(w for w in page.findChildren(QtWidgets.QDateEdit))
        date_edit.setDate(QtWidgets.QDateEdit().date().addYears(1))
        max_mag = next(w for w in page.findChildren(QtWidgets.QDoubleSpinBox))
        max_mag.setValue(99.0)

        rank_btn = next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Rank Tonight")
        rank_btn.click()

        results = page.findChildren(QtWidgets.QListWidget)[0]
        assert results.count() >= 1, "expected at least one ranked candidate"

        select_btn = next(
            b for b in results.itemWidget(results.item(0)).findChildren(QtWidgets.QPushButton)
            if b.text() == "Select"
        )
        assert win.current_object() is None
        select_btn.click()
        assert win.current_object() is not None, "Select must reuse AppWindow._select_result (IMG-140)"
    finally:
        win._window.close()
        db.close()


# ---------------------------------------------------------------------------
# TC-WUT-080
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-WUT-080")
@pytest.mark.priority("MVP")
def test_tc_wut_080_horizon_obstruction_excludes_observability(
    recommend_mod, observing_location, bright_circumpolar_object,
):
    """WUT-080: where a horizon obstruction profile is defined, the Observability Score
    excludes altitude/time ranges behind it; where none is defined, ranking proceeds on
    open-horizon altitude alone, reflected via confidence rather than blocking the list."""
    from galileo.planning.visibility import HorizonProfile

    without_horizon = recommend_mod.compute_observability(
        observing_location, [bright_circumpolar_object], night_date="2026-06-15",
    )
    assert without_horizon[0].observability.horizon_applied is False
    assert without_horizon[0].observability.visible_fraction > 0.0

    # An obstruction at 85° everywhere blocks this object's whole altitude range
    # (it never exceeds ~66.5° at this location).
    observing_location.set_horizon(HorizonProfile(points=[(0.0, 85.0), (180.0, 85.0)]))
    with_horizon = recommend_mod.compute_observability(
        observing_location, [bright_circumpolar_object], night_date="2026-06-15",
    )
    assert with_horizon[0].observability.horizon_applied is True
    assert with_horizon[0].observability.visible_fraction == 0.0
    assert with_horizon[0].observability.value == 0.0
    # Still present in the results, not silently dropped.
    assert with_horizon[0].obj.primary_name == "Bright"


# ---------------------------------------------------------------------------
# TC-WUT-090
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-WUT-090")
@pytest.mark.priority("P2")
def test_tc_wut_090_observing_date_is_threaded_through_to_sky_state(
    recommend_mod, observing_location, bright_circumpolar_object, monkeypatch,
):
    """WUT-090: setting an observing date other than today computes the ranked list
    against that date's local night — night_date reaches the same date-parameterized
    visibility calls galileo.planning.sky_atlas already uses, not a separate path."""
    import galileo.planning.visibility as vis_mod

    seen_dates = []
    real_altitude_chart = vis_mod.altitude_chart

    def spy_altitude_chart(ra_deg, dec_deg, location, date_str=None, *a, **k):
        seen_dates.append(date_str)
        return real_altitude_chart(ra_deg, dec_deg, location, date_str, *a, **k)

    monkeypatch.setattr(vis_mod, "altitude_chart", spy_altitude_chart)

    recommend_mod.compute_observability(
        observing_location, [bright_circumpolar_object], night_date="2027-03-10",
    )
    assert seen_dates == ["2027-03-10"]


@pytest.mark.requirement("TC-WUT-090")
@pytest.mark.priority("P2")
def test_tc_wut_090_tonight_is_the_default_when_no_date_given(recommend_mod, observing_location, bright_circumpolar_object, monkeypatch):
    """WUT-090: with no explicit date, ranking defaults to tonight (night_date=None
    threaded straight through, not a separate "tonight" code path)."""
    import galileo.planning.visibility as vis_mod

    seen_dates = []
    real_altitude_chart = vis_mod.altitude_chart

    def spy_altitude_chart(ra_deg, dec_deg, location, date_str=None, *a, **k):
        seen_dates.append(date_str)
        return real_altitude_chart(ra_deg, dec_deg, location, date_str, *a, **k)

    monkeypatch.setattr(vis_mod, "altitude_chart", spy_altitude_chart)

    recommend_mod.compute_observability(observing_location, [bright_circumpolar_object])
    assert seen_dates == [None]   # None means "tonight" to altitude_chart itself


@pytest.mark.requirement("TC-WUT-090")
@pytest.mark.priority("P2")
def test_tc_wut_090_date_outside_forecast_horizon_does_not_block_ranking(
    recommend_mod, observing_location, train, bright_circumpolar_object,
):
    """WUT-090: a date outside the weather forecast's range does not block ranking —
    it is reflected via the confidence indicator, same as a missing forecast."""
    recs = recommend_mod.rank_tonight(
        observing_location, train, [bright_circumpolar_object],
        forecast=None, night_date="2030-01-01",
    )
    assert len(recs) == 1
    assert recs[0].confidence == recommend_mod.Confidence.REDUCED


# ---------------------------------------------------------------------------
# TC-WUT-100
# ---------------------------------------------------------------------------

@pytest.mark.requirement("TC-WUT-100")
@pytest.mark.priority("P3")
def test_tc_wut_100_aurora_and_smoke_advisories_inform_the_score_when_available(
    recommend_mod, observing_location, bright_circumpolar_object,
):
    """WUT-100: aurora/smoke advisory estimates for the selected date, where available,
    factor into the Observability Score on the same advisory-only basis as weather."""
    calm = recommend_mod.compute_observability(
        observing_location, [bright_circumpolar_object], night_date="2026-06-15",
        aurora_estimate=1.0, smoke_estimate=5.0,
    )
    severe = recommend_mod.compute_observability(
        observing_location, [bright_circumpolar_object], night_date="2026-06-15",
        aurora_estimate=9.0, smoke_estimate=300.0,
    )
    unavailable = recommend_mod.compute_observability(
        observing_location, [bright_circumpolar_object], night_date="2026-06-15",
    )

    assert calm[0].observability.aurora_available is True
    assert calm[0].observability.smoke_available is True
    assert unavailable[0].observability.aurora_available is False
    assert unavailable[0].observability.smoke_available is False

    # Severe conditions reduce the score relative to calm ones.
    assert severe[0].observability.value < calm[0].observability.value
    # Unavailable advisories apply no penalty (treated as "no data," not "clear").
    assert unavailable[0].observability.value == calm[0].observability.value


@pytest.mark.requirement("TC-WUT-100")
@pytest.mark.priority("P3")
def test_tc_wut_100_never_required_for_ranking_to_proceed(recommend_mod, observing_location, train, bright_circumpolar_object):
    """WUT-100: neither aurora nor smoke estimates are required for ranking to proceed
    — their absence degrades confidence, never blocks the ranked list."""
    recs = recommend_mod.rank_tonight(
        observing_location, train, [bright_circumpolar_object], night_date="2026-06-15",
        aurora_estimate=None, smoke_estimate=None,
    )
    assert len(recs) == 1
    assert recs[0].confidence == recommend_mod.Confidence.REDUCED


