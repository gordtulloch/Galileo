# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""What's Up Tonight — ranking/recommendation engine (WUT-010 … WUT-100).

Not a second catalog or ephemeris engine: this module composes
``galileo.planning.sky_atlas``'s catalog and ``HorizonProfile``,
``galileo.planning.visibility``'s altitude/rise-transit-set/Moon-separation
functions, ``galileo.equipment.profiles``' ``OpticalTrain``, and
``galileo.safety``'s three advisory clients (weather forecast, aurora,
smoke/transparency) into a ranked "what's worth pointing at tonight" list.
Plain Python, no Qt/INDI/Alpaca, no I/O of its own — every caller (the
What's Up Tonight screen, ``galileo.ui.whats_up``) fetches the forecast,
catalog slice, advisories and Library history beforehand and passes them in,
the same pattern ``galileo.planning.sky_atlas.SkyAtlas.filter`` already uses.
This keeps every function here directly unit-testable against hand-
constructed inputs, with no network mocking required.

Four-axis decomposition (WUT's design rationale, not copied from any other
application's internal class names):

1. **Target Astrometry** — the object's own magnitude/size/position, already
   on ``DeepSkyObject`` (``galileo.planning.sky_atlas``); nothing new here.
2. **Sky State** — darkness/altitude, Moon separation, horizon obstruction,
   and (when available for the selected date) weather/aurora/smoke
   advisories; equipment-independent. Produces :class:`ObservabilityScore`.
3. **Equipment Envelope** — per optical train: realistic imaging limiting
   magnitude and field-of-view fit; sky-independent. Field-of-view fit is
   two-sided — an object larger than the frame is still a legitimate mosaic
   target, but one much smaller than the frame is penalized, since a target
   that technically clears the horizon but fills only a speck of the field
   isn't a reasonable single-frame recommendation. Produces
   :class:`FitScore`, computed independently per train (WUT-010/PROF-080).
4. **Recommendation** — ``ObservabilityScore.value * FitScore.value`` plus a
   human-readable ``reasons`` list (WUT-020).

**Confidence** (:class:`Confidence`) runs in parallel to all four, never
multiplied into the score (WUT-030) — it says how complete the inputs were
(missing forecast/aurora/smoke, no horizon profile, no Moon position), so a
data gap degrades the confidence badge rather than silently degrading the
number into a misleadingly precise one.

**Re-ranking on Pier/optical-train change (WUT-040):** :class:`ObservabilityScore`
is Pier-independent (sky state alone) — :func:`compute_observability` and
:func:`rank_for_train` are deliberately two functions, not one, so a caller
re-ranking after switching optical trains can call :func:`rank_for_train`
again against an already-computed observability list instead of recomputing
sky state. :func:`rank_tonight` is the one-call convenience wrapper over
both, for an initial ranking or a location/date change.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from galileo.equipment.profiles import OpticalTrain
    from galileo.planning.sky_atlas import DeepSkyObject
    from galileo.planning.visibility import ObservingLocation

logger = logging.getLogger(__name__)

# Below this altitude, an object is treated as not worth imaging even if it
# technically clears the local horizon — the same default SKY-020's own
# "reach an altitude of" filter already uses (galileo.planning.sky_atlas).
DEFAULT_MIN_ALTITUDE_DEG = 20.0

# Moon-separation and advisory heuristics below are a documented, reasonable
# v1 model, not a scientifically calibrated one -- deliberately simple so the
# "why" (WUT-020) stays explainable in one short sentence per factor.
_MOON_FULL_PENALTY_DEG = 45.0     # separation below which the Moon factor starts biting
_AURORA_KP_THRESHOLD = 4.0        # Kp index below which aurora glow is not considered a factor
_AURORA_KP_SEVERE = 9.0           # Kp index (max on the scale) at which the aurora factor bottoms out
_SMOKE_AQI_THRESHOLD = 50.0       # AQI ("good") below which smoke is not considered a factor
_SMOKE_AQI_SEVERE = 200.0         # AQI at which the smoke factor bottoms out

# Target fraction of the frame's shorter dimension a well-matched object should
# fill (WUT-010's "imaging capability" fit): below this, the object reads as a
# speck in an oversized field even though it technically "fits". An object
# *larger* than the frame is not penalized this way — mosaicking already
# covers that case (fits_field/mosaic_required below) — this factor only ramps
# down objects that are too small to be a reasonable single-frame target.
_TARGET_FIELD_FILL_FRACTION = 0.30


class Confidence(str, Enum):
    """How complete an entry's sky-state inputs were (WUT-030) — a parallel
    indicator, kept separate from and never multiplied into the score."""
    FULL = "full"
    REDUCED = "reduced"


@dataclass
class ObservabilityScore:
    """Sky-only observability (WUT-010): how much of the object is
    realistically visible from this location tonight, independent of what
    telescope is used."""
    value: float                        # 0..1
    max_altitude_deg: float
    visible_fraction: float             # fraction of the charted night at/above min_altitude_deg
    moon_separation_deg: float | None   # None when the Moon's position couldn't be computed
    horizon_applied: bool               # True when a HorizonProfile constrained this score (WUT-080)
    weather_available: bool
    aurora_available: bool
    smoke_available: bool


@dataclass
class FitScore:
    """Per-optical-train imaging fit (WUT-010), computed independently per
    train (PROF-080) — a multi-Pier Observatory can rank the same target
    differently for two Piers with different trains."""
    value: float                # 0..1
    limiting_magnitude: float
    fits_field: bool            # False when the object is larger than this train's field of view
    mosaic_required: bool = False
    fill_fraction: float | None = None   # object size / frame's shorter dimension; None when unknown


@dataclass
class Recommendation:
    obj: DeepSkyObject
    observability: ObservabilityScore
    fit: FitScore
    score: float
    reasons: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.FULL
    prior_integration_hours: float | None = None   # informational only (WUT-050); never scored


@dataclass
class _ObjectObservability:
    """Internal pairing of an object with its already-computed sky state —
    what :func:`compute_observability` returns and :func:`rank_for_train`
    consumes, so the two can be called independently (WUT-040)."""
    obj: DeepSkyObject
    observability: ObservabilityScore
    reasons: list[str]
    confidence_reduced: bool


# ---------------------------------------------------------------------------
# Sky State (Observability Score)
# ---------------------------------------------------------------------------

def compute_observability(
    location: ObservingLocation,
    catalog: Iterable[DeepSkyObject],
    night_date: str | None = None,
    forecast: dict | None = None,
    aurora_estimate: float | None = None,
    smoke_estimate: float | None = None,
    min_altitude_deg: float = DEFAULT_MIN_ALTITUDE_DEG,
) -> list[_ObjectObservability]:
    """Sky State (WUT-010/WUT-080/WUT-100): the sky-only, equipment-
    independent half of the ranking, for every object in *catalog* at
    *location* on *night_date* (tonight, when ``None``). Pier-independent —
    reuse this result across a Pier/optical-train switch via
    :func:`rank_for_train` instead of recomputing it (WUT-040).

    *forecast*/*aurora_estimate*/*smoke_estimate* are advisory-only
    (matching ``SAFE-050``/``SAFE-090``/``SAFE-100``'s own tier) and each
    ``None`` means "unavailable for this date" — never treated as "clear/no
    aurora/no smoke" by default. Every one of these degrades the resulting
    :class:`Confidence` (WUT-030), never the score's precision beyond the
    documented factor each contributes."""
    from galileo.planning.visibility import altitude_chart, moon_position_deg, moon_separation_deg

    horizon = getattr(location, "_horizon", None)
    weather_factor, weather_available = _weather_factor(forecast)
    aurora_factor, aurora_available = _advisory_factor(
        aurora_estimate, _AURORA_KP_THRESHOLD, _AURORA_KP_SEVERE)
    smoke_factor, smoke_available = _advisory_factor(
        smoke_estimate, _SMOKE_AQI_THRESHOLD, _SMOKE_AQI_SEVERE)

    moon_pos = moon_position_deg(location, night_date)

    results: list[_ObjectObservability] = []
    for obj in catalog:
        chart = altitude_chart(obj.ra_deg, obj.dec_deg, location, night_date)
        altitudes = chart.get("altitudes") or []
        above_horizon = chart.get("above_horizon")

        if altitudes:
            max_alt = max(altitudes)
            if above_horizon is not None:
                observable_samples = [
                    a >= min_altitude_deg and ok for a, ok in zip(altitudes, above_horizon, strict=True)
                ]
            else:
                observable_samples = [a >= min_altitude_deg for a in altitudes]
            visible_fraction = sum(observable_samples) / len(observable_samples)
        else:
            max_alt = 0.0
            visible_fraction = 0.0

        moon_sep: float | None = None
        moon_factor = 1.0
        if moon_pos is not None:
            moon_sep = moon_separation_deg(obj.ra_deg, obj.dec_deg, moon_pos[0], moon_pos[1])
            moon_factor = min(1.0, moon_sep / _MOON_FULL_PENALTY_DEG)

        value = visible_fraction * moon_factor * weather_factor * aurora_factor * smoke_factor
        value = min(1.0, max(0.0, value))

        reasons: list[str] = []
        if visible_fraction <= 0.0:
            reasons.append(f"Never reaches {min_altitude_deg:.0f}° altitude tonight")
        elif visible_fraction < 0.5:
            reasons.append(f"Low altitude — best only {max_alt:.0f}°")
        if moon_factor < 1.0 and moon_sep is not None:
            reasons.append(f"Close to the Moon ({moon_sep:.0f}° separation)")
        if weather_factor < 1.0:
            reasons.append("Forecast cloud cover reduces tonight's usable window")
        if aurora_factor < 1.0:
            reasons.append("Elevated aurora activity may wash out contrast")
        if smoke_factor < 1.0:
            reasons.append("Smoke/haze reduces tonight's transparency")

        confidence_reduced = (
            horizon is None
            or not weather_available
            or not aurora_available
            or not smoke_available
            or moon_pos is None
        )

        results.append(_ObjectObservability(
            obj=obj,
            observability=ObservabilityScore(
                value=value,
                max_altitude_deg=max_alt,
                visible_fraction=visible_fraction,
                moon_separation_deg=moon_sep,
                horizon_applied=horizon is not None,
                weather_available=weather_available,
                aurora_available=aurora_available,
                smoke_available=smoke_available,
            ),
            reasons=reasons,
            confidence_reduced=confidence_reduced,
        ))
    return results


def _weather_factor(forecast: dict | None) -> tuple[float, bool]:
    """Fraction (0..1, 1 = no reduction) applied for forecast cloud cover,
    and whether a usable forecast was available at all. An empty/malformed
    forecast dict (the Open-Meteo client's own "unreachable" degradation,
    ``galileo.safety.OpenMeteoClient.get_forecast``) is treated the same as
    no forecast — unavailable, not "zero cloud cover"."""
    if not forecast:
        return 1.0, False
    hourly = forecast.get("hourly") or {}
    cloudcover = hourly.get("cloudcover")
    if not cloudcover:
        return 1.0, False
    avg_cover = sum(cloudcover) / len(cloudcover)
    return max(0.0, 1.0 - avg_cover / 100.0), True


def _advisory_factor(value: float | None, threshold: float, severe: float) -> tuple[float, bool]:
    """Shared shape for the aurora-Kp and smoke-AQI advisories: 1.0 (no
    reduction) at/below *threshold*, linearly down to 0.0 at/above *severe*.
    ``None`` means unavailable for this date, not "clear" — returned as
    ``(1.0, False)`` so the caller applies no penalty but still knows to
    degrade Confidence (WUT-100)."""
    if value is None:
        return 1.0, False
    if value <= threshold:
        return 1.0, True
    if value >= severe:
        return 0.0, True
    return 1.0 - (value - threshold) / (severe - threshold), True


# ---------------------------------------------------------------------------
# Equipment Envelope (Fit Score) + Recommendation
# ---------------------------------------------------------------------------

def _fit_for_train(obj: DeepSkyObject, train: OpticalTrain | None) -> FitScore:
    """Equipment Envelope (WUT-010): realistic imaging limiting magnitude
    and field-of-view fit for *train*, independent of sky state. With no
    train (or one with no aperture/camera data configured), every object is
    treated as fitting — there is nothing about the equipment to rule it
    out, which matches this axis's "sky-independent" contract rather than
    silently excluding everything.

    The limiting-magnitude formula (``7.7 + 5*log10(aperture_mm)``) is the
    standard visual-limiting-magnitude estimate scaled by aperture; it is a
    documented, simple v1 heuristic, not exposure/stacking-aware — the
    Project Scope Document's own non-goals (§5.3) already scope out a more
    elaborate imaging-exposure model for this feature."""
    if train is None or not getattr(train, "aperture_mm", 0):
        return FitScore(value=1.0, limiting_magnitude=99.0, fits_field=True)

    limiting_magnitude = 7.7 + 5.0 * math.log10(train.aperture_mm)
    if obj.magnitude >= 90.0:
        # Unmeasured magnitude in the catalog — can't rule it out on brightness.
        magnitude_value = 1.0
    elif obj.magnitude > limiting_magnitude:
        magnitude_value = 0.0
    else:
        magnitude_value = min(1.0, max(0.0, (limiting_magnitude - obj.magnitude) / 5.0))

    fits_field = True
    size_fit = 1.0
    fill_fraction: float | None = None
    plate_scale = getattr(train, "plate_scale_arcsec_px", 0.0)
    camera = getattr(train, "camera", None) or {}
    width_px = camera.get("sensor_width_px", 0)
    height_px = camera.get("sensor_height_px", 0)
    if plate_scale and width_px and height_px and obj.size_arcmin > 0:
        field_arcmin = (min(width_px, height_px) * plate_scale) / 60.0
        fits_field = obj.size_arcmin <= field_arcmin
        fill_fraction = obj.size_arcmin / field_arcmin
        # An object larger than the frame is not penalized here — it's still a
        # worthwhile mosaic target (the 0.5x fits_field penalty below already
        # covers that tradeoff). Only ramp down objects too small to be a
        # reasonable single-frame target: linear from 0 at 0% fill up to full
        # value at the target fill fraction.
        if fill_fraction < _TARGET_FIELD_FILL_FRACTION:
            size_fit = fill_fraction / _TARGET_FIELD_FILL_FRACTION

    value = magnitude_value * size_fit * (1.0 if fits_field else 0.5)
    return FitScore(
        value=value,
        limiting_magnitude=limiting_magnitude,
        fits_field=fits_field,
        mosaic_required=not fits_field,
        fill_fraction=fill_fraction,
    )


def rank_for_train(
    observability_results: list[_ObjectObservability],
    train: OpticalTrain | None,
    library_lookup: Callable[[DeepSkyObject], float | None] | None = None,
) -> list[Recommendation]:
    """Equipment Envelope + Recommendation (WUT-010, WUT-040): combine an
    already-computed :func:`compute_observability` result with *train*'s Fit
    Score, without recomputing sky state — this is what a Pier/optical-train
    switch calls (WUT-040), reusing the same *observability_results*.

    *library_lookup*, when given, populates ``Recommendation.prior_integration_hours``
    (WUT-050) for display only — its return value is never read by the score
    computed here, enforced by simply not being one of this function's
    inputs to that computation. Results are sorted by score, descending."""
    recommendations: list[Recommendation] = []
    for entry in observability_results:
        fit = _fit_for_train(entry.obj, train)
        score = entry.observability.value * fit.value

        reasons = list(entry.reasons)
        if fit.value <= 0.0:
            reasons.append(
                f"Below usable aperture for this train (needs mag ≤ {fit.limiting_magnitude:.1f}, "
                f"object is mag {entry.obj.magnitude:.1f})"
            )
        elif fit.mosaic_required:
            reasons.append("Larger than this train's field of view — mosaic required")
        elif fit.fill_fraction is not None and fit.fill_fraction < _TARGET_FIELD_FILL_FRACTION:
            reasons.append(
                f"Small in this train's field of view — fills only "
                f"~{fit.fill_fraction * 100:.0f}% of the frame"
            )
        if not reasons:
            reasons.append("Good altitude and clear of the Moon")

        prior_hours: float | None = None
        if library_lookup is not None:
            try:
                prior_hours = library_lookup(entry.obj)
            except Exception:
                logger.debug("library_lookup failed for %s", entry.obj.primary_name, exc_info=True)
                prior_hours = None

        confidence = Confidence.REDUCED if entry.confidence_reduced else Confidence.FULL

        recommendations.append(Recommendation(
            obj=entry.obj,
            observability=entry.observability,
            fit=fit,
            score=score,
            reasons=reasons,
            confidence=confidence,
            prior_integration_hours=prior_hours,
        ))

    recommendations.sort(key=lambda r: r.score, reverse=True)
    return recommendations


def rank_tonight(
    location: ObservingLocation,
    train: OpticalTrain | None,
    catalog: Iterable[DeepSkyObject],
    forecast: dict | None = None,
    night_date: str | None = None,
    aurora_estimate: float | None = None,
    smoke_estimate: float | None = None,
    library_lookup: Callable[[DeepSkyObject], float | None] | None = None,
    min_altitude_deg: float = DEFAULT_MIN_ALTITUDE_DEG,
) -> list[Recommendation]:
    """The one-call convenience entry point: :func:`compute_observability`
    followed by :func:`rank_for_train`, for an initial ranking or a
    location/date change. Pure and I/O-free (see module docstring) — the
    caller (``galileo.ui.whats_up``) fetches *forecast*/*aurora_estimate*/
    *smoke_estimate*/*catalog*/*library_lookup* beforehand.

    *night_date* defaults to tonight (``None``, threaded straight through to
    ``galileo.planning.visibility``'s own date-parameterized calls — WUT-090:
    there is no separate "tonight" code path to generalize)."""
    observability_results = compute_observability(
        location, catalog, night_date, forecast, aurora_estimate, smoke_estimate, min_altitude_deg,
    )
    return rank_for_train(observability_results, train, library_lookup)
