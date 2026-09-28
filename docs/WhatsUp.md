# What's Up Tonight Implementation Plan

Requirement IDs below are
proposals (`WUT-*`) for discussion, not yet reserved in the RTM.

## 1. Purpose

Add a **"What's Up Tonight"** screen to Galileo's Planning section that answers, for the active Pier and its configured observing location: *given tonight's sky
and this equipment, what is worth pointing at?* This is a ranked, opinionated
view layered on top of the existing Targets (sky atlas) screen's catalog
search/filter — not a replacement for it.

## 2. What already exists in Galileo (reuse, don't duplicate)

Galileo's Planning domain already implements the primitives this feature
needs. The new work is the **ranking/recommendation layer on top**, not a
second catalog or a second ephemeris engine.

| Capability | Already implemented in |
|---|---|
| Offline DSO catalog (≥10,000 objects), search/filter | `galileo.planning.sky_atlas.SkyAtlas` (`SKY-010`, `SKY-020`) |
| Altitude-over-the-night charting, batched | `galileo.planning.visibility.altitude_chart` / `altitude_charts_batch` (`SKY-030`) |
| Rise/transit/set | `galileo.planning.visibility.rise_transit_set` |
| "Visible tonight" compound filter (min altitude, min duration) | `galileo.planning.visibility.is_observable_tonight` (`SKY-020`) |
| Moon position/separation | `galileo.planning.visibility.moon_position_deg` / `moon_separation_deg` |
| Custom horizon obstruction profile | `galileo.planning.visibility.HorizonProfile` (`SKY-040`) |
| Observing location(s) | `galileo.planning.sky_atlas.LocationManager` (`SKY-060`) |
| Survey-image thumbnails | `SkyAtlas._fetch_thumbnail` (`SKY-080`) |
| Weather forecast (Open-Meteo, advisory-only) | `galileo.safety.SafetyMonitorService.get_forecast_advisory` (`SAFE-050`, `EXT-130`) |
| Per-Pier optical train (aperture, focal length) | `galileo.equipment.profiles.OpticalTrain` (`PROF-080`) |
| Multi-Pier grouping / shared resources | `galileo.observatory` |
| Cross-module decoupling | `galileo.bus.EventBus` |
| Prior imaging history for an object | `galileo.library` (`fitsSession`/`fitsFile` catalog), `galileo.history` |

None of these should be reimplemented. The new module composes them.

## 3. Conceptual model (Galileo's own terms)

Separating "what the target intrinsically is" from "what tonight's sky does to
it" from "what this observer's equipment can actually use" from "how this
fits into a session plan" is standard practice in observability-scoring
systems and is restated here in Galileo's own vocabulary, mapped onto
Galileo's actual modules — not copied from any specific tool's internal class
names or formulas:

1. **Target Astrometry** (objective, sky-independent)
   Magnitude, angular size, object type, RA/Dec — already on
   `DeepSkyObject` (`galileo.planning.sky_atlas`).

2. **Sky State** (objective, location- and time-dependent, equipment-independent)
   Darkness window, altitude curve, Moon separation/illumination, horizon
   obstruction (all from `galileo.planning.visibility`), plus forecast cloud
   cover/transparency (from `galileo.safety`'s existing advisory forecast
   client, `EXT-130`). Produces an **Observability Score**: how much of the
   object is realistically visible from this location tonight, independent
   of what telescope is used. This is exactly `SKY-020`'s existing "Visible
   tonight" filter, generalized from a boolean gate into a continuous score.
   **Decision:** where the active location has a horizon obstruction profile
   configured (`SKY-040`), the Observability Score must be computed against
   it — an object whose altitude curve is behind an obstruction at a given
   time is not observable then, exactly as `SKYMAP-080`'s slew guard already
   treats obstructed altitude/azimuth as unreachable. Where no profile is
   configured, ranking proceeds using open-horizon altitude only, flagged via
   reduced Confidence (item 5 below, `WUT-030`), not blocked or silently
   assumed clear.

