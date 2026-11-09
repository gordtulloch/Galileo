# Galileo Mobile App — Recommended Features

**Status:** Draft for review. Not yet reflected in any SRS, RTM or PSD.
**Sources:** `Comparison of Functions.md` (ASIAIR baseline), `Competitive-Review.md` (rivals), `docs/plugins/mobileconnect/SRS.md` (`MCON-*`), the app repository's PSD (`Galileo-MobileConnect/docs/PSD.md`) and the core SRS.
**Scope:** Gaps in the *anticipated mobile feature set*. The app operates an observatory and never configures it (app PSD §5), so core-only gaps are listed separately in §5.

---

## 1. Summary

The planned feature set already covers the ASIAIR's operating functions (connect, slew, GOTO and centre, polar alignment, focus, guiding, flips, sessions, scheduling, safety) and goes beyond it in several places:

| Galileo advantage | Versus |
|---|---|
| Per-Pier control lease, with confirmation to take it (`MCON-140`) | ASIAIR's "single controller" rule, which is only a warning |
| Viewer and Operator roles, enforced on the Master (`MCON-110`, `120`) | ASIAIR device lock (all or nothing) |
| Multi-Pier, multi-node overview through one connection (`MCON-200`) | ASIAIR is one rig per box; dual-rig sync is a long-standing user request |
| Audit log of every request (`MCON-190`) | None on ASIAIR |
| Outreach guest mode (`MCON-1200`–`1330`) | ASIAIR has none; Seestar guest mode is the nearest |
| Session authoring on the tablet (`MCON-500`) | ASIAIR Autorun is edited on its own page, not as nested blocks |
| Meta Quest immersive planetarium (`MCON-1050`) | No rival |

The gaps below are specific and mostly small. **Power/dew, a demo mode and node health are cheap and should come first.** Alerts-while-closed and the Guiding Assistant need a design decision before work starts.

---

## 2. Recommended additions — detail

Each item gives: what is missing, the evidence, where it lands in the SRS, what it needs from core, and a rough size (S = days, M = a week or two, L = needs core work first).

### High priority

#### 1. Alerts while the app is closed — documentation fix, not a new feature (S)
- **Gap:** `MCON-340` and PSD D4/O6 rule out background push because it needs an internet relay. A user whose rig finishes, loses guiding or hits a safety stop overnight hears nothing unless the app is open. The competitive review rates alerts P1 (NINA Ground Station, Seestar message push).
- **Observation:** Galileo's desktop already has notification channels and rules, which live on the Master and need no app. A rule that sends by e-mail or text message (the only channels today; there is no Pushover/ntfy sender) already reaches a phone with the app closed.
- **Decision (2026-11-08):** Keep D4 (no relay, no cloud, no APNs/FCM) and add no external push services. The supported way to be alerted while away is the Master's own e-mail/text channels; `MCON-340`, PSD D4, the inline help and the wiki now say so. Pushover/ntfy senders and deep links are deferred.
- **Also consider (P3):** local notifications while the app is connected but backgrounded (Android foreground service, already contemplated by `MCON-870`; iOS is limited to ~30 s of background time, so this will be Android-only in practice).
- **SRS:** amend `MCON-340`; no new requirement ID needed.

#### 2. Power and dew control (M)
- **Gap:** `MCON-420` says "switches: toggle", which is on/off only. There is no way to set a dew-heater power level or see how much current each port draws.
- **Evidence:** SynLink has two dew channels with adjustable power in its app. Gaius-S2 and EAGLE6 do automatic dew control from temperature and humidity. The ASIAIR forum has a request for automated dew-heater control and for heater state to be remembered. The Missing Manual says overloaded 12 V ports are the top cause of crashes.
- **Proposed:**
  - Switch operations accept a numeric value (0–100 %) where the device reports one (INDI number/PWM properties, Alpaca `SetSwitchValue`).
  - Read-only telemetry per power device: input voltage, total and per-port current, temperature, as the device reports them. Show an overload warning when the device flags one.
  - Dew-point display (from the weather station if present) beside the heater controls.
  - Automatic dew control stays a Master-side setting (configuration), not an app control.
- **Core dependency:** the switch port needs value semantics and telemetry fields exposed through the Control Surface. Check whether `galileo.core.devices` already carries them.
- **SRS:** amend `MCON-420`; new requirement for telemetry (`MCON-4xx`).

#### 3. Demo observatory mode (S–M)
- **Gap:** no user-facing way to try the app without equipment.
- **Evidence:** SynLink ships device simulators for practice. The Missing Manual spends a large part of its length on first-night difficulty. Separately, Apple App Review and Google Play review need a way to exercise the app; an app that only works with a private Master is a common rejection cause.
- **Observation:** the iOS app already runs against a scripted mock Master (`tools/mock-master`, `api/scenarios`). The work is packaging it inside the app behind a "Try the demo" entry, clearly labelled, with a scenario for each major area (focus run, polar alignment, session run, safety stop).
- **Recommendation:** treat as an MVP item because it also unblocks store submission. Make the demo impossible to confuse with a real Master (banner, different theme accent).
- **SRS:** new requirement under §3.8 (e.g. `MCON-8xx`). Android parity via the shared protocol vectors (`MCON-880`).

#### 4. Guiding depth (M, partly L)
- **Gap:** `MCON-460` covers start, stop, dither, recalibrate, the error trace and the guide-star cut-out. It does not cover choosing the guide star, or any of the analysis rivals have.
- **Evidence:** PHD2's Guiding Assistant (drift, periodic error, polar error, Dec backlash, recommended settings) is rated P1 in the review. The ASIAIR hides advanced settings, which is the most common power-user complaint.
- **Proposed (in order of cost):**
  1. Tap-to-select guide star on the cut-out (S; needs a Control Surface operation). **Done**: `guiding.select_star`, on the cut-out and on the whole guide frame (`guide:<pier>`), on the desktop Guider screen and iOS.
  2. Show the calibration result and the last guiding statistics (RMS RA/Dec/total) (S).
  3. Run the Guiding Assistant and show its result and recommendations (L; needs the feature in core first).
  4. Per-run guiding parameters, e.g. exposure time and settle threshold for the next dither, allowed by `MCON-570` but not named in `MCON-460` (S).
- **Boundary:** persistent guide settings (aggressiveness, max pulse) are configuration and stay on the desktop.
- **SRS:** amend `MCON-460`.

### Medium priority

#### 5. Node health and shutdown/restart (S–M)
- ASIAIR has a red SHUTDOWN slider; a Raspberry Pi Master is headless, and today the app cannot shut it down cleanly or even show that it is struggling.
- Show: disk free (and free space per Library volume), CPU temperature, load, memory, uptime, input voltage where available, Galileo and plugin versions.
- Add confirmed, audited operations: shut down node, restart node. Shutdown while a session is running must be refused or require the stronger confirmation of `MCON-180`. Emergency-class? No. It is not an emergency operation.
- Related: `MCON-080` already commits to protecting a Pi-class Master. Reporting its health is the natural counterpart.
- **SRS:** new Operations requirement.

#### 6. Pre-run summary (S)
- The ASIAIR Autorun shows estimated total time, storage needed, and time until the meridian flip before you press start.
- Show on the session run screen: estimated duration, estimated storage against free space, predicted flip time, and a warning if the session would run into the flip, dawn or the horizon limit.
- **Core dependency:** the session executor needs to produce an estimate. Check `galileo.session_exec` and the Sessions screen; the desktop may already compute some of this.
- **SRS:** amend `MCON-490`.
- **Status (2026-11-08):** done in core as `session.estimate` (`CSURF-185`), which computes all of the above on the Master from the saved template; the phone and browser screens that display it are not built yet. Not estimated: time spent waiting on a condition or trigger, autofocus reruns and flips the session did not plan for.

#### 7. Polar alignment live loop (S)
- `MCON-450` says "run a polar-alignment routine" but does not say the live adjustment display (current error in altitude and azimuth, refresh) streams to the app.
- This is the one task where a user is standing at the mount with the tablet, turning knobs, so latency and update rate matter most.
- State it explicitly: progress events carry the current error vector at each refresh; the app shows large readouts with a trend; the preview of the last frame is available.
- **SRS:** amend `MCON-450`.
- **Status (2026-11-08):** done for the error readouts, trend and pole plot: core `polar.*` (`CSURF-145`), the iOS Solve screen and WebConnect's Polar tab. The last-frame preview during polar alignment is not wired in yet.