3. **Equipment Envelope** (per Pier/optical train, sky-independent, imaging-only)
   Aperture, focal length, and the active camera's sensor geometry — already
   on `OpticalTrain`/`Pier` (`galileo.equipment.profiles`) — determine a
   realistic imaging limiting magnitude, field-of-view fit (does the object
   fit the sensor, or need a mosaic — reuses `galileo.planning.framing`'s FOV
   math, `FRAME-010`), and whether the target is achievable at all with the
   active train. Produces a **Fit Score**, computed independently per Pier —
   a multi-Pier Observatory can rank the same target differently for two
   Piers with different trains. **Decision:** v1 is imaging-only; visual
   observing (eyepiece/Barlow-based limiting magnitude, per `PROF`'s
   eyepiece/Barlow data) is out of scope — see Section 5.3.

4. **Recommendation** (combination, presentation-facing)
   `Observability Score × Fit Score`, adjusted by session context — is it
   competing with a higher-ranked target for the same window, how much of
   tonight's darkness window remains. This produces the ranked list the
   screen shows, plus a short human-readable "why" (e.g. "low altitude
   before 23:00", "below usable aperture for this train"). **Decision:**
   prior Library integration time is shown per entry as an informational
   annotation only — it does not adjust the score (see `WUT-050`,
   Section 6).

5. **Confidence** (parallel, not multiplied into the score)
   A separate, explicit indicator of how complete the inputs were — e.g. no
   weather forecast available, no horizon profile configured, Moon position
   unavailable — shown as a badge/tooltip rather than silently degrading the
   score to a misleadingly precise number. This directly follows Galileo's
   existing convention elsewhere in the codebase of degrading to a status-bar
   note / placeholder rather than an error (`SkyAtlas`'s own location/weather
   degradation pattern, Section 4.8 of `docs/SDD.md`).

This is a 4+1 decomposition (astrometry → sky state → equipment fit →
recommendation, with confidence running alongside) chosen because it maps
cleanly onto modules Galileo already owns (`sky_atlas`, `visibility`,
`equipment.profiles`, `safety`, `library`) with one new module gluing them
together — not because it mirrors any other application's internal
architecture.

## 4. Proposed module design

### 4.1 New module: `galileo.planning.recommend`

Domain-core, plain Python, no Qt/INDI/Alpaca — consistent with
`ARCH`'s layering rule. Depends on `galileo.planning.sky_atlas`,
`galileo.planning.visibility`, `galileo.equipment.profiles`,
`galileo.safety` (via its existing advisory port, not a new weather client),
and read-only queries into `galileo.library`'s catalog.

Sketch (illustrative signatures — final shape decided during implementation,
not prescribed by this plan):

```python
@dataclass
class ObservabilityScore:
    value: float                 # 0..1, sky-only
    darkness_window: tuple[time, time]
    moon_separation_deg: float
    weather_confidence: float    # 0 when no forecast available
    horizon_applied: bool        # True when a HorizonProfile constrained this score

@dataclass
class FitScore:
    value: float                 # 0..1, per optical train
    limiting_magnitude: float
    fits_field: bool
    mosaic_required: bool

@dataclass
class Recommendation:
    obj: DeepSkyObject
    observability: ObservabilityScore
    fit: FitScore
    score: float
    reasons: list[str]                    # human-readable limiting factors
    confidence: Confidence                # enum or small struct, separate axis
    prior_integration_hours: float | None  # informational only, never scored

def rank_tonight(
    location: ObservingLocation,
    pier: Pier,
    catalog: Iterable[DeepSkyObject],
    forecast: dict | None,
    library_lookup: Callable[[DeepSkyObject], float] | None = None,  # hours integrated, annotation only
) -> list[Recommendation]: ...
```

`rank_tonight` is pure/testable: given a location, a Pier's optical train(s),
a catalog slice, and a forecast dict, it returns a deterministic ranked list.
No I/O inside it — callers (the UI layer) fetch the forecast, catalog, and
library history beforehand, matching the existing pattern in
`galileo.planning.sky_atlas.SkyAtlas.filter`. `library_lookup` (per Section 9
decision) only populates `Recommendation.prior_integration_hours` for
display — it must never factor into `score`.

### 4.2 UI: `galileo.ui.whats_up` (new screen)

- Sidebar entry under Planning, positioned **first in the Planning list**
  (per decision, Section 9) — ahead of Targets, Framing (contextual), Skymap,
  Scheduler — a primary-navigation screen like Targets, not a modal like
  Framing.
- Reuses the Targets screen's result-tile pattern (`AppWindow._build_sky_atlas_page`
  precedent): one tile per recommended object, altitude mini-chart (shared
  `_AltitudeChart` widget), thumbnail, and the same **Select / Slew To / Add
  to Session** action buttons already on Targets-screen tiles — no new
  selection mechanism, per the existing convention in `docs/SDD.md` Section 4.8.