#### 8. Library frame to GOTO (S)
- The ASIAIR can GOTO the field of a stored image. Link `MCON-540` (browse frames) to `MCON-440` (go to): from a Library frame, "centre on this field", using the frame's solved WCS or its header coordinates.
- **SRS:** amend `MCON-540` or `MCON-440`.

#### 9. Save or share a preview to the phone (S)
- The ASIAIR File Manager can save an image to the phone. `MCON-620` provides full FITS download for Operators, but a JPEG to the camera roll or the system share sheet is what most users actually want (post to a forum, send to a friend).
- Keep the Viewer restriction: a Viewer's preview shares the already-permitted preview only. Strip metadata (`MCON-1270` does this for guests; apply the same to shared JPEGs unless the user opts in) so the site location is not leaked by accident.
- **SRS:** new Images requirement.

#### 10. Annotate a solved frame (M)
- The ASIAIR "Annotate" labels known objects on a frame. It needs the solve WCS and the node's catalog, so the Master should render the annotation or send a list of object positions and names for the app to draw.
- A list of labelled positions is cheaper to send and lets the app toggle layers (galaxies, stars, nebulae).
- **SRS:** amend `MCON-430` or `MCON-450`; core dependency on a catalog-query-by-frame operation.

#### 11. Target import (S)
- The ASIAIR Plan accepts pasted CSV (name, RA, Dec), commonly exported from Telescopius. `MCON-440` only covers Telescopius and AAVSO targets "already available to the node".
- On a phone, the natural flow is the system share sheet: share a CSV or a link from the Telescopius site into Galileo.
- **Needs a ruling:** is an imported target list a per-run input (allowed, `MCON-570`) or a stored definition (forbidden, PSD §6.4)? Recommendation: allow it, because the targets end up in the Planning list the node already holds and the desktop has the same import.

#### 12. Focus detail (S–M)
- `MCON-470` covers manual focus and autofocus run, cancel, V-curve, result, and temperature compensation state. Missing from the text:
  - per-filter focus offsets (ASIAIR 2.5; stored offsets applied on filter change). Show them read-only.
  - the aberration/tilt result once core's `FOC-080` exists (rated P1 for large sensors in the review). Show the per-region HFR map.
  - per-run autofocus parameters (step size, number of points, exposure), allowed by `MCON-570` but worth listing.
  - a "preferred focus filter" (focus through L, then apply offsets) if core adds it.
- **SRS:** amend `MCON-470`.

#### 13. Tonight view and forecast (S–M)
- `MCON-420` shows live weather and safety state. Rivals show a forecast and a night plan at a glance: Seestar's weather and visibility forecast; ASIAIR's Tonight's Best with rise/transit graphs.
- Show: sunset, twilight times, Moon phase and rise/set, the next several hours of cloud/seeing from the node's weather source if it has one, and altitude graphs of the targets in the schedule.
- Internet forecasts need the Master, not the phone, to fetch them (the app never talks to the internet on the Master's behalf). If the Master has no forecast source, show only what it computes locally.
- **SRS:** amend `MCON-440` (Planning and visibility) or add a "Tonight" section.

#### 14. Several saved Masters (S)
- `MCON-830` describes discovery or manual address entry, and storing the issued credential. It does not say that more than one Master can be remembered.
- The review lists "saved remote connections (named IP or VPN profiles)" as a trivial P1 that the ASIAIR lacks.
- Support a list of saved Masters with a name, address, last-connected time and a connect-on-launch choice; a long-press to rename or forget.
- **SRS:** amend `MCON-830`.

#### 15. Live-stack control (M)
- `MCON-430` says "view … the live-stack view". It does not say an Operator can start, stop, reset or choose parameters (rejection method, frame count). The Galileo core now lets a phone or tablet start a live stack (see the recent `imaging.capture` `live_stack` change in `CHANGELOG.md`), so the control surface exists.
- Add: start/stop stack, reset stack, show frame count and total exposure, and the `stack:<pier>` picture beside `current:<pier>`.
- Competitor gaps to watch (core): gradient removal (StellarMate 2.2), no time cap (ASIAIR user request), AI denoise (Seestar).
- **SRS:** amend `MCON-430`.

### Lower priority / worth recording

| Idea | Note |
|---|---|
| Per-star detection overlay with HFD | ASIAIR "DETECT". `MCON-430` gives star count and HFR/FWHM but no per-star overlay. Useful during manual focus |
| Observatory relay inputs/outputs | Roof, alarms (EAGLE6). Covered if exposed as switches; confirm |
| Session timeline | Already planned as Dashboard timelines (`MCON-320`); competitors' Ekos Analyze is the model |
| Keep-screen-awake and haptics during held motion | Small platform items; mention in the app design |
| Accessibility and localisation | `MCON-880` covers shared strings; accessibility is not mentioned in the SRS |

---

## 3. Decisions needed before any of this is specified

| # | Question | Why it matters |
|---|---|---|
| D-1 | **Custom objects and favourites**: configuration or per-night data? | PSD §6.4 forbids editing stored definitions. The ASIAIR lets users add and edit custom objects. Recommendation: treat favourites and user targets as data, allowed |
| D-2 | **Phone GPS and clock to the Master** for portable setups? | The ASIAIR takes location from the phone and a wrong location breaks GOTO. Site and time are configuration in Galileo, but `MCON-421` already syncs the mount on connect. Recommendation: offer "use this device's location" as a confirmed one-off operation, off by default |
| D-3 | **Which items reach the phone** layout | `MCON-810` / O2 defers this to the tablet wireframes. Items 6, 13 and 14 look suitable for the phone |
| D-4 | **Is the demo mode MVP?** | Recommended yes, because of store review |
| D-5 | **Is automatic dew control an app setting?** | Recommendation: no, it is Master-side configuration; the app only shows and overrides |

---

## 4. Confirm as deliberate non-goals

| Not planned | Reason |
|---|---|
| Video / planetary capture | No `MCON` requirement and no core feature. Revisit if core adds it |
| AI denoise, gradient removal | Core feature first |
| iOS Live Activities, home-screen widgets | Updates need background push, ruled out by D4 |
| A Windows app | WebConnect covers browsers. SynLink has a native Windows app |
| Internet / cloud access (Telescope Network style) | Excluded by design (no relay, LAN or user VPN only) |
| Citizen-science campaigns | AAVSO targets give a partial answer; a larger feature |
| Configuration of any kind | App PSD §5; the line that keeps the app safe |

---

## 5. Core gaps the app inherits (track in core)

These came out of the competitive review. They are not mobile features, but several of the app items above depend on them.

| Core gap | Review priority | Mobile impact |
|---|---|---|
| Guiding Assistant, backlash compensation | P1 | Item 4 |
| Aberration/tilt inspector (`FOC-080`, P2 in core) | P1 | Item 12 |
| Smart exposure advisor | P1 | Show the recommendation when setting exposure |
| Constraint-based scheduler, artificial horizon | P1 | `MCON-510` shows and edits jobs, not the algorithm |
| Weather-safe pause and resume | P1 | Safety display, `MCON-530` |
| Atomic updates with rollback; firmware decoupled from the app | P1 | Item 5 (version display) |
| Manual-filter name in FITS headers | P1 | None |
| Session analytics and sub grading | P2 | `MCON-540` charts |
| Simulation mode for the desktop | P1 | Item 3 can share the mock devices |
| MCP / AI-assistant endpoint | P2 | None yet |

---

## 6. Suggested sequence

1. **Now (docs only):** item 1 text change; decisions D-1 to D-5.
2. **First build:** items 3 (demo mode), 14 (saved Masters), 5 (node health), 2 (power/dew), 7 (PA live loop).
3. **Second build:** items 4 (steps 1, 2, 4), 6, 8, 9, 12, 15.
4. **When core delivers:** item 4 step 3, item 10, item 12 tilt, item 13.

Once the list is agreed, the next step is to turn the amendments and new items into `MCON-*` requirements in `docs/plugins/mobileconnect/SRS.md`, with RTM rows and `TC-MCON-*` reservations, and mirror them into the app repository's SRS.

---

## 7. Sources

- `docs/Comparison of Functions.md` — ASIAIR baseline.
- `docs/Competitive-Review.md` — SynLink, StellarMate, Ekos, NINA, EAGLE6, Gaius-S2, StellaVita, AStarBox, Pegasus Unity, SharpCap, PHD2, Seestar, Unistellar.
- `docs/plugins/mobileconnect/SRS.md` — the `MCON-*` requirements referenced above.
- `Galileo-MobileConnect/docs/PSD.md` — non-goals (§5), decisions D4, D15, and the configuration boundary (§6.4).