- A "why this ranking" line per tile surfaces `Recommendation.reasons`.
- A confidence badge (not blended into the score) shown per tile when inputs
  were incomplete (no weather, no horizon profile, etc.). Where a horizon
  profile **is** configured (`SKY-040`), its obstruction is applied to the
  Observability Score before ranking, consistent with the horizon shading
  `galileo.ui.star_atlas` already draws and the obstruction check
  `SKYMAP-080`'s slew guard already applies (`WUT-080`).
- A prior-integration annotation (e.g. "8.5h already integrated") shown per
  tile when `Recommendation.prior_integration_hours` is set — informational
  text only, never affects tile ordering (per decision, Section 9).
- Top-bar Pier/optical-train selector (existing pattern, `PROF-110`) drives
  which Equipment Envelope is used — switching Pier re-ranks using that
  Pier's train, without a full catalog re-fetch (only the Fit Score layer
  needs to be recomputed; Observability Score is Pier-independent and can be
  cached for the session).
- Degrades exactly like the Targets screen when no Observatory location is
  configured: an empty-state placeholder with guidance to set one, not an
  error (existing convention, Section 4.8 of `docs/SDD.md`).

### 4.3 Explicit non-goals for this feature

- **Not a second weather client.** Reuses `galileo.safety`'s existing
  Open-Meteo advisory forecast (`EXT-130`, `SAFE-050`). If that forecast is
  unavailable, Sky State degrades gracefully (lower confidence), it does not
  block the screen.
- **Not a second catalog or ephemeris engine.** Reuses `SkyAtlas`/`visibility`
  entirely.
- **Not a solar-system/comet/ISS/meteor-shower calendar.** Out of scope for
  v1; Galileo has no existing module for this class of transient event, and
  adding one is a separate, larger proposal if wanted later.
- **Not a camera/exposure-planning advisor.** Galileo's imaging tab and
  sequencer already own capture parameters; this screen ranks *targets*, not
  exposure plans. A future integration point (e.g. surfacing suggested
  exposure ranges) is explicitly deferred, not designed here.
- **No AI-generated imagery or any new third-party image assets.** Uses
  Galileo's existing survey-thumbnail pipeline only.
- **No new bundled/paid data provider.** No Telescopius-equivalent, no
  COBS-equivalent, no VIIRS/AOD provider in v1 — `SKY-110`/`SKY-120` and
  `SAFE-090`/`SAFE-100` already cover optional advisory augmentation and stay
  independent of this feature.
- **No visual-observing mode.** v1 is imaging (camera sensor) only, per
  decision (Section 9); eyepiece/Barlow-based limiting-magnitude scoring is
  deferred to a future proposal if wanted.
- **No scoring effect from prior Library integration time.** Shown as an
  informational annotation per entry only, per decision (Section 9) — it
  does not deprioritize or hide a target.

## 5. Proposed requirements (draft — for SRS/RTM discussion, not yet added)

A new `WUT` domain under Section 4.8's neighborhood (after `SKY`, alongside
`FRAME`/`SKYMAP`/`SCHED`), consuming `SKY`/`SAFE`/`PROF` requirements by
reference rather than restating them:

| Draft ID | Draft requirement | Priority |
|---|---|---|
| WUT-010 | The system shall present a ranked list of catalog objects observable tonight from the active Pier's configured location, combining sky observability (`SKY-020`/`030`) with the active optical train's imaging capability (`PROF-080`). | MVP |
| WUT-020 | Each ranked entry shall show at least one human-readable reason for its ranking or exclusion (e.g. limiting altitude, equipment mismatch, Moon proximity). | MVP |
| WUT-030 | The system shall display a data-completeness confidence indicator per entry, separate from the ranking score, degrading rather than silently omitting entries when forecast/horizon data is unavailable. | MVP |
| WUT-040 | Re-ranking on Pier/optical-train change shall reuse the already-computed sky-observability data for that location/night rather than recomputing it. | MVP |
| WUT-050 | The system shall show, per ranked entry, prior integration time recorded in the Library for that object, as an informational annotation only — it shall never adjust the entry's score or position in the ranking. | MVP |
| WUT-060 | Each ranked entry shall offer the same Select / Slew To / Add to Session actions as the Targets screen (`SKY-050`, `SKYMAP-060`, `SES-160`), reusing the existing entry points. | MVP |
| WUT-070 | The "What's Up Tonight" screen shall be the first entry in the Planning sidebar section. | MVP |
| WUT-080 | Where a horizon obstruction profile (`SKY-040`) is defined for the active location, the Observability Score shall exclude altitude/time ranges behind that obstruction; where none is defined, ranking shall proceed on open-horizon altitude alone and reflect the omission via the confidence indicator (`WUT-030`), never blocking the ranked list. | MVP |

Per decision (Section 9), this whole feature is MVP priority — the original
P2/P3 default in this plan's first draft is superseded. These would still
need real RTM `TC-*` IDs reserved before implementation, per `CLAUDE.md`'s
test-authoring convention.

## 6. Phasing

All of `WUT-010`–`080` are MVP (Section 9 decision) and land together —
there is no longer a deferred Phase 2 for this feature's core scope. The only
work explicitly deferred is what Section 5.3 already excludes from v1
entirely (visual-observing mode, Library-based deprioritization, transient-
event calendar, exposure-planning integration, new paid data providers) —
those are future proposals, not a Phase 2 of this one.

## 7. Testing plan

Following `CLAUDE.md`'s per-domain test file convention: a new
`tests/test_wut.py`, one `test_tc_wut_<nnn>_<description>` per reserved
`TC-WUT-*` ID, using the existing `mock_indi_mount`/`minimal_profile`
fixtures plus a synthetic subset of the session-scoped 10K-object catalog
fixture already used by `test_sky.py`-equivalent tests — no new fixtures for
the catalog itself. `rank_tonight` being pure and I/O-free (Section 5.1)
makes it directly unit-testable with hand-constructed `DeepSkyObject`/
`OpticalTrain`/forecast-dict inputs, without mocking network calls.

## 8. Decisions

Resolved by the user; incorporated throughout this plan (see cross-references
above):

1. **Placement:** new primary Planning sidebar entry, positioned first in the
   Planning list — not a tab/mode within the existing Targets screen
   (`WUT-070`, Section 5.2).
2. **Scope:** imaging-only for v1 (camera-sensor-based Fit Score). Visual
   observing (eyepiece/Barlow-based limiting magnitude) is out of scope
   (Section 4 item 3, Section 5.3).
3. **Library history:** shown per entry as an informational annotation only
   (`prior_integration_hours`) — never scored, never affects ranking order
   (Section 4 item 4, Section 5.1, `WUT-050`).
4. **Priority:** the whole feature is MVP, superseding this plan's original
   P2/P3 default (Section 6, Section 7).
5. **Horizon obstruction:** where the user has configured a horizon profile
   (`SKY-040`) for the active location, the Observability Score must respect
   it (obstructed altitude/time = not observable), not just the existing
   Skymap/slew-guard path — added as `WUT-080` (Section 4 item 2, Section
   5.1's `horizon_applied` field, Section 5.2).
